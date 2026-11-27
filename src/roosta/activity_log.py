"""The AI activity feed: one place that sees every AI spawn the dashboard makes."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from roosta import paths

# Looked up on every call, so tests can point the feed at a throwaway file.
ACTIVITY_FILE = paths.CACHE_DIR / "activity.jsonl"


class ActivityLog:
    """Single window onto every scheduled AI process the dashboard spawns.

    Each spawn calls start(kind, label, source) -> id, then finish(id, status).
    Entries live in memory (last MAX), append to activity.jsonl for durability,
    and publish to subscriber queues so /api/activity/stream is live.

    `status` uses the same words as a task's status - running, success, error -
    so one run reads the same on the runner page as it does in the feed.
    """

    MAX = 200

    # Enough of the tail to rebuild MAX entries; each spawn writes 2-3 lines.
    HYDRATE_BYTES = 512 * 1024

    # The file is append-only, so server startup (lifespan, not import) trims it to its newest whole lines. About two
    # months of runs: enough history to diagnose failures, without growing forever.
    KEEP_BYTES = 4 * 1024 * 1024

    SUMMARY_CHARS = 400

    def __init__(self) -> None:
        self._entries: dict[str, dict] = {}      # id -> entry (running + recent)
        self._order: list[str] = []              # insertion order, newest last
        self._subs: set[asyncio.Queue] = set()

    def hydrate(self, path: Path | None = None) -> None:
        """Rebuild recent history from the append-only log after a restart.

        The runner restarts often (Roosta.app relaunch, reloader), and an
        in-memory-only feed leaves the activity panel almost empty each time.
        An entry still marked running belonged to the previous process, whose
        harness child died with it, so it is recorded as interrupted rather
        than reappearing as live work that will never finish.
        """
        try:
            with (path or ACTIVITY_FILE).open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - self.HYDRATE_BYTES))
                raw = f.read().decode("utf-8", "replace")
        except OSError:
            return
        lines = raw.splitlines()
        if size > self.HYDRATE_BYTES and lines:
            lines = lines[1:]  # first line is probably a partial record
        collapsed: dict[str, dict] = {}
        for line in lines:
            try:
                entry = json.loads(line)
            except (ValueError, TypeError):
                continue
            eid = entry.get("id")
            if isinstance(eid, str) and eid:
                collapsed[eid] = entry  # later writes supersede earlier ones
        ordered = sorted(collapsed.values(), key=lambda e: str(e.get("started", "")))
        for entry in ordered[-self.MAX :]:
            if entry.get("status") == "running":
                entry["status"] = "interrupted"
            self._entries[entry["id"]] = entry
            self._order.append(entry["id"])

    def compact(self, path: Path | None = None) -> None:
        """Keep only the newest KEEP_BYTES of whole lines. Runs before any spawn appends."""
        path = path or ACTIVITY_FILE
        try:
            if path.stat().st_size <= self.KEEP_BYTES:
                return
            with path.open("rb") as f:
                f.seek(-self.KEEP_BYTES, os.SEEK_END)
                tail = f.read()
            tail = tail[tail.find(b"\n") + 1 :]  # drop the partial first record
            tmp = path.with_suffix(".jsonl.tmp")
            tmp.write_bytes(tail)
            tmp.replace(path)
        except OSError:
            pass  # a full log is better than a lost one

    def start(
        self,
        kind: str,
        label: str,
        source: str,
        *,
        task_id: str = "",
        session_id: str = "",
        backend: str = "",
        connection_id: str = "",
        workspace: str = "",
    ) -> str:
        """Record a spawn. kind: skill|chat|action|send. source: scheduled|manual|you.

        `backend`, `connection_id` and the run's `workspace` locate its transcript.
        """
        eid = uuid.uuid4().hex[:12]
        entry = {
            "id": eid, "kind": kind, "label": label, "source": source,
            "status": "running", "started": datetime.now(timezone.utc).isoformat(),
            "finished": "", "duration": 0.0, "task_id": task_id, "session_id": session_id,
            "backend": backend, "connection_id": connection_id, "workspace": workspace,
            "summary": "", "_t0": time.monotonic(),
        }
        self._entries[eid] = entry
        self._order.append(eid)
        self._evict()
        self._record(entry)
        return eid

    def set_session(self, eid: str, session_id: str) -> None:
        entry = self._entries.get(eid)
        if entry is None or not session_id:
            return
        entry["session_id"] = session_id
        self._record(entry)

    def finish(self, eid: str, status: str = "success", summary: str = "") -> None:
        entry = self._entries.get(eid)
        if entry is None:
            return
        entry["status"] = status
        entry["summary"] = " ".join(str(summary or "").split())[: self.SUMMARY_CHARS]
        entry["finished"] = datetime.now(timezone.utc).isoformat()
        entry["duration"] = round(time.monotonic() - entry.pop("_t0", time.monotonic()), 1)
        self._record(entry)

    def session_ids(self) -> set[str]:
        """AI sessions the feed still links to, so their stores are kept."""
        return {e["session_id"] for e in self._entries.values() if e.get("session_id")}

    def get(self, eid: str) -> dict | None:
        entry = self._entries.get(eid)
        return self._public(entry) if entry else None

    def recent(self, limit: int = 50) -> list[dict]:
        ids = self._order[-limit:]
        return [self._public(self._entries[i]) for i in ids if i in self._entries]

    def running(self) -> list[dict]:
        """All in-flight spawns, regardless of recent-window eviction."""
        return [
            self._public(entry)
            for entry in self._entries.values()
            if entry.get("status") == "running"
        ]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    @staticmethod
    def _public(entry: dict) -> dict:
        return {k: v for k, v in entry.items() if not k.startswith("_")}

    def _evict(self) -> None:
        while len(self._order) > self.MAX:
            old = self._order.pop(0)
            self._entries.pop(old, None)

    def _record(self, entry: dict) -> None:
        """Append the entry to the log, then publish it to live subscribers."""
        public = self._public(entry)
        try:
            ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with ACTIVITY_FILE.open("a") as f:
                f.write(json.dumps(public) + "\n")
        except OSError:
            pass  # durability is best-effort; never crash a run over a log line
        for q in list(self._subs):
            q.put_nowait(dict(entry))
