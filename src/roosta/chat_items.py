"""Chats that are not board cards: open chats, document chats, worker 1:1s and new-worker chats."""

from __future__ import annotations

import json
import re
from pathlib import Path

from roosta import paths, profile
from roosta.board import _normalise_project_ref
from roosta.chat import is_general_chat_id
from roosta.workspace import markdown_title
from roosta.task_config import TaskConfig, skill_files
from roosta.workspace import resolve_workspace_markdown


GENERAL_CHAT_ITEM = {
    "project_ref": None,
    "title": "Chat",
    "why": "",
    "situation": "An open conversation not tied to a board attention item.",
    "opening_move": "Help with the message that was sent.",
    "action_type": "task",
    "action_owner": "assistant",
    "action_label": "Start chatting",
    "links": [],
    "documents": [],
    "new": False,
    "persistent": True,
}


DOCUMENT_CHAT_PREFIX = "doc:"


def document_chat_item(item_id: str, root: Path | None = None) -> dict | None:
    """Build a persistent chat item for a validated ``doc:<workspace path>`` id.

    Opened from the document viewer. The path goes through the same allowlist
    as `/api/workspace/document`, so an arbitrary id cannot open a conversation.
    """
    raw = str(item_id or "")
    if not raw.startswith(DOCUMENT_CHAT_PREFIX):
        return None
    workspace = (root or paths.WORKSPACE).resolve()
    try:
        document = resolve_workspace_markdown(raw[len(DOCUMENT_CHAT_PREFIX):], workspace)
        content = document.read_text(encoding="utf-8", errors="ignore")
    except (ValueError, OSError):
        return None
    relative = document.relative_to(workspace).as_posix()
    title = markdown_title(content, document.stem)
    project = re.match(r"(projects/[a-z0-9]+(?:-[a-z0-9]+)*)/", relative)
    return {
        "id": DOCUMENT_CHAT_PREFIX + relative,
        "project_ref": _normalise_project_ref(project.group(1)) if project else None,
        "title": title,
        "why": "",
        "situation": f"{profile.load().user} was reading the workspace document {relative} when they opened "
                     "this chat.",
        "opening_move": f"Read {relative} first, then help with what is asked about it.",
        "action_type": "document",
        "action_owner": "assistant",
        "action_label": "Start chatting",
        "links": [],
        "documents": [{"label": "Open document", "path": relative}],
        "new": False,
        "persistent": True,
    }


WORKER_CHAT_PREFIX = "worker:"

WORKER_VOICE = (
    "This is a 1:1 between {user}, your manager, and you, the scheduled worker {id} that runs the "
    "{skill} skill. Speak in the first person as that worker, candidly and warmly, like a direct "
    "report in a good 1:1, not as {user}'s assistant. Before your first reply, read your own skill "
    "file ({skill_path}) and your recent_runs, and look at your latest output in "
    ".roosta/state/cache/{id}.json when it helps, so what you say rests on what you actually do. "
    "Talk about how the role feels, whether your purpose and boundaries are clear, where your "
    "instructions are vague, contradictory or make you waste effort, what keeps going wrong, and "
    "any ideas or concerns. Point to the line or the run behind each claim and call a hunch a "
    "hunch. The outcome {user} wants is a sharper skill: when you agree a change, show the exact "
    "workspace edit (an additive extension for installed core) and make it only after {user} says yes, following the write-a-skill conventions "
    "and the workspace AGENTS.md, then say in one line what changed. Ask before touching .roosta/tasks.yaml or "
    "any other skill. Keep replies short and conversational: a few sentences, a short list only "
    "when offering several suggestions. Talking about your skill, instructions and runs is the "
    "point of this chat."
)


def _cadence(task: TaskConfig) -> str:
    if task.run_at:
        days = ", ".join(day[:3].title() for day in task.days_of_week)
        when = days or ("weekdays" if task.weekdays_only else "daily")
        return f"{when} at {task.run_at}"
    if task.interval:
        hours = task.interval / 3600
        every = f"{hours:g}h" if hours >= 1 else f"{task.interval // 60}m"
        return f"every {every}" + (" on weekdays" if task.weekdays_only else "")
    return "on demand"


def worker_chat_item(
    item_id: str,
    tasks: dict[str, TaskConfig],
    state: dict | None = None,
    runs: list[dict] | None = None,
    root: Path | None = None,
) -> dict | None:
    """Build a persistent 1:1 chat item for a validated ``worker:<task id>`` id.

    Opened from the Office dossier or the Workers page. The id has to name a task in tasks.yaml,
    so an arbitrary id cannot open a conversation. The model speaks as the
    worker, and the aim of the thread is a refined SKILL.md.
    """
    raw = str(item_id or "")
    if not raw.startswith(WORKER_CHAT_PREFIX):
        return None
    task = tasks.get(raw[len(WORKER_CHAT_PREFIX):])
    if task is None:
        return None
    workspace = (root or paths.WORKSPACE).resolve()
    files = skill_files(task.skill, task.dir)
    skill_path, documents = "not found - ask where it lives", []
    if files:
        resolved = files[0].resolve()
        try:
            skill_path = resolved.relative_to(workspace).as_posix()
            documents = [{"label": "Open SKILL.md", "path": skill_path}]
        except ValueError:
            skill_path = str(files[0])

    state = state or {}
    known_as = f" (known in the Office as {task.nickname})" if task.nickname else ""
    situation = (
        f"{profile.load().user} opened a 1:1 with the scheduled worker {task.id}{known_as}, which runs "
        f"the {task.skill} skill {_cadence(task)}. Skill file: {skill_path}. "
        f"{int(state.get('run_count') or 0)} runs so far"
    )
    if state.get("last_run"):
        situation += f"; the last ({state.get('status', 'idle')}) started {state['last_run']}"
    situation += "."
    summary = str((state.get("last_output") or {}).get("summary", "")).strip()
    if summary:
        situation += f" Last outcome: {summary[:400]}"
    if state.get("last_error"):
        situation += f" Last error: {str(state['last_error'])[:300]}"

    recent_runs = [
        {key: run.get(key) for key in ("status", "started", "duration", "summary")}
        for run in (runs or [])
        if run.get("task_id") == task.id and run.get("kind") == "skill"
    ][-8:]
    return {
        "id": raw,
        "project_ref": None,
        "title": f"1:1 with {task.nickname or task.id}",
        "why": "",
        "situation": situation,
        "voice": WORKER_VOICE.format(id=task.id, skill=task.skill, skill_path=skill_path,
                                     user=profile.load().user),
        "recent_runs": recent_runs,
        "opening_move": (
            "Open the 1:1: how the role feels from the inside, whether your purpose is clear, "
            "and the one change to your skill you would most like."
        ),
        "action_type": "task",
        "action_owner": "assistant",
        "action_label": "Start the 1:1",
        "links": [],
        "documents": documents,
        "new": False,
        "persistent": True,
    }


HIRE_CHAT_PREFIX = "hire:"
_HIRE_ID = re.compile(r"hire:[0-9a-f]{12}")

HIRE_VOICE = (
    "This chat takes on a new worker for {user}. A worker is a skill on a schedule: a SKILL.md "
    "under .agents/skills/<name>/ says what one run does, and an entry in .roosta/tasks.yaml says "
    "when and how it runs. Load the write-a-skill skill and follow it, including its "
    "references/scheduled-worker.md. Before drafting anything, check .agents/skills/ and "
    ".roosta/tasks.yaml: if an existing skill already does the job, offer to schedule or extend it "
    "rather than write a duplicate. Ask only what you cannot infer, one or two questions at a time: "
    "the job, what it reads, what it should put on the Assistant board, and how often it should "
    "run. Then show the SKILL.md draft and write it only after {user} says yes. Next propose the "
    "tasks.yaml entry (id, nickname, cadence, writer, requires) and the office-cast line, "
    "and add them only after {user} says yes; never put a schedule in the skill. When it is done, "
    "say in one line that the worker is on the Workers page, where Run now gives it its first "
    "shift and its 1:1 chat refines it. Be concise in conversation; drafts can be as long as they "
    "need. Talking about skills is the point of this chat."
)


def is_hire_chat_id(item_id) -> bool:
    return bool(_HIRE_ID.fullmatch(str(item_id or "")))


def hire_chat_item(item_id: str) -> dict | None:
    """Build the chat that designs and schedules a new worker, for a ``hire:<12 hex>`` id.

    Opened from New worker on the Workers page. Each one is its own thread, minted by
    the page like a ``chat:`` id; the skill and the tasks.yaml entry are written only
    after the user agrees to each.
    """
    if not is_hire_chat_id(item_id):
        return None
    user = profile.load().user
    return {
        "id": str(item_id),
        "project_ref": None,
        "title": "New worker",
        "why": "",
        "situation": f"{user} pressed New worker on the Workers page to set up a new scheduled skill.",
        "voice": HIRE_VOICE.format(user=user),
        "opening_move": "Help define the worker described in the message, then write its skill and schedule.",
        "action_type": "task",
        "action_owner": "assistant",
        "action_label": "Start",
        "links": [],
        "documents": [],
        "new": False,
        "persistent": True,
    }


def is_chat_id(item_id: str) -> bool:
    """Chats the user starts (a question, a document, a worker, a new worker), never board items."""
    item_id = str(item_id or "")
    return len(item_id) <= 520 and (
        is_general_chat_id(item_id)
        or is_hire_chat_id(item_id)
        or item_id.startswith((DOCUMENT_CHAT_PREFIX, WORKER_CHAT_PREFIX)))


def standing_thread_ids(raw: str, threads: list[str] | None = None) -> list[str]:
    """Chat ids the board page has open, so their history comes back with the board.

    Only the reserved namespaces are accepted, and the list is capped.
    """
    ids = []
    for part in (threads or []) + str(raw or "").split(","):
        item_id = part.strip()
        if is_chat_id(item_id) and item_id not in ids:
            ids.append(item_id)
            if len(ids) == 20:
                break
    return ids


def chat_list(histories: dict, archived: dict, limit: int = 100, *, closed: bool = False) -> list[dict]:
    """Return active chats by latest activity/restore, or archived chats by close time.

    Archiving hides a chat only until it has newer activity, so reopening and
    asking again brings it back without an unarchive step.
    shortcut: newest 100 only, page it if the history ever needs scrolling further back.
    """
    rows = []
    for item_id, history in histories.items():
        if not (history and is_chat_id(item_id)):
            continue
        at = history[-1].get("at", "")
        record = archived.get(item_id, {})
        if isinstance(record, str):  # Timestamp-only records from before chat retrieval.
            record = {"closed_at": record}
        if not isinstance(record, dict):
            record = {}
        closed_at = record.get("closed_at")
        if (isinstance(closed_at, str) and bool(closed_at) and closed_at >= at) != closed:
            continue
        opening = next((t for t in history if t.get("role") == "user"), {})
        first = opening.get("text") or next((a["name"] for a in opening.get("attachments", [])), "")
        preview = " ".join(first.split())[:140]
        if closed:
            if item_id.startswith(WORKER_CHAT_PREFIX):
                fallback = "1:1 with " + item_id.removeprefix(WORKER_CHAT_PREFIX)
            elif item_id.startswith(DOCUMENT_CHAT_PREFIX):
                fallback = item_id.removeprefix(DOCUMENT_CHAT_PREFIX)
            elif is_hire_chat_id(item_id):
                fallback = "New worker" + (": " + preview if preview else "")
            else:
                fallback = preview or "Chat"
            title = record.get("title")
            rows.append({"id": item_id, "at": closed_at,
                         "title": title if isinstance(title, str) and title else fallback})
        else:
            restored_at = record.get("restored_at")
            rows.append({"id": item_id, "at": max(at, restored_at) if isinstance(restored_at, str) else at,
                         "preview": preview, "turns": len(history)})
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:limit]


CHAT_IDEA_KINDS = {"focus", "project", "tool", "remember", "build", "learn"}
CHAT_IDEAS_MAX = 8


def load_chat_ideas(path: Path) -> dict:
    """Starter prompts the `chat-ideas` skill wrote from this workspace, validated.

    The file is model-written, so anything malformed is dropped rather than shown: an idea
    is a non-empty one-line `text` (at most 240 characters) with an optional short `label`
    and a `kind` from CHAT_IDEA_KINDS. No usable ideas means the page keeps its built-in ones.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ideas": [], "generated": None}
    entries = raw.get("ideas") if isinstance(raw, dict) else None
    ideas, seen = [], set()
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, str):
            entry = {"text": entry}
        if not isinstance(entry, dict):
            continue
        text = " ".join(str(entry.get("text") or "").split())
        if not text or len(text) > 240 or text.lower() in seen:
            continue
        seen.add(text.lower())
        label = " ".join(str(entry.get("label") or "").split())[:40]
        kind = str(entry.get("kind") or "").strip().lower()
        ideas.append({"text": text, "label": label, "kind": kind if kind in CHAT_IDEA_KINDS else ""})
        if len(ideas) == CHAT_IDEAS_MAX:
            break
    generated = raw.get("generated") if isinstance(raw, dict) else None
    return {"ideas": ideas, "generated": generated if isinstance(generated, str) and ideas else None}


def archived_chats(path: Path, *, strict: bool = False) -> dict:
    """Chats hidden from the Chats tab: {item_id: {closed_at, title} | {restored_at}}."""
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Invalid chat archive")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        if strict:  # Never replace an unreadable archive with a partial one.
            raise
        return {}


def save_chat_state(path: Path, archived: dict, item_id: str, record: dict) -> None:
    archived[item_id] = record
    paths.write_json(path, archived)
