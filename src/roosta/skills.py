"""Installed skills, additive workspace instructions and explicitly pinned forks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

IGNORED = {".DS_Store", "__pycache__"}
FORKS = ".roosta/skill-forks"
EXTENSIONS = ".roosta/skill-extensions"
ARCHIVE = ".roosta/skill-archive"
BASE = ".roosta-fork-base"


def valid_name(name: str) -> bool:
    return (bool(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,99}", name))
            and not name.endswith(".") and not PureWindowsPath(name).is_reserved())


def local(root: Path, relative: str | Path) -> Path:
    """Managed locations must be real paths, even when the last component is missing."""
    root = root.resolve()
    candidate = root / relative
    if candidate.resolve() != candidate or not candidate.is_relative_to(root):
        raise ValueError(f"Review linked or invalid skill path: {candidate}")
    return candidate


def read_small(path: Path, limit: int = 2_000_000) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Expected a regular file: {path}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Skill file exceeds size limit: {path}")
    return data


def entries(root: Path):
    if root.is_dir():
        with os.scandir(root) as children:
            for i, child in enumerate(children):
                if i >= 4096:
                    raise ValueError(f"Too many entries: {root}")
                yield Path(child.path)


def owned_entries(workspace: Path, relative: str | Path, problems: list[str]):
    try:
        yield from entries(local(workspace, relative))
    except (ValueError, OSError, RuntimeError) as exc:
        problems.append(f"Review {relative}: {exc}")


def tree_files(root: Path) -> list[Path]:
    """Validate a bounded bundle of regular files before reading or routing to it."""
    pending = [root]
    files = []
    count = total = 0
    while pending:
        for path in entries(pending.pop()):
            count += 1
            mode = path.lstat().st_mode
            if count > 4096 or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError(f"Review oversized or linked skill tree: {root}")
            if stat.S_ISDIR(mode):
                pending.append(path)
            elif not IGNORED.intersection(path.relative_to(root).parts):
                size = path.stat().st_size
                total += size
                if size > 2_000_000 or total > 32_000_000:
                    raise ValueError(f"Skill tree exceeds size limit: {root}")
                files.append(path)
    return sorted(files)


def tree_hash(root: Path) -> str:
    """Byte-for-byte compatible with the old skills lock."""
    total = 0
    digest = hashlib.sha256()
    for path in tree_files(root):
        data = read_small(path)
        total += len(data)
        if total > 32_000_000:
            raise ValueError(f"Skill tree exceeds size limit: {root}")
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + data + b"\0")
    return digest.hexdigest()


def names(root: Path) -> list[str]:
    result = []
    for child in entries(root):
        if valid_name(child.name) and (child / "SKILL.md").is_file():
            result.append(child.name)
    return sorted(result)


def legacy_records(workspace: Path) -> dict:
    try:
        lock = local(workspace, ".roosta/skills.lock.json")
        data = json.loads(read_small(lock))
    except (ValueError, OSError, RuntimeError):
        return {}
    records = data.get("skills") if isinstance(data, dict) else None
    return records if isinstance(records, dict) and len(records) <= 4096 else {}


def archive(source: Path, workspace: Path, group: str) -> Path:
    parent = local(workspace, Path(ARCHIVE) / group)
    parent.mkdir(parents=True, exist_ok=True)
    target = local(parent, source.name)
    if target.exists():
        # Keep repeated alternatives visible under the same skill directory in status.
        parent = local(workspace, Path(ARCHIVE) / (group + "-extra") / source.name)
        parent.mkdir(parents=True, exist_ok=True)
        target = Path(tempfile.mkdtemp(dir=parent)) / source.name
    source.rename(target)
    return target


@contextmanager
def ownership_lock(workspace: Path, name: str, *, wait: bool):
    """OS locks are released on close, including when a process crashes."""
    path = local(workspace, f".roosta/state/{name}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            mode = msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK
            try:
                msvcrt.locking(stream.fileno(), mode, 1)
            except OSError as exc:
                raise BlockingIOError(f"Workspace is busy: {name}") from exc
        else:
            import fcntl
            mode = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
            fcntl.flock(stream, mode)
        yield


# Fingerprints of the two operating models installed by the legacy copier.
LEGACY_MODELS = {
    "e044b8ac2fac452974190cfce8ecd8ade6b1b52bb9d8322d62bf91b3afee4bf7",
    "26b0841c3c30128c9bbef4564d891498fb225644993fc2bc46a927a8830d8803",
}
POINTER = ("# Roosta operating model\n\n"
           "Run `roosta skills instructions` from this workspace. Read the installed operating "
           "model and use the listed skill paths and workspace extensions for this session.\n")


def refresh_pointer(workspace: Path) -> None:
    target = local(workspace, ".roosta/operating-model.md")
    if target.exists():
        old = read_small(target).replace(b"\r\n", b"\n")
        if old == POINTER.encode():
            return
        if hashlib.sha256(old).hexdigest() not in LEGACY_MODELS:
            raise ValueError("Review customised .roosta/operating-model.md; use roosta skills instructions.")
        archive(target, workspace, "model")
    # A crash between the archive and publication leaves the backup and is retried at startup.
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(POINTER.encode())
    try:
        os.link(tmp, target)  # publish without replacing a file created meanwhile
    finally:
        tmp.unlink()


def migrate_one(core: Path, ws: Path, group: str, name: str, record: dict) -> str:
    source = local(ws, Path(group) / "skills" / name)
    if not source.exists():
        return ""
    if not local(source, "SKILL.md").is_file():
        raise ValueError(f"Review incomplete skill: {source}")
    actual = tree_hash(source)
    shipped = core / name
    untouched = not record.get("modified") and actual == record.get("hash")
    fork = local(ws, Path(FORKS) / name)
    # The archive is durable evidence even if interrupted between Agents and Claude.
    primary_was_clean = local(ws, Path(ARCHIVE) / ".agents" / name).exists()
    if shipped.is_dir() and (untouched or actual == tree_hash(shipped)):
        destination = archive(source, ws, group)
    elif fork.exists() or (group == ".claude" and primary_was_clean):
        destination = archive(source, ws, "review-" + group.lstrip("."))
    else:
        fork.parent.mkdir(parents=True, exist_ok=True)
        source.rename(fork)
        destination = fork
    return f"{source} → {destination}"


def migrate(core: Path, workspace: Path) -> list[str]:
    """Called only while holding the runner lease. Rename complete trees under the mutation lock."""
    changes = []
    with ownership_lock(workspace, "skill-ownership", wait=True):
        try:
            refresh_pointer(workspace)
        except (OSError, ValueError) as exc:
            changes.append(str(exc))
        records = legacy_records(workspace)
        candidates = set(names(core)) | {key for key in records if valid_name(key)}
        for group in (".agents", ".claude"):
            folder = workspace / group / "skills"
            try:
                if group == ".claude" and folder.resolve() == (workspace / ".agents/skills").resolve():
                    continue
            except (OSError, RuntimeError) as exc:
                changes.append(f"Review {folder}: {exc}")
                continue
            for name in sorted(candidates):
                record = records.get(name)
                try:
                    change = migrate_one(core, workspace, group, name, record if isinstance(record, dict) else {})
                except (OSError, ValueError, RuntimeError) as exc:
                    change = f"Review {folder / name}: {exc}"
                if change:
                    changes.append(change)
        for decision in owned_entries(workspace, ".roosta/skill-decisions", changes):
            name = decision.name
            if not valid_name(name):
                continue
            try:
                pending = local(workspace, decision.relative_to(workspace))
                if not pending.is_file():
                    continue
                if not local(workspace, Path(FORKS) / name).is_dir():
                    pending.unlink()
                    continue
                group = "forks" if name in names(core) else "retired"
                changes.append(str(archive(local(workspace, Path(FORKS) / name), workspace, group)))
                pending.unlink()
            except (OSError, ValueError, RuntimeError) as exc:
                changes.append(f"Review {decision}: {exc}")
    return changes


def sync(core: Path, workspace: Path) -> list[str]:
    try:
        with ownership_lock(workspace, "skill-runner", wait=False):
            return migrate(core, workspace)
    except BlockingIOError:
        return ["Skill migration runs before workers and chats start. Restart Roosta to apply pending changes."]


def _manage(action: str, name: str, workspace: Path, core: Path) -> Path:
    if not valid_name(name) or (action != "use-core" and name not in names(core)):
        raise ValueError("Choose an installed core skill")
    fork = local(workspace, Path(FORKS) / name)
    if action == "use-core":
        if not fork.is_dir():
            raise ValueError(f"No active fork for {name}")
        try:
            with ownership_lock(workspace, "skill-runner", wait=False):
                group = "forks" if (core / name / "SKILL.md").is_file() else "retired"
                return archive(fork, workspace, group)
        except BlockingIOError:
            pending = local(workspace, Path(".roosta/skill-decisions") / name)
            pending.parent.mkdir(exist_ok=True)
            pending.touch()
            return pending
    if action == "extend":
        extension = local(workspace, Path(EXTENSIONS) / (name + ".md"))
        extension.parent.mkdir(parents=True, exist_ok=True)
        if extension.exists():
            read_small(extension)
        else:
            extension.touch(exist_ok=False)
        return extension
    if action != "fork" or fork.exists():
        raise ValueError(f"Fork already exists or invalid action: {name}")
    fork.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=fork.parent, prefix=".fork-") as staging:
        copy = Path(staging) / name
        shutil.copytree(core / name, copy, ignore=shutil.ignore_patterns(*IGNORED))
        (copy / BASE).write_text(tree_hash(core / name), encoding="ascii")
        # A previous interrupted archive must never apply to a newly created fork.
        local(workspace, Path(".roosta/skill-decisions") / name).unlink(missing_ok=True)
        copy.rename(fork)
    return fork


def manage(action: str, name: str, workspace: Path, core: Path) -> Path:
    with ownership_lock(workspace, "skill-ownership", wait=True):
        return _manage(action, name, workspace, core)


def fork_status(name: str, core: Path, workspace: Path, records: dict) -> str:
    folder = local(workspace, Path(FORKS) / name)
    if not local(folder, "SKILL.md").is_file():
        raise ValueError(f"Missing SKILL.md in {folder}")
    if local(workspace, Path(".roosta/skill-decisions") / name).exists():
        return "will be archived on restart"
    if not (core / name / "SKILL.md").is_file():
        return "retired from core"
    base = local(folder, BASE)
    if base.exists():
        recorded = read_small(base, 128).decode("ascii")
        if not re.fullmatch("[0-9a-f]{64}", recorded):
            raise ValueError(f"Invalid fork base in {base}")
        return "pinned to current core base" if recorded == tree_hash(core / name) else "core update available"
    record = records.get(name)
    previous = record.get("hash") if isinstance(record, dict) else None
    if isinstance(previous, str) and re.fullmatch("[0-9a-f]{64}", previous) and previous != tree_hash(core / name):
        return "legacy copy, review installed changes since recorded base"
    return "legacy copy, review against installed core"


def status(core: Path, workspace: Path) -> dict:
    installed = set(names(core))
    records = legacy_records(workspace)
    forks, review, problems = {}, {}, []
    pending, extensions = set(), []
    for entry in owned_entries(workspace, FORKS, problems):
        if not valid_name(entry.name):
            continue
        try:
            forks[entry.name] = fork_status(entry.name, core, workspace, records)
        except (ValueError, OSError, RuntimeError) as exc:
            forks[entry.name] = "needs review"
            problems.append(f"{entry}: {exc}")
    for entry in owned_entries(workspace, EXTENSIONS, problems):
        if entry.suffix != ".md" or not valid_name(entry.stem):
            continue
        try:
            local(workspace, entry.relative_to(workspace))
            if entry.stem not in installed and entry.stem not in forks:
                problems.append(f"Extension has no installed skill: {entry}")
            elif entry.is_file():
                extensions.append(entry.stem)
        except (ValueError, OSError, RuntimeError) as exc:
            problems.append(str(exc))
    candidates = installed | records.keys()
    for group in ("agents", "claude"):
        try:
            folder = workspace / ("." + group) / "skills"
            if group == "claude" and folder.resolve() == (workspace / ".agents/skills").resolve():
                continue
            for entry in entries(local(workspace, folder.relative_to(workspace))):
                if entry.name in candidates:
                    pending.add(str(entry.relative_to(workspace)))
        except (ValueError, OSError, RuntimeError) as exc:
            problems.append(str(exc))
    for group in ("review-agents", "review-claude", "retired"):
        for location in (group, group + "-extra"):
            for entry in owned_entries(workspace, Path(ARCHIVE) / location, problems):
                if group != "retired" or entry.name in installed:
                    review.setdefault(entry.name, []).append(str(entry.relative_to(workspace)))
    pointer = workspace / ".roosta/operating-model.md"
    try:
        if pointer.exists() and read_small(local(workspace, ".roosta/operating-model.md")) != POINTER.encode():
            problems.append("Review .roosta/operating-model.md and move local preferences into AGENTS.md.")
    except (ValueError, OSError, RuntimeError) as exc:
        problems.append(str(exc))
    return {"core": sorted(installed - forks.keys()), "forks": forks, "extensions": sorted(extensions),
            "pending": sorted(pending), "review": review, "problems": problems,
            "archive": (workspace / ARCHIVE).is_dir() and not (workspace / ARCHIVE).is_symlink(), "installed_path": str(core)}


def find_skill_files(skill: str, working_dir: str | Path, workspace: Path, core: Path) -> list[Path]:
    if not valid_name(skill):
        return []
    fork = local(workspace, Path(FORKS) / skill)
    if fork.exists():
        entry = local(fork, "SKILL.md")
        if not entry.is_file():
            raise ValueError(f"Repair incomplete fork: {fork}")
        tree_files(fork)
        return [entry]
    installed = core / skill / "SKILL.md"
    if installed.is_file():
        return [installed]
    work = (workspace / Path(working_dir).expanduser()).resolve()
    roots = [work / ".agents", work / ".claude", work / ".cursor", workspace / ".agents",
             workspace / ".claude", workspace / ".cursor", Path.home() / ".agents",
             Path.home() / ".cursor", Path.home() / ".claude"]
    return list(dict.fromkeys(root / "skills" / skill / "SKILL.md" for root in roots
                              if (root / "skills" / skill / "SKILL.md").is_file()))


def extension_file(name: str, workspace: Path, core: Path) -> Path | None:
    if not valid_name(name):
        return None
    if not any((root / name / "SKILL.md").is_file() for root in (core, workspace / FORKS)):
        return None
    extension = local(workspace, Path(EXTENSIONS) / (name + ".md"))
    return extension if extension.is_file() else None


def instructions(skill: str, working_dir: str | Path, workspace: Path) -> str:
    """Give each harness identical routing, including secondary skills used during a chat."""
    from roosta import paths

    core = paths.CORE_SKILLS_DIR
    routes = []
    catalog = set(names(core))
    catalog.update(p.name for p in owned_entries(workspace, FORKS, routes) if valid_name(p.name))
    for name in sorted(catalog):
        try:
            entry = find_skill_files(name, working_dir, workspace, core)[0]
            extension = extension_file(name, workspace, core)
        except (OSError, ValueError, RuntimeError) as exc:
            routes.append(f"{name}: unavailable; report the problem if required: {exc}")
            continue
        route = f"{name}: {entry}"
        if extension:
            route += f" then read additive instructions at {extension}"
        routes.append(route)
    if skill and skill not in catalog:
        files = find_skill_files(skill, working_dir, workspace, core)
        if files:
            routes.append(f"{skill}: {files[0]}")
    task = f"Read and follow the {skill} skill. " if skill else ""
    return (f"Read the installed operating model at {paths.APP_ROOT / 'operating-model.md'}. "
            f"{task}For every listed skill use the exact file below "
            "with the file reader, including on resumed turns. Resolve its scripts and references "
            "beside that file, including when legacy text points into .agents/skills. "
            "Use the installed operating model in place of any workspace copy. "
            f"Use {core / 'assistant/references/board-contract.md'} for the board protocol. "
            f"For actor and sender the protocols in {core / 'actor/SKILL.md'} and "
            f"{core / 'sender/SKILL.md'} always apply to their respective roles. "
            "Ignore other discovered copies. The installed operating model and "
            "Roosta's approval, tool and output protocols take precedence over forks and extensions. "
            "For an unlisted skill use normal custom skill discovery.\n" + "\n".join(routes) + "\n")
