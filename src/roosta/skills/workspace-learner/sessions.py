#!/usr/bin/env python3
"""workspace-learner helper: read this workspace's interactive agent history
across all four local stores and print clean transcripts.

Sources (each session ID is printed source-tagged, e.g. ``cursor:0476ab68``):

  * ``oc``     - OpenCode SQLite store (``~/.local/share/opencode/opencode.db``)
  * ``cursor`` - Cursor agent transcripts (``~/.cursor/projects/<enc>/agent-transcripts/``)
  * ``cc``     - Claude Code JSONL (``~/.claude/projects/<enc>/``)
  * ``assistant`` - Roosta Assistant history (``.roosta/state/assistant/chat-history.json``)

Usage:
  sessions.py status                           # source availability as JSON
  sessions.py list [SINCE] [OPTIONS]           # interactive sessions (default 24h)
  sessions.py transcript SOURCE:ID [--tools]   # clean transcript; --tools appends tool calls

SINCE accepts "24h", "3d", an epoch-ms, or an ISO date (YYYY-MM-DD).
List options: --source SOURCE, --before TIME, --limit N, --newest-first,
--json. SOURCE is oc, cursor, cc or assistant. Use source-specific scans so
one unavailable store never advances another store's checkpoint.

Overrides: OC_DB, OC_WORKTREE, CURSOR_PROJECTS_DIR, CLAUDE_PROJECTS_DIR,
ASSISTANT_HISTORY.

Noise is excluded from ``list``: subagents (OpenCode ``parent_id``; Cursor
``subagents/`` dirs; Claude ``isSidechain``), Roosta skill-runner sessions
(their first user message carries the runner's template phrase), and trivial
sessions with no genuine back-and-forth. What remains is the user's own chats.
"""
import json
import os
import re
import sqlite3
import sys
import time

# SECURITY-REVIEW: Read-only transcript paths can be overridden by environment variables.
WORKTREE = os.environ.get("OC_WORKTREE") or os.environ.get("ROOSTA_WORKSPACE") or os.getcwd()
OC_DB = os.environ.get("OC_DB", os.path.expanduser("~/.local/share/opencode/opencode.db"))
CURSOR_DIR = os.environ.get(
    "CURSOR_PROJECTS_DIR",
    os.path.expanduser(
        "~/.cursor/projects/" + re.sub(r"[/.]", "-", WORKTREE.lstrip("/")) + "/agent-transcripts"
    ),
)
CLAUDE_DIR = os.environ.get(
    "CLAUDE_PROJECTS_DIR",
    os.path.expanduser("~/.claude/projects/" + re.sub(r"[/.]", "-", WORKTREE)),
)
ASSISTANT_HISTORY = os.environ.get(
    "ASSISTANT_HISTORY",
    os.path.join(WORKTREE, ".roosta", "state", "assistant", "chat-history.json"),
)

# Distinctive phrases in the first user message of a Roosta runner session.
BG_PHRASES = (
    "running as an unattended background task.",
    "running as an unattended scheduled background task.",
    "triggered Run now on the skill runner.",
)


def since_ms(s="24h"):
    s = (s or "24h").strip()
    now = int(time.time())
    if re.fullmatch(r"\d+h", s):
        return (now - int(s[:-1]) * 3600) * 1000
    if re.fullmatch(r"\d+d", s):
        return (now - int(s[:-1]) * 86400) * 1000
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return int(time.mktime(time.strptime(s, "%Y-%m-%d"))) * 1000
    if re.fullmatch(r"\d+", s):
        return int(s)
    return (now - 86400) * 1000


def iso_ms(ts):
    """ISO-8601 (with optional trailing Z) to epoch-ms, or None."""
    if not ts:
        return None
    ts = ts.replace("Z", "+00:00")
    try:
        import datetime

        return int(datetime.datetime.fromisoformat(ts).timestamp() * 1000)
    except ValueError:
        return None


def fmt_dt(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000))


def clean(text, limit=None):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text[:limit] if limit else text


def first_query(text):
    """Pull the human intent out of a Cursor first-user blob wrapped in tags."""
    m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", text or "", re.S)
    if m:
        return clean(m.group(1))
    return clean(re.sub(r"<[^>]+>", " ", text or ""))


def _oc_conn():
    return sqlite3.connect(f"file:{OC_DB}?mode=ro", uri=True)


def oc_list(since):
    if not os.path.exists(OC_DB):
        return []
    c = _oc_conn()
    proj = c.execute("SELECT id FROM project WHERE worktree=? LIMIT 1", (WORKTREE,)).fetchone()
    if not proj:
        return []
    rows = c.execute(
        """
        SELECT s.id, coalesce(s.time_updated, s.time_created), s.title
        FROM session s
        WHERE s.project_id=?
          AND s.parent_id IS NULL
          AND coalesce(s.time_updated, s.time_created) > ?
          AND NOT EXISTS (
            SELECT 1 FROM part p JOIN message m ON p.message_id=m.id
            WHERE p.session_id=s.id
              AND json_extract(m.data,'$.role')='user'
              AND ({phrase_clause}))
        ORDER BY s.time_created
        """.format(
            phrase_clause=" OR ".join(
                ["json_extract(p.data,'$.text') LIKE ?"] * len(BG_PHRASES)
            )
        ),
        (proj[0], since) + tuple("%" + phrase + "%" for phrase in BG_PHRASES),
    ).fetchall()
    return [("oc", sid, tc, clean(title, 60)) for sid, tc, title in rows]


def oc_transcript(sid, tools):
    c = _oc_conn()
    for role, txt in c.execute(
        """
        SELECT json_extract(m.data,'$.role'), json_extract(p.data,'$.text')
        FROM part p JOIN message m ON p.message_id=m.id
        WHERE p.session_id=?
          AND json_extract(p.data,'$.type')='text'
          AND json_extract(p.data,'$.text') IS NOT NULL
        ORDER BY p.time_created
        """,
        (sid,),
    ):
        print(f"{(role or '?').upper()}: {txt}")
    if tools:
        print("--- TOOL CALLS (tool | status | input-or-error) ---")
        for (line,) in c.execute(
            """
            SELECT json_extract(data,'$.tool') || ' | ' ||
                   coalesce(json_extract(data,'$.state.status'),'?') || ' | ' ||
                   substr(replace(coalesce(json_extract(data,'$.state.error'),
                           json_extract(data,'$.state.input'),''), char(10),' '), 1, 160)
            FROM part
            WHERE session_id=? AND json_extract(data,'$.type')='tool'
            ORDER BY time_created
            """,
            (sid,),
        ):
            print(line)


def _cursor_file(sid):
    return os.path.join(CURSOR_DIR, sid, sid + ".jsonl")


def _cursor_texts(sid):
    """Yield (role, kind, payload) for a Cursor session's message parts."""
    path = _cursor_file(sid)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = d.get("role", "?")
            content = (d.get("message") or {}).get("content")
            if isinstance(content, str):
                yield role, "text", content
                continue
            for it in content or []:
                t = it.get("type")
                if t == "text":
                    yield role, "text", it.get("text") or ""
                elif t == "tool_use":
                    yield role, "tool", it


def cursor_list(since):
    if not os.path.isdir(CURSOR_DIR):
        return []
    out = []
    for sid in os.listdir(CURSOR_DIR):
        path = _cursor_file(sid)
        if not os.path.isfile(path):
            continue
        mtime_ms = int(os.path.getmtime(path) * 1000)
        if mtime_ms <= since:
            continue
        title = ""
        skip = False
        for role, kind, payload in _cursor_texts(sid):
            if role == "user" and kind == "text":
                if any(phrase in (payload or "") for phrase in BG_PHRASES):
                    skip = True
                    break
                title = first_query(payload)
                if title:
                    break
        if skip or not title:
            continue
        out.append(("cursor", sid, mtime_ms, clean(title, 60)))
    return out


def cursor_transcript(sid, tools):
    if not os.path.isfile(_cursor_file(sid)):
        print(f"Transcript unavailable: cursor:{sid} was removed after listing.")
        return
    toolcalls = []
    for role, kind, payload in _cursor_texts(sid):
        if kind == "text":
            txt = first_query(payload) if role == "user" else payload
            if txt and txt.strip():
                print(f"{role.upper()}: {txt}")
        elif kind == "tool":
            name = payload.get("name", "?")
            inp = clean(json.dumps(payload.get("input", {})), 160)
            toolcalls.append(f"{name} | called | {inp}")
    if tools and toolcalls:
        print("--- TOOL CALLS (tool | status | input) ---")
        print("\n".join(toolcalls))


def _cc_lines(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def _cc_items(record):
    queued = record.get("type") == "attachment"
    if queued:
        attachment = record.get("attachment")
        if not isinstance(attachment, dict):
            return []
        origin = attachment.get("origin")
        if (
            attachment.get("type") != "queued_command"
            or attachment.get("humanTurn") is not True
            or attachment.get("isMeta")
            or attachment.get("commandMode", "prompt") != "prompt"
            or (origin is not None and (not isinstance(origin, dict) or origin.get("kind") != "human"))
        ):
            return []
        content = attachment.get("prompt")
    else:
        content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return [("text", content)]
    items = []
    if not isinstance(content, list):
        return items
    for it in content:
        if not isinstance(it, dict):
            continue
        t = it.get("type")
        if t == "text" and isinstance(it.get("text"), str):
            items.append(("text", it["text"]))
        elif t == "tool_use" and not queued:
            items.append(("tool", it))
    return items


_CC_SKIP = re.compile(r"^\s*<(command-name|command-message|command-args|local-command)")


def cc_list(since):
    if not os.path.isdir(CLAUDE_DIR):
        return []
    out = []
    for name in os.listdir(CLAUDE_DIR):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(CLAUDE_DIR, name)
        sid = name[:-6]
        title, last_ts, has_user, has_asst, is_bg = "", None, False, False, False
        for d in _cc_lines(path):
            t = d.get("type")
            if t == "ai-title" and d.get("aiTitle"):
                title = d["aiTitle"]
            ts = iso_ms(d["timestamp"]) if isinstance(d.get("timestamp"), str) else None
            if ts:
                last_ts = ts if last_ts is None else max(last_ts, ts)
            if t == "assistant" and not d.get("isSidechain"):
                has_asst = True
            if t in ("user", "attachment") and not d.get("isSidechain") and not d.get("isMeta"):
                for kind, payload in _cc_items(d):
                    if kind == "text" and payload.strip() and not _CC_SKIP.match(payload):
                        if any(phrase in payload for phrase in BG_PHRASES):
                            is_bg = True
                        has_user = True
                        if not title:
                            title = clean(payload, 60)
        if is_bg or not (has_user and has_asst):
            continue
        if last_ts is None or last_ts <= since:
            continue
        out.append(("cc", sid, last_ts, clean(title, 60)))
    return out


def cc_transcript(sid, tools):
    path = os.path.join(CLAUDE_DIR, sid + ".jsonl")
    toolcalls = []
    user_ids, queued_ids = set(), set()
    for d in _cc_lines(path):
        if d.get("isSidechain") or d.get("isMeta"):
            continue
        t = d.get("type")
        if t not in ("user", "assistant", "attachment"):
            continue
        queued = t == "attachment"
        role = "user" if queued else (d.get("message") or {}).get("role", t)
        uid = d.get("uuid")
        if queued and isinstance(d.get("attachment"), dict):
            uid = d["attachment"].get("source_uuid") or uid
        identified = isinstance(uid, str) and bool(uid)
        duplicate = identified and (uid in queued_ids or (queued and uid in user_ids))
        for kind, payload in _cc_items(d):
            if kind == "text":
                if _CC_SKIP.match(payload) or not payload.strip():
                    continue
                if t in ("user", "attachment") and identified:
                    if duplicate:
                        continue
                    (queued_ids if queued else user_ids).add(uid)
                print(f"{role.upper()}: {payload}")
            elif kind == "tool":
                name = payload.get("name", "?")
                inp = clean(json.dumps(payload.get("input", {})), 160)
                toolcalls.append(f"{name} | called | {inp}")
    if tools and toolcalls:
        print("--- TOOL CALLS (tool | status | input) ---")
        print("\n".join(toolcalls))


def _assistant_sessions():
    if not os.path.isfile(ASSISTANT_HISTORY):
        return {}
    try:
        with open(ASSISTANT_HISTORY, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def assistant_list(since):
    if not os.path.isfile(ASSISTANT_HISTORY):
        return []
    mtime_ms = int(os.path.getmtime(ASSISTANT_HISTORY) * 1000)
    if mtime_ms <= since:
        return []
    out = []
    for sid, messages in _assistant_sessions().items():
        if not isinstance(messages, list):
            continue
        roles = {message.get("role") for message in messages if isinstance(message, dict)}
        if not {"user", "assistant"}.issubset(roles):
            continue
        first_user = next(
            (
                message.get("text") or ""
                for message in messages
                if isinstance(message, dict) and message.get("role") == "user"
            ),
            "",
        )
        if any(phrase in first_user for phrase in BG_PHRASES):
            continue
        # One file holds every chat, so its mtime moves them all; use each chat's own
        # latest message time and fall back to the file's only when none is stamped.
        stamps = [
            iso_ms(message.get("at")) if isinstance(message.get("at"), str) else None
            for message in messages
            if isinstance(message, dict)
        ]
        ts = max((s for s in stamps if s is not None), default=mtime_ms)
        if ts <= since:
            continue
        title = clean(first_user, 60) or sid
        out.append(("assistant", sid, ts, title))
    return out


def assistant_transcript(sid, tools):
    messages = _assistant_sessions().get(sid)
    if not isinstance(messages, list):
        sys.exit(f"unknown assistant conversation '{sid}'")
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role", "?")
        text = message.get("text")
        if isinstance(text, str) and text.strip():
            print(f"{role.upper()}: {text}")


LIST_HANDLERS = {
    "oc": oc_list,
    "cursor": cursor_list,
    "cc": cc_list,
    "assistant": assistant_list,
}


def _source_status():
    """Return explicit availability; an absent store is not an empty scan."""
    statuses = {}

    if not os.path.isfile(OC_DB):
        statuses["oc"] = {"available": False, "detail": "database missing"}
    else:
        try:
            c = _oc_conn()
            project = c.execute(
                "SELECT id FROM project WHERE worktree=? LIMIT 1", (WORKTREE,)
            ).fetchone()
            statuses["oc"] = {
                "available": bool(project),
                "detail": "ready" if project else "workspace project missing",
            }
        except sqlite3.Error as exc:
            statuses["oc"] = {"available": False, "detail": f"database error: {exc}"}

    for source, path, kind in (
        ("cursor", CURSOR_DIR, "directory"),
        ("cc", CLAUDE_DIR, "directory"),
        ("assistant", ASSISTANT_HISTORY, "file"),
    ):
        exists = os.path.isdir(path) if kind == "directory" else os.path.isfile(path)
        statuses[source] = {
            "available": exists,
            "detail": "ready" if exists else f"{kind} missing",
        }
    return statuses


def cmd_status(_args):
    print(json.dumps(_source_status(), sort_keys=True))


def cmd_list(args):
    since_arg = "24h"
    source = None
    before = None
    limit = None
    newest_first = False
    json_output = False
    positional_seen = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--source":
            i += 1
            if i >= len(args):
                sys.exit("--source requires a value")
            source = args[i]
        elif arg == "--before":
            i += 1
            if i >= len(args):
                sys.exit("--before requires a value")
            before = since_ms(args[i])
        elif arg == "--limit":
            i += 1
            if i >= len(args) or not args[i].isdigit() or int(args[i]) < 1:
                sys.exit("--limit requires a positive integer")
            limit = int(args[i])
        elif arg == "--newest-first":
            newest_first = True
        elif arg == "--json":
            json_output = True
        elif arg.startswith("--"):
            sys.exit(f"unknown list option '{arg}'")
        elif positional_seen:
            sys.exit(f"unexpected list argument '{arg}'")
        else:
            since_arg = arg
            positional_seen = True
        i += 1

    if source is not None and source not in LIST_HANDLERS:
        sys.exit(f"unknown source '{source}' (expected oc, cursor, cc or assistant)")

    since = since_ms(since_arg)
    handlers = {source: LIST_HANDLERS[source]} if source else LIST_HANDLERS
    rows = []
    for handler in handlers.values():
        rows.extend(handler(since))
    if before is not None:
        rows = [row for row in rows if row[2] < before]
    rows.sort(key=lambda row: (row[2], row[0], row[1]), reverse=newest_first)
    if limit is not None:
        rows = rows[:limit]

    if json_output:
        print(
            json.dumps(
                [
                    {
                        "source": source_name,
                        "id": sid,
                        "timestamp_ms": ts,
                        "timestamp_utc": fmt_dt(ts),
                        "title": title,
                    }
                    for source_name, sid, ts, title in rows
                ]
            )
        )
        return
    for source_name, sid, ts, title in rows:
        print(f"{source_name:9}  {source_name}:{sid}  {fmt_dt(ts)}  {title}")


def cmd_transcript(args):
    if not args:
        sys.exit("usage: sessions.py transcript SOURCE:ID [--tools]")
    ident = args[0]
    tools = "--tools" in args[1:]
    if ":" not in ident:
        sys.exit("session id must be source-tagged, e.g. cursor:<id> (see `list`)")
    source, sid = ident.split(":", 1)
    handler = {
        "oc": oc_transcript,
        "cursor": cursor_transcript,
        "cc": cc_transcript,
        "assistant": assistant_transcript,
    }.get(source)
    if not handler:
        sys.exit(f"unknown source '{source}' (expected oc, cursor, cc or assistant)")
    handler(sid, tools)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("status", "list", "transcript"):
        sys.exit(
            "usage: sessions.py status | list [SINCE] [OPTIONS] | "
            "transcript SOURCE:ID [--tools]"
        )
    handler = {
        "status": cmd_status,
        "list": cmd_list,
        "transcript": cmd_transcript,
    }[sys.argv[1]]
    handler(sys.argv[2:])


if __name__ == "__main__":
    main()
