"""Custom pages: static HTML and JS in .roosta/pages/<name>/, served at /pages/<name>/.

Pages read the generic read-only APIs plus JSON that scheduled skills write to
.roosta/state/pages/<name>/. A workspace page named like a shipped one replaces it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from roosta import paths
from roosta.workspace import markdown_title, metadata, resolve_workspace_markdown, visible_path

PAGE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
PAGE_ASSET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,80}){0,3}")
PAGE_DATA_DIR = paths.STATE_DIR / "pages"
PAGE_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
              ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".woff2": "font/woff2"}
PAGE_FILES_LIMIT = 500


def page_file(name: str, pages_dir: Path | None = None) -> Path:
    """The workspace's own version of a shipped page if it has one, else Roosta's."""
    override = (pages_dir or paths.PAGES_DIR) / name / "index.html"
    return override if override.is_file() else paths.STATIC_DIR / f"{name}.html"


def contained(root: Path, relative: str) -> Path | None:
    """Resolve a validated relative path inside root, refusing symlink escapes."""
    if not PAGE_ASSET.fullmatch(relative) or ".." in relative.split("/"):
        return None
    base = root.resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target if target.is_file() else None


# Folders with these names replace a shipped page (page_file), so they already have a nav link.
SHIPPED_PAGES = frozenset({"assistant", "index", "workspace", "pulse", "office", "document", "changelog", "settings"})


def custom_pages(pages_dir: Path | None = None) -> list[dict]:
    """Every custom page with an index.html, titled from its <title> tag. Shipped-page overrides are excluded."""
    root = pages_dir or paths.PAGES_DIR
    pages = []
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        index = folder / "index.html"
        if not PAGE_NAME.fullmatch(folder.name) or folder.name in SHIPPED_PAGES or not index.is_file():
            continue
        match = re.search(r"<title>(.*?)</title>", index.read_text(encoding="utf-8", errors="ignore")[:4000], re.S | re.I)
        title = re.sub(r"\s+", " ", match.group(1)).strip() if match else folder.name.replace("-", " ").title()
        pages.append({"name": folder.name, "title": title[:40], "url": f"/pages/{folder.name}/"})
    return pages


def workspace_files(pattern: str, root: Path | None = None) -> list[dict]:
    """Workspace Markdown matching a glob, with titles and frontmatter but no bodies."""
    root = (root or paths.WORKSPACE).resolve()
    if not pattern or pattern.startswith("/") or ".." in pattern.split("/") or len(pattern) > 200:
        raise ValueError("invalid pattern")
    out = []
    for path in sorted(root.glob(pattern)):
        try:
            relative = path.relative_to(root).as_posix()
            resolved = resolve_workspace_markdown(relative, root)
        except (ValueError, FileNotFoundError):
            continue
        if not visible_path(Path(relative)):
            continue
        text = resolved.read_text(encoding="utf-8", errors="ignore")
        out.append({
            "path": relative,
            "title": markdown_title(text, path.stem),
            "frontmatter": metadata(text),
            "modified": datetime.fromtimestamp(resolved.stat().st_mtime, timezone.utc).isoformat(),
        })
        if len(out) >= PAGE_FILES_LIMIT:
            break
    return out
