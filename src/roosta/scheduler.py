"""Scheduler: the task runner loop, writer serialisation, and one unattended AI run per task."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import shutil
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, nullcontext
from dataclasses import asdict, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from roosta import ai_backend, ai_connections, paths, profile, skills
from roosta import connectors as connectors_mod
from roosta.activity_log import ActivityLog
from roosta.ai_settings import check_task_runtime, runtime_unavailable_message
from roosta.board import reconcile_board_output
from roosta.task_config import (
    TASK_SETTING_FLAGS,
    TaskConfig,
    TaskState,
    connection_task_model,
    load_tasks,
    remove_task,
    skill_description,
    task_engine,
    task_settings_changes,
    update_task_fields,
)

log = logging.getLogger(__name__)

CACHE_DIR = paths.CACHE_DIR
# Skill runs are killed on *inactivity*, not total elapsed time: a busy pass that
# keeps streaming JSON events is left alone, only a silent (presumed hung) one is
# reaped. TASK_MAX_TIMEOUT is an absolute backstop against a pathological loop.
TASK_IDLE_TIMEOUT = 300    # seconds of no stdout before a run is presumed hung
TASK_MAX_TIMEOUT = 3600    # absolute ceiling regardless of activity


PROMPT_TEMPLATE = (
    "You are running as an unattended background task. "
    "Execute the '{skill}' skill from its resolved instructions below. "
    "Do not ask questions - make autonomous decisions. "
    "Never create or modify external content or state, including chat messages, tickets, "
    "wiki pages, email, GitHub, deployments or jobs. "
    "Return findings that need {user} as Assistant board items instead. "
    "Assistant board items can link workspace Markdown through "
    "'documents': [{{'label': 'Open draft', 'path': 'drafts/example.md'}}]. "
    "When complete, wrap your final output in <task-output> tags as JSON "
    "with keys: summary, status, details."
)
UNRESTRICTED_PROMPT_TEMPLATE = (
    "You are running as an unattended background task. "
    "Execute the '{skill}' skill from its resolved instructions below. "
    "Do not ask questions - make autonomous decisions. "
    "You have standing approval for any local or external action this worker's work needs; nothing is off limits. "
    "Keep credentials and secrets out of messages, files and output. "
    "Return blockers as Assistant board items. "
    "Wrap your final output in <task-output> tags as JSON with keys: summary, status, details."
)


def outcome_summary(output: dict, error: str) -> str:
    """One brief outcome line for the activity feed."""
    summary = output.get("summary") if isinstance(output, dict) else ""
    return str(summary or error or "")


# --- Task execution ---


def parse_task_output(text: str) -> dict:
    """Extract JSON from <task-output> tags."""
    # The result block is last; earlier prose may quote the tag, so anchor on the final opener.
    start = text.rfind("<task-output>")
    match = re.compile(r"<task-output>(.*?)</task-output>", re.DOTALL).match(text, start) if start >= 0 else None
    if not match:
        return {"summary": text[:500], "status": "unknown", "details": ""}
    raw = match.group(1).strip()
    # Models sometimes drop or add a closing brace; recover the object rather than fail the run.
    for candidate in (raw, _close_json(raw)):
        try:
            parsed = json.JSONDecoder().raw_decode(candidate)[0]
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"summary": raw[:500], "status": "unknown", "details": ""}


def _close_json(raw: str) -> str:
    """Append the brackets a JSON document left open, ignoring brackets inside strings."""
    closers, in_string, escaped = [], False, False
    for ch in raw:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            closers.append("}" if ch == "{" else "]")
        elif ch in "}]" and closers:
            closers.pop()
    return raw + "".join(reversed(closers))


def missed_weekly_slot(days: list[str], run_at: str, last_run: str, now_local: datetime) -> bool:
    """True when a weekly task's most recent scheduled slot passed without a run.

    Without this, a Friday task missed while the Mac was off waits a whole week.
    A task that has never run is not caught up; its first run waits for its day.
    """
    if not days or not run_at or not last_run:
        return False
    try:
        h, m = map(int, run_at.split(":"))
        last = datetime.fromisoformat(last_run).astimezone()
    except ValueError:
        return False
    for back in range(8):  # 8: before today's slot, the latest is a week ago
        slot = (now_local - timedelta(days=back)).replace(hour=h, minute=m, second=0, microsecond=0)
        if slot <= now_local and slot.strftime("%A").lower() in days:
            return last < slot
    return False


def task_idle_timeout(task: TaskConfig, override: float | None = None) -> float:
    """Resolve the silence timeout: an explicit override, the task's own, else the default."""
    if override is not None:
        return override
    return task.idle_timeout or TASK_IDLE_TIMEOUT


def task_prompt(task: TaskConfig) -> str:
    """Build the harness prompt from the worker's template and its resolved skill."""
    template = UNRESTRICTED_PROMPT_TEMPLATE if task.unrestricted else PROMPT_TEMPLATE
    return (template.format(skill=task.skill, user=profile.load().user) + "\n"
            + skills.instructions(task.skill, task.dir, paths.WORKSPACE))


async def run_task(
    task: TaskConfig,
    *,
    session_id: str | None = None,
    idle_timeout: float | None = None,
    max_timeout: float | None = None,
) -> tuple[str, dict, str, str]:
    """Run the selected harness. Returns (status, output, error, session_id).

    The child is reaped on *inactivity*, not total runtime: harness JSON events
    keep a legitimately long-but-busy pass resetting
    the idle timer and is left to finish. Only a run that goes silent for `idle`
    seconds (presumed hung) is killed - with `maxt` as an absolute backstop against a
    pathological infinite-output loop.
    """
    idle = task_idle_timeout(task, idle_timeout)
    maxt = max_timeout if max_timeout is not None else (task.max_timeout or TASK_MAX_TIMEOUT)
    run = None
    prompt = task_prompt(task)
    try:
        run = ai_backend.prepare(task.connection, task.dir, session_id=session_id or "",
            model=connection_task_model(task, ai_connections.get(task.connection)),
            profile="unrestricted" if task.unrestricted else "safe", subject="task")
        if run.backend == ai_backend.CLAUDE:  # let long foreground scripts run, leaving time for the report
            run.env["BASH_MAX_TIMEOUT_MS"] = str(int(max(600, maxt - 120) * 1000))
        stdout = "".join([line async for line in ai_backend.stream(run, prompt, idle=idle, maximum=maxt)])
    except (ValueError, OSError) as exc:
        return "error", {}, str(exc), run.session_id if run is not None else (session_id or "")
    text = run.text(stdout)
    output = parse_task_output(text)
    status = TASK_STATUS_ALIASES.get(str(output.get("status", "")).strip().lower(), output.get("status"))
    if "<task-output>" not in text or status not in ("success", "error"):
        return "error", output, "Harness did not return a valid <task-output> result", run.session_id
    return status, output, "" if status == "success" else str(output.get("summary", ""))[:500], run.session_id


OFFLINE_RETRY_SECONDS = 900.0


TASK_STATUS_ALIASES = {
    **dict.fromkeys(("success", "ok", "complete", "completed", "done", "succeeded"), "success"),
    # An honest partial pass is still incomplete, so it stays visible as a failure.
    **dict.fromkeys(("error", "failed", "failure", "partial", "incomplete"), "error"),
}


# --- Runner loop ---


# Settings a task's state mirrors from tasks.yaml, and what a run records in its cache file.
CONFIG_FIELDS = tuple(f.name for f in fields(TaskState) if f.name in {c.name for c in fields(TaskConfig)})
RUN_FIELDS = ("status", "last_run", "last_duration", "last_output", "run_count", "last_error", "retry_at")


def apply_config(state: TaskState, task: TaskConfig) -> None:
    """Copy every mirrored setting, so an edit to tasks.yaml shows on the next cycle."""
    for name in CONFIG_FIELDS:
        value = getattr(task, name)
        setattr(state, name, list(value) if isinstance(value, list) else value)


async def precheck_unchanged(task: TaskConfig) -> bool:
    """Run a task's cheap pre-check. True only when it says nothing has changed (exit 1).

    Any other outcome, including a missing command or a timeout, runs the skill rather than
    risk missing work.
    """
    argv = shlex.split(task.precheck) if task.precheck else []
    if not argv:
        return False
    code, _, error = await connectors_mod.run_command(argv, PRECHECK_TIMEOUT)
    return error is None and code == 1


PRECHECK_TIMEOUT = 30


class TaskRunner:
    def __init__(
        self,
        *,
        task_loader: Callable[[], list[TaskConfig]] | None = None,
        auth_checker: Callable[[TaskConfig], Awaitable[bool]] | None = None,
        task_executor: Callable[[TaskConfig], Awaitable[tuple[str, dict, str]]] | None = None,
        connector_registry: "connectors_mod.Connectors | None" = None,
        prechecker: Callable[[TaskConfig], Awaitable[bool]] | None = None,
        activity_log=None,
        cache_dir: Path = CACHE_DIR,
        tasks_file: Path = paths.TASKS_FILE,
        startup_delay: float = 2.0,
        poll_interval: float = 30.0,
        auth_retry_interval: float = 60.0,
        weekday_interval: float = 300.0,
        watch_config: bool = True,
        reconcile_interval: float = 30.0,
        offline_retry: float = OFFLINE_RETRY_SECONDS,
    ) -> None:
        self._tasks: list[TaskConfig] = []
        self._states: dict[str, TaskState] = {}
        self._loop_tasks: list[asyncio.Task] = []
        self._triggers: dict[str, asyncio.Event] = {}
        self._cancelled: set[str] = set()
        self._writer_lock = asyncio.Lock()  # serialises workspace-writing tasks against each other only
        self._writer_holder: str | None = None
        self._writer_waiting: set[str] = set()
        self._running = False
        self._stop_event = asyncio.Event()
        self._task_loader = task_loader
        self._auth_checker = auth_checker
        self._task_executor = task_executor
        self._connectors = (connector_registry if connector_registry is not None
                            else connectors_mod.Connectors(path=paths.CONNECTORS_FILE))
        self._prechecker = prechecker or precheck_unchanged
        self._activity_log = activity_log if activity_log is not None else ActivityLog()
        self._cache_dir = Path(cache_dir)
        self._tasks_file = Path(tasks_file)
        self._startup_delay = startup_delay
        self._poll_interval = poll_interval
        self._auth_retry_interval = auth_retry_interval
        self._weekday_interval = weekday_interval
        self._offline_retry = offline_retry
        self._watch_config_enabled = watch_config
        self._reconcile_interval = reconcile_interval

    def start(self) -> None:
        try:
            self._tasks = self._load_tasks()
        except (OSError, ValueError, TypeError, AttributeError, KeyError, yaml.YAMLError):
            log.warning("Cannot load tasks.yaml. Scheduling will resume after the file is repaired.")
            self._tasks = []
        self._running = True
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        for task in self._tasks:
            self._spawn(task)
        if self._watch_config_enabled:
            self._loop_tasks.append(
                asyncio.create_task(self._watch_config(), name="config-watcher")
            )
        if self._reconcile_interval:
            self._loop_tasks.append(
                asyncio.create_task(self._reconcile_loop(), name="config-reconcile")
            )
        log.info("Task runner started with %d task(s)", len(self._tasks))

    def _load_tasks(self) -> list[TaskConfig]:
        loader = self._task_loader or load_tasks
        return loader()

    def _load_tasks_map(self) -> dict[str, TaskConfig]:
        return {t.id: t for t in self._load_tasks()}

    async def _check_auth(self, task: TaskConfig) -> bool:
        checker = self._auth_checker or check_task_runtime
        return await checker(task)

    async def _run_task(self, task: TaskConfig) -> tuple[str, dict, str, str]:
        executor = self._task_executor or run_task
        return await executor(task)

    def _activity(self):
        return self._activity_log

    def _spawn(self, task: TaskConfig) -> None:
        """Register a task's state and start its poll loop."""
        self._states[task.id] = self._load_state(task)
        self._triggers[task.id] = asyncio.Event()
        self._loop_tasks.append(
            asyncio.create_task(self._supervised_loop(task.id), name=f"task-{task.id}")
        )

    async def _supervised_loop(self, task_id: str) -> None:
        """Keep a task's poll loop alive through unexpected errors."""
        while self._running:
            try:
                await self._poll_loop(task_id)
                return
            except Exception as exc:
                log.exception("Task %s: poll loop crashed, restarting", task_id)
                state = self._states.get(task_id)
                if state is not None:
                    state.status = "error"
                    state.last_error = f"Scheduler loop crashed and restarted: {exc!r}"
                    self._save_state(state)
                await asyncio.sleep(self._poll_interval)

    def trigger(self, task_id: str) -> bool:
        """Request an immediate run of a task, bypassing its interval gate.

        Returns False if the task isn't running a loop. The poll loop picks
        the event up within its wait and runs as soon as its scheduling gate allows.
        """
        ev = self._triggers.get(task_id)
        if ev is None:
            return False
        ev.set()
        return True

    def cancel_queued(self, task_id: str) -> bool:
        """Drop a manual trigger that has not started running yet."""
        state = self._states.get(task_id)
        ev = self._triggers.get(task_id)
        if state is None or ev is None:
            return False
        if state.status == "running" or not ev.is_set():
            return False
        self._cancelled.add(task_id)
        ev.clear()
        return True

    def remove(self, task_id: str) -> bool:
        """Fire a worker: drop it from tasks.yaml and the board now; its poll loop exits
        on its next cycle. Raises RuntimeError while it is running or queued."""
        state = self._states.get(task_id)
        if state is None:
            return False
        if state.status == "running" or self.is_queued(task_id):
            raise RuntimeError("cannot fire a worker while it is running or queued")
        try:
            remove_task(self._tasks_file, task_id)
        except (OSError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc
        self._states.pop(task_id, None)
        (self._cache_dir / f"{task_id}.json").unlink(missing_ok=True)
        # The skill's own scratch state, named after the worker; kept while another
        # worker still runs a skill of that name (they share it).
        if not any(t.skill == task_id for t in self._load_tasks()):
            (paths.STATE_DIR / f"{task_id}.json").unlink(missing_ok=True)
            if task_id not in {"cache", "assistant", "pages", ".", ".."}:  # Roosta's own folders
                shutil.rmtree(paths.STATE_DIR / task_id, ignore_errors=True)
        return True

    def set_settings(self, task_id: str, body: dict) -> dict | None:
        """Persist the Skill runner settings form: name, nickname, description,
        schedule, connection and model. Raises ValueError for bad
        input and RuntimeError when the task file cannot take the edit."""
        state = self._states.get(task_id)
        if state is None:
            return None
        values, remove = task_settings_changes(body)
        if "connection" in body:
            if state.status == "running" or self.is_queued(task_id):
                raise RuntimeError("AI connection cannot change while the worker is running or queued")
            connection_id = body["connection"]
            if not isinstance(connection_id, str):
                raise ValueError("Choose an AI connection")
            if connection_id:
                ai_connections.get(connection_id)
                values["connection"] = connection_id
            else:
                remove.add("connection")
        connection_model = body.get("connection_model")
        if connection_model is not None:
            if not isinstance(connection_model, str):
                raise ValueError("Choose a model")
            current = values.get("connection", "" if "connection" in remove else state.connection)
            if not current:
                current = "default" if ai_backend.default_connection() else ""
            if not current:
                raise ValueError("Choose an AI connection before choosing its model")
            provider = ai_connections.get("" if current == "default" else current, connected=False)["provider"]
            if connection_model.strip():
                ai_connections.runtime(provider, connection_model.strip())
                values["model"] = connection_model.strip()
            elif state.model:
                remove.add("model")
        if values or remove:
            try:
                update_task_fields(self._tasks_file, task_id, values, remove)
            except (OSError, ValueError) as exc:
                raise RuntimeError(str(exc)) from exc
        for key in ("connection", "model"):
            if key in values or key in remove:
                setattr(state, key, values.get(key, ""))
        # Apply now; the poll loop re-reads tasks.yaml on its next cycle anyway.
        for key in ("name", "nickname"):
            if key in values or key in remove:
                setattr(state, key, values.get(key, ""))
        if "description" in values or "description" in remove:
            state.custom_description = values.get("description", "")
            state.description = state.custom_description or skill_description(
                state.skill, next((t.dir for t in self._tasks if t.id == task_id), paths.WORKSPACE),
            )
        for key in ("interval", "run_at", "weekdays_only", "days_of_week"):
            if key in values:
                setattr(state, key, values[key])
            elif key in remove:
                setattr(state, key, {"run_at": "", "weekdays_only": False, "days_of_week": []}[key])
        for key in TASK_SETTING_FLAGS:
            if key in values or key in remove:
                setattr(state, key, key in values)
        return self.get_state(task_id)

    def _spawn_new_tasks(self) -> None:
        """Start a loop for every task id in tasks.yaml that has none yet."""
        try:
            for task in self._load_tasks():
                if task.id not in self._states:
                    log.info("Config changed: new task %s, spawning", task.id)
                    self._spawn(task)
        except Exception as e:
            log.warning("Config reload failed: %s", e)

    async def _watch_config(self) -> None:
        """Spawn loops for new task ids as soon as tasks.yaml changes.

        Edits to existing tasks and removals are handled by each poll loop re-reading config
        every cycle. If the watcher itself fails it logs and restarts, so it can never die
        silently and leave new tasks unstarted.
        """
        from watchfiles import awatch

        while self._running:
            try:
                async for _ in awatch(self._tasks_file, stop_event=self._stop_event):
                    self._spawn_new_tasks()
                return  # stop_event was set
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("tasks.yaml watcher failed, restarting")
                await asyncio.sleep(5)

    async def _reconcile_loop(self) -> None:
        """Backstop for missed file events: re-read tasks.yaml on a timer."""
        while self._running:
            await asyncio.sleep(self._reconcile_interval)
            self._spawn_new_tasks()

    async def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        for t in self._loop_tasks:
            t.cancel()
        for t in self._loop_tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._loop_tasks.clear()

    def is_queued(self, task_id: str) -> bool:
        """True once a trigger has been requested but the run hasn't started yet
        (e.g. blocked behind the writer lock)."""
        ev = self._triggers.get(task_id)
        return ev is not None and ev.is_set()

    def waiting_behind(self, task_id: str) -> str:
        """The writer task this one is waiting on, or '' when it is not waiting."""
        return (self._writer_holder or "") if task_id in self._writer_waiting else ""

    def _view(self, s: TaskState) -> dict:
        return {**asdict(s), "queued": self.is_queued(s.id), "waiting_behind": self.waiting_behind(s.id)}

    def get_states(self) -> list[dict]:
        return [self._view(s) for s in self._states.values()]

    def get_state(self, task_id: str) -> dict | None:
        s = self._states.get(task_id)
        return self._view(s) if s else None

    @asynccontextmanager
    async def _writer_slot(self, task_id: str):
        """Hold the writer lock, recording who holds it and who is waiting behind them."""
        self._writer_waiting.add(task_id)
        try:
            async with self._writer_lock:
                self._writer_waiting.discard(task_id)
                self._writer_holder = task_id
                try:
                    yield
                finally:
                    self._writer_holder = None
        finally:
            self._writer_waiting.discard(task_id)

    def _load_state(self, task: TaskConfig) -> TaskState:
        state = TaskState(id=task.id, skill=task.skill, interval=task.interval)
        apply_config(state, task)
        try:
            data = json.loads((self._cache_dir / f"{task.id}.json").read_text())
        except (OSError, ValueError):
            data = {}
        for key in RUN_FIELDS if isinstance(data, dict) else ():
            if key in data:
                setattr(state, key, data[key])
        if state.status == "running":  # a restart ended that run
            state.status = "idle"
        return state

    def _save_state(self, state: TaskState) -> None:
        paths.write_json(self._cache_dir / f"{state.id}.json", asdict(state))

    async def _poll_loop(self, task_id: str) -> None:
        # Stagger start by a few seconds per task
        await asyncio.sleep(self._startup_delay)

        while self._running:
            # Re-read config each cycle so interval/skill/dir edits apply live.
            task = self._load_tasks_map().get(task_id)
            if task is None:
                log.info("Task %s: removed from config, stopping loop", task_id)
                self._states.pop(task_id, None)
                return
            state = self._states[task_id]
            apply_config(state, task)

            triggered = self._triggers[task_id].is_set()

            # Day gate: manual runs bypass calendar restrictions.
            now_local = datetime.now().astimezone()
            day_name = now_local.strftime("%A").lower()
            day_blocked = task.days_of_week and day_name not in task.days_of_week
            weekend_blocked = task.weekdays_only and now_local.weekday() >= 5
            # Off-day catch-up only: on the scheduled day the normal run_at gate decides.
            catch_up = bool(day_blocked) and not weekend_blocked and missed_weekly_slot(
                task.days_of_week, task.run_at, state.last_run, now_local)
            if not triggered and not catch_up and (day_blocked or weekend_blocked):
                await self._wait_or_trigger(task_id, self._weekday_interval)
                continue
            if catch_up and not triggered:
                log.info("Task %s: catching up a missed weekly run", task_id)

            # A run lost to the network or sleep retries soon instead of losing its slot.
            retry_due = bool(state.retry_at) and datetime.now(timezone.utc) >= datetime.fromisoformat(state.retry_at)

            # Check scheduling gate (skip if manually triggered, catching up or retrying).
            if not triggered and not catch_up and not retry_due:
                if task.run_at:
                    # Time-of-day scheduling: run once per day at the specified local time.
                    h, m = map(int, task.run_at.split(":"))
                    target_today = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
                    if now_local < target_today:
                        # Before today's window - sleep until close to it.
                        secs = (target_today - now_local).total_seconds()
                        await self._wait_or_trigger(task_id, min(secs, self._poll_interval))
                        continue
                    if state.last_run:
                        try:
                            last_local = datetime.fromisoformat(state.last_run).astimezone()
                            if last_local >= target_today:
                                # Already ran today - sleep until tomorrow's window.
                                target_tomorrow = target_today + timedelta(days=1)
                                secs = (target_tomorrow - now_local).total_seconds()
                                await self._wait_or_trigger(task_id, min(secs, self._poll_interval))
                                continue
                        except ValueError:
                            pass
                elif state.last_run:
                    # Interval-based scheduling.
                    try:
                        last = datetime.fromisoformat(state.last_run)
                        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
                        if elapsed < task.interval:
                            await self._wait_or_trigger(task_id, self._poll_interval)
                            continue
                    except ValueError:
                        pass

            registry = self._connectors
            down = await registry.signed_out(task.requires) if registry is not None and task.requires else []
            if down:
                reason = "Waiting for sign-in: " + ", ".join(down)
                if state.status != "blocked" or state.last_error != reason:
                    state.status = "blocked"
                    state.last_error = reason
                    self._save_state(state)
                    log.info("Task %s: %s", task_id, reason)
                # A manual run cannot bypass this gate, so consume its trigger.
                # Left set, _wait_or_trigger returns instantly and the loop spins
                # at full CPU, starving the event loop that serves the dashboard.
                if triggered:
                    self._triggers[task_id].clear()
                await self._wait_or_trigger(task_id, self._auth_retry_interval)
                continue
            if state.status == "blocked":
                # The connector is back; a writer may still wait for the lock, so stop blaming it.
                state.status = "idle"
                state.last_error = ""
                self._save_state(state)

            # A cheap pre-check can confirm nothing changed and skip the model run. The
            # last output carries forward, minus any old error the assistant task would re-raise.
            if not triggered and task.precheck:
                started = time.monotonic()
                if await self._prechecker(task):
                    output = dict(state.last_output)
                    details = output.get("details")
                    if isinstance(details, dict) and "error" in details:
                        output["details"] = {k: v for k, v in details.items() if k != "error"}
                    output.update({"summary": "Nothing new since the last run", "status": "success"})
                    state.status = "success"
                    state.last_run = datetime.now(timezone.utc).isoformat()
                    state.last_duration = round(time.monotonic() - started, 1)
                    state.last_output = output
                    state.run_count += 1
                    state.last_error = ""
                    state.retry_at = ""
                    self._save_state(state)
                    log.info("Task %s: pre-check unchanged, skipped agent run", task_id)
                    await self._wait_or_trigger(task_id, self._poll_interval)
                    continue

            # Auth check
            if not await self._check_auth(task):
                state.status = "auth-failed"
                state.last_error = runtime_unavailable_message(task)
                self._save_state(state)
                if triggered:
                    self._triggers[task_id].clear()
                log.info("Task %s: auth failed, skipping", task_id)
                await self._wait_or_trigger(task_id, self._auth_retry_interval)
                continue

            # Run the task. Writers (tasks that rewrite workspace docs / auto-commit) are
            # serialised against each other via _writer_lock; everything else runs
            # freely in parallel, including alongside a writer.
            lock_cm = self._writer_slot(task_id) if task.writer else nullcontext()
            async with lock_cm:
                if task_id in self._cancelled:
                    self._cancelled.discard(task_id)
                    self._triggers[task_id].clear()
                else:
                    if not task.connection:
                        # Bind once after the writer queue, before activity and execution.
                        try:
                            task = replace(task, connection=ai_connections.get(connected=False)["id"])
                        except ValueError:
                            pass  # run_task reports the missing connection
                    source = "manual" if self._triggers[task_id].is_set() else "scheduled"
                    self._triggers[task_id].clear()
                    state.status = "running"
                    state.last_error = ""
                    self._save_state(state)
                    log.info("Task %s: starting (%s)", task_id, source)
                    act_id = self._activity().start(
                        "skill", task.skill, source, task_id=task.id,
                        backend=task_engine(task), connection_id=task.connection, workspace=task.dir,
                    )

                    start = time.monotonic()
                    status, output, error, session_id = await self._run_task(task)
                    duration = time.monotonic() - start
                    if session_id:
                        self._activity().set_session(act_id, session_id)
                    self._activity().finish(
                        act_id,
                        "error" if status == "error" else "success",
                        outcome_summary(output, error),
                    )

                    state.status = status
                    state.last_run = datetime.now(timezone.utc).isoformat()
                    state.last_duration = round(duration, 1)
                    previous = (state.last_output or {}).get("details")
                    state.last_output = reconcile_board_output(task.id, status, output, previous)
                    state.run_count += 1
                    state.last_error = error
                    state.retry_at = (
                        (datetime.now(timezone.utc) + timedelta(seconds=self._offline_retry)).isoformat()
                        if status == "error" and ai_backend.is_offline_failure(outcome_summary(output, error))
                        else ""
                    )
                    self._save_state(state)
                    log.info("Task %s: finished in %.1fs with status=%s", task_id, duration, status)

            await self._wait_or_trigger(task_id, self._poll_interval)

    async def _wait_or_trigger(self, task_id: str, timeout: float) -> None:
        """Sleep up to `timeout`s, returning early if the task is triggered."""
        ev = self._triggers.get(task_id)
        if ev is None:
            await asyncio.sleep(timeout)
            return
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
