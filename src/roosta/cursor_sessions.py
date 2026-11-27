"""Read Cursor Agent chat transcripts written under ~/.cursor/projects."""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path

from roosta import ai_connections, paths

log = logging.getLogger(__name__)

VAULT_ROOT = paths.WORKSPACE
SESSION_ID_RE = re.compile(r"^[0-9a-fA-F-]{20,}$")


def cursor_transcript_dir(workspace: str | Path = VAULT_ROOT) -> Path:
    """Cursor encodes the workspace path as a project directory name."""
    enc = str(workspace).lstrip("/").replace("/", "-").replace(".", "-")
    return Path.home() / ".cursor" / "projects" / enc / "agent-transcripts"


def valid_session_id(session_id: str) -> bool:
    return bool(session_id and SESSION_ID_RE.fullmatch(session_id))


def cursor_transcript_path(session_id: str, workspace: str | Path = VAULT_ROOT) -> Path | None:
    if not valid_session_id(session_id):
        return None
    path = cursor_transcript_dir(workspace) / session_id / f"{session_id}.jsonl"
    return path if path.is_file() else None


def _strip_user_query(text: str) -> str:
    match = re.search(r"<user_query>\s*(.*?)\s*</user_query>", text or "", re.S)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def read_cursor_transcript(session_id: str, workspace: str | Path = VAULT_ROOT) -> list[dict]:
    """Return ordered user/assistant turns from a Cursor agent transcript."""
    path = cursor_transcript_path(session_id, workspace)
    if path is None:
        return []
    turns: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = event.get("role")
            if role not in ("user", "assistant"):
                continue
            message = event.get("message") or {}
            content = message.get("content")
            if isinstance(content, list):
                text = " ".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            else:
                text = str(content or "")
            text = _strip_user_query(text) if role == "user" else text.strip()
            if not text:
                continue
            turns.append({"role": role, "text": text})
    except OSError:
        return []
    return turns


# Prune only Cursor's per-run SQLite stores under each config directory's chats/ tree.
# The ~/.cursor/projects and ~/.claude/projects transcripts supply the activity drill-down
# and include the user's own CLI sessions.
SESSION_STORE_RETENTION_DAYS = 30


def prune_cursor_session_stores(
    retention_days: int = SESSION_STORE_RETENTION_DAYS,
    referenced: set[str] | None = None,
) -> int:
    """Delete Cursor CLI session-store dirs older than the retention window.

    Each store is `<config>/chats/<hash>/<session-uuid>/`. A store is kept when its
    newest file is within the window or its uuid is still referenced by the activity
    log (so a resumable chat is never pulled out from under the CLI). Returns the count
    removed. Never raises: a stale store is cheaper than a crashed startup.
    """
    keep = referenced or set()
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for config_dir in ai_connections.CONNECTIONS_DIR.glob("*/cursor"):
        chats = config_dir / "chats"
        if not chats.is_dir():
            continue
        for store in chats.glob("*/*"):
            if not store.is_dir() or store.name in keep:
                continue
            try:
                newest = max((p.stat().st_mtime for p in store.rglob("*")), default=store.stat().st_mtime)
                if newest >= cutoff:
                    continue
                shutil.rmtree(store)
                removed += 1
            except OSError:
                continue
    if removed:
        log.info("pruned %d stale Cursor session store(s)", removed)
    return removed
