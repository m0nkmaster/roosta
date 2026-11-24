"""Cursor Agent CLI integration for a Cursor AI connection, plus the permission policy shared by every runtime."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from pathlib import Path

from roosta import connectors, paths

VAULT = str(paths.WORKSPACE)
CURSOR_ENV_FILE = Path(VAULT) / ".env"
CURSOR_AGENT = shutil.which("agent") or str(Path.home() / ".local" / "bin" / "agent")
SAFE_CONFIG_TEMPLATE = Path(__file__).resolve().parent / "cursor-permissions.json"


def agent_path(base_path: str | None = None) -> str:
    """PATH with common local bins prepended."""
    home = Path.home()
    preferred = [
        str(home / ".bun" / "bin"),
        str(home / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    inherited = [part for part in str(base_path or os.environ.get("PATH", "")).split(os.pathsep) if part]
    return os.pathsep.join(dict.fromkeys(preferred + inherited))


def _dotenv_value(path: Path, key: str) -> str:
    """Read one simple dotenv value without evaluating the file as shell code."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return ""
    prefix = f"{key}="
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return ""


# Login/token state the CLI caches into its config after an interactive sign-in.
# We strip these so a headless run can never fall back to a (possibly locked)
# macOS keychain login: a connection authenticates purely via its CURSOR_API_KEY.
CONFIG_LOGIN_KEYS = ("authInfo", "authToken", "authId", "accessToken", "refreshToken")


def merged_permissions(permissions: dict) -> dict:
    """The shipped policy plus each workspace connector's denied write commands."""
    extra = [connectors.cursor_shell_rule(rule)
             for rule in connectors.shell_denials(paths.CONNECTORS_FILE)]
    deny = list(permissions.get("deny", []))
    return {**permissions, "deny": deny + [rule for rule in extra if rule not in deny]}


def write_config(directory: Path, permissions: dict, mcp: dict) -> Path:
    """Write a connection's private Cursor config, dropping any interactive login the CLI cached."""
    path = directory / "cli-config.json"
    try:
        config = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    for key in CONFIG_LOGIN_KEYS:
        config.pop(key, None)
    template = json.loads(SAFE_CONFIG_TEMPLATE.read_text())
    config.update(version=template["version"], editor=template["editor"], permissions=permissions)
    for name, value in (("cli-config.json", config), ("mcp.json", mcp)):
        temporary = directory / f"{name}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(value, indent=2))
        temporary.chmod(0o600)
        temporary.replace(directory / name)
    return directory


def cursor_args(*, workspace: str, session_id: str = "", model: str = "", binary: str = CURSOR_AGENT) -> list[str]:
    """A headless Cursor turn with streaming JSON; the prompt is appended as the last argument."""
    args = [binary, "--print", "--trust", "--force", "--approve-mcps", "--output-format", "stream-json",
            "--stream-partial-output", "--workspace", workspace]
    if model:
        args.extend(["--model", model])
    if session_id:
        args.extend(["--resume", session_id])
    return args


async def create_chat(binary: str, env: dict, workspace: str) -> str:
    """Create an empty Cursor chat so its id is known before the turn runs."""
    # `create-chat` runs no tools; Cursor prints the id but does not exit under a custom config dir.
    env = {key: value for key, value in env.items() if key != "CURSOR_CONFIG_DIR"}
    proc = await asyncio.create_subprocess_exec(binary, "create-chat", cwd=workspace, env=env,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        raw, error = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ValueError("Cursor did not create a chat within 20 seconds")
    session_id = raw.decode(errors="replace").strip()
    if proc.returncode != 0 or not re.fullmatch(r"[0-9a-fA-F-]{20,}", session_id):
        raise ValueError(error.decode(errors="replace").strip()[:300] or "Cursor could not create a chat")
    return session_id


def parse_cursor_models(stdout: str) -> list[dict[str, str]]:
    """Parse `agent models` output into model choices."""
    return [{"id": match.group(1), "label": match.group(2).strip()} for line in stdout.splitlines()
            if (match := re.fullmatch(r"([A-Za-z0-9._-]+)\s+-\s+(.+)", line.strip()))]


def cursor_result_text(stdout: str) -> str:
    """Extract the terminal result text from a Cursor stream-json transcript."""
    result = ""
    deltas = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            result = event["result"]
        elif (
            event.get("type") == "assistant"
            and "timestamp_ms" in event
            and "model_call_id" not in event
        ):
            message = event.get("message")
            raw_content = message.get("content", []) if isinstance(message, dict) else []
            content = raw_content if isinstance(raw_content, list) else []
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "text"
                    and isinstance(part.get("text"), str)
                ):
                    deltas.append(part["text"])
    streamed = "".join(deltas)
    # Cursor can emit a stale progress-only `result` while the assistant stream
    # contains the actual final task envelope. Prefer whichever source proves it
    # reached the required completion contract.
    if "<task-output>" in streamed:
        return streamed
    if "<task-output>" in result:
        return result
    return result or streamed


def parse_chat_line(line: str) -> dict | None:
    """Extract visible Cursor deltas and tool call boundaries."""
    line = line.strip()
    if not line:
        return None
    try:
        evt = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(evt, dict):
        return None
    if evt.get("type") == "tool_call" and evt.get("subtype") in ("started", "completed"):
        call = evt.get("tool_call")
        name = None
        if isinstance(call, dict):
            name = next((key.removesuffix("ToolCall") for key in call if key.endswith("ToolCall")), None)
        return {"kind": "tool" if evt["subtype"] == "started" else "tool_end", "name": name, "text": ""}
    if (
        evt.get("type") == "assistant"
        and "timestamp_ms" in evt
        and "model_call_id" not in evt
    ):
        message = evt.get("message")
        raw_content = message.get("content", []) if isinstance(message, dict) else []
        content = raw_content if isinstance(raw_content, list) else []
        text = "".join(
            part.get("text", "")
            for part in content if isinstance(part, dict)
            if part.get("type") == "text" and isinstance(part.get("text"), str)
        )
        return {"kind": "text", "text": text}
    return None
