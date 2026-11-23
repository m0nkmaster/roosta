"""Worker configuration: the task data model, `.roosta/tasks.yaml` loading and in-place edits."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from roosta import ai_backend, ai_connections, ai_runtime, paths
from roosta.claude_code import is_claude_model
from roosta.opencode_ollama import opencode_model_compatible

log = logging.getLogger(__name__)


CURSOR_HARNESS = "cursor"
CLAUDE_HARNESS = "claude"
OPENCODE_OLLAMA_HARNESS = "opencode-ollama"
VALID_HARNESSES = {CURSOR_HARNESS, CLAUDE_HARNESS, OPENCODE_OLLAMA_HARNESS}
HARNESS_LABELS = {
    CLAUDE_HARNESS: "Claude Code",
    CURSOR_HARNESS: "Cursor",
    OPENCODE_OLLAMA_HARNESS: "Ollama (OpenCode)",
}
def resolve_harness(value) -> str:
    """A task's concrete harness. Unset follows the Chats tab's Engine picker."""
    harness = str(value or "").strip()
    if not harness:
        if ai_backend.default_connection():
            return "connection"
        return CLAUDE_HARNESS if ai_backend.current() == ai_backend.CLAUDE else CURSOR_HARNESS
    return harness


@dataclass
class TaskConfig:
    id: str
    skill: str
    description: str = ""   # effective: custom_description, else the skill's own
    name: str = ""          # display name in the Skill runner; empty means the id
    nickname: str = ""      # what the Office calls this worker; empty means the id
    custom_description: str = ""  # tasks.yaml `description:` override
    interval: int = 1800
    dir: str = str(paths.WORKSPACE)
    harness: str = CURSOR_HARNESS  # cursor, claude or opencode-ollama; see resolve_harness
    model: str = ""  # Cursor or Ollama model; empty means CURSOR_MODEL, else the harness's own default
    connection: str = ""    # stable named connection id; empty follows the connected default
    claude_model: str = ""    # Claude Code model; empty means CLAUDE_MODEL
    run_at: str = ""          # HH:MM local time; run once per day at this time
    weekdays_only: bool = False  # skip Saturday and Sunday when True
    days_of_week: list[str] = field(default_factory=list)  # lowercase day names; empty means every day
    writer: bool = False      # rewrites vault docs / auto-commits; serialised against other writers
    sensor: bool = False      # feeds the board; board health warns when it fails or goes stale
    allow_git_push: bool = False  # narrowly privileged scheduled repository refresh
    push_on_schedule: bool = False  # timer runs may push too; otherwise only Run now pushes
    unrestricted: bool = False  # standing approval for external actions explicitly directed by this worker
    requires: list[str] = field(default_factory=list)  # connector ids that must be signed in
    precheck: str = ""  # cheap command; exit 1 means nothing changed, so skip the model run
    idle_timeout: float = 0   # override TASK_IDLE_TIMEOUT for this task (0 = default)
    max_timeout: float = 0    # override TASK_MAX_TIMEOUT for this task (0 = default)


@dataclass
class TaskState:
    id: str
    skill: str
    interval: int
    description: str = ""
    name: str = ""
    nickname: str = ""
    custom_description: str = ""
    harness: str = CURSOR_HARNESS
    model: str = ""
    connection: str = ""    # stable named connection id; empty follows the connected default
    claude_model: str = ""
    run_at: str = ""
    weekdays_only: bool = False
    days_of_week: list[str] = field(default_factory=list)
    writer: bool = False
    unrestricted: bool = False
    sensor: bool = False
    requires: list[str] = field(default_factory=list)
    status: str = "idle"  # idle, running, success, error, auth-failed, blocked
    last_run: str = ""
    last_duration: float = 0.0
    last_output: dict = field(default_factory=dict)
    run_count: int = 0
    last_error: str = ""
    retry_at: str = ""  # ISO time a run lost to the network/sleep is retried


# --- Config loading ---


def skill_files(skill: str, working_dir: str | Path) -> list[Path]:
    """Existing SKILL.md files for a skill, in the order the runner prefers them."""
    from roosta.skills import find_skill_files
    return find_skill_files(skill, working_dir, paths.WORKSPACE, paths.CORE_SKILLS_DIR)


def skill_description(skill: str, working_dir: str | Path) -> str:
    """Read a skill's description from the first matching SKILL.md."""
    from roosta.workspace import read_document
    try:
        files = skill_files(skill, working_dir)
    except (ValueError, OSError, RuntimeError):
        return ""
    for candidate in files:
        try:
            _, text, _ = read_document(candidate.parent.parent, f"{skill}/SKILL.md")
        except (ValueError, OSError):
            continue
        frontmatter = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.DOTALL)
        if not frontmatter:
            continue
        raw_metadata = frontmatter.group(1)
        try:
            metadata = yaml.safe_load(raw_metadata)
        except yaml.YAMLError:
            metadata = None
        description = metadata.get("description") if isinstance(metadata, dict) else None
        if isinstance(description, str):
            return " ".join(description.split())
        # Some existing skills have an unquoted colon in a one-line description,
        # which strict YAML rejects even though skill loaders accept it.
        fallback = re.search(r"^description:\s*(.+)$", raw_metadata, re.MULTILINE)
        if fallback and fallback.group(1).strip() not in {"|", ">", "|-", ">-"}:
            return " ".join(fallback.group(1).split())
    return ""


# The dashboard invokes these core skills itself; putting one on a schedule would be a mistake.
DASHBOARD_SKILLS = frozenset({"actor", "sender"})


def workspace_skills() -> list[str]:
    """Names of the skills this workspace holds, from its own skill roots only."""
    names: set[str] = set()
    for root in (paths.WORKSPACE / ".agents" / "skills", paths.WORKSPACE / ".claude" / "skills",
                 paths.WORKSPACE / ".cursor" / "skills", paths.CORE_SKILLS_DIR,
                 paths.WORKSPACE / ".roosta/skill-forks"):
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if (re.fullmatch(r"[A-Za-z0-9._-]{1,100}", entry.name) and not entry.name.startswith(".")
                    and (entry / "SKILL.md").is_file()):
                names.add(entry.name)
    return sorted(names, key=str.lower)


def unscheduled_skills(tasks) -> list[dict]:
    """Workspace skills no task runs, with their own descriptions, for the Workers page."""
    scheduled = {t.skill for t in tasks}
    return [{"skill": name, "description": skill_description(name, paths.WORKSPACE)}
            for name in workspace_skills() if name not in scheduled and name not in DASHBOARD_SKILLS]


def runtime_model_key(harness: str) -> str:
    """The tasks.yaml field holding the model for this harness.

    Cursor and Claude Code model names are disjoint, so Claude keeps its own
    field and switching a task between them never loses the other's pick.
    """
    return "claude_model" if harness == CLAUDE_HARNESS else "model"


def connection_task_model(task: TaskConfig, connection: dict) -> str:
    """The model a connection-backed worker runs: its own field when valid for the provider, else the default."""
    provider = connection["provider"]
    candidate = task.claude_model if provider == "anthropic" else task.model
    try:
        ai_connections.runtime(provider, candidate)
        # `model` is shared with Cursor/Ollama workers, so Pi providers need the harness's own list.
        if provider in {"openai", "openrouter"} and candidate not in ai_runtime.model_catalog(provider):
            raise ValueError("Not offered by this provider")
        return candidate
    except (ValueError, OSError):
        return ai_connections.default_model(provider)


def task_engine(task: TaskConfig) -> str:
    """Which engine runs this task: the session store its transcript lands in."""
    if task.connection or task.harness == "connection":
        try:
            connection = ai_connections.get(task.connection)
            return ai_connections.engine(connection["provider"])
        except ValueError:
            return "connection"
    if task.harness == OPENCODE_OLLAMA_HARNESS:
        return "opencode"
    return ai_backend.CLAUDE if task.harness == CLAUDE_HARNESS else ai_backend.CURSOR


def valid_runtime(harness: str, model: str) -> bool:
    """Validate persisted runtime selectors before they reach a subprocess."""
    if harness == CLAUDE_HARNESS:
        return is_claude_model(model)
    if harness == CURSOR_HARNESS:
        return bool(re.fullmatch(r"[A-Za-z0-9._-]{1,100}", model))
    if harness == OPENCODE_OLLAMA_HARNESS:
        return (
            bool(re.fullmatch(r"[A-Za-z0-9._:/-]{1,120}", model))
            and opencode_model_compatible(model)
        )
    return False


def update_task_runtime(
    path: Path, task_id: str, harness: str, model: str, model_key: str = "model",
) -> None:
    """Update one task's runtime fields without discarding YAML comments."""
    if model_key != runtime_model_key(harness):
        raise ValueError("invalid model field")
    if not valid_runtime(harness, model):
        raise ValueError("invalid harness or model")
    update_task_fields(path, task_id, {"harness": harness, model_key: model})


EDITABLE_TASK_FIELDS = {
    "name", "nickname", "description", "harness", "model", "claude_model", "connection",
    "interval", "run_at", "weekdays_only", "days_of_week",
    "writer", "unrestricted",
}
TASK_SETTING_FLAGS = ("writer", "unrestricted")
DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
TASK_NAME_MAX = 60
TASK_NICKNAME_MAX = 24
TASK_DESCRIPTION_MAX = 500
TASK_INTERVAL_MIN = 60
TASK_INTERVAL_MAX = 30 * 86400


def _yaml_scalar(value) -> str:
    """One-line YAML for a tasks.yaml value; strings are quoted only when YAML
    would otherwise read them differently ("08:00" is a base-60 int unquoted)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_scalar(item) for item in value) + "]"
    text = str(value)
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        return json.dumps(text)  # house style: times always quoted, as YAML may read them as numbers
    try:
        bare_ok = (
            text == text.strip() and "#" not in text and "\n" not in text
            and yaml.safe_load(f"k: {text}") == {"k": text}
        )
    except yaml.YAMLError:
        bare_ok = False
    return text if bare_ok else json.dumps(text, ensure_ascii=False)


_TASK_LINE = re.compile(r"^(\s*)-\s+id:\s*([A-Za-z0-9._-]+)(?:\s+#.*)?\s*$")


def _task_block(lines: list[str], task_id: str) -> tuple[int, int, str]:
    """(start, end, indent) of one task's lines in tasks.yaml; end is the next task's line."""
    start = next(
        (index for index, line in enumerate(lines)
         if (match := _TASK_LINE.match(line.rstrip("\r\n"))) and match.group(2) == task_id),
        None,
    )
    if start is None:
        raise ValueError("task not found in tasks.yaml")
    indent = _TASK_LINE.match(lines[start].rstrip("\r\n")).group(1)
    end = next(
        (index for index in range(start + 1, len(lines))
         if (match := _TASK_LINE.match(lines[index].rstrip("\r\n")))
         and match.group(1) == indent),
        len(lines),
    )
    # Leave comment lines that sit directly above the next task with that task.
    while end > start + 1 and end < len(lines) and lines[end - 1].lstrip().startswith("#"):
        end -= 1
    return start, end, indent


def remove_task(path: Path, task_id: str) -> None:
    """Delete one task's block from tasks.yaml, keeping every other line and comment."""
    destination = Path(path)
    lines = destination.read_text().splitlines(keepends=True)
    start, end, _ = _task_block(lines, task_id)
    del lines[start:end]
    updated = "".join(lines)
    parsed = yaml.safe_load(updated) or {}
    if any(item.get("id") == task_id for item in parsed.get("tasks") or []):
        raise ValueError("updated tasks.yaml did not validate")
    temporary = destination.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(updated)
    temporary.replace(destination)


def update_task_fields(
    path: Path, task_id: str, values: dict, remove: Iterable[str] = (),
) -> None:
    """Set or remove top-level fields of one task, keeping every other line and comment.

    A field's trailing comment survives only while its value is unchanged, so an
    edited `interval: 3600  # 1 hour` does not keep a now-wrong note.
    """
    remove = set(remove) - set(values)
    unknown = (set(values) | remove) - EDITABLE_TASK_FIELDS
    if unknown:
        raise ValueError(f"field not editable: {', '.join(sorted(unknown))}")
    destination = Path(path)
    lines = destination.read_text().splitlines(keepends=True)
    start, end, indent = _task_block(lines, task_id)
    field_indent = indent + "  "
    keys = "|".join(re.escape(key) for key in sorted(set(values) | remove))
    field_pattern = re.compile(
        rf"^{re.escape(field_indent)}({keys}):[ \t]*(.*?)(\r?\n)?$"
    )
    found: set[str] = set()
    index = start + 1
    while index < end:
        match = field_pattern.match(lines[index])
        if not match:
            index += 1
            continue
        key, raw, newline = match.group(1), match.group(2), match.group(3) or "\n"
        # Swallow a block scalar's continuation lines along with the key.
        stop = index + 1
        while stop < end and lines[stop].strip() and (
            len(lines[stop]) - len(lines[stop].lstrip()) > len(field_indent)
        ):
            stop += 1
        if key in remove:
            del lines[index:stop]
            end -= stop - index
            continue
        value_part, _, comment_part = raw.partition(" #")
        rendered = _yaml_scalar(values[key])
        comment = f"  #{comment_part}" if comment_part and value_part.strip() == rendered else ""
        lines[index:stop] = [f"{field_indent}{key}: {rendered}{comment}{newline}"]
        end -= stop - index - 1
        found.add(key)
        index += 1

    missing = [key for key in values if key not in found]
    if missing:
        insert_at = next(
            (index + 1 for index in range(start + 1, end)
             if re.match(rf"^{re.escape(field_indent)}skill:", lines[index])),
            start + 1,
        )
        additions = [f"{field_indent}{key}: {_yaml_scalar(values[key])}\n" for key in missing]
        lines[insert_at:insert_at] = additions

    updated = "".join(lines)
    parsed = yaml.safe_load(updated)
    task = next(
        (item for item in parsed.get("tasks", []) if item.get("id") == task_id),
        None,
    )
    if (
        not isinstance(task, dict)
        or any(task.get(key) != value for key, value in values.items())
        or any(key in task for key in remove)
    ):
        raise ValueError("updated tasks.yaml did not validate")
    temporary = destination.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(updated)
    temporary.replace(destination)


def _one_line(value, limit: int, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    text = " ".join(value.split())
    if len(text) > limit:
        raise ValueError(f"{label} must be {limit} characters or fewer")
    return text


def task_settings_changes(body: dict) -> tuple[dict, set[str]]:
    """Validate a Skill runner settings form into tasks.yaml edits.

    Only keys present in the body change. Empty name, nickname or description
    remove the field, so the task falls back to its id or skill description.
    Harness and model are handled separately because they need the live engine.
    """
    values: dict = {}
    remove: set[str] = set()
    for key, limit in (("name", TASK_NAME_MAX), ("nickname", TASK_NICKNAME_MAX),
                       ("description", TASK_DESCRIPTION_MAX)):
        if key in body:
            text = _one_line(body[key] if body[key] is not None else "", limit, key)
            if text:
                values[key] = text
            else:
                remove.add(key)
    # Flags are written only when on, so an off flag leaves no line in tasks.yaml.
    for key in TASK_SETTING_FLAGS:
        if key in body:
            if not isinstance(body[key], bool):
                raise ValueError(f"{key} must be true or false")
            if body[key]:
                values[key] = True
            else:
                remove.add(key)
    schedule = body.get("schedule")
    if schedule is None:
        return values, remove
    if not isinstance(schedule, dict):
        raise ValueError("schedule must be an object")
    mode = schedule.get("mode")
    if mode == "interval":
        interval = schedule.get("interval")
        if isinstance(interval, bool) or not isinstance(interval, int) or not (
            TASK_INTERVAL_MIN <= interval <= TASK_INTERVAL_MAX
        ):
            raise ValueError("interval must be between 1 minute and 30 days")
        values["interval"] = interval
        remove.add("run_at")
    elif mode == "daily":
        run_at = str(schedule.get("run_at", ""))
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", run_at):
            raise ValueError("time must be HH:MM")
        values["run_at"] = run_at
    else:
        raise ValueError("schedule mode must be interval or daily")
    days = schedule.get("days", "every")
    if days == "every":
        remove |= {"weekdays_only", "days_of_week"}
    elif days == "weekdays":
        values["weekdays_only"] = True
        remove.add("days_of_week")
    elif days == "specific":
        picked = schedule.get("days_of_week")
        if not isinstance(picked, list) or not picked or any(day not in DAY_NAMES for day in picked):
            raise ValueError("choose at least one day")
        values["days_of_week"] = [day for day in DAY_NAMES if day in picked]
        remove.add("weekdays_only")
    else:
        raise ValueError("days must be every, weekdays or specific")
    return values, remove


def _task_flag(task: dict, key: str) -> bool:
    """Only a real YAML boolean switches a task flag on. A typo such as `true.` or
    a quoted "false" is truthy to bool(), which would silently grant privilege
    flags like `unrestricted`, so anything else fails closed with a warning."""
    value = task.get(key, False)
    if isinstance(value, bool):
        return value
    log.warning("Task %s: %s must be true or false, got %r - treating as false",
                task.get("id"), key, value)
    return False


def load_tasks() -> list[TaskConfig]:
    if not paths.TASKS_FILE.is_file():
        log.warning("No tasks.yaml found at %s", paths.TASKS_FILE)
        return []
    with open(paths.TASKS_FILE) as f:
        data = yaml.safe_load(f)
    tasks = []
    for t in data.get("tasks", []):
        if t.get("script"):
            log.warning("Task %s has a 'script:' key; script tasks are no longer supported", t.get("id"))
            continue
        working_dir = str((paths.WORKSPACE / Path(t.get("dir", ".")).expanduser()).resolve())
        custom_description = str(t.get("description", "") or "").strip()
        connection = str(t.get("connection") or "")
        if connection == "default":  # Read old files without keeping the sentinel alive.
            connection = ""
        tasks.append(TaskConfig(
            id=t["id"],
            skill=t["skill"],
            description=custom_description or skill_description(t["skill"], working_dir),
            name=str(t.get("name", "") or "").strip(),
            nickname=str(t.get("nickname", "") or "").strip(),
            custom_description=custom_description,
            interval=t.get("interval", 1800),
            dir=working_dir,
            harness="connection" if connection or ai_backend.default_connection() else resolve_harness(t.get("harness")),
            connection=connection,
            model=str(t.get("model", "") or ""),
            claude_model=str(t.get("claude_model", "") or ""),
            run_at=t.get("run_at", ""),
            weekdays_only=_task_flag(t, "weekdays_only"),
            days_of_week=[str(day).lower() for day in t.get("days_of_week", [])],
            writer=_task_flag(t, "writer"),
            sensor=_task_flag(t, "sensor"),
            allow_git_push=_task_flag(t, "allow_git_push"),
            push_on_schedule=_task_flag(t, "push_on_schedule"),
            unrestricted=_task_flag(t, "unrestricted"),
            requires=_task_requires(t),
            precheck=str(t.get("precheck", "") or "").strip(),
            idle_timeout=float(t.get("idle_timeout", 0) or 0),
            max_timeout=float(t.get("max_timeout", 0) or 0),
        ))
    return tasks


def _task_requires(t: dict) -> list[str]:
    """Connector ids a task needs."""
    raw = t.get("requires") or []
    return [str(c).strip().lower() for c in (raw if isinstance(raw, list) else [raw]) if str(c).strip()]


def load_tasks_map() -> dict[str, TaskConfig]:
    return {t.id: t for t in load_tasks()}
