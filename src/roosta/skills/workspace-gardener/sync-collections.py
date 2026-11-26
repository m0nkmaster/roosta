#!/usr/bin/env python3
"""workspace-gardener helper: keep Workspace collection indexes in step with
their frontmatter membership rules.

A collection overview linked from WORKSPACE.md may declare, in its frontmatter:

    collect_tag: ai                       # visible docs tagged `ai` become members
    collect_path: projects/*/README.md    # and/or a glob from the workspace root
    collect_order: newest-first           # optional: newest-first | alphabetical
    exclude: [../notes/old.md]            # optional; paths relative to the index

The helper only ever ADDS list items. It never removes, reorders or rewrites
existing entries, headings or prose, so curated lists survive. To keep a page
out, add its path to `exclude` (deleting the line alone lets the next run re-add
it). Links whose target no longer exists are reported, never removed.

Usage (from the workspace root):
  sync-collections.py            # dry run: print what would change
  sync-collections.py --write    # apply
  sync-collections.py --json     # machine-readable report

Standard library only; run with `python3 -I`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Matches roosta.workspace.EXCLUDED so members are pages the Workspace can show.
EXCLUDED = {"private", "code", "node_modules", "cache", "__pycache__"}
LINK_RE = re.compile(r"\[[^\]]*\]\((<[^>]+>|[^)\s]+)[^)]*\)")
ITEM_RE = re.compile(r"^[-*+] \[")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def glob_match(rel: str, pattern: str) -> bool:
    """Workspace-root glob where `*` stays inside one folder and `**/` spans any depth."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.fullmatch(out, rel) is not None


def frontmatter(text: str) -> dict[str, object]:
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, re.S)
    if not m:
        return {}
    data: dict[str, object] = {}
    lines = m.group(1).splitlines()
    for i, line in enumerate(lines):
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", line)
        if not km:
            continue
        key, raw = km.group(1), km.group(2)
        if raw == "":
            items = []
            for nxt in lines[i + 1:]:
                bm = re.match(r"^\s+-\s+(.*?)\s*$", nxt)
                if not bm:
                    break
                items.append(bm.group(1).strip("'\""))
            data[key] = items
        elif raw.startswith("[") and raw.endswith("]"):
            data[key] = [v.strip().strip("'\"") for v in raw[1:-1].split(",") if v.strip()]
        else:
            data[key] = raw.split(" #", 1)[0].strip().strip("'\"")
    return data


def values(raw: object) -> list[str]:
    if isinstance(raw, str):
        return [raw] if raw else []
    return [v for v in raw if isinstance(v, str) and v] if isinstance(raw, list) else []


def title_of(path: Path, text: str) -> str:
    t = frontmatter(text).get("title")
    if isinstance(t, str) and t:
        return t
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else path.stem.replace("-", " ").title()


def visible(root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return (path.suffix.lower() == ".md" and path.is_file() and not path.is_symlink()
            and all(p.lower() not in EXCLUDED and not p.startswith(".") for p in rel.parts))


def markdown_files(root: Path) -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in EXCLUDED and not d.startswith(".")]
        out.extend(Path(dirpath) / n for n in filenames if n.lower().endswith(".md"))
    return sorted(p for p in out if visible(root, p))


def link_target(index: Path, line: str) -> Path | None:
    m = LINK_RE.search(line)
    if not m:
        return None
    dest = m.group(1).strip("<>").split("#", 1)[0].replace("%20", " ")
    if not dest or re.match(r"^[a-z][a-z0-9+.-]*:", dest, re.I):
        return None
    return Path(os.path.normpath(index.parent / dest))


def collections(root: Path) -> list[Path]:
    ws = root / "WORKSPACE.md"
    if not ws.is_file():
        return []
    seen, out = set(), []
    for line in ws.read_text(encoding="utf-8").splitlines():
        if ITEM_RE.match(line):
            target = link_target(ws, line)
            if target and target not in seen and visible(root, target):
                seen.add(target)
                out.append(target)
    return out


def sync(root: Path, index: Path, docs: list[Path], write: bool) -> dict | None:
    text = index.read_text(encoding="utf-8")
    fm = frontmatter(text)
    tags = values(fm.get("collect_tag"))
    globs = values(fm.get("collect_path"))
    if not tags and not globs:
        return None
    order = fm.get("collect_order") if isinstance(fm.get("collect_order"), str) else ""
    excluded = {Path(os.path.normpath(index.parent / e)) for e in values(fm.get("exclude"))}
    lines = text.splitlines()
    linked, rows, missing = set(), [], []
    for i, line in enumerate(lines):
        if not ITEM_RE.match(line):
            continue
        rows.append(i)
        target = link_target(index, line)
        if target:
            linked.add(target)
            if not target.exists():
                missing.append(line.strip())

    def wanted(doc: Path) -> bool:
        rel = doc.relative_to(root).as_posix()
        if any(glob_match(rel, g) for g in globs):
            return True
        texts = doc.read_text(encoding="utf-8", errors="replace")
        return bool(set(tags) & set(values(frontmatter(texts).get("tags"))))

    new = [d for d in docs if d != index and d not in linked and d not in excluded and wanted(d)]
    added = []
    for doc in new:
        title = title_of(doc, doc.read_text(encoding="utf-8", errors="replace"))
        rel = os.path.relpath(doc, index.parent).replace(os.sep, "/").replace(" ", "%20")
        entry = f"- [{title}]({rel})"
        added.append(entry)
        if not rows:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(entry)
            rows.append(len(lines) - 1)
            continue
        pos = rows[-1] + 1
        for r in rows:
            if order == "alphabetical":
                m = re.match(r"^[-*+] \[([^\]]*)\]", lines[r])
                if m and m.group(1).lower() > title.lower():
                    pos = r
                    break
            elif order == "newest-first":
                other = link_target(index, lines[r])
                if other and DATE_RE.match(other.name) and other.name < doc.name:
                    pos = r
                    break
        lines.insert(pos, entry)
        rows = sorted([r + 1 if r >= pos else r for r in rows] + [pos])
    if added and write:
        index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not added and not missing:
        return None
    return {"index": index.relative_to(root).as_posix(), "added": added, "missing": missing}


def main(argv: list[str]) -> int:
    write, as_json = "--write" in argv, "--json" in argv
    root = Path.cwd().resolve()
    docs = markdown_files(root)
    report = [r for i in collections(root) if (r := sync(root, i, docs, write))]
    if as_json:
        print(json.dumps({"written": write, "collections": report}, indent=2))
    elif not report:
        print("collections in sync")
    else:
        for r in report:
            print(r["index"])
            print("".join(f"  add: {a}\n" for a in r["added"]), end="")
            print("".join(f"  missing target: {m}\n" for m in r["missing"]), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
