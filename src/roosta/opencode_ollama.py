"""OpenCode through Ollama integration for scheduled dashboard tasks."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from roosta.cursor_agent import agent_path

from roosta import connectors, paths, skills

DASHBOARD_ROOT = Path(__file__).resolve().parent
OLLAMA = shutil.which("ollama") or "/usr/local/bin/ollama"
USER_OPENCODE = Path.home() / ".opencode" / "bin" / "opencode"
OPENCODE = (
    str(USER_OPENCODE)
    if USER_OPENCODE.is_file()
    else shutil.which("opencode") or str(USER_OPENCODE)
)
SAFE_CONFIG = DASHBOARD_ROOT / "opencode-runner.json"
SAFE_CONFIG_DIR = paths.CACHE_DIR / "opencode-runner-config"
INCOMPATIBLE_OPENCODE_MODEL_PREFIXES = ("qwen2.5-coder:",)


def opencode_model_compatible(model: str) -> bool:
    """Reject installed models proven unable to execute OpenCode tools."""
    return bool(model.strip()) and not model.startswith(INCOMPATIBLE_OPENCODE_MODEL_PREFIXES)


def opencode_ollama_available(
    model: str,
    *,
    ollama_binary: str = OLLAMA,
    opencode_binary: str = OPENCODE,
) -> bool:
    """Check the local binaries and model name without starting a model."""
    def executable(binary: str) -> bool:
        return Path(binary).is_file() if Path(binary).is_absolute() else bool(shutil.which(binary))

    return (
        executable(ollama_binary)
        and executable(opencode_binary)
        and opencode_model_compatible(model)
    )


def ensure_opencode_config(
    workspace: str | None = None,
    skill: str | None = None,
) -> Path:
    """Seed the safety policy and explicit skill paths into runtime config."""
    config = json.loads(SAFE_CONFIG.read_text(encoding="utf-8"))
    for rule in connectors.shell_denials(paths.CONNECTORS_FILE):
        config["permission"]["bash"].setdefault(f"{rule} *", "deny")
    files = skills.find_skill_files(skill or "", workspace or paths.WORKSPACE,
                                   paths.WORKSPACE, paths.CORE_SKILLS_DIR)
    config["skills"] = {"paths": [str(path.parent) for path in files[:1]]}
    directory = SAFE_CONFIG_DIR
    if files:
        # Parallel workers may have different skill roots, even for the same name.
        directory /= hashlib.sha256(str(files[0]).encode()).hexdigest()[:24]
    destination = directory / "opencode.json"
    source = json.dumps(config, indent=2) + "\n"
    try:
        if destination.read_text(encoding="utf-8") == source:
            return directory
    except OSError:
        pass
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = directory / f"opencode.{os.getpid()}.tmp"
    temporary.write_text(source, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(destination)
    return directory


def opencode_ollama_env(
    base: dict | None = None,
    *,
    workspace: str | None = None,
    skill: str | None = None,
) -> dict:
    """Return a child environment with the dashboard's unattended safety policy."""
    env = dict(os.environ if base is None else base)
    inherited = agent_path(env.get("PATH")).split(os.pathsep)
    env["PATH"] = os.pathsep.join(dict.fromkeys([str(Path(OPENCODE).parent), *inherited]))
    env["OPENCODE_CONFIG_DIR"] = str(ensure_opencode_config(workspace, skill))
    if workspace:
        # OpenCode 2 takes its project directory from PWD, not the process cwd, so an
        # inherited PWD (the dashboard's own folder) would put the run in the wrong project.
        env["PWD"] = str(Path(workspace).expanduser())
    return env


def opencode_ollama_args(
    prompt: str,
    *,
    workspace: str,
    model: str,
    ollama_binary: str = OLLAMA,
) -> list[str]:
    """Build a headless OpenCode run using Ollama's ephemeral provider config."""
    args = [
        ollama_binary,
        "launch",
        "opencode",
        "--model",
        model,
        "--yes",
        "--",
        "run",
        # A private server reads this run's OPENCODE_CONFIG_DIR policy; the shared
        # background service would apply whatever config it started with.
        "--standalone",
        "--format",
        "json",
        "--auto",
    ]
    if model.startswith("qwen3.5:"):
        # OpenCode 2 names the variant on the model: provider/model#variant.
        args.extend(["--model", f"ollama/{model}#none"])
    # OpenCode 2 dropped --dir (the project comes from PWD; see opencode_ollama_env) and --pure.
    return [*args, prompt]


def opencode_result_text(stdout: str) -> str:
    """Collect completed assistant text from OpenCode's JSON event stream."""
    text_parts: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part")
        if (
            event.get("type") == "text"
            and isinstance(part, dict)
            and isinstance(part.get("text"), str)
        ):
            text_parts.append(part["text"])
    return "\n".join(text_parts)


def is_unexecuted_tool_call(text: str) -> bool:
    """Detect a model printing a tool call as text instead of invoking it."""
    candidate = text.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, count=1)
        candidate = re.sub(r"\s*```$", "", candidate, count=1)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    tool_name = payload.get("name", payload.get("function"))
    return (
        isinstance(tool_name, str)
        and isinstance(payload.get("arguments"), dict)
    )


def parse_cursor_models(stdout: str) -> list[dict[str, str]]:
    """Parse `agent models` output into model choices."""
    choices = []
    for line in stdout.splitlines():
        match = re.fullmatch(r"([A-Za-z0-9._-]+)\s+-\s+(.+)", line.strip())
        if match:
            choices.append({"id": match.group(1), "label": match.group(2).strip()})
    return choices


def parse_ollama_models(stdout: str) -> list[dict[str, str]]:
    """Parse the first column of `ollama list` output."""
    choices = []
    for line in stdout.splitlines()[1:]:
        columns = line.split()
        if (
            columns
            and re.fullmatch(r"[A-Za-z0-9._:/-]{1,120}", columns[0])
            and opencode_model_compatible(columns[0])
        ):
            choices.append({"id": columns[0], "label": columns[0]})
    return choices
