"""The board's own memory: closed, parked, first-seen and merged cards, plus reminders.

Kept apart from chats, so the board works whether or not an AI connection can run.
Each store is one JSON file in the gitignored `.roosta/state/assistant/` folder. Reads
tolerate a missing or damaged file; writes are atomic.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from roosta.chat import ConversationHistoryStore, JsonFile, clip_body

_SNAPSHOT_FIELDS = (
    "title", "why", "situation", "opening_move",
    "action_type", "action_owner", "action_label",
)


def closed_snapshot(item: dict | None) -> dict | None:
    """Compact copy of a board item kept so a closed item can be revived with
    its original context. Trusts already-normalised board fields."""
    if not isinstance(item, dict):
        return None
    snapshot: dict = {}
    for field in _SNAPSHOT_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            snapshot[field] = value
    for field in ("links", "documents"):
        value = item.get(field)
        if isinstance(value, list) and value:
            snapshot[field] = value
    project_ref = item.get("project_ref")
    if isinstance(project_ref, str) and project_ref.strip():
        snapshot["project_ref"] = project_ref
    return snapshot or None


def resolve_alias(item_id: str, merged: dict) -> str:
    """Follow duplicate -> kept links to the surviving card id (cycle-safe)."""
    seen = set()
    while item_id in merged and item_id not in seen:
        seen.add(item_id)
        target = merged[item_id]
        nxt = str(target.get("into", "") if isinstance(target, dict) else target or "")
        if not nxt:
            break
        item_id = nxt
    return item_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BoardState:
    """Without a directory it holds nothing and writes nowhere, which tests rely on."""

    def __init__(self, directory: Path | None = None,
                 history: ConversationHistoryStore | None = None) -> None:
        def store(name: str, kind: type) -> JsonFile:
            return JsonFile(Path(directory) / name if directory else None, kind)

        self._handled = store("handled.json", dict)
        self._snoozed = store("snoozed.json", dict)
        self._reminders = store("reminders.json", list)
        self._raised = store("raised.json", dict)
        self._merged = store("merged.json", dict)
        self._history = history

    def talked_on(self, item_id: str) -> bool:
        """Whether the user has a conversation on this card."""
        return bool(self._history and self._history.read(item_id))

    # --- handled: cards the AI solved or the user closed. The rail hides them
    #     at once and the assistant task suppresses them on its next pass. ---

    def handled(self) -> dict:
        """The handled map {item_id: {result, at, item?}}."""
        data = self._handled.read()
        wrapped_items = data.get("items")
        if isinstance(wrapped_items, list):  # a model sometimes writes the board's list shape
            return {
                str(item["id"]): {
                    "result": str(item.get("result") or "Handled"),
                    "at": str(item.get("at") or ""),
                }
                for item in wrapped_items
                if isinstance(item, dict) and item.get("id")
            }
        return {str(item_id): value for item_id, value in data.items() if isinstance(value, dict)}

    def mark_handled(self, item_id: str, result: str, item: dict | None = None) -> None:
        """Record a card as solved or closed with a one-line outcome.

        The chat's session, summary and transcript stay: card ids are stable per open
        reason, so a reply after closing must keep its context. A compact snapshot of
        the card is kept so it can be reviewed and revived (`unhandle`)."""
        if not item_id:
            return
        data = self.handled()
        record = {"result": result or "Done", "at": _now()}
        snapshot = closed_snapshot(item)
        if snapshot:
            record["item"] = snapshot
        data[item_id] = record
        self._handled.write(data)
        self.unsnooze(item_id)
        self.remove_reminder(item_id)
        self.clear_raised(item_id)

    def unhandle(self, item_id: str) -> dict | None:
        """Reopen a closed card and return its stored snapshot, if any.
        The caller decides how to resurface it."""
        data = self.handled()
        record = data.pop(item_id, None)
        if record is None:
            return None
        self._handled.write(data)
        snapshot = record.get("item") if isinstance(record, dict) else None
        return snapshot if isinstance(snapshot, dict) else None

    # --- raised: when each card id first appeared on the board ---

    def raised(self) -> dict:
        """The first-seen map {item_id: {at}}."""
        return self._raised.read()

    def record_raised(self, item_ids: list[str]) -> dict:
        """Save first-seen times for new ids and return the full map."""
        data = self.raised()
        new = {item_id: {"at": _now()} for item_id in item_ids if item_id and item_id not in data}
        if new:
            data.update(new)
            self._raised.write(data)
        return data

    def clear_raised(self, item_id: str) -> None:
        data = self.raised()
        if data.pop(item_id, None) is not None:
            self._raised.write(data)

    # --- merged: duplicate card ids the assistant task folded into another card.
    #     Saved because the skill that minted the duplicate keeps returning its id;
    #     the alias makes those returns refine the kept card. ---

    def merged(self) -> dict:
        """The merge map {duplicate_id: {into, at}}."""
        return self._merged.read()

    def record_merges(self, merges) -> dict:
        """Save the assistant task's merges {duplicate_id: kept_id} and return the full map.

        The card the user has talked on keeps its id, so their conversation stays on the
        surviving card. A merge that would loop back on itself is ignored."""
        data = self.merged()
        if not isinstance(merges, dict):
            return data
        now = _now()
        changed = False
        for dup, kept in list(merges.items())[:20]:
            dup, kept = str(dup or "").strip(), str(kept or "").strip()
            if not dup or not kept or dup == kept:
                continue
            if self.talked_on(dup) and not self.talked_on(kept):
                dup, kept = kept, dup
            if resolve_alias(kept, data) == dup or data.get(dup, {}).get("into") == kept:
                continue
            data[dup] = {"into": kept, "at": now}
            changed = True
        if changed:
            self._merged.write(data)
        return data

    # --- snoozed: deliberate "not now" choices, distinct from done ---

    def snoozed(self) -> dict:
        """The snooze map {item_id: {until, at}}."""
        return self._snoozed.read()

    def snooze(self, item_id: str, until: str) -> None:
        """Park a card until an ISO-8601 instant."""
        if not (item_id and until):
            return
        data = self.snoozed()
        data[item_id] = {"until": until, "at": _now()}
        self._snoozed.write(data)

    def unsnooze(self, item_id: str) -> None:
        """Bring a parked card back now."""
        data = self.snoozed()
        if data.pop(item_id, None) is not None:
            self._snoozed.write(data)

    # --- reminders: cards a chat authored ("remind me", "put this on my board").
    #     They have no live source, so they persist here until closed. ---

    def reminders(self) -> list[dict]:
        """The reminder list [{id, title, body, due, created}]."""
        return self._reminders.read()

    def add_reminder(self, title: str, body: str = "", due: str | None = None) -> str | None:
        """Save a new card. `due` is a validated ISO instant, or None for now."""
        if not (self._reminders.path and title):
            return None
        data = self.reminders()
        reminder_id = f"remind-{uuid.uuid4().hex[:8]}"
        data.append({
            "id": reminder_id,
            "title": str(title)[:120],
            "body": clip_body(body),
            "due": due,
            "created": _now(),
        })
        self._reminders.write(data)
        return reminder_id

    def remove_reminder(self, reminder_id: str) -> None:
        data = self.reminders()
        kept = [r for r in data if not isinstance(r, dict) or r.get("id") != reminder_id]
        if len(kept) != len(data):
            self._reminders.write(kept)
