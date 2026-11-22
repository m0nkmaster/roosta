"""Pi's RPC subprocess transport; Pi owns the agent loop and execution context."""
from __future__ import annotations

import json
import re
from pathlib import Path

from roosta import paths, skills


def pi_args(binary: str, connection: dict, model: str, directory: Path, session_id: str, workspace: str) -> list[str]:
    args = [binary, "--mode", "rpc", "--provider", connection["provider"],
            "--model", model, "--session-id", session_id,
            "--session-dir", str(directory / "sessions"), "--no-approve", "--no-extensions",
            "--extension", "builtin:mcp", "--extension", "builtin:tool-search", "--extension", str(paths.APP_ROOT / "pi_guard.mjs"),
            "--no-prompt-templates", "--no-themes", "--no-skills",
            "--tools", "read,bash,edit,write,tool_search,mcp__*",
            "--offline"]
    # Roosta supplies core and fork paths in the prompt. Native discovery adds custom skills only.
    seen = set(skills.names(paths.CORE_SKILLS_DIR)) | set(skills.names(skills.local(paths.WORKSPACE, skills.FORKS)))
    for root in (Path(workspace) / ".agents/skills", paths.WORKSPACE / ".agents/skills", Path.home() / ".agents/skills"):
        for name in skills.names(root):
            if name not in seen:
                args.extend(["--skill", str(root / name / "SKILL.md")])
                seen.add(name)
    return args


def events(stdout: str):
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict):
            yield event


def result_text(stdout: str) -> str:
    messages = []
    for event in events(stdout):
        message = event.get("message", {})
        if event.get("type") == "message_end" and message.get("role") == "assistant":
            messages.append("".join(p.get("text", "") for p in message.get("content", []) if p.get("type") == "text"))
    return "\n\n".join(messages)


def failure(stdout: str) -> str:
    for event in reversed(list(events(stdout))):
        message = event.get("message", {})
        if event.get("type") == "message_end" and message.get("role") == "assistant":
            if message.get("stopReason") in ("error", "aborted"):
                return message.get("errorMessage") or "The model request was interrupted"
            return ""
    return "Pi returned no completed assistant response"


def parse_line(line: str) -> dict | None:
    for event in events(line):
        kind = event.get("type")
        if kind == "message_start" and event.get("message", {}).get("role") == "assistant":
            return {"kind": "separator", "text": "\n\n"}
        if kind == "tool_execution_start":
            return {"kind": "tool", "text": "", "name": event.get("toolName")}
        if kind == "tool_execution_update":
            return {"kind": "tool_running", "name": event.get("toolName")}
        if kind == "tool_execution_end":
            return {"kind": "tool_end", "name": event.get("toolName")}
        update = event.get("assistantMessageEvent", {})
        if kind == "message_update" and update.get("type") == "text_delta":
            return {"kind": "text", "text": update["delta"]}
    return None


def read_transcript(directory: Path, session_id: str) -> list[dict]:
    if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
        return []
    transcript = next(directory.rglob(f"*{session_id}*.jsonl"), None)
    if transcript is None:
        return []
    turns = []
    for event in events(transcript.read_text()):
        message = event.get("message", {})
        if event.get("type") == "message" and message.get("role") in ("user", "assistant"):
            content = message.get("content", [])
            text = content if isinstance(content, str) else "".join(p.get("text", "") for p in content if p.get("type") == "text")
            if text:
                turns.append({"role": message["role"], "text": text})
    return turns
