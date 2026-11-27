import asyncio
import json
import os
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from roosta import scheduler
from roosta import ai_settings
from roosta import cursor_sessions, task_config
from roosta import app as appmod
from roosta.activity_log import ActivityLog


class FakeActivity:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self._next = 0

    def start(self, kind: str, label: str, source: str, **kwargs) -> str:
        self._next += 1
        eid = f"act-{self._next}"
        self.events.append({
            "event": "start", "id": eid, "kind": kind, "label": label, "source": source, **kwargs,
        })
        return eid

    def set_session(self, eid: str, session_id: str) -> None:
        self.events.append({"event": "session", "id": eid, "session_id": session_id})

    def finish(self, eid: str, status: str = "success", summary: str = "") -> None:
        self.events.append({"event": "finish", "id": eid, "status": status, "summary": summary})


async def wait_until(predicate, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


async def always_authed(_task=None) -> bool:
    return True


def cached_state(cache_dir: Path, task_id: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{task_id}.json").write_text(json.dumps({
        "status": "success",
        "last_run": datetime.now(timezone.utc).isoformat(),
        "last_duration": 0.1,
        "last_output": {"summary": "previous run"},
        "run_count": 1,
        "last_error": "",
    }))


class FakeConnectors:
    """A one-connector set: `teams`, whose sign-in verdict a test controls."""

    def __init__(self, status=None, on_check=None):
        self._status = status or (lambda: "success")
        self._on_check = on_check or (lambda: None)

    async def signed_out(self, requires):
        if "teams" not in requires:
            return []
        self._on_check()
        return ["Teams (run `msteams login`)"] if self._status() == "auth-failed" else []


def make_runner(
    tmp_path: Path,
    tasks: list[task_config.TaskConfig],
    executor,
    auth_checker=always_authed,
    teams_auth_status=None,
    task_loader=None,
    on_check=None,
    prechecker=None,
):
    return scheduler.TaskRunner(
        task_loader=task_loader or (lambda: tasks),
        auth_checker=auth_checker,
        task_executor=executor,
        connector_registry=FakeConnectors(teams_auth_status, on_check),
        prechecker=prechecker,
        activity_log=FakeActivity(),
        cache_dir=tmp_path / "cache",
        tasks_file=tmp_path / "tasks.yaml",
        startup_delay=0,
        poll_interval=0.02,
        auth_retry_interval=0.02,
        weekday_interval=0.02,
        watch_config=False,
        reconcile_interval=0,
    )


def test_interval_task_runs_automatically_when_due(tmp_path):
    async def scenario():
        started: list[str] = []

        async def executor(task: task_config.TaskConfig, **_):
            started.append(task.id)
            return "success", {"summary": "ran", "status": "success"}, "", ""

        runner = make_runner(tmp_path, [task_config.TaskConfig(id="scheduled", skill="skill", interval=3600)], executor)
        runner.start()
        try:
            await wait_until(lambda: started == ["scheduled"])
            state = runner.get_state("scheduled")
            assert state["status"] == "success"
            assert state["run_count"] == 1
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_manual_trigger_bypasses_interval_gate(tmp_path):
    async def scenario():
        cache_dir = tmp_path / "cache"
        cached_state(cache_dir, "manual")
        started: list[str] = []

        async def executor(task: task_config.TaskConfig, **_):
            started.append(task.id)
            return "success", {"summary": "manual ran", "status": "success"}, "", ""

        runner = make_runner(tmp_path, [task_config.TaskConfig(id="manual", skill="skill", interval=3600)], executor)
        runner.start()
        try:
            await asyncio.sleep(0.05)
            assert started == []

            assert runner.trigger("manual") is True
            await wait_until(lambda: started == ["manual"])
            assert runner.get_state("manual")["run_count"] == 2
            assert runner._activity().events[0]["source"] == "manual"
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_days_of_week_gate_blocks_scheduled_run_but_not_manual_run(tmp_path):
    async def scenario():
        started: list[str] = []

        async def executor(task: task_config.TaskConfig, **_):
            started.append(task.id)
            return "success", {"summary": "ran", "status": "success"}, "", ""

        current_day = datetime.now().astimezone().strftime("%A").lower()
        blocked_day = "monday" if current_day != "monday" else "tuesday"
        task = task_config.TaskConfig(
            id="weekly",
            skill="skill",
            run_at="00:00",
            days_of_week=[blocked_day],
        )
        runner = make_runner(tmp_path, [task], executor)
        runner.start()
        try:
            await asyncio.sleep(0.05)
            assert started == []

            assert runner.trigger("weekly") is True
            await wait_until(lambda: started == ["weekly"])
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_missed_weekly_slot_finds_the_latest_scheduled_day():
    tz = timezone.utc
    monday = datetime(2026, 11, 2, 17, 0, tzinfo=tz)
    friday_run = "2026-10-23T09:25:00+00:00"  # ran the Friday before last
    assert scheduler.missed_weekly_slot(["friday"], "10:00", friday_run, monday) is True
    assert scheduler.missed_weekly_slot(["friday"], "10:00", "2026-10-30T10:01:00+00:00", monday) is False
    assert scheduler.missed_weekly_slot(["friday"], "10:00", "", monday) is False  # never ran
    # Monday 08:00, task due Monday 09:00: last week's slot is the latest, and it ran.
    early = datetime(2026, 11, 2, 8, 0, tzinfo=tz)
    assert scheduler.missed_weekly_slot(["monday"], "09:00", "2026-10-26T09:00:30+00:00", early) is False
    assert scheduler.missed_weekly_slot(["monday"], "09:00", "2026-10-19T09:00:30+00:00", early) is True


def test_weekly_task_missed_on_its_day_catches_up_on_an_off_day(tmp_path):
    async def scenario():
        started: list[str] = []

        async def executor(task: task_config.TaskConfig, **_):
            started.append(task.id)
            return "success", {"summary": "ran", "status": "success"}, "", ""

        now_local = datetime.now().astimezone()
        yesterday = (now_local - timedelta(days=1)).strftime("%A").lower()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "weekly.json").write_text(json.dumps({
            "status": "success",
            "last_run": (now_local - timedelta(days=8)).isoformat(),
            "last_output": {}, "run_count": 1, "last_error": "",
        }))
        runner = make_runner(tmp_path, [task_config.TaskConfig(
            id="weekly", skill="skill", run_at="00:00", days_of_week=[yesterday],
        )], executor)
        runner.start()
        try:
            await wait_until(lambda: started == ["weekly"])
            await asyncio.sleep(0.1)
            assert started == ["weekly"]  # one catch-up, not a loop
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_non_writer_tasks_run_in_parallel(tmp_path):
    async def scenario():
        started: dict[str, float] = {}
        release = asyncio.Event()

        async def executor(task: task_config.TaskConfig, **_):
            started[task.id] = asyncio.get_running_loop().time()
            await release.wait()
            return "success", {"summary": f"{task.id} ran", "status": "success"}, "", ""

        tasks = [
            task_config.TaskConfig(id="reader-a", skill="a", interval=3600),
            task_config.TaskConfig(id="reader-b", skill="b", interval=3600),
        ]
        runner = make_runner(tmp_path, tasks, executor)
        runner.start()
        try:
            await wait_until(lambda: set(started) == {"reader-a", "reader-b"})
            assert abs(started["reader-a"] - started["reader-b"]) < 0.05
        finally:
            release.set()
            await runner.stop()

    asyncio.run(scenario())


def test_writer_tasks_serialise_but_reader_runs_alongside_writer(tmp_path):
    async def scenario():
        writer_started: list[str] = []
        reader_started = asyncio.Event()
        first_writer_started = asyncio.Event()
        first_writer_release = asyncio.Event()
        second_writer_started = asyncio.Event()

        async def executor(task: task_config.TaskConfig, **_):
            if task.writer:
                writer_started.append(task.id)
                if len(writer_started) == 1:
                    first_writer_started.set()
                    await first_writer_release.wait()
                else:
                    second_writer_started.set()
            else:
                reader_started.set()
            return "success", {"summary": f"{task.id} ran", "status": "success"}, "", ""

        tasks = [
            task_config.TaskConfig(id="writer-a", skill="wa", interval=3600, writer=True),
            task_config.TaskConfig(id="writer-b", skill="wb", interval=3600, writer=True),
            task_config.TaskConfig(id="reader", skill="r", interval=3600),
        ]
        runner = make_runner(tmp_path, tasks, executor)
        runner.start()
        try:
            await wait_until(lambda: first_writer_started.is_set() and reader_started.is_set())
            await asyncio.sleep(0.05)
            assert not second_writer_started.is_set()

            first_writer_release.set()
            await wait_until(second_writer_started.is_set)
            assert set(writer_started) == {"writer-a", "writer-b"}
        finally:
            first_writer_release.set()
            await runner.stop()

    asyncio.run(scenario())


def test_writer_waiting_on_lock_names_the_holder_not_a_stale_teams_block(tmp_path):
    async def scenario():
        teams_status = "auth-failed"
        holder_started = asyncio.Event()
        release = asyncio.Event()
        started: list[str] = []

        async def executor(task: task_config.TaskConfig, **_):
            started.append(task.id)
            if task.id == "office-director":
                holder_started.set()
                await release.wait()
            return "success", {"summary": "ran", "status": "success"}, "", ""

        tasks = [
            task_config.TaskConfig(id="office-director", skill="od", interval=3600, writer=True),
            task_config.TaskConfig(id="incident-tracker", skill="it", interval=3600, writer=True, requires=["teams"]),
        ]
        runner = make_runner(tmp_path, tasks, executor, teams_auth_status=lambda: teams_status)
        runner.start()
        try:
            await wait_until(holder_started.is_set)
            await wait_until(lambda: runner.get_state("incident-tracker")["status"] == "blocked")
            assert runner.get_state("incident-tracker")["waiting_behind"] == ""

            teams_status = "success"
            await wait_until(lambda: runner.get_state("incident-tracker")["waiting_behind"] == "office-director")
            state = runner.get_state("incident-tracker")
            assert (state["status"], state["last_error"]) == ("idle", "")
            assert runner.get_state("office-director")["waiting_behind"] == ""

            release.set()
            await wait_until(lambda: "incident-tracker" in started)
            await wait_until(lambda: runner.get_state("incident-tracker")["status"] == "success")
            assert runner.get_state("incident-tracker")["waiting_behind"] == ""
        finally:
            release.set()
            await runner.stop()

    asyncio.run(scenario())


def test_auth_failure_clears_manual_trigger_instead_of_staying_queued(tmp_path):
    async def scenario():
        cache_dir = tmp_path / "cache"
        cached_state(cache_dir, "manual")

        async def executor(task: task_config.TaskConfig, **_):
            pytest.fail("task executor should not run when auth fails")

        async def auth_checker(_task) -> bool:
            return False

        runner = make_runner(
            tmp_path,
            [task_config.TaskConfig(id="manual", skill="skill", interval=3600)],
            executor,
            auth_checker=auth_checker,
        )
        runner.start()
        try:
            assert runner.trigger("manual") is True
            await wait_until(lambda: runner.get_state("manual")["status"] == "auth-failed")
            assert runner.get_state("manual")["queued"] is False
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_teams_dependent_task_waits_for_auth_recovery_without_spawning_agent(tmp_path):
    async def scenario():
        started: list[str] = []
        teams_status = "auth-failed"

        async def executor(task: task_config.TaskConfig, **_):
            started.append(task.id)
            return "success", {"summary": "ran", "status": "success"}, "", ""

        runner = make_runner(
            tmp_path,
            [
                task_config.TaskConfig(
                    id="support",
                    skill="support-watch",
                    interval=3600,
                    requires=["teams"],
                )
            ],
            executor,
            teams_auth_status=lambda: teams_status,
        )
        runner.start()
        try:
            await wait_until(lambda: runner.get_state("support")["status"] == "blocked")
            assert started == []
            assert runner.get_state("support")["run_count"] == 0
            assert runner.get_state("support")["last_error"] == "Waiting for sign-in: Teams (run `msteams login`)"
            assert runner._activity().events == []

            teams_status = "success"
            await wait_until(lambda: started == ["support"])
            assert runner.get_state("support")["status"] == "success"
            assert runner.get_state("support")["last_error"] == ""
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_teams_blocked_manual_trigger_clears_instead_of_spinning(tmp_path):
    """Run now on a Teams-blocked task must consume its trigger.

    Left set, _wait_or_trigger returns without ever awaiting, so the poll loop
    re-reads tasks.yaml and every SKILL.md in a tight loop that yields nothing -
    monopolising the event loop that serves the dashboard. The scenario runs on a
    daemon thread so that failure reports here rather than wedging the suite.
    """
    async def scenario():
        loads = 0

        def counting_loader():
            nonlocal loads
            loads += 1
            return [
                task_config.TaskConfig(
                    id="support",
                    skill="support-watch",
                    interval=3600,
                    requires=["teams"],
                )
            ]

        async def executor(task: task_config.TaskConfig, **_):
            pytest.fail("task executor should not run while Teams auth is failed")

        runner = make_runner(
            tmp_path,
            [],
            executor,
            teams_auth_status=lambda: "auth-failed",
            task_loader=counting_loader,
        )
        runner.start()
        try:
            await wait_until(lambda: runner.get_state("support")["status"] == "blocked")
            assert runner.trigger("support") is True
            await wait_until(lambda: runner.get_state("support")["queued"] is False)

            before = loads
            await asyncio.sleep(0.2)
            # A 0.02s retry interval allows ~10 passes in that window; a spinning
            # loop would manage thousands.
            assert loads - before < 100
        finally:
            await runner.stop()

    outcome: dict = {}

    def run_scenario() -> None:
        try:
            asyncio.run(scenario())
        except BaseException as exc:  # re-raised on the test thread below
            outcome["error"] = exc

    thread = threading.Thread(target=run_scenario, daemon=True)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive(), "poll loop never yielded - the Teams gate is spinning"
    if "error" in outcome:
        raise outcome["error"]


def test_unchanged_precheck_skips_agent_and_preserves_board_items(tmp_path):
    async def scenario():
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        item = {"id": "self-chat-existing", "title": "Existing command"}
        (cache_dir / "self-chat-commands.json").write_text(json.dumps({
            "status": "success",
            "last_run": "2020-01-01T00:00:00+00:00",
            "last_duration": 50.0,
            "last_output": {
                "summary": "Processed 0 new self-chat messages",
                "status": "success",
                "details": {"items": [item],
                            "error": "teams_get_thread returned AUTH_REQUIRED"},
            },
            "run_count": 10,
            "last_error": "",
        }))

        async def unchanged(_task):
            return True

        async def executor(_task: task_config.TaskConfig, **_):
            pytest.fail("an unchanged pre-check should not start an agent")

        runner = make_runner(
            tmp_path,
            [task_config.TaskConfig(
                id="self-chat-commands",
                skill="self-chat-commands",
                interval=600,
                precheck="check-inbox",
            )],
            executor,
            prechecker=unchanged,
        )
        runner.start()
        try:
            await wait_until(
                lambda: runner.get_state("self-chat-commands")["run_count"] == 11
            )
            state = runner.get_state("self-chat-commands")
            assert state["status"] == "success"
            assert state["last_output"]["summary"] == "Nothing new since the last run"
            assert state["last_output"]["details"]["items"] == [item]
            # The successful probe read disproves the earlier auth error.
            assert "error" not in state["last_output"]["details"]
            assert runner._activity().events == []
        finally:
            await runner.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("failed_output", [
    {}, {"summary": "blocked", "status": "error", "details": {"reason": "could not read the board"}},
    {"summary": "snapshot failed", "status": "error", "details": {"items": []}},
    {"status": "error", "details": {"items": [{"id": "partial", "title": "Incomplete read"}],
                                    "merges": {"existing-card": "partial"}}},
])
def test_failed_run_keeps_the_previous_board_items(tmp_path, failed_output):
    async def scenario():
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        item = {"id": "existing-card", "title": "Existing card"}
        (cache_dir / "assistant.json").write_text(json.dumps({
            "status": "success", "last_run": "2020-01-01T00:00:00+00:00", "last_duration": 5.0,
            "last_output": {"summary": "ok", "status": "success", "details": {"items": [item]}},
            "run_count": 1, "last_error": "",
        }))

        async def executor(_task: task_config.TaskConfig, **_):
            return "error", dict(failed_output), "AI request failed", ""

        runner = make_runner(tmp_path, [task_config.TaskConfig(id="assistant", skill="assistant", interval=600)],
                             executor)
        runner.start()
        try:
            await wait_until(lambda: runner.get_state("assistant")["run_count"] == 2)
            state = runner.get_state("assistant")
            assert state["status"] == "error" and state["last_error"] == "AI request failed"
            assert state["last_output"]["details"]["items"] == [item]
            assert "merges" not in state["last_output"]["details"]
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_poll_loop_survives_a_crashing_precheck_and_still_serves_manual_runs(tmp_path):
    async def scenario():
        cached_state(tmp_path / "cache", "self-chat-commands")
        started: list[str] = []
        probes = 0

        async def flaky_probe(_task):
            nonlocal probes
            probes += 1
            if probes == 1:
                raise ProcessLookupError()
            return True

        async def executor(task: task_config.TaskConfig, **_):
            started.append(task.id)
            return "success", {"summary": "ran", "status": "success"}, "", ""

        task = task_config.TaskConfig(id="self-chat-commands", skill="self-chat-commands", interval=0,
                                 precheck="check-inbox")
        runner = make_runner(tmp_path, [task], executor, prechecker=flaky_probe)
        runner.start()
        try:
            await wait_until(lambda: probes >= 2)
            assert runner.trigger("self-chat-commands") is True
            await wait_until(lambda: started == ["self-chat-commands"])
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_manual_run_bypasses_unchanged_precheck(tmp_path):
    async def scenario():
        cache_dir = tmp_path / "cache"
        cached_state(cache_dir, "self-chat-commands")
        started: list[str] = []

        async def unchanged(_task):
            return True

        async def executor(task: task_config.TaskConfig, **_):
            started.append(task.id)
            return "success", {"summary": "forced run", "status": "success"}, "", ""

        runner = make_runner(
            tmp_path,
            [task_config.TaskConfig(
                id="self-chat-commands",
                skill="self-chat-commands",
                interval=600,
                precheck="check-inbox",
            )],
            executor,
            prechecker=unchanged,
        )
        runner.start()
        try:
            assert runner.trigger("self-chat-commands") is True
            await wait_until(lambda: started == ["self-chat-commands"])
            assert runner.get_state("self-chat-commands")["last_output"]["summary"] == "forced run"
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_http_manual_run_endpoint_starts_task(tmp_path, monkeypatch):
    async def scenario():
        from httpx import ASGITransport, AsyncClient

        cache_dir = tmp_path / "cache"
        cached_state(cache_dir, "manual")
        started = asyncio.Event()

        async def executor(task: task_config.TaskConfig, **_):
            started.set()
            return "success", {"summary": "started from API", "status": "success"}, "", ""

        runner = make_runner(tmp_path, [task_config.TaskConfig(id="manual", skill="skill", interval=3600)], executor)
        monkeypatch.setattr(appmod, "runner", runner)
        runner.start()
        try:
            transport = ASGITransport(app=appmod.app)
            async with AsyncClient(transport=transport, base_url="http://localhost") as client:
                response = await client.post("/api/tasks/manual/run")
                assert response.status_code == 200
                assert response.json() == {"triggered": True}

                await wait_until(started.is_set)
                state = (await client.get("/api/tasks/manual")).json()
                assert state["run_count"] == 2
                assert state["last_output"]["summary"] == "started from API"
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_load_tasks_reads_model_and_ignores_retired_fields(tmp_path, monkeypatch):
    tasks_file = tmp_path / "tasks.yaml"
    tasks_file.write_text(
        "tasks:\n"
        "  - id: plain\n"
        "    skill: first\n"
        "  - id: old\n"
        "    skill: second\n"
        "    model: sonnet\n"
        "    allow_git_push: true\n"
        "    requires: [jira]\n"
        "    precheck: check-inbox --quiet\n"
    )
    monkeypatch.setattr(appmod.paths, "TASKS_FILE", tasks_file)
    plain, old = task_config.load_tasks()
    assert (plain.model, old.model) == ("", "sonnet")
    assert not old.unrestricted  # a retired privilege flag never grants anything
    assert old.requires == ["jira"] and old.precheck == "check-inbox --quiet"


def test_runner_starts_with_invalid_yaml_then_loads_repaired_tasks(tmp_path, monkeypatch):
    path = tmp_path / "tasks.yaml"
    path.write_text("tasks: [")
    monkeypatch.setattr(task_config.paths, "TASKS_FILE", path)
    runner = scheduler.TaskRunner(cache_dir=tmp_path, watch_config=False, reconcile_interval=0)
    spawned = []
    monkeypatch.setattr(runner, "_spawn", spawned.append)
    runner.start()
    assert not spawned
    path.write_text("tasks: [{id: repaired, skill: actor}]")
    runner._spawn_new_tasks()
    assert [task.id for task in spawned] == ["repaired"]
    asyncio.run(runner.stop())


def test_load_tasks_flags_fail_closed_on_non_boolean_values(tmp_path, monkeypatch):
    tasks_file = tmp_path / "tasks.yaml"
    tasks_file.write_text(
        "tasks:\n"
        "  - id: typo\n"
        "    skill: first\n"
        "    unrestricted: true.\n"
        "    writer: \"false\"\n"
        "  - id: real\n"
        "    skill: second\n"
        "    unrestricted: true\n"
    )
    monkeypatch.setattr(appmod.paths, "TASKS_FILE", tasks_file)

    typo, real = task_config.load_tasks()

    assert typo.unrestricted is False
    assert typo.writer is False
    assert real.unrestricted is True


def test_shipped_tasks_yaml_flags_are_real_booleans():
    import yaml
    from roosta import paths
    flags = ("weekdays_only", "writer", "unrestricted", "sensor")
    for task in yaml.safe_load((paths.CORE_SKILLS_DIR / "setup" / "references" / "starter-tasks.yaml").read_text())["tasks"]:
        assert "connection" not in task
        for flag in flags:
            assert isinstance(task.get(flag, False), bool), (task["id"], flag)


def test_skill_description_reads_and_compacts_local_frontmatter(tmp_path):
    skill_dir = tmp_path / ".claude" / "skills" / "daily-brief"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: daily-brief\n"
        "description: >-\n"
        "  Summarises the latest activity\n"
        "  without adding noise.\n"
        "---\n"
        "# Daily brief\n"
    )

    assert task_config.skill_description("daily-brief", tmp_path) == (
        "Summarises the latest activity without adding noise."
    )
    assert task_config.skill_description("../daily-brief", tmp_path) == ""

    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: daily-brief\n"
        "description: Summarises activity: briefly and clearly.\n"
        "---\n"
    )
    assert task_config.skill_description("daily-brief", tmp_path) == (
        "Summarises activity: briefly and clearly."
    )


def test_worker_skill_preview_uses_runner_lookup_order(monkeypatch, tmp_path):
    task = task_config.TaskConfig(id="brief-worker", skill="daily-brief", dir=str(tmp_path / "work"))
    monkeypatch.setattr(appmod, "load_tasks_map", lambda: {task.id: task})
    monkeypatch.setattr(appmod.paths, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(appmod.paths, "CORE_SKILLS_DIR", tmp_path / "core")
    roots = [Path(task.dir) / ".agents/skills", tmp_path / "home/.agents/skills", tmp_path / "core"]
    for root in roots:
        skill = root / task.skill / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"---\nname: daily-brief\n---\n# {root}\n")
    for root in (roots[2], roots[0], roots[1]):
        response = asyncio.run(appmod.api_task_skill(task.id))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert json.loads(response.body) == {
            "skill": task.skill, "content": (root / task.skill / "SKILL.md").read_text(),
        }
        (root / task.skill / "SKILL.md").unlink()
    assert asyncio.run(appmod.api_task_skill(task.id)).status_code == 404
    assert asyncio.run(appmod.api_task_skill("unknown")).status_code == 404


def test_unscheduled_skills_lists_workspace_skills_no_worker_runs(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(appmod.paths, "WORKSPACE", workspace)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(appmod.paths, "CORE_SKILLS_DIR", tmp_path / "core")
    for root, name in [(".agents/skills", "daily-brief"), (".agents/skills", "Skill-Auditor"),
                       (".claude/skills", "write-a-skill"), (".agents/skills", "actor"),
                       (".agents/skills", "sender"), (tmp_path / "home/.agents/skills", "global-only"),
                       (tmp_path / "core", "core-only")]:
        skill = (workspace / root if isinstance(root, str) else root) / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"---\nname: {name}\ndescription: Does {name}.\n---\n")
    (workspace / ".agents/skills/no-skill-file").mkdir()
    (workspace / ".agents/skills/.hidden").mkdir()
    (workspace / ".agents/skills/.hidden/SKILL.md").write_text("---\nname: hidden\n---\n")
    task = task_config.TaskConfig(id="brief", skill="daily-brief", dir=str(workspace))
    monkeypatch.setattr(appmod, "load_tasks_map", lambda: {task.id: task})

    response = asyncio.run(appmod.api_unscheduled_skills())

    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.body) == {"skills": [
        {"skill": "core-only", "description": "Does core-only."},
        {"skill": "Skill-Auditor", "description": "Does Skill-Auditor."},
        {"skill": "write-a-skill", "description": "Does write-a-skill."},
    ]}
    preview = asyncio.run(appmod.api_workspace_skill("write-a-skill"))
    assert preview.status_code == 200
    assert json.loads(preview.body)["content"].startswith("---\nname: write-a-skill")
    for refused in ("global-only", "no-skill-file", "../workspace", ".hidden"):
        assert asyncio.run(appmod.api_workspace_skill(refused)).status_code == 404


def test_workspace_skill_preview_rejects_symlinks_outside_the_skill_root(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod.paths, "WORKSPACE", tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    outside = tmp_path / "private.md"
    outside.write_text("must not be exposed")
    skill = tmp_path / ".agents/skills/leaky/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.symlink_to(outside)

    response = asyncio.run(appmod.api_workspace_skill("leaky"))

    assert response.status_code == 400
    assert "content" not in json.loads(response.body)


@pytest.mark.parametrize("problem", ["symlink", "large", "encoding", "traversal"])
def test_worker_skill_preview_rejects_unsafe_documents(monkeypatch, tmp_path, problem):
    task = task_config.TaskConfig(id="worker", skill="preview-test", dir=str(tmp_path))
    monkeypatch.setattr(appmod, "load_tasks_map", lambda: {task.id: task})
    monkeypatch.setattr(appmod.paths, "WORKSPACE", tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(appmod.paths, "CORE_SKILLS_DIR", tmp_path / "core")
    skill = tmp_path / ".agents/skills" / task.skill / "SKILL.md"
    skill.parent.mkdir(parents=True)
    if problem == "symlink":
        outside = tmp_path / "private.md"
        outside.write_text("must not be exposed")
        skill.symlink_to(outside)
    elif problem == "large":
        skill.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    elif problem == "encoding":
        skill.write_bytes(b"\xff")
    else:
        task.skill = "../private"
    response = asyncio.run(appmod.api_task_skill(task.id))
    assert response.status_code == (404 if problem == "traversal" else 400)
    assert "content" not in json.loads(response.body)


def test_runtime_model_list_parsers():
    from roosta import ai_runtime, cursor_agent
    cursor = cursor_agent.parse_cursor_models(
        "Available models\n\n"
        "auto - Auto (default)\n"
        "gpt-5.6-sol-high - GPT-5.6 Sol 1M High\n"
    )
    ollama = ai_runtime.parse_ollama_models(
        "NAME ID SIZE MODIFIED\n"
        "qwen3.5:latest abc 6.6 GB 1 day ago\n"
        "qwen3.5:9b-mlx def 8.9 GB 1 day ago\n"
    )
    assert cursor == [
        {"id": "auto", "label": "Auto (default)"},
        {"id": "gpt-5.6-sol-high", "label": "GPT-5.6 Sol 1M High"},
    ]
    assert [model["id"] for model in ollama] == ["qwen3.5:latest", "qwen3.5:9b-mlx"]


def test_settings_edit_identity_and_schedule_in_tasks_yaml(tmp_path, monkeypatch):
    tasks_file = tmp_path / "tasks.yaml"
    tasks_file.write_text(
        "tasks:\n"
        "  - id: local\n"
        "    skill: skill  # keep this comment\n"
        "    interval: 3600  # 1 hour\n"
        "    weekdays_only: true\n"
        "    writer: true  # and this one\n"
        "\n"
        "  - id: other\n"
        "    skill: skill\n"
    )
    task = task_config.TaskConfig(id="local", skill="skill", interval=3600, weekdays_only=True)
    runner = make_runner(tmp_path, [task], lambda _task: None)
    runner._tasks = runner._load_tasks()
    runner._states[task.id] = runner._load_state(task)
    runner._triggers[task.id] = asyncio.Event()

    state = runner.set_settings("local", {
        "name": "Local helper",
        "nickname": "Dwight",
        "description": "Does a thing: carefully # really",
        "schedule": {"mode": "daily", "run_at": "08:30", "days": "specific",
                     "days_of_week": ["friday", "monday"]},
    })

    assert (state["name"], state["nickname"]) == ("Local helper", "Dwight")
    assert state["description"] == state["custom_description"] == "Does a thing: carefully # really"
    assert (state["run_at"], state["days_of_week"], state["weekdays_only"]) == (
        "08:30", ["monday", "friday"], False)
    updated = tasks_file.read_text()
    assert "skill: skill  # keep this comment" in updated
    assert "writer: true  # and this one" in updated
    assert "weekdays_only" not in updated
    monkeypatch.setattr(appmod.paths, "TASKS_FILE", tasks_file)
    loaded = task_config.load_tasks_map()
    assert loaded["local"].nickname == "Dwight"
    assert loaded["local"].description == "Does a thing: carefully # really"
    assert loaded["local"].days_of_week == ["monday", "friday"]
    assert loaded["local"].run_at == "08:30"
    assert task_config._yaml_scalar("10:00") == '"10:00"'  # bare 10:00 is YAML base-60 600
    assert loaded["other"].nickname == ""

    runner.set_settings("local", {"nickname": "", "description": "",
                                  "schedule": {"mode": "interval", "interval": 7200, "days": "every"}})
    updated = tasks_file.read_text()
    assert "nickname" not in updated and "description" not in updated
    assert "run_at" not in updated and "days_of_week" not in updated
    assert "    interval: 7200\n" in updated  # stale "# 1 hour" goes with the old value
    assert runner.get_state("local")["run_at"] == ""


def test_settings_toggle_writer(tmp_path, monkeypatch):
    tasks_file = tmp_path / "tasks.yaml"
    tasks_file.write_text("tasks:\n  - id: local\n    skill: skill\n    writer: true  # serialise\n")
    task = task_config.TaskConfig(id="local", skill="skill", writer=True)
    runner = make_runner(tmp_path, [task], lambda _task: None)
    runner._states[task.id] = runner._load_state(task)
    runner._triggers[task.id] = asyncio.Event()
    assert runner.get_state("local")["writer"] is True

    state = runner.set_settings("local", {"writer": False})

    assert state["writer"] is False
    assert tasks_file.read_text() == "tasks:\n  - id: local\n    skill: skill\n"
    monkeypatch.setattr(appmod.paths, "TASKS_FILE", tasks_file)
    assert task_config.load_tasks_map()["local"].writer is False


def test_settings_unrestricted_api(tmp_path, monkeypatch):
    tasks_file = tmp_path / "tasks.yaml"
    tasks_file.write_text("tasks:\n  - id: local\n    skill: skill  # keep\n")
    monkeypatch.setattr(appmod.paths, "TASKS_FILE", tasks_file)
    task = task_config.load_tasks_map()["local"]
    runner = make_runner(tmp_path, [task], lambda _task: None)
    runner._states[task.id] = runner._load_state(task)
    runner._states[task.id].status = "running"
    monkeypatch.setattr(appmod, "runner", runner)
    url = "/api/tasks/local/settings"
    client = TestClient(appmod.app, base_url="http://localhost", client=("127.0.0.1", 1234))
    remote = TestClient(appmod.app, base_url="http://localhost", client=("192.0.2.1", 1234))
    assert remote.post(url, json={"unrestricted": True}).status_code == 403
    assert client.post(url, json={"unrestricted": True}, headers={"Origin": "https://other.invalid"}).status_code == 403
    assert client.get("/api/tasks").json()[0]["unrestricted"] is False
    assert client.post(url, json={"unrestricted": True}).json()["unrestricted"] is True
    assert task_config.load_tasks_map()["local"].unrestricted is True
    assert task.unrestricted is False  # executing run keeps its config
    assert remote.post(url, json={"nickname": "Helper"}).json()["unrestricted"] is True
    saved = tasks_file.read_bytes()
    for invalid in ("true", "false", 1, 0, None, {}, []):
        assert client.post(url, json={"unrestricted": invalid}).status_code == 400
    assert tasks_file.read_bytes() == saved
    assert client.post(url, json={"unrestricted": False}).json()["unrestricted"] is False
    assert task_config.load_tasks_map()["local"].unrestricted is False
    assert "skill: skill  # keep" in tasks_file.read_text()


def test_unrestricted_state_uses_config_at_startup_and_on_poll(tmp_path):
    task = task_config.TaskConfig(id="local", skill="skill", unrestricted=True)
    runner = make_runner(tmp_path, [task], lambda _task: pytest.fail("unexpected run"))
    assert runner._load_state(task).unrestricted is True
    cached_state(tmp_path / "cache", task.id)
    cache = tmp_path / "cache" / "local.json"
    cache.write_text(json.dumps({**json.loads(cache.read_text()), "unrestricted": False}))

    async def scenario():
        runner.start()
        try:
            assert runner.get_states()[0]["unrestricted"] is True
            task.unrestricted = False
            await wait_until(lambda: runner.get_states()[0]["unrestricted"] is False)
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_settings_reject_bad_input(tmp_path):
    tasks_file = tmp_path / "tasks.yaml"
    tasks_file.write_text("tasks:\n  - id: local\n    skill: skill\n")
    task = task_config.TaskConfig(id="local", skill="skill")
    runner = make_runner(tmp_path, [task], lambda _task: None)
    runner._states[task.id] = runner._load_state(task)
    runner._triggers[task.id] = asyncio.Event()
    for body in (
        {"nickname": "x" * 25},
        {"schedule": {"mode": "daily", "run_at": "25:00"}},
        {"schedule": {"mode": "interval", "interval": 10}},
        {"schedule": {"mode": "interval", "interval": 600, "days": "specific", "days_of_week": []}},
        {"writer": "true"},
    ):
        with pytest.raises(ValueError):
            runner.set_settings("local", body)
    assert tasks_file.read_text() == "tasks:\n  - id: local\n    skill: skill\n"


def test_runtime_options_list_ai_connections(monkeypatch):
    data = {"default": "a" * 32, "connections": [{"id": "a" * 32, "provider": "cursor"}]}
    monkeypatch.setattr(ai_settings.ai_connections, "load", lambda: data)
    monkeypatch.setattr(ai_settings.ai_backend, "default_connection", lambda: data["default"])
    assert asyncio.run(ai_settings.available_runtime_options()) == {
        "connections": data["connections"], "default_connection": "a" * 32}


def fake_connection_run(monkeypatch, text, captured=None):
    """Stand in for one AI connection run that prints `text`."""
    class Run:
        backend, env = "pi", {}
        session_id = "11111111-1111-4111-8111-111111111111"

        def text(self, output):
            return output

    def prepare(connection, workspace, **kwargs):
        if captured is not None:
            captured.update(connection=connection, workspace=workspace, **kwargs)
        return Run()

    async def stream(_run, prompt, **_kwargs):
        if captured is not None:
            captured["prompt"] = prompt
        yield text

    monkeypatch.setattr(scheduler.ai_backend, "prepare", prepare)
    monkeypatch.setattr(scheduler.ai_backend, "stream", stream)
    monkeypatch.setattr(scheduler.ai_connections, "get", lambda *_a, **_k: {"id": "c" * 32, "provider": "anthropic"})


@pytest.mark.parametrize("unrestricted,profile", [(False, "safe"), (True, "unrestricted")])
def test_run_task_runs_the_connection_and_parses_task_output(tmp_path, monkeypatch, unrestricted, profile):
    captured = {}
    fake_connection_run(monkeypatch, '<task-output>{"summary":"ok","status":"success","details":{"x":1}}</task-output>',
                        captured)
    status, output, error, session_id = asyncio.run(scheduler.run_task(
        task_config.TaskConfig(id="x", skill="skill", dir=str(tmp_path), unrestricted=unrestricted), idle_timeout=1))
    assert (status, error) == ("success", "")
    assert output == {"summary": "ok", "status": "success", "details": {"x": 1}}
    assert session_id == "11111111-1111-4111-8111-111111111111"
    assert captured["workspace"] == str(tmp_path) and captured["profile"] == profile
    assert "'skill'" in captured["prompt"] and "<task-output>" in captured["prompt"]


def test_run_task_without_an_ai_connection_says_how_to_add_one(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler.ai_connections, "load", lambda: {"default": "", "connections": []})
    status, _, error, _ = asyncio.run(scheduler.run_task(
        task_config.TaskConfig(id="x", skill="skill", dir=str(tmp_path)), idle_timeout=1))
    assert status == "error" and error == "Choose an AI connection in Settings"


@pytest.mark.parametrize("text", ["I am still checking the workspace.", "<task-output>not json</task-output>"])
def test_run_without_a_valid_task_output_is_an_error(tmp_path, monkeypatch, text):
    fake_connection_run(monkeypatch, text)
    status, output, error, _ = asyncio.run(scheduler.run_task(
        task_config.TaskConfig(id="x", skill="skill", dir=str(tmp_path)), idle_timeout=1))
    assert (status, output["status"]) == ("error", "unknown")
    assert error == "Harness did not return a valid <task-output> result"


@pytest.mark.parametrize("given,expected", [
    ("ok", "success"), ("complete", "success"), ("Completed", "success"),
    ("failed", "error"), ("maybe", "error"), ("partial", "error"),
])
def test_task_output_status_synonyms_are_normalised(tmp_path, monkeypatch, given, expected):
    fake_connection_run(monkeypatch, f"<task-output>{json.dumps({'summary': 's', 'status': given})}</task-output>")
    status, output, error, _ = asyncio.run(scheduler.run_task(
        task_config.TaskConfig(id="x", skill="skill", dir=str(tmp_path)), idle_timeout=1))
    assert status == expected
    assert output["summary"] == "s"
    assert bool(error) == (expected == "error")


def test_get_states_exposes_run_at_and_days(tmp_path):
    """A run_at task must surface its scheduled time and calendar restrictions through the API,
    not just an interval - the frontend can't render the schedule otherwise."""
    async def scenario():
        async def executor(task, **_):
            return "success", {"summary": "ok", "status": "success"}, "", ""

        runner = make_runner(tmp_path, [
            task_config.TaskConfig(
                id="timed",
                skill="s",
                run_at="09:00",
                weekdays_only=True,
                days_of_week=["monday"],
            ),
            task_config.TaskConfig(id="polled", skill="s", interval=3600),
        ], executor)
        runner.start()
        try:
            states = {s["id"]: s for s in runner.get_states()}
            assert states["timed"]["run_at"] == "09:00"
            assert states["timed"]["weekdays_only"] is True
            assert states["timed"]["days_of_week"] == ["monday"]
            assert states["polled"]["run_at"] == ""
            assert states["polled"]["weekdays_only"] is False
            assert states["polled"]["days_of_week"] == []
        finally:
            await runner.stop()

    asyncio.run(scenario())




def test_cancel_queued_clears_manual_trigger(tmp_path):
    async def scenario():
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def executor(task: task_config.TaskConfig, **_):
            if task.id == "writer-a":
                first_started.set()
                await release_first.wait()
            return "success", {"summary": "ran", "status": "success"}, "", "sess-1"

        runner = make_runner(
            tmp_path,
            [
                task_config.TaskConfig(id="writer-a", skill="skill", interval=3600, writer=True),
                task_config.TaskConfig(id="writer-b", skill="skill", interval=3600, writer=True),
            ],
            executor,
        )
        runner.start()
        try:
            assert runner.trigger("writer-a") is True
            await wait_until(first_started.is_set)
            assert runner.trigger("writer-b") is True
            await wait_until(lambda: runner.get_state("writer-b")["queued"] is True)
            assert runner.cancel_queued("writer-b") is True
            assert runner.get_state("writer-b")["queued"] is False
            release_first.set()
            await wait_until(lambda: runner.get_state("writer-a")["run_count"] >= 1)
            assert runner.get_state("writer-b")["run_count"] == 0
        finally:
            release_first.set()
            await runner.stop()

    asyncio.run(scenario())


def test_cancel_queued_rejects_running_task(tmp_path):
    async def scenario():
        release = asyncio.Event()

        async def executor(task: task_config.TaskConfig, **_):
            release.set()
            await asyncio.Event().wait()

        runner = make_runner(
            tmp_path,
            [task_config.TaskConfig(id="writer", skill="skill", interval=3600, writer=True)],
            executor,
        )
        runner.start()
        try:
            assert runner.trigger("writer") is True
            await wait_until(lambda: runner.get_state("writer")["status"] == "running")
            assert runner.cancel_queued("writer") is False
        finally:
            release.set()
            await runner.stop()

    asyncio.run(scenario())


def test_http_cancel_endpoint_drops_queued_run(tmp_path, monkeypatch):
    async def scenario():
        from httpx import ASGITransport, AsyncClient

        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def executor(task: task_config.TaskConfig, **_):
            if task.id == "writer-a":
                first_started.set()
                await release_first.wait()
            return "success", {"summary": "ran", "status": "success"}, "", ""

        runner = make_runner(
            tmp_path,
            [
                task_config.TaskConfig(id="writer-a", skill="skill", interval=3600, writer=True),
                task_config.TaskConfig(id="manual", skill="skill", interval=3600, writer=True),
            ],
            executor,
        )
        monkeypatch.setattr(appmod, "runner", runner)
        runner.start()
        try:
            assert runner.trigger("writer-a") is True
            await wait_until(first_started.is_set)
            transport = ASGITransport(app=appmod.app)
            async with AsyncClient(transport=transport, base_url="http://localhost") as client:
                assert (await client.post("/api/tasks/manual/run")).json() == {"triggered": True}
                await wait_until(lambda: runner.get_state("manual")["queued"] is True)
                response = await client.post("/api/tasks/manual/cancel")
                assert response.status_code == 200
                assert response.json() == {"cancelled": True}
                assert runner.get_state("manual")["queued"] is False
            release_first.set()
            await wait_until(lambda: runner.get_state("writer-a")["run_count"] >= 1)
            assert runner.get_state("manual")["run_count"] == 0
        finally:
            release_first.set()
            await runner.stop()

    asyncio.run(scenario())


def test_activity_records_session_id_from_task_run(tmp_path):
    async def scenario():
        async def executor(task: task_config.TaskConfig, **_):
            return "success", {"summary": "ran", "status": "success"}, "", "abcd-efgh"

        activity = FakeActivity()
        runner = scheduler.TaskRunner(
            task_loader=lambda: [task_config.TaskConfig(id="scheduled", skill="skill", interval=3600)],
            auth_checker=always_authed,
            task_executor=executor,
            activity_log=activity,
            cache_dir=tmp_path / "cache",
            tasks_file=tmp_path / "tasks.yaml",
            startup_delay=0,
            poll_interval=0.02,
            watch_config=False,
        )
        runner.start()
        try:
            await wait_until(lambda: runner.get_state("scheduled")["run_count"] >= 1)
            session_events = [e for e in activity.events if e.get("event") == "session"]
            assert session_events == [{"event": "session", "id": "act-1", "session_id": "abcd-efgh"}]
            start = next(e for e in activity.events if e["event"] == "start")
            assert start["backend"] == "connection"  # no AI connection is configured here
            finish = next(e for e in activity.events if e["event"] == "finish")
            assert finish["summary"] == "ran"
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_roosta_engineer_run_never_commits_the_workspace(tmp_path, monkeypatch):
    """Other sessions' pending .roosta/ edits stay theirs: no pre-run checkpoint commit."""
    async def scenario():
        spawned: list[tuple] = []

        async def no_subprocess(*args, **_):
            spawned.append(args)
            raise OSError("no subprocesses in this test")

        async def executor(task: task_config.TaskConfig, **_):
            return "success", {"summary": "ran", "status": "success"}, "", ""

        monkeypatch.setattr(appmod.asyncio, "create_subprocess_exec", no_subprocess)
        task = task_config.TaskConfig(id="roosta-engineer", skill="roosta-engineer", interval=3600, writer=True)
        runner = make_runner(tmp_path, [task], executor)
        status, *_ = await runner._run_task(task)
        assert status == "success" and spawned == []

    asyncio.run(scenario())


# --- activity log durability across runner restarts ---


def test_activity_hydrates_history_and_retires_stranded_running(tmp_path):
    """A restart must not empty the feed or leave a dead run showing as live."""
    log = tmp_path / "activity.jsonl"
    log.write_text(
        "\n".join([
            json.dumps({
                "id": "aaa", "kind": "skill", "label": "assistant", "source": "scheduled",
                "status": "running", "started": "2026-09-18T08:00:00+00:00",
            }),
            json.dumps({
                "id": "aaa", "kind": "skill", "label": "assistant", "source": "scheduled",
                "status": "success", "started": "2026-09-18T08:00:00+00:00", "duration": 12.0,
            }),
            json.dumps({
                "id": "bbb", "kind": "skill", "label": "skill-auditor", "source": "scheduled",
                "status": "running", "started": "2026-09-18T08:30:00+00:00",
            }),
            "{not json",
        ]) + "\n"
    )

    log_obj = ActivityLog()
    log_obj.hydrate(log)
    entries = {entry["id"]: entry for entry in log_obj.recent(50)}

    assert [entry["id"] for entry in log_obj.recent(50)] == ["aaa", "bbb"]
    assert entries["aaa"]["status"] == "success"
    assert entries["bbb"]["status"] == "interrupted"
    assert log_obj.running() == []


def test_activity_log_is_trimmed_to_its_newest_whole_lines_on_startup(tmp_path, monkeypatch):
    """The append-only log must not grow forever; the newest runs survive intact."""
    monkeypatch.setattr(ActivityLog, "KEEP_BYTES", 2000)
    log = tmp_path / "activity.jsonl"
    rows = [
        json.dumps({"id": f"r{i:04d}", "kind": "skill", "label": "assistant",
                    "source": "scheduled", "status": "success",
                    "started": f"2026-10-01T00:00:{i % 60:02d}+00:00"})
        for i in range(200)
    ]
    log.write_text("\n".join(rows) + "\n")
    ActivityLog().hydrate(log)
    assert log.stat().st_size > 2000  # importing app (hydrate) must never rewrite the log

    log_obj = ActivityLog()
    log_obj.compact(log)
    log_obj.hydrate(log)

    kept = log.read_text().splitlines()
    assert log.stat().st_size <= 2000
    assert kept[-1] == rows[-1]
    assert all(json.loads(line) for line in kept)  # no partial first record
    assert log_obj.recent(1)[0]["id"] in {json.loads(line)["id"] for line in kept}


def test_activity_hydrate_survives_a_missing_log(tmp_path):
    log_obj = ActivityLog()
    log_obj.hydrate(tmp_path / "nope.jsonl")
    assert log_obj.recent(10) == []


def _make_store(config_dir, uuid, age_days):
    """Create a fake Cursor CLI session store and backdate its files."""
    store = config_dir / "chats" / "hash0" / uuid
    store.mkdir(parents=True)
    db = store / "store.db"
    db.write_bytes(b"x" * 16)
    when = time.time() - age_days * 86400
    os.utime(db, (when, when))
    os.utime(store, (when, when))
    return store


def test_prune_removes_only_old_unreferenced_cursor_session_stores(tmp_path, monkeypatch):
    """Old scratch is reclaimed; recent or still-referenced stores survive intact."""
    safe = tmp_path / ("a" * 32) / "cursor"
    gitpush = tmp_path / ("b" * 32) / "cursor"
    monkeypatch.setattr(appmod.ai_connections, "CONNECTIONS_DIR", tmp_path)

    stale = _make_store(safe, "stale-0000", age_days=90)
    recent = _make_store(safe, "recent-0000", age_days=1)
    referenced = _make_store(safe, "keepme-0000", age_days=90)
    stale_push = _make_store(gitpush, "stale-push0", age_days=90)

    removed = cursor_sessions.prune_cursor_session_stores(referenced={"keepme-0000"})

    assert removed == 2
    assert not stale.exists()
    assert not stale_push.exists()
    assert recent.exists()       # inside the retention window
    assert referenced.exists()   # a resumable chat is never pulled from under the CLI


def test_only_tasks_that_require_a_connector_check_it_before_running(tmp_path):
    async def scenario():
        checks = []

        async def executor(task, **_):
            return "success", {"summary": "ran", "status": "success"}, "", ""

        runner = make_runner(
            tmp_path,
            [
                task_config.TaskConfig(id="watch", skill="watch", interval=3600, requires=["teams"]),
                task_config.TaskConfig(id="other", skill="assistant", interval=3600),
            ],
            executor,
            on_check=lambda: checks.append(1),
        )
        runner.start()
        try:
            await wait_until(lambda: runner.get_state("watch")["run_count"] == 1
                             and runner.get_state("other")["run_count"] == 1)
            assert checks == [1]
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_task_output_with_a_missing_or_extra_closing_brace_still_parses():
    missing = '<task-output>{"summary":"No incident changes.","status":"success","details":{"notes":"a {b} c"}</task-output>'
    extra = '<task-output>{"summary":"No new activity.","status":"success","details":{"auth":"ok"}}}</task-output>'
    assert scheduler.parse_task_output(missing)["status"] == "success"
    assert scheduler.parse_task_output(missing)["details"] == {"notes": "a {b} c"}
    assert scheduler.parse_task_output(extra)["summary"] == "No new activity."
    assert scheduler.parse_task_output("<task-output>not json</task-output>")["status"] == "unknown"


def test_task_output_quoted_in_prose_does_not_hide_the_real_block():
    text = 'It said "invalid <task-output> result". <task-output>{"summary": "ok", "status": "success"}</task-output>'
    assert scheduler.parse_task_output(text) == {"summary": "ok", "status": "success"}


def test_partial_pass_reports_its_own_summary_not_an_invalid_result(tmp_path, monkeypatch):
    payload = json.dumps({"summary": "Scan only: open-file refresh not done.", "status": "partial"})
    fake_connection_run(monkeypatch, f"<task-output>{payload}</task-output>")
    status, _, error, _ = asyncio.run(scheduler.run_task(
        task_config.TaskConfig(id="x", skill="skill", dir=str(tmp_path)), idle_timeout=1))
    assert (status, error) == ("error", "Scan only: open-file refresh not done.")


def test_daily_run_lost_to_the_network_retries_soon_but_real_errors_wait(tmp_path):
    async def scenario():
        calls: list[str] = []

        async def executor(task: task_config.TaskConfig, **_):
            calls.append(task.id)
            if calls.count(task.id) == 1:
                reason = ("API Error: Can't reach the API server — check your internet"
                          if task.id == "offline" else "Skill crashed")
                return "error", {}, reason, ""
            return "success", {"summary": "ran", "status": "success"}, "", ""

        tasks = [
            task_config.TaskConfig(id="offline", skill="s", interval=86400, run_at="00:00"),
            task_config.TaskConfig(id="broken", skill="s", interval=86400, run_at="00:00"),
        ]
        runner = make_runner(tmp_path, tasks, executor)
        runner._offline_retry = 0.1
        runner.start()
        try:
            await wait_until(lambda: runner.get_state("offline")["retry_at"])
            assert runner.get_state("offline")["status"] == "error"
            await wait_until(lambda: runner.get_state("offline")["status"] == "success")
            assert runner.get_state("offline")["retry_at"] == ""
            await asyncio.sleep(0.2)
            assert calls.count("offline") == 2
            assert calls.count("broken") == 1
            assert runner.get_state("broken")["retry_at"] == ""
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_offline_failure_matches_observed_messages_only():
    assert scheduler.is_offline_failure("API Error: Your computer went to sleep mid-response.")
    assert scheduler.is_offline_failure("\x1b[31m✗ Failed to reach the Cursor API.")
    assert scheduler.is_offline_failure("Error: [aborted] read ECONNRESET")
    assert not scheduler.is_offline_failure("Teams not connected - run `msteams login`.")


def test_a_task_added_to_tasks_yaml_starts_even_without_file_events(tmp_path):
    """Setup writes the schedule while the runner is up; a missed file event must not hide it."""
    async def scenario():
        tasks = []
        started = []

        async def executor(task, **_):
            started.append(task.id)
            return "success", {"summary": "ran", "status": "success"}, "", ""

        runner = scheduler.TaskRunner(
            task_loader=lambda: list(tasks), auth_checker=always_authed, task_executor=executor,
            connector_registry=FakeConnectors(), activity_log=FakeActivity(),
            cache_dir=tmp_path / "cache", tasks_file=tmp_path / "tasks.yaml", startup_delay=0,
            poll_interval=0.02, auth_retry_interval=0.02, weekday_interval=0.02,
            watch_config=False, reconcile_interval=0.05,
        )
        runner.start()
        try:
            tasks.append(task_config.TaskConfig(id="gardener", skill="workspace-gardener", interval=3600))
            await wait_until(lambda: started == ["gardener"])
            assert runner.get_state("gardener") is not None
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_firing_a_worker_removes_it_and_its_rubbish(tmp_path, monkeypatch):
    (tmp_path / "tasks.yaml").write_text(
        "tasks:\n  - id: local\n    skill: skill\n  - id: other\n    skill: skill\n")
    monkeypatch.setattr(appmod.paths, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state" / "local").mkdir(parents=True)
    (tmp_path / "state" / "local.json").write_text("{}")
    task = task_config.TaskConfig(id="local", skill="skill", interval=3600)
    runner = make_runner(tmp_path, [task], lambda _task: None)
    runner._states[task.id] = runner._load_state(task)
    runner._save_state(runner._states[task.id])
    runner._triggers[task.id] = asyncio.Event()

    assert runner.remove("local") is True
    assert "local" not in (tmp_path / "tasks.yaml").read_text()
    assert runner.get_state("local") is None
    assert not (tmp_path / "cache" / "local.json").exists()
    assert not (tmp_path / "state" / "local.json").exists()
    assert not (tmp_path / "state" / "local").exists()
    assert runner.remove("local") is False


def test_every_task_state_field_is_loaded_from_config_or_cache():
    """A new TaskState field must come from tasks.yaml or the run cache, or it silently resets."""
    from dataclasses import fields
    names = {f.name for f in fields(task_config.TaskState)}
    assert names == set(scheduler.CONFIG_FIELDS) | set(scheduler.RUN_FIELDS)


def test_load_state_restores_run_fields_and_ends_a_running_run(tmp_path):
    task = task_config.TaskConfig(id="t", skill="s", interval=60, nickname="Tess", days_of_week=["monday"])
    (tmp_path / "t.json").write_text(json.dumps({"status": "running", "run_count": 4, "last_run": "x",
                                                 "nickname": "stale"}))
    state = scheduler.TaskRunner(cache_dir=tmp_path, watch_config=False)._load_state(task)
    assert (state.status, state.run_count, state.last_run, state.nickname) == ("idle", 4, "x", "Tess")
    assert state.days_of_week == ["monday"] and state.days_of_week is not task.days_of_week
    (tmp_path / "t.json").write_text("[1, 2")
    assert scheduler.TaskRunner(cache_dir=tmp_path, watch_config=False)._load_state(task).run_count == 0
