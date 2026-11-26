"""Vault Pulse - live workspace telemetry for the dashboard."""

from __future__ import annotations

import base64
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from roosta.task_config import workspace_skills
from roosta.workspace import (catalogue_files, index_links, index_members, markdown_title, metadata,
                              read_document, selected_collections)

STALE_AFTER_DAYS = 30
LIVE_STATUSES = {"active", "blocked"}

RELATED_SECTION = re.compile(r"^##\s+Related\s*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)
WIKILINK = re.compile(r"\[\[([^\]|#]+)")
README_LINK = re.compile(r"\]\(\s*(?:\.\./|/)?(?:projects/)?([a-z0-9][a-z0-9-]*)/README\.md")


def frontmatter_field(content: str, field: str) -> str:
    """Read one scalar value from a Markdown file's YAML frontmatter."""
    if not content.startswith("---"):
        return ""
    end = content.find("\n---", 3)
    if end == -1:
        return ""
    for line in content[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == field:
            return value.strip().strip("\"'")
    return ""


def frontmatter_text(content: str) -> str:
    """Flatten a Markdown file's YAML frontmatter values into searchable text."""
    if not content.startswith("---"):
        return ""
    end = content.find("\n---", 3)
    if end == -1:
        return ""
    values = []
    for line in content[3:end].splitlines():
        _, sep, value = line.partition(":")
        text = value if sep else line
        values.append(re.sub(r"[\[\]\"']", " ", text).strip(" -"))
    return " ".join(v for v in values if v)


def related_projects(content: str, known: set[str], path: str = "", by_path: dict | None = None) -> list[str]:
    """Project slugs linked from a README's `## Related` section."""
    section = RELATED_SECTION.search(content)
    if not section:
        return []
    body = section.group(1)
    found: list[str] = []
    legacy = README_LINK.findall(body) if by_path is None else []
    for raw in WIKILINK.findall(body) + legacy:
        slug = raw.strip().strip("/").split("/")[-1].removesuffix(".md")
        if slug in known and slug not in found:
            found.append(slug)
    if by_path is not None:
        for target, _ in index_links({"path": path, "text": body}, by_path, list_only=False):
            peer = by_path[target]
            if peer in known and peer not in found:
                found.append(peer)
    return found


PROJECT_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REVIEW_STATUSES = ("active", "blocked", "paused", "completed")
REVIEWER = "human:user"  # default; callers pass the profile's reviewer
JIRA_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-[0-9]{1,6})\b")
URL = re.compile(r"https?://[^\s)\]>\"'|]+")
LINK_KINDS = (
    ("atlassian.net/browse", "Jira"),
    ("atlassian.net/wiki", "Confluence"),
    ("confluence.", "Confluence"),
    ("docs.google.com", "Google Doc"),
    ("github", "GitHub"),
    ("teams.microsoft.com", "Teams"),
    ("miro.com", "Miro"),
)


def iso_day(value) -> str:
    if not isinstance(value, (str, date)):
        return ""
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        return ""


def provenance(content: str, today: str) -> dict:
    """Read `verified` / `stale_after` and say whether the doc is due a check."""
    front = metadata(content)
    raw = front.get("verified")
    entries = [{"by": entry["by"], "at": iso_day(entry.get("at"))}
               for entry in (raw if isinstance(raw, list) else [])
               if isinstance(entry, dict) and isinstance(entry.get("by"), str) and iso_day(entry.get("at"))]
    entries.sort(key=lambda entry: entry["at"], reverse=True)
    status = front.get("status")
    stale_after = iso_day(front.get("stale_after"))
    human = any(entry["by"].startswith("human:") for entry in entries)
    expired = bool(stale_after) and stale_after <= today
    return {
        "verified": entries,
        "stale_after": stale_after,
        "state": "human" if human else "machine" if entries else "unverified",
        # Completed projects are reference material: they never fall due.
        "due": status != "completed" and (not entries or expired),
        "expired": expired,
    }


def markdown_section(content: str, heading: str) -> str:
    """Body of one `## heading` section, or an empty string."""
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", content,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def artefact_links(content: str, limit: int = 20, per_kind: int = 6) -> list[dict]:
    """Jira keys and external URLs a README points at, labelled by kind."""
    found: dict[str, dict] = {}
    for raw in URL.findall(content):
        url = raw.rstrip(".,;:")
        kind = next((label for needle, label in LINK_KINDS if needle in url), "Link")
        key = JIRA_KEY.search(url) if kind == "Jira" else None
        label = key.group(1) if key else re.sub(r"^https?://(www\.)?", "", url)[:60]
        found.setdefault(url, {"kind": kind, "label": label, "url": url})
    linked_keys = {link["label"] for link in found.values() if link["kind"] == "Jira"}
    for key in JIRA_KEY.findall(content):
        if key in linked_keys or key.startswith(("ISO-", "UTF-", "SHA-")):
            continue
        linked_keys.add(key)
        url = f"https://deept.atlassian.net/browse/{key}"
        found.setdefault(url, {"kind": "Jira", "label": key, "url": url})
    order = {label: i for i, (_, label) in enumerate(LINK_KINDS)}
    # First mentions win within a kind, so a ticket-heavy README still shows its docs.
    kept: list[dict] = []
    for link in found.values():
        if sum(1 for other in kept if other["kind"] == link["kind"]) < per_kind:
            kept.append(link)
    return sorted(kept, key=lambda link: order.get(link["kind"], 99))[:limit]


def entity_id(path: str) -> str:
    parts = Path(path).parts
    if len(parts) == 3 and parts[0] == "projects" and parts[2] == "README.md" and PROJECT_SLUG.fullmatch(parts[1]):
        return parts[1]
    return "page." + base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")


def constellation_pages(root: Path):
    files, _ = catalogue_files(root)
    known = {file["path"]: file for file in files}
    groups = selected_collections(known, os.path.lexists(root / "WORKSPACE.md"))
    entities = {}
    for group in groups:
        for path in group["paths"]:
            entities.setdefault(path, []).append(group["title"])
    return known, entities


def supporting_paths(page, known, entities):
    path = Path(page["path"])
    if path.name.lower() == "readme.md" and path.parent != Path("."):
        candidates = [p for p in known if p.startswith(path.parent.as_posix() + "/")]
    else:
        candidates = index_members(page, known)
    return [p for p in candidates if p not in entities]


def selected_page(root: Path, slug: str):
    if not (PROJECT_SLUG.fullmatch(slug) or re.fullmatch(r"page\.[A-Za-z0-9_-]+", slug)):
        raise ValueError("invalid page")
    known, entities = constellation_pages(root)
    for path in entities:
        if entity_id(path) == slug:
            return known[path], known, entities
    raise FileNotFoundError(slug)


def project_brief(root: Path, slug: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    page, known, entities = selected_page(root, slug)
    content = page["text"]
    paths = [page["path"], *supporting_paths(page, known, entities)]
    return {
        "name": slug, "path": page["path"], "title": page["title"],
        "status": page["status"] or "unknown",
        "last_updated": iso_day(metadata(content).get("last_updated")),
        "overview": (markdown_section(content, "Overview").split("\n\n")[0] or page["summary"])[:900],
        "current_state": markdown_section(content, "Current state")[:12000],
        "provenance": provenance(content, now.date().isoformat()),
        "links": artefact_links(content),
        "linked_paths": list(dict.fromkeys(p for p, _ in index_links(page, known, list_only=False))),
        "recent_files": [{"path": p, "name": os.path.relpath(p, Path(page["path"]).parent),
                          "mtime": known[p]["modified"]}
                         for p in sorted(paths, key=lambda p: known[p]["modified"], reverse=True)[:8]],
    }


def _set_key(lines: list[str], end: int, key: str, value: str | None) -> int:
    """Set, add or (value None) drop one top-level scalar; returns the new end index."""
    for i in range(1, end):
        if not lines[i][:1].isspace() and lines[i].split(":", 1)[0].strip() == key:
            if value is None:
                del lines[i]
                return end - 1
            lines[i] = f"{key}: {value}"
            return end
    if value is None:
        return end
    lines.insert(end, f"{key}: {value}")
    return end + 1


_review_lock = Lock()


def review_project(root: Path, slug: str, action: str, status: str = "",
                   now: datetime | None = None, reviewer: str = REVIEWER) -> dict:
    with _review_lock:
        return _review_page(root, slug, action, status, now, reviewer)


def _review_page(root: Path, slug: str, action: str, status: str,
                 now: datetime | None, reviewer: str) -> dict:
    """Apply one review decision to a selected page's frontmatter.

    `status` changes the lifecycle state (an edit, so `last_updated` moves);
    `confirm` records the user's word that the page is right (a verification, so
    only `verified` and `stale_after` move). Nothing below the frontmatter changes.
    """
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    page, _, _ = selected_page(root, slug)
    path = page["path"]
    canonical, original, _ = read_document(root, path)
    if canonical.as_posix() != path:
        raise ValueError("Page path changed")
    readme = root.resolve() / canonical
    newline = "\r\n" if original.startswith("---\r\n") else "\n"
    header = re.match(r"\A---[ \t]*\r?\n(.*?)^---[ \t]*(?=\r?$)", original, re.M | re.S)
    if not header and re.match(r"\A---[ \t]*(?:\r?\n|$)", original):
        raise ValueError("Page has incomplete frontmatter")
    suffix = original[header.end():] if header else newline + original
    lines = ["---", *(header[1].splitlines() if header else []), "---"]
    end = len(lines) - 1
    content = "\n".join(lines)
    front = metadata(content)
    if not front and any(line.partition("#")[0].strip() for line in lines[1:end]):
        raise ValueError("Page requires valid mapping frontmatter")
    expected = dict(front)
    current = front.get("status")
    if action == "status":
        if status not in REVIEW_STATUSES:
            raise ValueError("invalid status")
        if current == status:
            return project_brief(root, slug, now)
        end = _set_key(lines, end, "status", status)
        end = _set_key(lines, end, "last_updated", today)
        expected.update(status=status, last_updated=now.date())
        if status == "completed":
            expected.pop("stale_after", None)
            end = _set_key(lines, end, "stale_after", None)
    elif action == "confirm":
        entry = f"  - {{ by: {reviewer}, at: {today} }}"
        at = next((i for i in range(1, end) if not lines[i][:1].isspace()
                   and lines[i].split(":", 1)[0].strip() == "verified"), None)
        if at is None:
            lines.insert(end, "verified:")
            at, end = end, end + 1
        previous = front.get("verified") or []
        if not isinstance(previous, list):
            raise ValueError("verified must be a list")
        if {"by": reviewer, "at": today} not in provenance(content, today)["verified"]:
            expected["verified"] = [{"by": reviewer, "at": now.date()}, *previous]
            value = lines[at].split(":", 1)[1].partition("#")[0].strip()
            if value.startswith("[") and value != "[]":
                pos = lines[at].index("[") + 1
                lines[at] = lines[at][:pos] + entry.split("- ", 1)[1] + ", " + lines[at][pos:]
            elif value in ("", "[]"):
                if value:
                    lines[at] = lines[at].replace("[]", "", 1).rstrip()
                if previous:
                    for line in lines[at + 1:end]:
                        if indent := re.match(r"^( *)-", line):
                            entry = indent[1] + entry.lstrip()
                            break
                lines.insert(at + 1, entry)
                end += 1
            else:
                raise ValueError("verified must be a list")
        deadline = None
        if current in ("active", "blocked", "paused") or (current != "completed" and iso_day(front.get("stale_after"))):
            days = 30 if current == "active" else 90
            deadline = (now + timedelta(days=days)).date()
            expected["stale_after"] = deadline
        else:
            expected.pop("stale_after", None)
        _set_key(lines, end, "stale_after", deadline.isoformat() if deadline else None)
    else:
        raise ValueError("invalid action")
    updated = newline.join(lines) + suffix
    if updated != original:
        if metadata(updated) != expected:
            raise ValueError("Page has incompatible frontmatter")
        with tempfile.NamedTemporaryFile(dir=readme.parent, delete=False) as stream:
            temp = Path(stream.name)
            try:
                stream.write(updated.encode())
                temp.chmod(readme.stat().st_mode & 0o777)
            except OSError:
                temp.unlink(missing_ok=True)
                raise
        try:
            if readme.resolve() != readme or readme.read_bytes() != original.encode():
                raise ValueError("Page changed during review")
            temp.replace(readme)
        finally:
            temp.unlink(missing_ok=True)
    return project_brief(root, slug, now)


PAGES_PER_PROJECT = 40


def link_projects(signals: dict[str, dict], readmes: dict[str, str]) -> None:
    """Attach the documented relationship graph to each project signal."""
    names = set(signals)
    by_path = {signal["path"]: name for name, signal in signals.items()}
    for name, signal in signals.items():
        signal["related"] = related_projects(readmes.get(name, ""), names - {name}, signal["path"], by_path)
    # `## Related` is meant to be bidirectional; draw a half-written pair anyway.
    for name, signal in signals.items():
        for peer in signal["related"]:
            if name not in signals[peer]["related"]:
                signals[peer]["related"].append(name)
    for signal in signals.values():
        signal["related"].sort()


def scan_vault(root: Path) -> dict:
    """Count vault artefacts without touching secrets or dashboard internals."""
    root = root.resolve()
    known, entities = constellation_pages(root)
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()
    recent_edits = [{"path": p, "title": f["title"], "mtime": f["modified"]}
                    for p, f in known.items() if f["modified"] >= week_ago]
    project_signals = {}
    project_readmes = {}
    for path, groups in entities.items():
        page = known[path]
        text = page["text"]
        slug = entity_id(path)
        front = metadata(text)
        check = provenance(text, now.date().isoformat())
        dates = [(entry["at"], "verified") for entry in check["verified"]]
        if updated := iso_day(front.get("last_updated")):
            dates.append((updated, "last_updated"))
        attention, basis = max(dates) if dates else (page["modified"], "file modification")
        instant = datetime.fromisoformat(attention)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        age = max(0, (now - instant).total_seconds() / 86400)
        supporting = supporting_paths(page, known, entities)
        project_signals[slug] = {
            "name": slug, "path": path, "collections": groups, "title": page["title"],
            "owner": frontmatter_field(text, "owner"), "status": page["status"] or "unknown",
            "keywords": frontmatter_text(text), "last_activity": instant.isoformat(), "attention_basis": basis,
            "age_days": round(age, 2), "stale": page["status"] in LIVE_STATUSES and age >= STALE_AFTER_DAYS,
            "provenance": check["state"], "verification_due": check["due"], "expired": check["expired"],
            "recent_edits": sum(known[p]["modified"] >= week_ago for p in [path, *supporting]),
            "pages": [{"path": p, "title": known[p]["title"], "mtime": known[p]["modified"]}
                      for p in sorted(supporting, key=lambda p: known[p]["modified"], reverse=True)[:PAGES_PER_PROJECT]],
        }
        project_readmes[slug] = text
    link_projects(project_signals, project_readmes)

    recent_edits.sort(key=lambda item: item["mtime"], reverse=True)
    return {
        "projects": sum(1 for p in known if re.fullmatch(r"projects/[^/]+/README\.md", p)),
        "project_names": list(project_signals)[:48],
        "project_signals": list(project_signals.values()),
        "stale_projects": sum(1 for s in project_signals.values() if s["stale"]),
        "stale_after_days": STALE_AFTER_DAYS,
        "markdown_files": len(known),
        "words": sum(len(re.findall(r"\b\w+\b", f["text"])) for f in known.values()),
        "skills": len(workspace_skills(root)),
        "recent_files_7d": len(recent_edits),
        "hot_files": recent_edits[:6],
    }


def activity_stats(entries: list[dict], now: datetime | None = None) -> dict:
    """Summarise AI activity from the activity log."""
    now = now or datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today = [entry for entry in entries if entry.get("started", "") >= today_start]
    runs = [entry for entry in today if entry.get("kind") == "skill"]
    running = [entry for entry in entries if entry.get("status") == "running"]
    return {
        "today_runs": len(runs),
        "today_success": sum(1 for entry in today if entry.get("status") == "success"),
        "today_errors": sum(1 for entry in today if entry.get("status") == "error"),
        "running_now": len(running),
        "today_ai_seconds": round(
            sum(entry.get("duration", 0) for entry in runs), 1
        ),
    }


def board_stats(
    handled: dict,
    board_active: int,
    board_later: int,
    health: dict,
) -> dict:
    """Summarise Assistant board throughput."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    cleared_today = sum(
        1 for value in handled.values()
        if isinstance(value, dict) and value.get("at", "") >= today_start
    )
    return {
        "board_active": board_active,
        "board_later": board_later,
        "cleared_today": cleared_today,
        "sensors_ok": bool(health.get("ok", True)),
        "degraded_sensors": len(health.get("degraded", [])),
    }


def command_mood(vault: dict, activity: dict, board: dict) -> dict:
    """Pick a playful operational headline from live telemetry."""
    if not board["sensors_ok"]:
        return {
            "code": "sensor_fog",
            "headline": "Sensor fog",
            "detail": (
                f"{board['degraded_sensors']} sensor"
                f"{'s' if board['degraded_sensors'] != 1 else ''} offline. "
                "The all-clear may be a mirage."
            ),
            "accent": "#d29922",
        }
    if activity["running_now"]:
        return {
            "code": "agents_active",
            "headline": "Agents active",
            "detail": (
                f"{activity['running_now']} skill"
                f"{'s' if activity['running_now'] != 1 else ''} running right now. "
                "The command centre hums."
            ),
            "accent": "#58a6ff",
        }
    if board["board_active"] == 0 and board["board_later"] == 0:
        return {
            "code": "all_clear",
            "headline": "All clear",
            "detail": "Nothing on the board. Either you're winning or it's suspiciously quiet.",
            "accent": "#3fb950",
        }
    if board["cleared_today"] >= 3:
        return {
            "code": "productive_orbit",
            "headline": "Productive orbit",
            "detail": (
                f"{board['cleared_today']} items cleared today. "
                "Momentum looks real."
            ),
            "accent": "#79c0ff",
        }
    if activity["today_errors"]:
        return {
            "code": "turbulence",
            "headline": "Turbulence detected",
            "detail": (
                f"{activity['today_errors']} failed pass"
                f"{'es' if activity['today_errors'] != 1 else ''} today. "
                "Worth a glance at the runner."
            ),
            "accent": "#f85149",
        }
    if vault["recent_files_7d"] >= 15:
        return {
            "code": "vault_alive",
            "headline": "Vault alive",
            "detail": (
                f"{vault['recent_files_7d']} files touched this week across "
                f"{vault['projects']} projects."
            ),
            "accent": "#d2a8ff",
        }
    return {
        "code": "steady_state",
        "headline": "Steady state",
        "detail": (
            f"{board['board_active']} on the board, "
            f"{vault['words']:,} words in the vault. Systems nominal."
        ),
        "accent": "#8b949e",
    }


def running_workloads(
    task_states: list[dict],
    running_activity: list[dict],
    chat_items: list[dict],
) -> list[dict]:
    """Normalise in-flight scheduled tasks, AI skill runs and board chats."""
    items: list[dict] = []
    covered_tasks: set[str] = set()

    for entry in running_activity:
        if entry.get("status") != "running":
            continue
        label = str(entry.get("label", "")).strip() or "unknown"
        covered_tasks.add(label)
        items.append({
            "kind": str(entry.get("kind", "skill")),
            "name": label,
            "detail": str(entry.get("source", "")).strip() or "scheduled",
            "status": "running",
            "started": entry.get("started", ""),
            "action": "trace",
            "trace_key": label,
        })

    for state in task_states:
        task_id = str(state.get("id", "")).strip()
        skill = str(state.get("skill", task_id)).strip()
        queued = bool(state.get("queued"))
        running = state.get("status") == "running"
        if not running and not queued:
            continue
        if running and (task_id in covered_tasks or skill in covered_tasks):
            continue
        covered_tasks.add(task_id or skill)
        items.append({
            "kind": "task",
            "name": task_id or skill,
            "detail": skill,
            "status": "queued" if queued and not running else "running",
            "started": state.get("last_run", "") if running else "",
            "action": "trace",
            "trace_key": task_id or skill,
        })

    for chat in chat_items:
        item_id = str(chat.get("id", "")).strip()
        title = str(chat.get("title", "")).strip() or "Conversation"
        item = {
            "kind": "chat",
            "name": title,
            "detail": "Assistant reply in progress",
            "status": "running",
            "started": "",
            "action": "open",
            "href": f"/assistant?item={item_id}" if item_id else "/assistant",
        }
        project_ref = str(chat.get("project_ref", "")).strip()
        if re.fullmatch(r"projects/[a-z0-9]+(?:-[a-z0-9]+)*", project_ref):
            item["project_ref"] = project_ref
        items.append(item)

    return items


def build_pulse(
    root: Path,
    activity_entries: list[dict],
    handled: dict,
    board_active: int,
    board_later: int,
    health: dict,
    task_states: list[dict] | None = None,
    running_activity: list[dict] | None = None,
    chat_items: list[dict] | None = None,
    now: datetime | None = None,
    active_project_refs: list[str] | None = None,
    active_project_items: list[dict] | None = None,
) -> dict:
    """Assemble the full pulse payload.

    `active_project_items` (`{id, title, project_ref}`) lets the constellation
    list each board item by name; bare refs still count when titles are unknown.
    """
    now = now or datetime.now(timezone.utc)
    vault = scan_vault(root)
    items = list(active_project_items or []) + [
        {"project_ref": ref} for ref in active_project_refs or []
    ]
    project_items: dict[str, list[dict]] = {}
    for item in items:
        refs = {doc["path"] for doc in (item.get("documents") or [])
                if isinstance(doc, dict) and isinstance(doc.get("path"), str)}
        ref = item.get("project_ref")
        if isinstance(ref, str) and ref:
            refs.add(ref + "/README.md" if re.fullmatch(r"projects/[a-z0-9-]+", ref) else ref)
        for ref in refs:
            project_items.setdefault(ref, []).append(item)
    for project in vault["project_signals"]:
        linked = project_items.get(project["path"], [])
        project["active_board_items"] = len(linked)
        project["board_items"] = [
            {"id": str(item["id"]), "title": str(item.get("title") or "Board item")}
            for item in linked if item.get("id")
        ]
    activity = activity_stats(activity_entries, now)
    board = board_stats(handled, board_active, board_later, health)
    running = running_workloads(
        task_states or [],
        running_activity or [],
        chat_items or [],
    )
    mood = command_mood(vault, activity, board)
    return {
        "generated_at": now.isoformat(),
        "local_hour": now.astimezone().hour,
        "vault": vault,
        "activity": activity,
        "board": board,
        "running": running,
        "mood": mood,
    }
