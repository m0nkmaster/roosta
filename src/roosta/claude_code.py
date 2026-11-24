"""Claude Code headless CLI integration for dashboard tasks and conversations.

Mirrors `cursor_agent.py` so `ai_backend.py` can switch between the two. The
permission policy is translated from the tracked Cursor profiles, so both
engines enforce one set of rules.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import shlex
import sys
import uuid
from pathlib import Path

from roosta import paths
from roosta.cursor_agent import (
    CURSOR_ENV_FILE,
    SAFE_CONFIG_TEMPLATE,
    merged_permissions,
    _dotenv_value,
    agent_path,
)

DASHBOARD_ROOT = Path(__file__).resolve().parent
CLAUDE_BIN = str(Path.home() / ".local" / "bin" / "claude")
if not Path(CLAUDE_BIN).is_file():
    CLAUDE_BIN = shutil.which("claude") or CLAUDE_BIN
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
CLAUDE_CONFIG_DIR = paths.CACHE_DIR / "claude-config"
GUARD_SCRIPT = DASHBOARD_ROOT / "claude_guard.py"
CLAUDE_MODEL_ENV = "CLAUDE_MODEL"
CLAUDE_GENERAL_CHAT_MODEL_ENV = "CLAUDE_GENERAL_CHAT_MODEL"
# The one permitted model hardcode: unversioned aliases offered only when Claude Code cannot list its models.
CLAUDE_FALLBACK_ALIASES = ("fable", "opus", "sonnet", "haiku")
PROFILES = ("safe", "unrestricted")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Argv-safety format only: a model may carry a reasoning effort, `<model>@<effort>`, passed as
# `--effort`. Which models and efforts exist is decided by Claude Code's own list.
_CLAUDE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-\[\]]{0,99}(?:@[a-z]{1,16})?")
_CLAUDE_EFFORT_ONLY = re.compile(r"@[a-z]{1,16}")
# Tools a headless run may use without a prompt. `dontAsk` denies everything
# else, and deny rules always win over these.
BASE_ALLOW = [
    "Read", "Edit", "Write", "Glob", "Grep", "Bash", "Skill", "Task", "Agent",
    "TodoWrite", "NotebookEdit", "WebFetch", "WebSearch", "ToolSearch",
]
TRANSIENT_CLAUDE_FAILURES = (
    "overloaded_error",
    "api error: 529",
    "connection error",
    "getaddrinfo enotfound",
    "etimedout",
)


def is_claude_model(model: str | None) -> bool:
    return bool(model and _CLAUDE_MODEL.fullmatch(model))


def is_claude_effort_only(model: str | None) -> bool:
    return bool(model and _CLAUDE_EFFORT_ONLY.fullmatch(model))


def _configured_model(env_key: str, env_file: Path | None) -> str:
    value = str(
        os.environ.get(env_key, "") or _dotenv_value(Path(env_file or CURSOR_ENV_FILE), env_key)
    ).strip()
    return value if is_claude_model(value) else ""


def claude_model(requested: str | None = None, env_file: Path | None = None) -> str:
    """A requested Claude model, else CLAUDE_MODEL, else "" (Claude Code's own default)."""
    if is_claude_model(requested):
        return str(requested)
    return _configured_model(CLAUDE_MODEL_ENV, env_file)


def claude_general_chat_model(env_file: Path | None = None) -> str:
    return _configured_model(CLAUDE_GENERAL_CHAT_MODEL_ENV, env_file)


def _shell_rule(rule: str) -> str:
    """Cursor `Shell(git:push*)` -> Claude `Bash(git push:*)`."""
    command, _, args = rule.partition(":")
    words = f"{command} {args}".strip() if args else command
    if words.endswith("*"):
        return f"Bash({words.rstrip('*').rstrip()}:*)"
    return f"Bash({words})" if args else f"Bash({words}:*)"


def translate_permissions(cursor_permissions: dict) -> tuple[list[str], list[str], list[str]]:
    """Map a Cursor permission profile to Claude (allow, deny, mcp_block_keywords)."""
    allow: list[str] = []
    deny: list[str] = []
    keywords: list[str] = []
    for bucket, target in (("allow", allow), ("deny", deny)):
        for entry in cursor_permissions.get(bucket, []):
            match = re.fullmatch(r"(Read|Write|Shell|Mcp)\((.*)\)", entry)
            if not match:
                continue
            kind, body = match.groups()
            if kind == "Read":
                if body != "**":
                    target.append(f"Read({body})")
            elif kind == "Write":
                if body != "**":
                    target.extend([f"Edit({body})", f"Write({body})"])
            elif kind == "Shell":
                target.append(_shell_rule(body))
                if bucket == "deny" and not body.endswith("*") and ":" not in body:
                    target.append(f"Bash({body})")
            elif kind == "Mcp" and bucket == "deny":
                keyword = body.split(":", 1)[-1].strip("*")
                if keyword:
                    keywords.append(keyword)
    return allow, deny, keywords


def claude_settings(profile: str = "safe", config_dir: Path | None = None) -> Path:
    """Write the gitignored Claude settings file for one permission profile."""
    if profile not in PROFILES:
        raise ValueError(f"unknown Claude permission profile: {profile}")
    allow, deny, keywords = [], [], []
    if profile != "unrestricted":
        allow, deny, keywords = translate_permissions(
            merged_permissions(json.loads(Path(SAFE_CONFIG_TEMPLATE).read_text())["permissions"])
        )
    guard = shlex.join([sys.executable, "--claude-guard"] if getattr(sys, "frozen", False)
                       else [sys.executable, str(GUARD_SCRIPT)])
    if keywords:
        guard += " " + shlex.join(keywords)
    settings = {
        "permissions": {"allow": BASE_ALLOW + allow, "deny": deny},
        # MCP tool names are unbounded, so a hook approves read-shaped MCP calls
        # and blocks write-shaped ones instead of a static allow list.
        "hooks": {
            "PreToolUse": [
                {"matcher": "mcp__.*", "hooks": [{"type": "command", "command": guard}]}
            ]
        },
    }
    directory = Path(config_dir or CLAUDE_CONFIG_DIR)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"settings-{profile}.json"
    rendered = json.dumps(settings, indent=2)
    try:
        if path.read_text() == rendered:
            return path
    except OSError:
        pass
    temporary = directory / f"settings-{profile}.{os.getpid()}.tmp"
    temporary.write_text(rendered)
    temporary.chmod(0o600)
    temporary.replace(path)
    return path


# Claude provider settings a GUI-launched runner would otherwise miss; read from the
# workspace .env when the process environment lacks them.
CLAUDE_PROVIDER_KEYS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "AWS_PROFILE",
                        "AWS_REGION", "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION")


def claude_env(base: dict | None = None, env_file: Path | None = None) -> dict:
    """Child environment: local bins on PATH, blocking MCP startup, no nested-session markers."""
    env = dict(os.environ if base is None else base)
    for key in CLAUDE_PROVIDER_KEYS:
        if not env.get(key):
            value = _dotenv_value(Path(env_file or CURSOR_ENV_FILE), key)
            if value:
                env[key] = value
    env["PATH"] = agent_path(env.get("PATH"))
    for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
        env.pop(key, None)
    # Print mode otherwise starts the model before MCP servers connect, so the
    # first tool search finds the MCP servers still "connecting".
    env["MCP_CONNECTION_NONBLOCKING"] = "false"
    return env


def claude_available(binary: str = CLAUDE_BIN) -> bool:
    """Check the CLI exists. Auth is the user's own Claude login and is not probed."""
    return Path(binary).is_file() if Path(binary).is_absolute() else bool(shutil.which(binary))


def new_session_id() -> str:
    return str(uuid.uuid4())


def session_exists(session_id: str, projects: Path | None = None) -> bool:
    if not _UUID.fullmatch(session_id or ""):
        return False
    return any(Path(projects or CLAUDE_PROJECTS).glob(f"*/{session_id}.jsonl"))


def read_claude_transcript(session_id: str, projects: Path | None = None) -> list[dict]:
    """Ordered user/assistant text turns from a Claude Code session file.

    Tool calls, tool results, thinking and injected meta messages are dropped:
    the feed wants what was asked and what was said, not the working.
    """
    if not _UUID.fullmatch(session_id or ""):
        return []
    path = next(Path(projects or CLAUDE_PROJECTS).glob(f"*/{session_id}.jsonl"), None)
    if path is None:
        return []
    turns: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = event.get("type")
        if role not in ("user", "assistant") or event.get("isMeta") or event.get("isSidechain"):
            continue
        content = (event.get("message") or {}).get("content")
        text = content if isinstance(content, str) else _message_text(event)
        text = (text or "").strip()
        if text:
            turns.append({"role": role, "text": text})
    return turns


def claude_args(
    *,
    session_id: str | None = None,
    model: str | None = None,
    profile: str = "safe",
    partial: bool = False,
    binary: str = CLAUDE_BIN,
    projects: Path | None = None,
) -> list[str]:
    """Build a headless Claude Code invocation with stream-json output.

    The caller writes the prompt to stdin, never argv: endpoint security SIGKILLs
    any process whose command line holds certain words (e.g. "openclaw"), so a
    chat message quoting one would kill the turn before Claude starts.
    """
    args = [
        binary,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "dontAsk",
        "--settings",
        str(claude_settings(profile)),
    ]
    if is_claude_effort_only(model):
        name, effort = claude_model().partition("@")[0], model[1:]
    else:
        name, _, effort = claude_model(model).partition("@")
    if name:
        args.extend(["--model", name])
    if effort:
        args.extend(["--effort", effort])
    if partial:
        args.append("--include-partial-messages")
    if session_id:
        # A dashboard-minted id becomes a Claude session on its first turn.
        flag = "--resume" if session_exists(session_id, projects) else "--session-id"
        args.extend([flag, session_id])
    return args


def is_transient_claude_failure(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in TRANSIENT_CLAUDE_FAILURES)


CLAUDE_AUTH_FAILURES = (
    "failed to authenticate",
    "oauth session expired",
    "oauth token has expired",
    "please run /login",
)
CLAUDE_SIGNIN_MESSAGE = "Claude sign-in expired - run `claude /login` in a terminal, then Run now"


def is_claude_auth_failure(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in CLAUDE_AUTH_FAILURES)


def claude_stream_has_progress(stdout: str) -> bool:
    """True once the stream holds anything beyond the init event."""
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return True
        if event.get("type") == "system" and event.get("subtype") == "init":
            continue
        return True
    return False


def _message_text(event: dict) -> str:
    message = event.get("message")
    content = message.get("content", []) if isinstance(message, dict) else []
    if not isinstance(content, list):
        return ""
    return "".join(
        part["text"]
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    )


def claude_result_text(stdout: str) -> str:
    """Extract the final text from a Claude stream-json transcript."""
    result = ""
    messages: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            result = event["result"]
        elif event.get("type") == "assistant":
            text = _message_text(event)
            if text:
                messages.append(text)
    streamed = "\n\n".join(messages)
    if "<task-output>" in result:
        return result
    if "<task-output>" in streamed:
        return streamed
    return result or streamed


def parse_claude_chat_line(line: str) -> dict | None:
    """Extract visible text, message boundaries and public tool activity."""
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    if event.get("type") == "tool_progress":
        return {"kind": "tool_running", "name": event.get("tool_name")}
    if event.get("type") == "tool_use_summary" and isinstance(event.get("summary"), str):
        return {"kind": "progress", "label": " ".join(event["summary"].split())[:160]}
    if event.get("type") != "stream_event":
        return None
    inner = event.get("event") or {}
    if inner.get("type") == "message_start":
        return {"kind": "separator", "text": "\n\n"}
    block = inner.get("content_block") or {}
    if inner.get("type") == "content_block_start" and block.get("type") == "tool_use":
        return {"kind": "tool", "text": "", "name": block.get("name")}
    delta = inner.get("delta") or {}
    if (
        inner.get("type") == "content_block_delta"
        and delta.get("type") == "text_delta"
        and isinstance(delta.get("text"), str)
    ):
        return {"kind": "text", "text": delta["text"]}
    return None
