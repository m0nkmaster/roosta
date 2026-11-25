"""Assistant board: normalise every feed's cards, merge them, and add reminders, setup and health."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from roosta import ai_backend, ai_connections, paths, profile
from roosta.chat import clip_body, resolve_alias
from roosta.claude_code import CLAUDE_SIGNIN_MESSAGE
from roosta.task_config import load_tasks
from roosta.workspace import markdown_path

log = logging.getLogger(__name__)


def _repair_teams_chat_permalink(url: str) -> str:
    """Replace channel-only query fields on Teams group-chat permalinks."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    path_parts = parts.path.split("/")
    if (
        parts.hostname not in {"teams.microsoft.com", "www.teams.microsoft.com"}
        or len(path_parts) < 5
        or path_parts[1:3] != ["l", "message"]
        or not unquote(path_parts[3]).endswith("@thread.v2")
    ):
        return url

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    repaired_query = []
    if query.get("tenantId"):
        repaired_query.append(("tenantId", query["tenantId"]))
    repaired_query.append(("context", json.dumps({"contextType": "chat"}, separators=(",", ":"))))
    return urlunsplit(parts._replace(query=urlencode(repaired_query)))


def _normalise_links(raw) -> list:
    """Keep only well-formed CTA links: a label plus an http(s) URL.

    Anything else (missing url, non-http scheme like javascript:, junk) is
    dropped, so a fabricated or unsafe link can never reach the UI as a CTA.
    """
    links = []
    for ln in raw if isinstance(raw, list) else []:
        if not isinstance(ln, dict):
            continue
        url = str(ln.get("url", "")).strip()
        if not (url.startswith("https://") or url.startswith("http://")):
            continue
        label = str(ln.get("label", "")).strip() or "Open"
        links.append({"label": label, "url": _repair_teams_chat_permalink(url)})
    return links[:4]


def _normalise_documents(raw) -> list:
    """Keep safe relative paths to Markdown documents in the vault."""
    documents = []
    for doc in raw if isinstance(raw, list) else []:
        if not isinstance(doc, dict):
            continue
        path = markdown_path(doc.get("path"))
        if path is None:
            continue
        label = str(doc.get("label", "")).strip() or "Open document"
        documents.append({"label": label[:80], "path": path})
    return documents[:4]


def _normalise_project_ref(raw) -> str | None:
    """Allow only canonical top-level vault project directories."""
    ref = str(raw or "").strip()
    return ref if re.fullmatch(r"projects/[a-z0-9]+(?:-[a-z0-9]+)*", ref) else None


ACTION_TYPES = {
    "chat", "ticket", "email", "standup", "meeting",
    "document", "review", "decision", "task",
}
ACTION_TYPE_ALIASES = {
    "teams": "chat",
    "teams_message": "chat",
    "message": "chat",
    "jira": "ticket",
    "jira_ticket": "ticket",
    "stand-up": "standup",
    "ask_at_standup": "standup",
    "draft": "document",
    "decide": "decision",
    "next_action": "task",
}
ACTION_LABELS = {
    "chat": "Draft reply",
    "ticket": "Review ticket",
    "email": "Draft email",
    "standup": "Prepare talking point",
    "meeting": "Prepare for meeting",
    "document": "Draft document",
    "review": "Review it",
    "decision": "Help me decide",
    "task": "Take next step",
}


def _normalise_action_type(raw, item: dict) -> str:
    """Return a small visual action category, inferring it for older board items."""
    explicit = str(raw or "").strip().lower().replace(" ", "_")
    explicit = ACTION_TYPE_ALIASES.get(explicit, explicit)
    if explicit in ACTION_TYPES:
        return explicit

    text = " ".join(str(item.get(k, "")) for k in
                    ("title", "opening_move", "situation")).lower()
    if "standup" in text or "stand-up" in text:
        return "standup"
    if "email" in text or "e-mail" in text:
        return "email"
    if "teams" in text or re.search(r"\b(dm|message|reply|post)\b", text):
        return "chat"
    if "jira" in text or re.search(
            r"\b(raise|create|update|comment on)\b.{0,30}\b(ticket|[a-z]+-\d+)\b", text):
        return "ticket"
    if re.search(r"\b(meeting|1:1|one-to-one)\b", text):
        return "meeting"
    if re.search(r"\b(draft|write|prepare)\b", text) or re.search(
            r"\b(prd|proposal|brief|document)\b", text):
        return "document"
    if re.search(r"\b(decide|prioritise|choose|shape)\b", text):
        return "decision"
    if re.search(r"\b(review|check|investigate|assess|pull)\b", text):
        return "review"
    return "task"


def _normalise_action_owner(raw) -> str:
    """Keep ownership explicit so the UI never implies the user must act when AI can.

    `user` means the person the assistant works for; their own name from the profile is
    accepted too. Anything unrecognised falls back to the assistant.
    """
    owner = str(raw or "").strip().lower()
    return "user" if owner in {"user", profile.load().user.lower()} else "assistant"


def _normalise_action_label(raw, action_type: str) -> str:
    """Return a short button label, with a useful fallback for older items."""
    label = " ".join(str(raw or "").split()).strip()
    if not label:
        return ACTION_LABELS[action_type]
    return label[:40].rstrip()


def normalise_board_doc(raw) -> dict:
    """Coerce conductor `details` into a safe board document. Garbage -> empty."""
    if not isinstance(raw, dict):
        raw = {}
    items = []
    for it in raw.get("items", []) if isinstance(raw.get("items"), list) else []:
        if not isinstance(it, dict):
            continue
        item_id = str(it.get("id", "")).strip()[:200]
        action_type = _normalise_action_type(it.get("action_type"), it)
        items.append({
            "id": item_id,
            "project_ref": _normalise_project_ref(it.get("project_ref")),
            "title": str(it.get("title", "")),
            "why": str(it.get("why", "")),
            "situation": str(it.get("situation", "")),
            "opening_move": str(it.get("opening_move", "")),
            "action_type": action_type,
            "action_owner": _normalise_action_owner(it.get("action_owner")),
            "action_label": _normalise_action_label(it.get("action_label"), action_type),
            "links": _normalise_links(it.get("links")),
            "documents": _normalise_documents(it.get("documents")),
            "new": bool(it.get("new", False)),
        })
    done = []
    for d in raw.get("done_today", []) if isinstance(raw.get("done_today"), list) else []:
        if isinstance(d, dict):
            done.append({"text": str(d.get("text", "")), "at": str(d.get("at", ""))})
    return {"items": items, "done_today": done}


# Fields a later source may refine on an existing card. Links and documents
# are combined rather than replaced, so context accumulates.
_REFINABLE_FIELDS = ("project_ref", "title", "why", "situation", "opening_move",
                     "action_type", "action_owner", "action_label")
_CARRIED_FIELDS = _REFINABLE_FIELDS + ("links", "documents")


def carry_forward_board_items(details, previous) -> None:
    """Fill a conductor pass's id-only "keep" stubs from the board it replaced.

    For matching ids, copy missing or empty fields into `details`. Values
    supplied by the current pass take precedence.
    """
    if not isinstance(details, dict) or not isinstance(details.get("items"), list):
        return
    old_items = previous.get("items") if isinstance(previous, dict) else None
    if not isinstance(old_items, list):
        return
    old = {str(it.get("id", "")).strip(): it for it in old_items
           if isinstance(it, dict) and str(it.get("id", "")).strip()}
    for item in details["items"]:
        if not isinstance(item, dict):
            continue
        prior = old.get(str(item.get("id", "")).strip())
        if not prior:
            continue
        for name in _CARRIED_FIELDS:
            if not item.get(name) and prior.get(name):
                item[name] = prior[name]


def _refine_board_item(target: dict, update: dict, raw: dict,
                       fill_only: bool = False) -> None:
    """Apply a newer source's view of a card: supplied fields win, context merges.

    `fill_only` is for a duplicate folded in by a conductor merge: the kept card
    is the conductor's synthesis, so the duplicate's narrower view only fills
    blanks and adds context.
    """
    for name in _REFINABLE_FIELDS:
        if raw.get(name) and not (fill_only and target.get(name)):
            target[name] = update[name]
    for name, key in (("links", "url"), ("documents", "path")):
        seen = {entry[key] for entry in target.get(name, [])}
        extra = [entry for entry in update[name] if entry[key] not in seen]
        target[name] = (target.get(name, []) + extra)[:4]
    target["new"] = bool(target.get("new")) or update["new"]


def merge_board_feed_items(conductor_items: list[dict], states: list[dict],
                           aliases: dict | None = None) -> list[dict]:
    """Merge every scheduled skill's `details.items` into the conductor's board.

    Any skill may add a card. A skill returning an id already on the board
    refines that card instead of duplicating it: sources apply oldest run
    first, so the freshest view of each field wins. An update for an id not on
    the board needs a title, so a partial refinement never becomes a blank card.
    `aliases` maps duplicate ids the conductor folded away to the kept card, so
    a duplicate's later returns add to the kept card instead of reappearing.
    """
    aliases = aliases or {}
    run_at = {state.get("id"): str(state.get("last_run") or "") for state in states}
    merged = []
    by_id = {}
    updated = {}
    for item in conductor_items:
        item_id = resolve_alias(item.get("id") or "", aliases)
        if not item_id:
            continue
        if item_id in by_id:
            _refine_board_item(by_id[item_id], item, item)
            continue
        item["id"] = item_id
        by_id[item_id] = item
        updated[item_id] = run_at.get("assistant", "")
        merged.append(item)

    feeds = [state for state in states if state.get("id") != "assistant"]
    for state in sorted(feeds, key=lambda state: str(state.get("last_run") or "")):
        state_id = state.get("id")
        output = state.get("last_output")
        details = output.get("details", {}) if isinstance(output, dict) else {}
        if not isinstance(details, dict):
            continue
        stamp = str(state.get("last_run") or "")
        feed_documents = _normalise_documents(details.get("documents"))
        draft = _normalise_documents([
            {"label": "Open draft", "path": details.get("draft", "")}
        ])
        for document in draft:
            if document not in feed_documents:
                feed_documents.append(document)
        raw_items = details.get("items") if isinstance(details.get("items"), list) else []
        raw_items = [raw for raw in raw_items if isinstance(raw, dict)]
        feed_items = normalise_board_doc({"items": raw_items})["items"]
        for raw, item in zip(raw_items, feed_items, strict=True):
            if not item["documents"] and feed_documents:
                item["documents"] = feed_documents[:4]
            item_id = resolve_alias(item.get("id") or "", aliases)
            if not item_id:
                continue
            folded = item_id != item.get("id")
            item["id"] = item_id
            if item_id in by_id:
                if stamp >= updated[item_id]:
                    _refine_board_item(by_id[item_id], item, raw, fill_only=folded)
                    updated[item_id] = stamp
                continue
            if not item["title"].strip():
                continue
            by_id[item_id] = item
            updated[item_id] = stamp
            merged.append(item)
        # Older task outputs put edit descriptions in `items`, but still expose
        # the draft path at details.draft. Attach that draft to the matching
        # conductor episode so the current rolling-comms card remains useful.
        if feed_documents and not feed_items:
            candidates = [
                item for item in merged
                if str(item.get("id", "")).startswith(f"{state_id}-")
            ]
            if len(candidates) == 1 and not candidates[0].get("documents"):
                candidates[0]["documents"] = feed_documents[:4]
    return merged


def roosta_engineer_item(states: list[dict]) -> dict | None:
    """Make the latest engineer delivery or failure visible on the Assistant board."""
    state = next((row for row in states if row.get("id") == "roosta-engineer"), None)
    if not state or not state.get("last_run"):
        return None
    output = state.get("last_output", {})
    details = output.get("details", {}) if isinstance(output, dict) else {}
    details = details if isinstance(details, dict) else {}
    stamp = re.sub(r"[^0-9]", "", str(state["last_run"]))[:12] or "latest"

    if state.get("status") == "error":
        summary = str(output.get("summary", "") if isinstance(output, dict) else "").strip()
        reason = str(state.get("last_error", "")).strip() or summary or "The pass did not finish."
        return {
            "id": f"roosta-engineer-failed-{stamp}",
            "project_ref": None,
            "title": "Dashboard engineer needs attention",
            "why": "The latest autonomous improvement pass failed, so no app change shipped.",
            "situation": reason[:240],
            "opening_move": "Inspect the failed run and fix the blocker.",
            "action_owner": "assistant",
            "action_label": "Diagnose failure",
            "action_type": "task",
            "links": [{"label": "Open engineer run",
                       "url": f"{paths.BASE_URL}/runner?task=roosta-engineer"}],
            "documents": [],
            "new": True,
        }

    built = details.get("built", [])
    if state.get("status") != "success" or not isinstance(built, list) or not built:
        return None
    first = built[0] if isinstance(built[0], dict) else {}
    what = str(first.get("what", "")).strip() or str(output.get("summary", "")).strip()
    why = str(first.get("why", "")).strip()
    commit = str(first.get("commit", "")).strip()
    identity = re.sub(r"[^a-zA-Z0-9]", "", commit)[:12] or stamp
    return {
        "id": f"dashboard-improvement-{identity}",
        "project_ref": None,
        "title": f"Assistant improved: {what[:90]}" if what else "Assistant improved",
        "why": why[:240] or "The dashboard engineer shipped a new improvement.",
        "situation": str(output.get("summary", "")).strip()[:240],
        "opening_move": "Review what changed and leave feedback if it missed the mark.",
        "action_owner": "user",
        "action_label": "Review improvement",
        "action_type": "review",
        "links": [{"label": "Open engineer run",
                   "url": f"{paths.BASE_URL}/runner?task=roosta-engineer"}],
        "documents": [],
        "new": True,
    }


# Ad-hoc notifications a skill pushes via POST /api/notify. Kept in memory (they
# are ephemeral pings); /api/board merges them so the existing desktop notifier
# and deep-link flow handle them with zero extra plumbing.
_pushed_notifications: list[dict] = []


def push_notification(item: dict) -> None:
    """Show a pushed item on the board, replacing any earlier push with the same id."""
    _pushed_notifications[:] = [n for n in _pushed_notifications if n["id"] != item["id"]]
    _pushed_notifications.append(item)


def merge_pushed_notifications(items: list[dict]) -> list[dict]:
    """Prepend skill-pushed notifications, skipping ids the board already has."""
    have = {i.get("id") for i in items}
    extra = [n for n in _pushed_notifications if n["id"] not in have]
    return extra + items


def reminder_to_item(reminder: dict) -> dict:
    """Render a stored reminder as a board item the user owns."""
    item = {
        "id": reminder["id"], "project_ref": None,
        "title": str(reminder.get("title", ""))[:120],
        "why": clip_body(reminder.get("body", "")),
        "situation": "", "opening_move": "Take a look",
        "action_owner": "user", "action_label": "Review", "action_type": "task",
        "links": [], "documents": [], "new": True,
    }
    created = str(reminder.get("created", "")).strip()
    if created:
        item["raised_at"] = created
    return item


def attach_raised_at(items: list[dict], raised: dict) -> None:
    """Stamp each item with its first-seen board time when known."""
    if not isinstance(raised, dict):
        return
    for item in items:
        if item.get("raised_at"):
            continue
        record = raised.get(item.get("id"))
        if isinstance(record, dict) and record.get("at"):
            item["raised_at"] = str(record["at"])


def split_due_reminders(reminders: list[dict], now: datetime | None = None
                        ) -> tuple[list[dict], list[dict]]:
    """Partition file-backed reminders into due-now board items and a future
    (later-lane) set. A reminder with no/`null` due, or an unparseable one, is
    treated as due now so it can never be silently swallowed."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    due, later = [], []
    for reminder in reminders:
        if not isinstance(reminder, dict) or not reminder.get("id") or not reminder.get("title"):
            continue
        item = reminder_to_item(reminder)
        raw_due = reminder.get("due")
        if not raw_due:
            due.append(item)
            continue
        try:
            when = datetime.fromisoformat(str(raw_due).replace("Z", "+00:00"))
        except ValueError:
            due.append(item)
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when <= current:
            due.append(item)
        else:
            later.append({**item, "new": False,
                          "snoozed_until": when.astimezone(timezone.utc).isoformat()})
    later.sort(key=lambda i: i["snoozed_until"])
    return due, later


def recently_closed(handled: dict, router, limit: int = 15) -> list[dict]:
    """Newest-first view of closed items for the Recently closed list.

    Title comes from the stored snapshot, falling back to the router's known
    item (topic/transcript) so items closed before snapshots existed still show
    something meaningful.
    """
    rows = []
    for item_id, record in handled.items() if isinstance(handled, dict) else []:
        if not isinstance(record, dict):
            continue
        snapshot = record.get("item") if isinstance(record.get("item"), dict) else None
        title = str((snapshot or {}).get("title", "")).strip()
        if not title and router:
            known = router.known_item(item_id)
            title = str((known or {}).get("title", "")).strip()
        rows.append({
            "id": item_id,
            "title": title or "(closed item)",
            "result": str(record.get("result", "")),
            "at": str(record.get("at", "")),
            "action_type": _normalise_action_type((snapshot or {}).get("action_type"),
                                                   snapshot or {}),
        })
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:limit]


def board_merges(states: list[dict], router=None) -> dict:
    """Saved duplicate -> kept merges, plus any the conductor's latest pass made."""
    conductor = next((s for s in states if s.get("id") == "assistant"), {})
    output = conductor.get("last_output")
    details = output.get("details", {}) if isinstance(output, dict) else {}
    merges = details.get("merges") if isinstance(details, dict) else None
    return router.record_merges(merges) if router else {}


SETUP_ITEM_ID = "roosta-setup"
AI_SETUP_ITEM_ID = "roosta-ai-setup"


def setup_item(router=None) -> dict | None:
    """The AI card while no AI connection can run; otherwise the first-run card, shown until
    PROFILE.md names the user and kept once a setup conversation has started, because setup
    writes the name in its first step. The card goes when setup ends with DONE (or the user
    closes it), through the usual handled store."""
    title = situation = ""
    try:
        selected = ai_connections.get()
        if not ai_backend.connection_available():
            title = "Install your AI software"
            situation = "Install the software for your default account in Settings."
        elif ai_backend.signed_in(selected) is False:
            title = "Sign in to your AI account"
            situation = "Complete the browser sign-in for your default account in Settings."
        elif (selected["provider"] not in ("anthropic", "cursor")
              and not ai_connections.default_model(selected["provider"])):
            title = "Choose your AI model"
            situation = "Choose a model in Settings to finish connecting AI."
    except ValueError:
        try:
            accounts = [c for c in ai_connections.load()["connections"] if c.get("connected")]
        except ValueError:
            accounts = []
        if any(c["auth"] == "system" for c in accounts):
            title = "Choose your Claude Code account"
            situation = "Roosta can use the existing Claude Code login on this computer."
        elif accounts:
            title = "Choose your default AI account"
            situation = "Choose Use as default beside the saved account you want for new chats and workers."
        else:
            title = "Connect your AI"
            situation = "Add or reconnect an AI account in Settings."
    if title:
        return {
            "id": AI_SETUP_ITEM_ID,
            "project_ref": None,
            "title": title,
            "why": "Connect AI before setting up your workspace so Roosta can help you.",
            "situation": situation,
            "opening_move": "Open AI settings to finish setting up your default account. Then return here to set up your workspace.",
            "action_type": "task", "action_owner": "user", "action_label": "Open AI settings",
            "links": [], "documents": [], "new": True,
        }
    if profile.load().name:
        history = getattr(router, "conversation_history", None)
        if not (history and history(SETUP_ITEM_ID)):
            return None
    return {
        "id": SETUP_ITEM_ID,
        "project_ref": None,
        "title": "Set up your workspace",
        "why": "Roosta doesn't know who you are, what matters to you or which tools you use yet.",
        "situation": "A new workspace. Setup takes about ten minutes and can be re-run any time.",
        "opening_move": ("Load the 'setup' skill and run it: interview me for my profile, "
                         "priorities and tools, connect the tools I use with my approval, turn on "
                         "the starter schedule and create a first real board card."),
        "action_type": "task",
        "action_owner": "assistant",
        "action_label": "Start setup",
        "links": [],
        "documents": [{"label": "Open profile", "path": "PROFILE.md"}],
        "new": True,
    }


PRIORITY_ITEM = re.compile(r"^\s*(?:\d+\.|[-*])\s+\S")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def setup_gaps() -> list[str]:
    """Concrete setup outputs that are still missing, in the words Settings shows."""
    gaps = []
    if not profile.load().name:
        gaps.append("your name in PROFILE.md")
    try:
        text = (paths.WORKSPACE / "PRIORITIES.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        text = ""
    section = re.search(r"^##[ \t]+My priorities[ \t]*$(.*?)(?=^##[ \t]|\Z)", HTML_COMMENT.sub("", text),
                        re.S | re.M)
    if not section or not any(PRIORITY_ITEM.match(line) for line in section.group(1).splitlines()):
        gaps.append("your priorities in PRIORITIES.md")
    try:
        if not load_tasks():
            gaps.append("a starter schedule of workers")
    except Exception:
        log.warning("Could not read tasks while checking setup", exc_info=True)
    return gaps


def collect_board_items(items: list[dict], states: list[dict], reminders: list[dict],
                        router=None) -> tuple[list[dict], list[dict]]:
    """Build the active and future item sources shared by the board and chat."""
    active = merge_pushed_notifications(
        merge_board_feed_items(items, states, board_merges(states, router)))
    engineer_item = roosta_engineer_item(states)
    if engineer_item and engineer_item["id"] not in {item["id"] for item in active}:
        active.insert(0, engineer_item)
    # Prerequisites come from local state, never cached model output.
    active = [item for item in active if item["id"] not in {SETUP_ITEM_ID, AI_SETUP_ITEM_ID}]
    first_run = setup_item(router)
    if first_run:
        active.insert(0, first_run)
    due_reminders, later_reminders = split_due_reminders(reminders)
    have = {item["id"] for item in active}
    active = [item for item in due_reminders if item["id"] not in have] + active
    have.update(item["id"] for item in active)
    later = [item for item in later_reminders if item["id"] not in have]
    return active, later


# The conductor's picture is only as complete as the sensors feeding its signal
# world. If a sensor task has errored or gone stale, the board can show a false
# all-clear - fewer items, no warning. Sensors are the conductor plus every task
# marked `sensor: true` in tasks.yaml: the watchers gathering the signal it reasons over.
BOARD_SENSOR_IDS = ("assistant",)
BOARD_STALE_FACTOR = 3  # last_run older than N x interval => stale

SERVER_STARTED = time.time()


def restart_pending(started: float | None = None, root: Path | None = None) -> bool:
    """True when a Roosta module changed on disk after this server loaded it.

    An editable install or an upgrade replaces the code under a running runner; HTML and CSS
    reload by themselves, but Python changes wait for a restart, so the board says so.
    """
    started = SERVER_STARTED if started is None else started
    try:
        return any(p.stat().st_mtime > started for p in (root or paths.APP_ROOT).glob("*.py"))
    except OSError:
        return False


# A run that says the GitHub sign-in failed ("gh auth failed", "GitHub auth is broken").
# A dot inside a hostname does not end the sentence.
GITHUB_SIGNIN_LOST = re.compile(
    r"\b(?:github|gh)\b(?:[^.]|\.\S){0,60}?\b(?:auth|token|login)\b"
    r"(?:[^.]|\.\S){0,40}?\b(?:invalid|failed|broken|expired)\b",
    re.IGNORECASE,
)


def board_health(states: list[dict], now: datetime | None = None) -> dict:
    """Report failed board sensors and other scheduled automations.

    Degraded if a sensor last errored or hasn't run in BOARD_STALE_FACTOR x its
    interval. Other failed tasks are reported separately so the Assistant does
    not hide maintenance failures. `ok` remains the sensor-trust verdict.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    degraded = []
    automation_failures = []
    for s in states:
        sid = s.get("id", "")
        if sid not in BOARD_SENSOR_IDS and not s.get("sensor"):
            if (s.get("status") == "error" and sid != "roosta-engineer"
                    and sid):
                automation_failures.append({
                    "id": sid,
                    "nickname": str(s.get("nickname") or "").strip(),
                    "reason": str(s.get("last_error", "")).strip()[:160]
                    or "last run failed",
                })
            continue
        if s.get("status") == "error":
            degraded.append({"id": sid, "nickname": str(s.get("nickname") or "").strip(),
                             "reason": "last run failed"})
            continue
        interval = s.get("interval") or 0
        last_run = s.get("last_run") or ""
        if interval and last_run:
            try:
                last = datetime.fromisoformat(last_run)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (current - last).total_seconds() > interval * BOARD_STALE_FACTOR:
                    degraded.append({"id": sid, "nickname": str(s.get("nickname") or "").strip(),
                                     "reason": "stale"})
            except ValueError:
                pass  # unparseable timestamp isn't itself a sensor failure
    return {
        "ok": not degraded,
        "degraded": degraded,
        "automation_failures": automation_failures,
        # One expired sign-in fails every scheduled run; name the cause once.
        "claude_signin_expired": any(
            str(s.get("last_error", "")).startswith(CLAUDE_SIGNIN_MESSAGE)
            for s in states if s.get("status") == "error"
        ),
        # Skills word it differently; a network blip without an auth word stays out.
        "github_signin_expired": any(
            GITHUB_SIGNIN_LOST.search(str(s.get("last_error", "")))
            for s in states if s.get("status") == "error"
        ),
    }


def snooze_deadline(preset: str, now: datetime | None = None) -> str:
    """Resolve an allowlisted attention preset to a UTC instant."""
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if preset == "one_hour":
        deadline = current + timedelta(hours=1)
    elif preset == "tomorrow":
        deadline = (current + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0)
    elif preset == "next_monday":
        days = (7 - current.weekday()) % 7 or 7
        deadline = (current + timedelta(days=days)).replace(
            hour=9, minute=0, second=0, microsecond=0)
    else:
        raise ValueError("unknown snooze preset")
    return deadline.astimezone(timezone.utc).isoformat()


def split_snoozed_items(items: list[dict], snoozed: dict,
                         now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """Partition current conductor items into active and deliberately parked.

    Only items the conductor still believes need the user appear in Later. Expired or
    malformed records fail open and put the item back in the active queue.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    active, later = [], []
    for item in items:
        record = snoozed.get(item.get("id")) if isinstance(snoozed, dict) else None
        until_raw = record.get("until", "") if isinstance(record, dict) else ""
        if not isinstance(until_raw, str):
            active.append(item)
            continue
        try:
            until = datetime.fromisoformat(until_raw.replace("Z", "+00:00"))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            active.append(item)
            continue
        if until <= current:
            active.append(item)
            continue
        later.append({**item, "snoozed_until": until.astimezone(timezone.utc).isoformat()})
    later.sort(key=lambda item: item["snoozed_until"])
    return active, later
