import asyncio
import json
from pathlib import Path

import pytest

from roosta import scheduler
from roosta import task_config
from roosta import ai_backend
from roosta import app as appmod
from roosta import chat as cmod
from roosta import claude_code
from roosta import claude_guard


@pytest.fixture
def claude(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_code, "CLAUDE_CONFIG_DIR", tmp_path / "claude-config")
    monkeypatch.setattr(claude_code, "CLAUDE_PROJECTS", tmp_path / "projects")
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.setattr(claude_code, "CURSOR_ENV_FILE", tmp_path / "missing.env")
    return tmp_path


def test_translate_permissions_maps_cursor_profile():
    allow, deny, keywords = claude_code.translate_permissions({
        "allow": ["Read(**)", "Write(**)", "Shell(git:push origin main)"],
        "deny": ["Read(**/.env*)", "Write(**/*.pem)", "Shell(rm)", "Shell(git:push*)",
                 "Shell(jira:--agent issue create*)", "Mcp(*:*send*)"],
    })
    assert allow == ["Bash(git push origin main)"]
    assert "Read(**/.env*)" in deny
    assert {"Edit(**/*.pem)", "Write(**/*.pem)"} <= set(deny)
    assert {"Bash(rm:*)", "Bash(rm)", "Bash(git push:*)",
            "Bash(jira --agent issue create:*)"} <= set(deny)
    assert keywords == ["send"]


def test_profiles_keep_push_denied_unless_unrestricted(claude):
    safe = json.loads(claude_code.claude_settings("safe").read_text())
    open_ = json.loads(claude_code.claude_settings("unrestricted").read_text())
    assert "Bash(git push:*)" in safe["permissions"]["deny"]
    assert open_["permissions"]["deny"] == []
    guard = safe["hooks"]["PreToolUse"][0]
    assert guard["matcher"] == "mcp__.*"
    assert "send" in guard["hooks"][0]["command"]
    assert not {"Bash(rm:*)", "Bash(git reset:*)", "Bash(git clean:*)"} & set(safe["permissions"]["deny"])
    assert "Bash(curl:*)" in safe["permissions"]["deny"]
    with pytest.raises(ValueError):
        claude_code.claude_settings("git-push")


def test_guard_blocks_write_shaped_mcp_tools_case_insensitively():
    keywords = ["create", "send", "comment"]
    decision = lambda name: claude_guard.decide(name, keywords)["hookSpecificOutput"][
        "permissionDecision"]
    assert decision("mcp__teams__teams_send_message") == "deny"
    assert decision("mcp__atlassian__addCommentToJiraIssue") == "deny"
    assert decision("mcp__tracker__getExperiment") == "allow"


def test_claude_args_mint_then_resume_session(claude, monkeypatch):
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    sid = "11111111-1111-4111-8111-111111111111"
    first = claude_code.claude_args(session_id=sid, model="bad model;")
    assert first[first.index("--session-id") + 1] == sid
    assert "--model" not in first and "--effort" not in first  # unsafe ids are dropped; no hardcoded default
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5-5@medium")
    configured = claude_code.claude_args(session_id=sid, model="bad model;")
    assert configured[configured.index("--model") + 1] == "claude-opus-5-5"
    assert configured[configured.index("--effort") + 1] == "medium"
    monkeypatch.delenv("CLAUDE_MODEL")
    assert "--model" not in claude_code.claude_args(model="")
    assert "--model" not in claude_code.claude_args(model="@high")
    assert claude_code.claude_args(model="@high")[claude_code.claude_args(model="@high").index("--effort") + 1] == "high"
    explicit = claude_code.claude_args(model="sonnet@high")
    assert explicit[explicit.index("--model") + 1] == "sonnet" and explicit[explicit.index("--effort") + 1] == "high"
    assert first[first.index("--permission-mode") + 1] == "dontAsk"
    assert first[-1] == sid  # prompt goes on stdin, never argv
    (claude / "projects" / "-vault").mkdir(parents=True)
    (claude / "projects" / "-vault" / f"{sid}.jsonl").write_text("{}\n")
    again = claude_code.claude_args(session_id=sid, model="opus")
    assert again[again.index("--resume") + 1] == sid
    assert again[again.index("--model") + 1] == "opus"


def test_claude_env_drops_nested_session_markers():
    env = claude_code.claude_env({"PATH": "/usr/bin", "CLAUDECODE": "1"})
    assert "CLAUDECODE" not in env
    assert env["MCP_CONNECTION_NONBLOCKING"] == "false"
    assert str(Path.home() / ".local" / "bin") in env["PATH"]


def test_claude_result_text_prefers_envelope():
    body = '<task-output>{"summary":"ok","status":"success","details":{}}</task-output>'
    stdout = "\n".join(json.dumps(e) for e in [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": body}]}},
        {"type": "result", "subtype": "success", "result": "stale"},
    ])
    assert claude_code.claude_result_text(stdout) == body
    assert not claude_code.claude_stream_has_progress(stdout.splitlines()[0])
    assert claude_code.claude_stream_has_progress(stdout)


def test_parse_claude_chat_line_reads_text_deltas():
    delta = {"type": "stream_event", "event": {
        "type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}}
    assert claude_code.parse_claude_chat_line(json.dumps(delta)) == {"kind": "text", "text": "hi"}
    start = {"type": "stream_event", "event": {"type": "message_start"}}
    assert claude_code.parse_claude_chat_line(json.dumps(start))["kind"] == "separator"
    assert claude_code.parse_claude_chat_line('{"type":"assistant"}') is None
    tool = {"type": "stream_event", "event": {"type": "content_block_start",
                                              "content_block": {"type": "tool_use"}}}
    assert claude_code.parse_claude_chat_line(json.dumps(tool))["kind"] == "tool"


@pytest.mark.parametrize("unrestricted,rule", [
    (False, "Never create or modify external content or state"),
    (True, "nothing is off limits"),
])
def test_task_prompt_matches_the_permission_profile(unrestricted, rule):
    prompt = scheduler.task_prompt(task_config.TaskConfig(id="x", skill="skill", unrestricted=unrestricted))
    assert prompt.startswith("You are running as an unattended background task.")
    assert rule in prompt and "'skill'" in prompt and "<task-output>" in prompt
    if unrestricted:
        assert "any local or external action" in prompt and "Keep credentials" in prompt
        assert "Never create or modify external" not in prompt


def test_claude_task_bash_cap_follows_the_run_ceiling(monkeypatch, tmp_path):
    captured = {}

    class Run:
        backend, session_id, env = ai_backend.CLAUDE, "s", {}

        def text(self, output):
            return output

    async def stream(run, _prompt, **_kwargs):
        captured["env"] = dict(run.env)
        yield '<task-output>{"summary":"ok","status":"success"}</task-output>'

    monkeypatch.setattr(scheduler.ai_backend, "prepare", lambda *_a, **_k: Run())
    monkeypatch.setattr(scheduler.ai_backend, "stream", stream)
    monkeypatch.setattr(scheduler.ai_connections, "get", lambda *_a, **_k: {"id": "c" * 32, "provider": "anthropic"})
    asyncio.run(scheduler.run_task(task_config.TaskConfig(id="x", skill="skill", dir=str(tmp_path), max_timeout=2700),
                                   idle_timeout=1))
    # Long scripts (teams-archive) outlived Claude's default 10-minute foreground cap.
    assert captured["env"]["BASH_MAX_TIMEOUT_MS"] == str(2580 * 1000)


def test_claude_model_effort_suffix_becomes_the_effort_flag():
    assert claude_code.is_claude_model("claude-opus-5-5@medium")
    assert claude_code.is_claude_model("claude-brand-new-7@xlow")  # format only; Claude Code's list decides membership
    for unsafe in ("bad model", "-x", "opus;rm", "opus@HIGH", "a@b@c", "", "opus@"):
        assert not claude_code.is_claude_model(unsafe)
    assert claude_code.is_claude_effort_only("@high") and not claude_code.is_claude_effort_only("high")
    args = claude_code.claude_args(model="sonnet@high")
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--effort") + 1] == "high"
    assert "--effort" not in claude_code.claude_args(model="haiku")


def test_claude_env_reads_provider_settings_from_workspace_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("AWS_PROFILE=bedrock\nSECRET=never\nAWS_REGION='eu-west-2'\n")
    env = claude_code.claude_env({"PATH": "/bin", "AWS_REGION": "us-east-1"}, env_file)
    assert env["AWS_PROFILE"] == "bedrock"
    assert env["AWS_REGION"] == "us-east-1"   # the process environment wins
    assert "SECRET" not in env


def test_frozen_hook_quotes_app_path_and_uses_bundled_guard(claude, monkeypatch):
    import shlex
    monkeypatch.setattr(claude_code.sys, "frozen", True, raising=False)
    executable = "/Applications/Roosta Test.app/Contents/Resources/roosta-backend/roosta-backend"
    monkeypatch.setattr(claude_code.sys, "executable", executable)
    settings = json.loads(claude_code.claude_settings("safe").read_text())
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    args = shlex.split(command)
    assert args[:2] == [executable, "--claude-guard"]
    assert "send" in args[2:]
