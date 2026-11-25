"""The `roosta` command: set up a workspace, run the assistant, install it as a service."""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from roosta import __version__, skills

DEFAULT_PORT = 7667  # R-O-O-S on a phone keypad
GITIGNORE_LINES = (".roosta/state/", ".env", ".env.*", "__pycache__/", ".DS_Store")


# --- init ---


def preflight() -> list[str]:
    """What is missing for a first run. Empty means ready."""
    problems = []
    if sys.version_info < (3, 11):
        problems.append(f"Python 3.11 or newer is needed (this is {platform.python_version()}).")
    if not shutil.which("git"):
        problems.append("git is not installed.")
    return problems


def copy_skeleton(source: Path, target: Path) -> list[str]:
    """Copy the starter workspace without overwriting anything that exists."""
    created = []
    existing = any(target.iterdir())
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if existing and relative.as_posix() in {"WORKSPACE.md", "Working context.md"}:
            continue
        if "__pycache__" in relative.parts:
            continue
        destination = skills.local(target, relative)
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            created.append(relative.as_posix())
    return created


def ensure_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [line for line in GITIGNORE_LINES if line not in existing]
    if missing:
        text = "\n".join(existing + ([""] if existing else []) + ["# Roosta"] + missing) + "\n"
        path.write_text(text, encoding="utf-8")


def ensure_links(root: Path) -> list[str]:
    """CLAUDE.md -> AGENTS.md and .claude/skills -> .agents/skills, where nothing is there yet.

    On platforms without symlinks Claude gets its own folder.
    """
    notes = []
    claude_md = root / "CLAUDE.md"
    if not claude_md.exists() and not claude_md.is_symlink():
        try:
            claude_md.symlink_to("AGENTS.md")
        except OSError:
            shutil.copy2(root / "AGENTS.md", claude_md)
            notes.append("CLAUDE.md is a copy of AGENTS.md; keep them in step.")
    claude_skills = root / ".claude" / "skills"
    if not claude_skills.exists() and not claude_skills.is_symlink():
        claude_skills.parent.mkdir(parents=True, exist_ok=True)
        try:
            claude_skills.symlink_to(Path("..") / ".agents" / "skills", target_is_directory=True)
        except OSError:
            claude_skills.mkdir()
            notes.append("Claude has an independent skills folder. Roosta reads workspace skills from .agents/skills.")
    return notes


CONFIG_FILE = Path.home() / ".config" / "roosta" / "config.json"


def read_config(config: Path | None = None) -> dict:
    try:
        data = json.loads((config or CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_config(updates: dict, config: Path | None = None) -> None:
    config = config or CONFIG_FILE
    data = {**read_config(config), **updates}
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def remember_workspace(target: Path, config: Path | None = None) -> None:
    """Record the workspace so Roosta.app and a bare `roosta start` find it."""
    write_config({"workspace": str(target)}, config)


def remember_address(host: str, port: int, config: Path | None = None) -> None:
    """Record the address a bare `roosta start` binds to."""
    write_config({"host": host, "port": port}, config)


def notifications_enabled(config: Path | None = None) -> bool:
    """Whether Roosta.app shows native notifications. On unless turned off in Settings."""
    return read_config(config).get("notifications") is not False


def remember_notifications(enabled: bool, config: Path | None = None) -> None:
    """Record the Settings choice; Roosta.app reads it before each notification."""
    write_config({"notifications": enabled}, config)


def default_workspace() -> str:
    return read_config().get("workspace") or "."


def default_address() -> tuple[str, int]:
    """Saved host and port for `roosta start`, ignoring anything invalid."""
    data = read_config()
    host, port = data.get("host"), data.get("port")
    host = host.strip() if isinstance(host, str) and host.strip() else "127.0.0.1"
    port = port if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535 else DEFAULT_PORT
    return host, port


def init(target: Path, adopt: bool = False, check: bool = True, initialise_git: bool = True) -> int:
    from roosta import paths

    target = target.expanduser().resolve()
    if check:
        problems = preflight()
        if problems:
            print("Roosta needs a few things first:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
    if target.exists() and any(target.iterdir()) and not adopt and not (target / ".roosta").exists():
        print(f"{target} already has files. Use `roosta init --adopt {target}` to convert it in place.")
        return 1
    target.mkdir(parents=True, exist_ok=True)
    created = copy_skeleton(paths.SKELETON_DIR, target)
    if not os.path.lexists(target / ".roosta/operating-model.md"):
        skills.install_pointer(target)
    ensure_gitignore(target)
    notes = ensure_links(target)
    if initialise_git and not (target / ".git").exists() and shutil.which("git"):
        subprocess.run(["git", "init", "-q"], cwd=target, check=False)
        if not adopt:
            # A fresh workspace holds only Roosta's files, so commit them; setup and the
            # gardener then commit their own work on top. Adopted folders are left to the user.
            subprocess.run(["git", "add", "-A"], cwd=target, check=False)
            committed = subprocess.run(["git", "commit", "-qm", "chore: initialise Roosta workspace"],
                                       cwd=target, check=False, capture_output=True)
            if committed.returncode != 0:
                notes.append("could not make the first commit (is git's user.name set?); commit it yourself")
    remember_workspace(target)
    print(f"Roosta {__version__} workspace ready at {target}")
    print(f"  {len(created)} starter files. Core skills run from the installed package.")
    for note in notes:
        print(f"  note: {note}")
    print(f"\nNext: roosta start --workspace {target}")
    return 0


# --- start ---


def start(workspace: Path, host: str, port: int) -> int:
    workspace = workspace.expanduser().resolve()
    if not (workspace / ".roosta").is_dir():
        print(f"{workspace} is not a Roosta workspace. Run `roosta init {workspace}` first.")
        return 1
    # paths reads this at import, so it must be set before the app loads.
    os.environ["ROOSTA_WORKSPACE"] = str(workspace)
    # Runs and chats inherit this, so skills can reach the runner on whatever port it uses.
    os.environ["ROOSTA_PORT"] = str(port)
    os.environ["ROOSTA_HOST"] = host
    os.chdir(workspace)
    import uvicorn

    print(f"Roosta {__version__}: http://{host}:{port}/assistant  (workspace {workspace})")
    uvicorn.run("roosta.app:app", host=host, port=port, log_level="info")
    return 0


# --- service ---

LAUNCHD_LABEL = "dev.roosta.runner"


def launchd_plist(executable: str, workspace: Path, port: int, log_dir: Path) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{executable}</string><string>start</string>
    <string>--workspace</string><string>{workspace}</string>
    <string>--port</string><string>{port}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StandardOutPath</key><string>{log_dir}/runner.log</string>
  <key>StandardErrorPath</key><string>{log_dir}/runner.log</string>
</dict>
</plist>
"""


def systemd_unit(executable: str, workspace: Path, port: int) -> str:
    return f"""[Unit]
Description=Roosta runner
After=network-online.target

[Service]
ExecStart={executable} start --workspace {workspace} --port {port}
Restart=on-failure
Environment=PATH={Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
"""


def launchd_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def systemd_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "roosta.service"


def activation_command(system: str, path: Path) -> str:
    return f"launchctl load -w {path}" if system == "Darwin" else "systemctl --user enable --now roosta"


def _service_arguments(arguments: list[str]) -> tuple[str | None, int | None]:
    def value(flag: str) -> str | None:
        return arguments[arguments.index(flag) + 1] if flag in arguments[:-1] else None

    port = value("--port")
    return value("--workspace"), int(port) if port and port.isdigit() else None


def _probe(argv: list[str]) -> bool | None:
    try:
        # Resolve OS service utilities on the system path when called from a workspace.
        return subprocess.run(argv, env={**os.environ, "PATH": os.defpath}, capture_output=True,
                              timeout=5, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def service_status(workspace: Path, *, probe: bool = True) -> dict:
    """What `roosta service install` left behind for this platform, and whether it is running."""
    system = platform.system()
    status = {"supported": system in ("Darwin", "Linux"), "platform": {"Darwin": "macos", "Linux": "linux"}.get(system, "other"),
              "path": None, "installed": False, "workspace": None, "port": None, "active": None, "activate": None}
    if not status["supported"]:
        return status
    path = launchd_path() if system == "Darwin" else systemd_path()
    status["path"] = str(path)
    status["activate"] = activation_command(system, path)
    try:
        text = path.read_bytes() if system == "Darwin" else path.read_text(encoding="utf-8")
    except OSError:
        return status
    status["installed"] = True
    try:
        if system == "Darwin":
            arguments = [str(a) for a in plistlib.loads(text).get("ProgramArguments", [])]
        else:
            match = re.search(r"^ExecStart=(.*)$", text, re.M)
            arguments = match.group(1).split() if match else []
    except (ValueError, AttributeError, plistlib.InvalidFileException):
        arguments = []
    status["workspace"], status["port"] = _service_arguments(arguments)
    if not probe:
        return status
    status["active"] = _probe(["launchctl", "list", LAUNCHD_LABEL] if system == "Darwin"
                              else ["systemctl", "--user", "is-active", "--quiet", "roosta"])
    return status


def service_install(workspace: Path, port: int) -> int:
    workspace = workspace.expanduser().resolve()
    executable = shutil.which("roosta") or sys.argv[0]
    system = platform.system()
    if system == "Darwin":
        log_dir = workspace / ".roosta" / "state"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = launchd_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(launchd_plist(executable, workspace, port, log_dir), encoding="utf-8")
        print(f"Wrote {path}\nStart it with: {activation_command(system, path)}")
        return 0
    if system == "Linux":
        path = systemd_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_unit(executable, workspace, port), encoding="utf-8")
        print(f"Wrote {path}\nStart it with: {activation_command(system, path)}")
        return 0
    print("On Windows, run `roosta start` from Task Scheduler at log-on; see the README.")
    return 1


# --- entry point ---


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="roosta", description=__doc__)
    parser.add_argument("--version", action="version", version=f"roosta {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    update = sub.add_parser("update", help="upgrade this installation to the latest stable release")
    update.add_argument("--check", action="store_true", help="preview the update")
    doctor = sub.add_parser("doctor", help="check this installation and workspace")
    doctor.add_argument("--workspace", type=Path)
    doctor.add_argument("--json", action="store_true", help="print a structured report")
    doctor.add_argument("--offline", action="store_true", help="skip network and local endpoint probes")

    p_init = sub.add_parser("init", help="create a workspace, or convert an existing folder")
    p_init.add_argument("directory", nargs="?", default=".")
    p_init.add_argument("--no-git", action="store_true", help="skip Git repository creation")
    p_init.add_argument("--adopt", action="store_true", help="convert an existing folder in place")
    p_init.add_argument("--skip-checks", action="store_true", help=argparse.SUPPRESS)

    p_start = sub.add_parser("start", help="run the assistant in the foreground")
    p_start.add_argument("--workspace", default=None, help="default: the last workspace you initialised")
    p_start.add_argument("--host", default=None, help="default: the saved address, else 127.0.0.1")
    p_start.add_argument("--port", type=int, default=None, help=f"default: the saved port, else {DEFAULT_PORT}")

    p_service = sub.add_parser("service", help="run the assistant as a background service")
    service_sub = p_service.add_subparsers(dest="action", required=True)
    p_install = service_sub.add_parser("install")
    p_install.add_argument("--workspace", default=".")
    p_install.add_argument("--port", type=int, default=DEFAULT_PORT)

    p_skills = sub.add_parser("skills", help="manage the core skills Roosta ships")
    skills_sub = p_skills.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("instructions", "print the installed operating model and effective skill routes"),
        ("status", "show installed skills, extensions and pinned forks"),
        ("sync", "show skill ownership and restart guidance for legacy copies"),
        ("extend", "create or locate additive instructions"),
        ("fork", "pin an editable copy of the installed skill"),
        ("use-core", "archive the fork and resume installed core plus extensions"),
    ):
        command = skills_sub.add_parser(action, help=help_text)
        command.add_argument("--workspace", default=os.environ.get("ROOSTA_WORKSPACE") or ".")
        if action == "instructions":
            command.add_argument("name", nargs="?", default="")
        if action in {"extend", "fork", "use-core"}:
            command.add_argument("name")
    skills_sub.add_parser("path", help="print the folder holding Roosta's shipped core skills")

    snapshot = sub.add_parser("snapshot", help="read live board or worker JSON from the local runner")
    snapshot.add_argument("resource", choices=("board", "tasks"))

    p_usage = sub.add_parser("usage", help="summarise local Assistant usage (for the roosta-engineer)")
    p_usage.add_argument("--workspace", default=None)
    p_usage.add_argument("--days", type=int, default=14)

    args = parser.parse_args(argv)
    if args.command == "update":
        try:
            from roosta.cli_update import update
        except (ImportError, ValueError, OSError, RuntimeError):
            print("Cannot load the updater. Run roosta doctor --offline to check this installation.")
            return 1
        return update(args.check)
    if args.command == "doctor":
        from roosta.doctor import doctor
        return doctor(args.workspace, args.json, args.offline)
    if args.command == "init":
        return init(Path(args.directory), adopt=args.adopt, check=not args.skip_checks, initialise_git=not args.no_git)
    if args.command == "start":
        saved_host, saved_port = default_address()
        return start(Path(args.workspace or default_workspace()), args.host or saved_host, args.port or saved_port)
    if args.command == "service":
        return service_install(Path(args.workspace), args.port)
    if args.command == "snapshot":
        import httpx

        try:
            port = int(os.environ.get("ROOSTA_PORT") or default_address()[1])
            if not 1 <= port <= 65535:
                raise ValueError("port must be between 1 and 65535")
            response = httpx.get(f"http://127.0.0.1:{port}/api/{args.resource}",
                                 trust_env=False, follow_redirects=False, timeout=10)
            response.raise_for_status()
            data = response.json()
            if args.resource == "board":
                document = data.get("document") if isinstance(data, dict) else None
                if not isinstance(document, dict) or not all(isinstance(document.get(key), list) for key in ("items", "later")):
                    raise ValueError("expected a board with document.items and document.later lists")
            print(json.dumps(data))
        except (ValueError, httpx.HTTPError) as exc:
            print(f"Cannot read local {args.resource} snapshot: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "usage":
        from roosta.usage import UsageStore

        root = Path(args.workspace or os.environ.get("ROOSTA_WORKSPACE") or default_workspace()).expanduser().resolve()
        store = UsageStore(root / ".roosta" / "state" / "cache" / "product-usage.jsonl")
        print(json.dumps(store.summary(args.days), indent=2))
        return 0
    if args.command == "skills":
        from roosta import paths

        if args.action == "path":
            print(paths.CORE_SKILLS_DIR)
            return 0
        workspace = Path(args.workspace).expanduser().resolve()
        if not (workspace / ".roosta").is_dir():
            print("Choose a Roosta workspace with --workspace.")
            return 1
        try:
            if args.action == "instructions":
                print(skills.instructions(args.name, workspace, workspace))
                return 0
            if args.action == "sync":
                print("Legacy skills migrate on the next Roosta startup. Finish active runs before restarting.")
            if args.action in {"sync", "status"}:
                print(json.dumps(skills.status(paths.CORE_SKILLS_DIR, workspace), indent=2))
            else:
                result = skills.manage(args.action, args.name, workspace, paths.CORE_SKILLS_DIR)
                if result.parent.name == "skill-decisions":
                    print(f"{args.name} will be archived the next time Roosta starts.")
                else:
                    print(result)
        except (OSError, ValueError) as exc:
            print(exc)
            return 1
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
