"""Read-only diagnostics. Report fixed descriptions for untrusted configuration values."""
import asyncio
from collections import Counter
from importlib import metadata
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys

from roosta import __version__, cli, skills

READ_ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, OverflowError)
STATUSES = ("PASS", "WARN", "FAIL", "SKIP")


def read_file(path, root=None):
    # Workspace metadata may be replaced with a link to a credential file or a FIFO.
    if path.is_symlink() or (root and (not path.is_relative_to(root) or path.resolve() != path)):
        raise ValueError("linked file")
    if not path.is_file():
        if not path.exists():
            raise FileNotFoundError
        raise ValueError("not a regular file")
    with path.open("rb") as stream:
        body = stream.read(2**20 + 1)
    if len(body) > 2**20:
        raise ValueError("oversized file")
    return body


def mapping(data):
    if not isinstance(data, dict):
        raise ValueError("expected mapping")
    return data


def entries(data, key):
    values = mapping(data)[key]
    if not isinstance(values, list) or not all(isinstance(v, dict) for v in values):
        raise ValueError("expected records")
    return values


def yaml_entries(root, key):
    import yaml
    try:
        return entries(yaml.safe_load(read_file(root / ".roosta" / (key + ".yaml"), root)), key)
    except yaml.YAMLError:
        raise ValueError("invalid YAML") from None


def check_install(add, offline):
    from importlib.util import find_spec

    add("Python", "PASS" if sys.version_info >= (3, 11) else "FAIL",
        f"{platform.python_version()} on {platform.system()} {platform.machine()} (requires 3.11+)")
    try:
        pkg = metadata.version("roosta")
        if not isinstance(pkg, str) or not re.fullmatch(r"[0-9][A-Za-z0-9.+!-]{0,79}", pkg):
            raise ValueError
        add("Roosta", "PASS" if pkg == __version__ else "WARN", f"Running {__version__}, package metadata {pkg}")
    except (metadata.PackageNotFoundError, ValueError):
        add("Roosta", "WARN", f"Running {__version__}. Package metadata unavailable. Check the installation.")
    missing = [mod for mod in ("fastapi", "httpx", "packaging", "uvicorn", "yaml", "keyring") if not find_spec(mod)]
    add("Python dependencies", "FAIL" if missing else "PASS",
        "Repair the installation. Missing " + ", ".join(missing) if missing else "Required modules present")
    try:
        from roosta import updates
        from packaging.version import Version
    except (ImportError, *READ_ERRORS):
        add("Install route", "WARN", "Check Python dependencies and the Roosta environment variables.")
        add("Latest stable", "SKIP", "Release checker unavailable")
    else:
        kind = updates.installation()
        manager = "uv" if kind == "uv-venv" else kind
        if manager in ("uv", "pipx") and not shutil.which(manager):
            add("Install route", "WARN", f"{kind}. Put {manager} on PATH to update.")
        elif kind == "unknown":
            add("Install route", "WARN", "Check the original installer for this Python environment.")
        else:
            add("Install route", "PASS", kind)
        if offline:
            add("Latest stable", "SKIP", "Offline mode")
        else:
            try:
                version, _ = asyncio.run(updates.stable_release())
                newer = Version(version) > Version(__version__)
                add("Latest stable", "WARN" if newer else "PASS",
                    version + (". Run roosta update --check." if newer else ""))
            except updates.CHECK_ERRORS:
                add("Latest stable", "WARN", "Could not verify the GitHub release. Retry later.")
    for tool in ("git", "uv", "pipx"):
        if shutil.which(tool):
            add(tool, "PASS", "Available")
        elif tool == "git":
            add(tool, "FAIL", "Install Git for workspace setup.")
        else:
            add(tool, "SKIP", "Optional manager absent")


def check_config(add, explicit):
    data = {}
    try:
        data = mapping(json.loads(read_file(cli.CONFIG_FILE)))
        saved = data.get("workspace")
        if saved is not None and (not isinstance(saved, str) or not Path(saved).is_absolute()
                                  or "\x00" in saved):
            data.pop("workspace")
            raise ValueError
        address(data)
        stale = saved and not Path(saved).is_dir()
        add("Saved settings", "WARN" if stale else "PASS",
            "Choose an existing workspace in Settings." if stale else "Config file readable")
    except FileNotFoundError:
        add("Saved settings", "SKIP", "No saved settings")
    except READ_ERRORS:
        add("Saved settings", "WARN", "Repair workspace, host or port in the saved config.json.")
    for source, raw in (("--workspace", explicit), ("ROOSTA_WORKSPACE", os.getenv("ROOSTA_WORKSPACE")),
                        ("saved config", data.get("workspace")), ("current directory", Path.cwd())):
        if raw:
            try:
                root = Path(raw).expanduser().resolve()
            except READ_ERRORS:
                add("Workspace selection", "FAIL", f"Invalid path from {source}. Pass --workspace <folder>.")
                return None, data
            add("Workspace selection", "PASS", f"{ascii(str(root))} from {source}" if root.is_dir() else f"Missing directory from {source}")
            return root, data


def address(data):
    host, port = data.get("host", "127.0.0.1"), data.get("port", cli.DEFAULT_PORT)
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9.:%_-]+", host):
        raise ValueError
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError
    return host, port


def connector_checks(root, add):
    from roosta.connectors import ID_RE, _command

    rows = yaml_entries(root, "connectors")
    ids = set()
    for i, row in enumerate(rows, 1):
        raw_id = row.get("id")
        cid = raw_id.strip().lower() if isinstance(raw_id, str) else ""
        if (not ID_RE.fullmatch(cid) or cid in ids or ("check" in row and not _command(row["check"]))
                or type(row.get("timeout", 45)) is not int or row.get("timeout", 45) < 1
                or not isinstance(row.get("deny", []), list)
                or not all(_command(cmd) for cmd in row.get("deny", []))
                or not all(isinstance(row.get(k, {}), dict) for k in ("expect", "reject"))):
            add(f"Connector {i}", "FAIL", "Correct the id, duplicate entry, check command or policy in connectors.yaml.")
        else:
            ids.add(cid)
    add("Connector metadata", "PASS" if len(ids) == len(rows) else "WARN",
        f"{len(ids)} valid of {len(rows)}. Sign-in checks were skipped.")
    return ids


def task_checks(root, add, connectors):
    from roosta.paths import CORE_SKILLS_DIR

    rows = yaml_entries(root, "tasks")
    ids = set()
    for i, row in enumerate(rows, 1):
        label = f"Worker {i}"
        tid, skill = row.get("id"), row.get("skill")
        if not isinstance(tid, str) or not tid.strip() or tid in ids:
            add(label, "FAIL", "Set a unique non-empty id in tasks.yaml.")
        else:
            ids.add(tid)
        folder = row.get("dir", ".")
        if not isinstance(folder, str) or not folder or not (root / Path(folder).expanduser()).is_dir():
            add(label, "FAIL", "Correct this worker's working directory in tasks.yaml.")
        elif not isinstance(skill, str) or not skills.find_skill_files(skill, root / Path(folder).expanduser(), root, CORE_SKILLS_DIR):
            add(label, "FAIL", "Install the referenced skill or correct its name in tasks.yaml.")
        requires = row.get("requires", [])
        requires = [requires] if isinstance(requires, str) else requires
        if not isinstance(requires, list) or any(not isinstance(r, str) or
                (connectors is not None and r.strip().lower() not in connectors) for r in requires):
            add(label, "FAIL", "Correct the required connector references in tasks.yaml.")
        problem = task_field_error(row)
        if problem:
            add(label, "FAIL", f"Correct {problem} in this worker's tasks.yaml entry.")
        elif row.get("allow_git_push") or row.get("push_on_schedule"):
            add(label, "WARN", "allow_git_push and push_on_schedule are ignored; set unrestricted: true "
                "to give this worker standing approval.")
    add("Worker definitions", "PASS", f"Read {len(rows)} worker definitions")
    return rows


def task_field_error(row):
    for key in ("writer", "sensor", "unrestricted", "weekdays_only"):
        if type(row.get(key, False)) is not bool:
            return f"the boolean {key} flag"
    for key in ("idle_timeout", "max_timeout"):
        if type(row.get(key, 0)) not in (int, float) or not 0 <= row.get(key, 0) < float("inf"):
            return key
    if row.get("script"):
        return "the obsolete script field (choose a skill)"
    if not isinstance(row.get("connection", ""), str):
        return "the connection id"
    interval = row.get("interval", 1800)
    if type(interval) is not int or interval <= 0:
        return "the interval in seconds"
    run_at = row.get("run_at", "")
    if not isinstance(run_at, str) or (run_at and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", run_at)):
        return "run_at (HH:MM)"
    days = row.get("days_of_week", [])
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if not isinstance(days, list) or any(not isinstance(d, str) or d.lower() not in weekdays for d in days):
        return "days_of_week"


def ownership_check(root, add):
    from roosta.paths import CORE_SKILLS_DIR

    report = skills.status(CORE_SKILLS_DIR, root)
    forks = report["forks"]
    detail = ", ".join(f"{name} ({reason})" for name, reason in forks.items())
    add("Core skills", "WARN" if forks or report["pending"] or report["review"] or report["problems"] else "PASS",
        f"{len(report['core'])} installed core skills. " +
        (" ".join(report["problems"]) + " " if report["problems"] else "") +
        (f"Legacy copies awaiting migration: {', '.join(report['pending'])}. " if report["pending"] else "") +
        (f"Additional archived edits to review: {', '.join(report['review'])}. " if report["review"] else "") +
        (f"Forks: {detail}. Review with roosta skills status; use extend and use-core to follow updates." if forks else ""))


def ai_checks(root, add, tasks):
    path = root / ".roosta/state/ai-connections.json"
    try:
        data = json.loads(read_file(path, root))
    except FileNotFoundError:
        data = {"connections": []}
    rows = entries(data, "connections")
    providers = {"anthropic": "claude", "openai": "pi", "openrouter": "pi", "ollama": "pi", "cursor": "agent"}
    auth_types = {"anthropic": ("cli", "system", "api_key"), "openai": ("cli", "api_key"),
                  "openrouter": ("api_key",), "ollama": ("local",), "cursor": ("api_key",)}
    connected = {}
    required = set()
    worker_tools = set()
    ids = set()
    for row in rows:
        cid = row["id"]
        if not re.fullmatch(r"[a-f0-9]{32}", cid) or cid in ids or type(row["connected"]) is not bool:
            raise ValueError
        provider = row["provider"]
        if row.get("auth") not in auth_types[provider] or type(row.get("tested", False)) is not bool:
            raise ValueError
        if row["auth"] == "api_key" and not row.get("credential_ref"):
            raise ValueError
        ids.add(cid)
        if row["connected"]:
            runtimes = ("pi", "ollama") if provider == "ollama" else (providers[provider],)
            connected[cid] = runtimes
            required.update(runtimes)
    default = data.get("default", "")
    if not isinstance(default, str):
        raise ValueError
    tested = {r["id"] for r in rows if r.get("tested") is True}
    for i, task in enumerate(tasks, 1):
        connection = task.get("connection")
        if not connection or connection == "default":
            connection = default
        if isinstance(connection, str) and connection:
            if connection in connected:
                worker_tools.update(connected[connection])
            else:
                add(f"Worker {i} account", "FAIL", "Select a connected AI account in worker settings.")
        else:
            add(f"Worker {i} account", "FAIL", "Add an AI connection in Settings and make it the default.")
    add("AI accounts", "WARN" if len(rows) > len(connected) else "PASS" if rows else "SKIP",
        f"{len(connected)} connected, {len(rows)-len(connected)} disconnected in metadata. "
        "Use AI Settings to test authentication.")
    if default in connected and default in tested:
        add("Default AI account", "PASS", "Connected and previously tested in Settings")
    elif rows or default:
        add("Default AI account", "WARN", "Test and select a connected default in AI Settings.")
    else:
        add("Default AI account", "SKIP", "No named accounts configured")
    for tool in ("claude", "pi", "ollama", "agent"):
        cache = root / ".roosta/state/cache/runtimes"
        found = shutil.which(tool)
        if not found and tool in ("claude", "pi") and cache.resolve() == cache:
            found = any(p.is_file() and os.access(p, os.X_OK) and p.resolve().is_relative_to(cache)
                        for p in cache.glob(f"{tool}-*/{tool}"))
        if not found and tool in ("claude", "agent"):
            binary = Path.home() / ".local/bin" / tool
            found = binary.is_file() and os.access(binary, os.X_OK)
        if found:
            add(tool, "PASS", "Executable present")
        elif tool in worker_tools or tool in required:
            add(tool, "FAIL" if tool in worker_tools else "WARN",
                "Install this configured runtime or select an available engine in Settings.")
        else:
            add(tool, "SKIP", "Optional runtime absent")


def workspace_checks(root, add, selected):
    if not root.is_dir():
        add("Directory", "FAIL", "Workspace directory missing. Choose an existing folder.")
        return
    config_dir = root / ".roosta"
    if not config_dir.is_dir():
        add("Workspace layout", "FAIL" if selected else "WARN",
            "No .roosta directory. Pass --workspace <folder> or initialise a workspace with roosta init.")
        return
    if config_dir.resolve() != config_dir:
        add("Workspace layout", "FAIL", "Replace the linked .roosta directory with workspace-local configuration.")
        return
    ready = all(os.access(p, os.R_OK | os.W_OK | os.X_OK) for p in (root, config_dir))
    state = config_dir / "state"
    if state.exists() or state.is_symlink():
        ready = ready and state.is_dir() and state.resolve() == state and os.access(state, os.R_OK | os.W_OK | os.X_OK)
    add("Permissions", "PASS" if ready else "FAIL", "Workspace and state accessible" if ready
        else "Check workspace and state directory ownership and permissions.")
    free = shutil.disk_usage(root).free
    add("Disk space", "WARN" if free < 100 * 2**20 else "PASS", f"{free // 2**20:,} MiB free"
        + (". Free space for worker output." if free < 100 * 2**20 else ""))
    missing = [name for name in ("PROFILE.md", "AGENTS.md", ".agents/skills") if not (root / name).exists()]
    add("Starter files", "WARN" if missing else "PASS", "Restore using roosta init. Missing " + ", ".join(missing)
        if missing else "Profile, instructions and skill directory present")
    connectors = None
    try:
        connectors = connector_checks(root, add)
    except FileNotFoundError:
        add("Connectors", "WARN", "Missing connectors.yaml. Restore it with roosta init.")
        connectors = set()
    except (ImportError, *READ_ERRORS):
        add("Connectors", "FAIL", "Check connectors.yaml syntax, structure and read permissions.")
    try:
        tasks = task_checks(root, add, connectors)
    except (ImportError, *READ_ERRORS):
        tasks = []
        add("Workers", "FAIL", "Repair tasks.yaml or restore it with roosta init.")
    try:
        ownership_check(root, add)
    except READ_ERRORS:
        add("Core skills", "WARN", "Review skill ownership paths and run roosta skills status for this workspace.")
    return tasks


def service_checks(root, config, add, offline):
    status = cli.service_status(root, probe=not offline)
    if status["installed"]:
        matches = status["workspace"] and Path(status["workspace"]) == root
        add("Background service", "PASS" if matches else "WARN", "Configured for this workspace" if matches
            else "Check the workspace in the installed service definition.")
        if offline:
            add("Service status", "SKIP", "Offline mode. Only the service definition was checked.")
        elif status["active"] is True:
            add("Service status", "PASS", "Active")
        elif status["active"] is False:
            add("Service status", "WARN", "Inactive. Check the user service if it should be running.")
        else:
            add("Service status", "WARN", "Unknown. Check the user service manager.")
    else:
        add("Background service", "SKIP", "No service definition for this platform or user")
    try:
        host, port = address(config)
        if status["installed"] and status["workspace"] == str(root) and status["port"]:
            port = status["port"]
        if host in ("localhost", "0.0.0.0"):
            host = "127.0.0.1"
        elif host == "::":
            host = "::1"
        ip = ipaddress.ip_address(host)
        if not ip.is_loopback or "%" in host or not 1 <= port <= 65535:
            raise ValueError
        endpoint = f"http://{'['+host+']' if ip.version == 6 else host}:{port}"
    except ValueError:
        add("Local endpoint", "SKIP", "Select a valid loopback address to probe the runner.")
        return
    if offline:
        add("Local endpoint", "SKIP", f"{endpoint} (offline mode)")
        return
    try:
        from roosta import updates
    except (ImportError, *READ_ERRORS):
        add("Local endpoint", "SKIP", "Repair the Roosta environment to probe the runner.")
        return
    try:
        result = asyncio.run(updates.read_json(endpoint + "/api/settings/workspace"))
        running = result["version"]
        if not isinstance(running, str) or not re.fullmatch(r"\d{1,9}\.\d{1,9}\.\d{1,9}", running):
            raise ValueError
        workspace = result["workspace"]
        if not isinstance(workspace, str) or not Path(workspace).is_absolute():
            raise ValueError
        served = Path(workspace).resolve()
        add("Local endpoint", "PASS" if running == __version__ else "WARN",
            f"{endpoint} serves Roosta {running}." + (" Restart the intended runner if needed." if running != __version__ else ""))
        if root is None:
            add("Runner workspace", "SKIP", "No workspace selected for comparison.")
        elif served == root:
            add("Runner workspace", "PASS", "Serving the selected workspace")
        else:
            add("Runner workspace", "WARN", "Serving a different workspace. Check the runner address and workspace.")
    except (*updates.CHECK_ERRORS, RuntimeError):
        add("Local endpoint", "WARN", f"No verified Roosta response at {endpoint}. Check the runner address or start it.")


def doctor(workspace=None, as_json=False, offline=False):
    checks = []

    def add(name, status, detail):
        checks.append(dict(section=section, name=name, status=status, detail=detail))

    section = "Installation"
    check_install(add, offline)
    section = "Workspace"
    root, config = check_config(add, workspace)
    if root is not None:
        try:
            selected = workspace is not None or os.getenv("ROOSTA_WORKSPACE") or config.get("workspace")
            tasks = workspace_checks(root, add, selected)
        except READ_ERRORS:
            tasks = None
            add("Workspace access", "FAIL", "Check the path and read permissions.")
        section = "AI accounts and runtimes"
        if tasks is None:
            add("AI configuration", "SKIP", "Select an initialised workspace.")
        else:
            try:
                ai_checks(root, add, tasks)
            except READ_ERRORS:
                add("AI accounts", "WARN", "Repair ai-connections.json in workspace state or review AI Settings.")
    section = "Service"
    try:
        service_checks(root, config, add, offline)
    except READ_ERRORS:
        add("Background service", "WARN", "Check the local service definition.")
    counts = Counter(c["status"] for c in checks)
    summary = {s: counts[s] for s in STATUSES}
    if as_json:
        print(json.dumps({"checks": checks, "summary": summary}, indent=2))
    else:
        previous = None
        for c in checks:
            if c["section"] != previous:
                previous = c["section"]
                print(f"\n{previous}")
            print(f"  {c['status']:4}  {c['name']:<20}  {c['detail']}")
        print("\nSummary  " + "   ".join(f"{n} {s}" for s, n in summary.items()))
    return int(bool(counts["FAIL"]))
