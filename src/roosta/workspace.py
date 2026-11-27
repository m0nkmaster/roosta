"""Read-only workspace catalogue and explicit chat attachments."""

from datetime import datetime, timezone
import os
import posixpath
from pathlib import Path
import re
from textwrap import shorten
from urllib.parse import unquote

import yaml

from roosta import paths


EXCLUDED = {"private", "code", "node_modules", "cache", "__pycache__"}
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_CONTEXT_FILES = 8
MAX_CONTEXT_BYTES = 192 * 1024


def markdown_title(content: str, stem: str) -> str:
    """Resolve a display title from frontmatter, first heading, or filename."""
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            for line in content[3:end].splitlines():
                if line.strip().startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip("\"'")
                    if title:
                        return title
    heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if heading:
        return heading.group(1).strip()
    return stem.replace("-", " ").title()


def plain_text(value: str) -> str:
    """Flatten Markdown emphasis and links to escapable plain text."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", str(value or ""))
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def strip_frontmatter(content: str) -> str:
    """Return the document body with any frontmatter block removed."""
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 3)
    return content if end == -1 else content[end + 4:]


def metadata(content: str) -> dict:
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", content, re.S)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except (yaml.YAMLError, ValueError, OverflowError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def text_values(raw) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    return [value.strip() for value in raw if isinstance(value, str) and value.strip()] if isinstance(raw, list) else []


def document_summary(content: str, front: dict) -> str:
    description = front.get("description") or front.get("summary")
    if isinstance(description, str):
        return shorten(plain_text(description), width=240, placeholder="…")
    body = strip_frontmatter(content)
    overview = re.search(r"^##?\s+(?:Overview|Purpose|Summary|About)\s*\n(.*?)(?=^##?\s|\Z)", body, re.M | re.S | re.I)
    if overview:
        body = overview.group(1)
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    for paragraph in re.split(r"\n\s*\n", body):
        lines = [line.strip() for line in paragraph.splitlines()
                 if line.strip() and not line.lstrip().startswith(("#", "|", "- ", "* ", ">", "!["))]
        if lines:
            return shorten(plain_text(" ".join(lines)), width=240, placeholder="…")
    return ""


def document_kind(path: str, title: str, front: dict) -> str:
    name = Path(path).stem.lower()
    declared = front.get("type")
    declared = declared.lower() if isinstance(declared, str) else ""
    words = re.sub(r"[^a-z]+", " ", name + " " + title.lower()).split()
    if declared in {"decision", "adr"} or {"decision", "decisions", "adr"}.intersection(words):
        return "Decision record"
    if declared in {"plan", "proposal", "roadmap"} or {"plan", "proposal", "roadmap"}.intersection(words):
        return "Plan"
    if path.startswith("projects/") and name == "readme":
        return "Project overview"
    if path.startswith("drafts/"):
        return "Draft"
    if path.startswith("analysis/"):
        return "Research"
    return "Reference" if name in {"readme", "agents", "tools", "context"} else "Notes"


def navigation_text(body: str) -> str:
    """Mask examples and comments while keeping offsets into the original body."""
    def blank(match):
        return re.sub(r"[^\n]", " ", match[0])

    return re.sub(r"<!--.*?(?:-->|\Z)|^ {0,3}(?P<fence>(?P<marker>[`~])(?P=marker){2,})[^\n]*\n"
                  r".*?(?:^ {0,3}(?P=fence)(?P=marker)*[ \t\r]*$|\Z)", blank, body, flags=re.M | re.S)


def index_links(page: dict, known: dict, *, list_only: bool = True):
    """The first link of each top-level Markdown list item selects a visible page."""
    prefix = r"^(?:[-*+]|\d+\.)[ \t]+" if list_only else r"(?<!!)"
    links = re.finditer(prefix + r"\[[^]\n]+\]\((?:<([^>\n]+)>|([^()\s]+))\)",
                        navigation_text(strip_frontmatter(page["text"])), re.M)
    for link in links:
        raw, _, anchor = (link[1] or link[2]).partition("#")
        target = unquote(raw)
        if not target or target.startswith("/") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            continue
        path = posixpath.normpath(posixpath.join(posixpath.dirname(page["path"]), target))
        if path in known and path != page["path"]:
            yield path, unquote(anchor)


def index_members(page: dict, known: dict) -> list[str]:
    return list(dict.fromkeys(path for path, _ in index_links(page, known)))


def selected_collections(files: dict, indexed: bool) -> list[dict]:
    if indexed:
        home = files.get("WORKSPACE.md")
        overviews = index_members(home, files) if home else []
        indexes = set(overviews) | {"WORKSPACE.md"}
        return [{"id": "collection:" + path, "group": "collections", "overview": path,
                 "title": files[path]["title"], "summary": files[path]["summary"],
                 "paths": [p for p in index_members(files[path], files) if p not in indexes]}
                for path in overviews]
    paths = [p for p in files if re.fullmatch(r"projects/[^/]+/README\.md", p)]
    if paths:
        return [{"id": "collection:projects", "group": "collections", "title": "Projects",
                 "summary": "Project overviews in this workspace.", "paths": paths}]
    return [{"id": "collection:context", "group": "collections", "title": "Working context",
             "summary": "Your priorities and domain knowledge.",
             "paths": [p for p in ("PRIORITIES.md", "CONTEXT.md") if p in files]}]


def knowledge_collections(files: list[dict]) -> list[dict]:
    """Group existing metadata and document conventions; never infer claims with AI."""
    collections = []
    projects = {str(Path(file["path"]).parent): file for file in files
                if re.fullmatch(r"projects/[^/]+/README\.md", file["path"], re.I)}
    tag_sources: dict[str, list[dict]] = {}
    for file in files:
        for tag in sorted({tag.lower() for tag in file["tags"]}):
            tag_sources.setdefault(tag, []).append(file)
        parent = projects.get("/".join(file["path"].split("/")[:2]))
        file["project"] = parent["title"] if parent else ""
        file["topics"] = sorted(set(file["tags"] + (parent["tags"] if parent else [])))
        if parent and file is not parent and file["title"].lower() in {"plan", "decisions", "notes", "overview"}:
            file["title"] = parent["title"] + " — " + file["title"]
    for folder, overview in projects.items():
        collections.append({"id": "project:" + folder.split("/")[1], "group": "projects",
                            "title": overview["title"], "summary": overview["summary"],
                            "status": overview["status"], "overview": overview["path"],
                            "paths": [file["path"] for file in files if file["path"].startswith(folder + "/")]})

    acronyms = {word.lower(): word for word in ["AI", "API", "AWS", "CI", "MCP", "OKR", "SDK", "SDKs", "UI", "UX"]}
    known = {file["path"]: file for file in files}
    topics = {Path(p).stem.lower(): f for p, f in known.items() if re.fullmatch(r"topics/[^/]+\.md", p)}
    for tag in sorted(tag_sources.keys() | topics.keys()):
        sources = tag_sources.get(tag, [])
        overview = topics.get(tag)
        if len(sources) < 2 and not overview:
            continue
        paths = [file["path"] for file in files if tag in {value.lower() for value in file["topics"]}]
        if overview:
            paths = list(dict.fromkeys(index_members(overview, known) + paths))
        names = sorted({file["project"] or file["title"] for file in sources})
        title = " ".join(acronyms.get(word, word.capitalize()) for word in tag.replace("_", "-").split("-"))
        collections.append({"id": "topic:" + tag, "group": "topics", "title": overview["title"] if overview else title,
                            "overview": overview["path"] if overview else None,
                            "summary": overview["summary"] if overview else "Across " + ", ".join(names[:3]) + (" and more." if len(names) > 3 else "."),
                            "paths": paths})

    for key, title, kind, heading, summary in [
        ("decisions", "Decisions", "Decision record", r"(?:Key\s+)?Decisions?", "Decision records and documents with a decisions section."),
        ("plans", "Plans & roadmaps", "Plan", r"(?:Current\s+)?(?:Plan|Roadmap|Proposal)s?", "Plans, proposals and roadmaps for what comes next."),
    ]:
        overview = known.get(key.capitalize() + ".md")
        sources = {}
        if overview:
            for path, anchor in index_links(overview, known):
                sources.setdefault(path, []).append(anchor)
        sections = {}
        for file in files:
            path = file["path"]
            if overview is file:
                continue
            anchors = sources.get(path, [])
            excerpts = []
            body = strip_frontmatter(file["text"]) + "\n"
            for section in re.finditer(r"^##[ \t]+([^\n]+)\n(.*?)(?=^#{1,2}[ \t]|\Z)",
                                       navigation_text(body), re.M | re.S):
                title_text = section[1].strip()
                anchor = re.sub(r"[^\w -]", "", title_text.lower()).replace(" ", "-")
                if anchor in anchors or re.fullmatch(heading, title_text, re.I):
                    excerpts.append("## " + title_text + "\n\n" + body[section.start(2):section.end(2)].strip()[:2400])
            if excerpts:
                sections[path] = "\n\n".join(excerpts)
            if excerpts or file["kind"] == kind:
                sources.setdefault(path, [])
        if sources or overview:
            collections.append({"id": "work:" + key, "group": "work", "title": title,
                                "summary": overview["summary"] if overview else summary,
                                "overview": overview["path"] if overview else None,
                                "ordered": bool(overview), "paths": list(sources), "sections": sections})
    order = {"active": 0, "blocked": 1, "paused": 2, "completed": 3}
    return sorted(collections, key=lambda entry: (order.get(entry.get("status"), 4), entry["title"].casefold()))


def visible_path(path: Path) -> bool:
    return (path.suffix.lower() == ".md"
            and not path.is_absolute()
            and all(part.lower() not in EXCLUDED and not part.startswith(".") for part in path.parts))


def read_document(root: Path, raw: str) -> tuple[Path, str, int]:
    """Constrain both the requested and resolved path, including symlink targets."""
    if not isinstance(raw, str) or not raw or len(raw) > 500 or "\\" in raw:
        raise ValueError("Choose a workspace Markdown document.")
    relative = Path(raw)
    if not visible_path(relative):
        raise ValueError("Choose a workspace Markdown document.")
    workspace = root.resolve()
    try:
        target = (workspace / relative).resolve()
    except (RuntimeError, OSError) as exc:
        raise ValueError("Invalid document path.") from exc
    try:
        canonical = target.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("Document is outside the workspace.") from exc
    if not visible_path(canonical):
        raise ValueError("Choose a workspace Markdown document.")
    if not target.is_file():
        raise FileNotFoundError("Document no longer exists.")
    with target.open("rb") as source:
        content = source.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds the 2 MB preview limit.")
    return canonical, content.decode("utf-8"), len(content)


def catalogue_files(root: Path) -> tuple[list[dict], int]:
    files = []
    skipped = 0
    for parent, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories
                                if name.lower() not in EXCLUDED and not name.startswith("."))
        for name in sorted(names):
            candidate = Path(parent) / name
            relative = candidate.relative_to(root)
            if not visible_path(relative):
                continue
            try:
                if candidate.is_symlink():
                    continue
                canonical, content, size = read_document(root, relative.as_posix())
                modified = datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc).isoformat()
            except (OSError, UnicodeError, ValueError):
                skipped += 1
                continue
            front = metadata(content)
            title = plain_text(front["title"]) if isinstance(front.get("title"), str) and front["title"].strip() else markdown_title(strip_frontmatter(content), candidate.stem)
            files.append({"path": canonical.as_posix(), "title": title,
                          "text": content, "size": size, "modified": modified,
                          "summary": document_summary(content, front),
                          "kind": document_kind(canonical.as_posix(), title, front),
                          "tags": text_values(front.get("tags")),
                          "status": front.get("status") if isinstance(front.get("status"), str) else ""})
    return files, skipped


def build_catalogue(root: Path) -> dict:
    files, skipped = catalogue_files(root)
    selected = selected_collections({f["path"]: f for f in files}, os.path.lexists(root / "WORKSPACE.md"))
    return {"files": files, "collections": selected + knowledge_collections(files), "skipped": skipped,
            "indexed_at": datetime.now(timezone.utc).isoformat()}


def context_documents(root: Path, paths: list) -> list[dict]:
    if not isinstance(paths, list) or len(paths) > MAX_CONTEXT_FILES:
        raise ValueError(f"Choose up to {MAX_CONTEXT_FILES} context files.")
    documents = []
    seen = set()
    size = 0
    for raw in paths:
        relative, content, count = read_document(root, raw)
        path = relative.as_posix()
        if path in seen:
            continue
        seen.add(path)
        size += count
        if size > MAX_CONTEXT_BYTES:
            raise ValueError("Selected files exceed the 192 KB context limit. Choose fewer files.")
        documents.append({"path": path, "content": content})
    return documents


def markdown_path(raw) -> str | None:
    """A safe relative path to a Markdown document in the workspace, or None."""
    raw_path = str(raw or "").strip()
    path = Path(raw_path)
    if (
        not raw_path
        or len(raw_path) > 500
        or path.is_absolute()
        or path.suffix.lower() != ".md"
        or ".." in path.parts
        or (path.parts and path.parts[0].lower() == ".roosta")
        or any(part.lower() == "private" for part in path.parts)
    ):
        return None
    return path.as_posix()


def resolve_workspace_markdown(raw_path: str, root: Path | None = None) -> Path:
    """Resolve an allowlisted Markdown path without permitting workspace escape."""
    relative = markdown_path(raw_path)
    if relative is None:
        raise ValueError("invalid document path")
    workspace = (root or paths.WORKSPACE).resolve()
    # SECURITY-REVIEW: the path comes from a query parameter. It is constrained
    # to a relative Markdown path, resolved, and the resolved path must pass the
    # same rule, so a symlink cannot reach `.roosta/state`, `private/` or a non-Markdown file.
    target = (workspace / relative).resolve()
    try:
        canonical = target.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("invalid document path") from exc
    if markdown_path(canonical.as_posix()) is None:
        raise ValueError("invalid document path")
    if not target.is_file():
        raise FileNotFoundError("document not found")
    return target


# Plain-text files a chat reply may link (a Confluence storage body, a CSV); shown as source.
SOURCE_SUFFIXES = {".html", ".txt", ".json", ".yaml", ".yml", ".csv"}


def is_workspace_config(parts: tuple[str, ...]) -> bool:
    """A file in the user's `.roosta/` config, never its runtime `state/` or a nested dotfile."""
    lowered = [part.lower() for part in parts]
    return (
        len(lowered) >= 2
        and lowered[0] == ".roosta"
        and lowered[1] != "state"
        and not any(part.startswith(".") for part in lowered[1:])
    )


def _viewable_parts(parts: tuple[str, ...]) -> bool:
    if any(part == ".." or part.lower() == "private" for part in parts):
        return False
    return is_workspace_config(parts) or not any(part.startswith(".") for part in parts)


def resolve_workspace_text(raw_path: str, root: Path | None = None) -> Path:
    """Resolve a workspace Markdown document, an allowlisted plain-text file, or `.roosta/` config."""
    path = Path(str(raw_path or "").strip())
    suffixes = SOURCE_SUFFIXES | {".md"}
    if path.suffix.lower() not in suffixes:
        raise ValueError("invalid document path")
    if len(str(path)) > 500 or path.is_absolute() or not _viewable_parts(path.parts):
        raise ValueError("invalid document path")
    workspace = (root or paths.WORKSPACE).resolve()
    # SECURITY-REVIEW: same containment check as resolve_workspace_markdown. Dotfiles stay
    # hidden (.env, .git, .claude) except `.roosta/` config; `.roosta/state/` holds runtime
    # caches and agent configs with tokens, so it is refused, including via a symlink.
    target = (workspace / path).resolve()
    try:
        relative = target.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("invalid document path") from exc
    if not _viewable_parts(relative.parts) or target.suffix.lower() not in suffixes:
        raise ValueError("invalid document path")
    if not target.is_file():
        raise FileNotFoundError("document not found")
    return target


def source_as_markdown(content: str, suffix: str) -> str:
    """Fence a non-Markdown file so it renders verbatim; the fence outruns any backtick run."""
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{suffix.lstrip('.')}\n{content.rstrip()}\n{fence}"


def split_front_matter(content: str) -> tuple[str, list[list[str]]]:
    """Separate YAML front matter from a Markdown body as display-ready pairs.

    Marked would otherwise render the block as a rule plus a setext heading.
    """
    match = re.match(r"\A---\s*\n(.*?)\n---[ \t]*(?:\n|\Z)", content, re.DOTALL)
    if not match:
        return content, []
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return content, []
    if not isinstance(metadata, dict):
        return content, []
    properties = []
    for key, value in metadata.items():
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if not isinstance(v, (dict, list)))
        elif isinstance(value, dict) or value is None:
            continue
        if str(value).strip():
            properties.append([str(key), str(value)])
    return content[match.end():].lstrip("\n"), properties
