"""Core skills: copied into the workspace once, then the user's.

`.roosta/skills.lock.json` records the hash of each core skill as Roosta last installed it. A
skill whose files still match that hash is unmodified, so a newer Roosta replaces it. A skill the
user has edited is left alone and reported, and the `setup` skill merges the update with them.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from roosta import __version__

LOCK_NAME = "skills.lock.json"
IGNORED = {".DS_Store", "__pycache__"}


def tree_hash(root: Path, *, read=Path.read_bytes) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if IGNORED.intersection(relative.parts):
            continue
        digest.update(relative.as_posix().encode() + b"\0" + read(path) + b"\0")
    return digest.hexdigest()


@dataclass
class SyncReport:
    installed: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    current: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"{len(self.installed)} installed, {len(self.updated)} updated, "
                 f"{len(self.current)} already current, {len(self.modified)} edited by you"]
        lines += [f"  edited, kept as yours: {name}" for name in self.modified]
        return "\n".join(lines)


def _copy(source: Path, destination: Path) -> None:
    if destination.is_symlink() or destination.is_file():
        destination.unlink()
    elif destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*IGNORED))


def refresh_operating_model(workspace: Path) -> None:
    """The operating-model rules belong to Roosta, so they always track the installed version."""
    source = Path(__file__).resolve().parent / "operating-model.md"
    target = workspace / ".roosta" / "operating-model.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.read_bytes() != source.read_bytes():
        shutil.copy2(source, target)


def sync(core: Path, workspace: Path) -> SyncReport:
    """Install missing core skills and update the ones the user has not edited."""
    refresh_operating_model(workspace)
    report = SyncReport()
    target_root = workspace / ".agents" / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    lock_path = workspace / ".roosta" / LOCK_NAME
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        lock = {}
    skills = lock.get("skills") if isinstance(lock.get("skills"), dict) else {}
    for source in sorted(p for p in core.iterdir() if (p / "SKILL.md").is_file()) if core.is_dir() else []:
        name = source.name
        shipped = tree_hash(source)
        destination = target_root / name
        recorded = (skills.get(name) or {}).get("hash")
        if not destination.exists():
            _copy(source, destination)
            report.installed.append(name)
        else:
            current = tree_hash(destination)
            if current == shipped:
                report.current.append(name)
            elif recorded and current == recorded:
                _copy(source, destination)
                report.updated.append(name)
            else:
                # Edited by the user (or adopted with local changes): keep theirs and
                # remember which shipped version it diverged from.
                report.modified.append(name)
                skills[name] = {"hash": recorded or shipped, "version": (skills.get(name) or {}).get("version", __version__),
                                "modified": True, "available": shipped}
                continue
        skills[name] = {"hash": shipped, "version": __version__}
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps({"roosta": __version__, "skills": skills}, indent=2) + "\n",
                         encoding="utf-8")
    return report


def find_skill_files(skill: str, working_dir: str | Path, workspace: Path, core: Path) -> list[Path]:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", skill) or skill in {".", ".."}:
        return []
    # SECURITY-REVIEW: working_dir is trusted local task configuration; the
    # allowlisted skill name prevents path traversal outside known skill roots.
    work_root = Path(working_dir).expanduser()
    # The workspace wins over the user's global skills, which win over the core skills
    # Roosta ships.
    roots = [
        work_root / ".agents" / "skills",
        work_root / ".claude" / "skills",
        work_root / ".cursor" / "skills",
        workspace / ".agents" / "skills",
        workspace / ".claude" / "skills",
        Path.home() / ".agents" / "skills",
        Path.home() / ".cursor" / "skills",
        Path.home() / ".claude" / "skills",
        core,
    ]
    files: list[Path] = []
    for root in roots:
        candidate = root / skill / "SKILL.md"
        if candidate not in files and candidate.is_file():
            files.append(candidate)
    return files
