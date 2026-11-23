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
    ai_backend.set_backend(ai_backend.CLAUDE)
    monkeypatch.setattr(claude_code, "CLAUDE_CONFIG_DIR", tmp_path / "claude-config")
    monkeypatch.setattr(claude_code, "CLAUDE_PROJECTS", tmp_path / "projects")
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.setattr(claude_code, "CURSOR_ENV_FILE", tmp_path / "missing.env")
    return tmp_path


def test_toggle_persists_and_rejects_unknown(pinned_backend):
    assert ai_backend.current() == ai_backend.CURSOR
    ai_backend.set_backend(ai_backend.CLAUDE)
    assert ai_backend.current() == ai_backend.CLAUDE
    assert json.loads(pinned_backend.read_text()) == {"backend": "claude"}
    with pytest.raises(ValueError):
        ai_backend.set_backend("copilot")


def test_backend_api_switches_engine(monkeypatch):
    async def noop():
        return None

    monkeypatch.setattr(appmod, "_start_chat_router", noop)
    bad = asyncio.run(appmod.api_set_ai_backend({"backend": "nope"}))
    assert bad.status_code == 400
    ok = asyncio.run(appmod.api_set_ai_backend({"backend": "claude"}))
    assert json.loads(ok.body)["backend"] == "claude"
    assert ai_backend.current() == ai_backend.CLAUDE


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


def test_profiles_keep_push_denied_except_for_git_push_task(claude):
    safe = json.loads(claude_code.claude_settings("safe").read_text())
    push = json.loads(claude_code.claude_settings("git-push").read_text())
    open_ = json.loads(claude_code.claude_settings("unrestricted").read_text())
    assert "Bash(git push:*)" in safe["permissions"]["deny"]
    assert "Bash(git push:*)" not in push["permissions"]["deny"]
    assert "Bash(git push origin main)" in push["permissions"]["allow"]
    assert open_["permissions"]["deny"] == []
    guard = safe["hooks"]["PreToolUse"][0]
    assert guard["matcher"] == "mcp__.*"
    assert "send" in guard["hooks"][0]["command"]


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


class Stdin:
    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        pass


@pytest.mark.parametrize("run_source", ["manual", "scheduled"])
@pytest.mark.parametrize("flags,profile,prompt_rule", [
    ({"allow_git_push": True}, "git-push", "Never push another repository"),
    ({"unrestricted": True}, "unrestricted", "standing approval only for external actions"),
    ({"unrestricted": True, "allow_git_push": True, "push_on_schedule": True},
     "unrestricted", "standing approval only for external actions"),
    ({}, "safe", "Never create or modify external content or state"),
])
def test_run_task_uses_claude_harness(claude, monkeypatch, flags, profile, prompt_rule, run_source):
    captured = {}
    body = '<task-output>{"summary":"ok","status":"success","details":{}}</task-output>'
    line = json.dumps({"type": "result", "subtype": "success", "result": body}).encode()

    class Stream:
        def __init__(self, chunks):
            self._chunks = list(chunks)

        async def read(self, _n):
            return self._chunks.pop(0) if self._chunks else b""

    class Proc:
        returncode = 0
        stdout = Stream([line])
        stderr = Stream([])
        stdin = Stdin()

        async def wait(self):
            return 0

    async def fake_create(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        captured["proc"] = Proc()
        return captured["proc"]

    monkeypatch.setattr(appmod.asyncio, "create_subprocess_exec", fake_create)
    status, output, error, session_id = asyncio.run(scheduler.run_task(
        task_config.TaskConfig(id="x", skill="skill", harness="claude", dir=str(claude), **flags),
        run_source=run_source, idle_timeout=1,
    ))
    assert (status, error) == ("success", "")
    assert captured["cmd"][0] == claude_code.CLAUDE_BIN
    assert "--session-id" in captured["cmd"] and session_id in captured["cmd"]
    settings = captured["cmd"][captured["cmd"].index("--settings") + 1]
    assert settings.endswith(f"settings-{profile}.json")
    prompt = captured["proc"].stdin.data.decode()
    assert prompt_rule in prompt and "'skill'" in prompt
    assert "<task-output>" in prompt
    if profile == "unrestricted":
        assert prompt.startswith("You are running as an unattended background task.")
        assert "Do not ask questions - make autonomous decisions." in prompt
        assert "explicitly directed by this worker's instructions" in prompt
        assert "blockers as Assistant board items" in prompt
        assert "Never create or modify external" not in prompt
        assert "git push origin main" not in prompt
    assert captured["env"]["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"


def test_claude_task_bash_cap_follows_the_run_ceiling(claude, monkeypatch):
    captured = {}

    async def fake_create(*cmd, **kwargs):
        captured["env"] = kwargs["env"]
        raise RuntimeError("stop")

    monkeypatch.setattr(appmod.asyncio, "create_subprocess_exec", fake_create)
    asyncio.run(scheduler.run_task(
        task_config.TaskConfig(id="x", skill="skill", harness="claude", dir=str(claude), max_timeout=2700),
        idle_timeout=1,
    ))
    # Long scripts (teams-archive) outlived Claude's default 10-minute foreground cap.
    assert captured["env"]["BASH_MAX_TIMEOUT_MS"] == str(2580 * 1000)


def test_chat_turn_streams_claude_deltas(claude, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_GENERAL_CHAT_MODEL", "opus")
    captured = {}
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "stream_event", "event": {"type": "content_block_delta",
         "delta": {"type": "thinking_delta", "thinking": "private thought"}}},
        {"type": "stream_event", "event": {"type": "content_block_start",
         "content_block": {"type": "tool_use", "name": "Read", "input": {"path": "private file"}}}},
        {"type": "tool_progress", "tool_name": "Read"},
        {"type": "tool_use_summary", "summary": "Read project notes."},
        {"type": "stream_event", "event": {"type": "message_start"}},
        {"type": "stream_event", "event": {"type": "content_block_delta",
                                           "delta": {"type": "text_delta", "text": "Checked."}}},
        {"type": "stream_event", "event": {"type": "message_start"}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {
            "type": "text_delta", "text": 'All clear.\n<<<STATE>>>{"thread_summary":"ok"}'}}},
    ]

    class Proc:
        returncode = 0

        def __init__(self):
            async def lines():
                for event in events:
                    yield (json.dumps(event) + "\n").encode()
            self.stdout = lines()
            self.stdin = Stdin()

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["proc"] = Proc()
        return captured["proc"]

    monkeypatch.setattr(cmod.asyncio, "create_subprocess_exec", fake_exec)
    router = cmod.ChatRouter(
        ai_backend.AIAgent(workspace=str(tmp_path)),
        cmod.SessionMap(tmp_path / "sessions.json"), str(tmp_path),
    )

    async def run():
        return [e async for e in router.run_turn("chat:0123456789ab", {"id": "chat:0123456789ab"}, "hi")]

    out = asyncio.run(run())
    text = "".join(e["text"] for e in out if e["kind"] == "text")
    assert [e["label"] for e in out if e["kind"] == "progress"] == [
        "Tool started · Read", "Tool running · Read", "Read project notes."]
    assert "private" not in json.dumps(out)
    assert "Read project notes." not in text
    assert text.startswith("Checked.\n\nAll clear.")
    assert captured["args"][0] == claude_code.CLAUDE_BIN
    assert "--include-partial-messages" in captured["args"]
    assert captured["args"][captured["args"].index("--model") + 1] == "opus"
    # The message rides stdin: endpoint security kills processes with some words in argv.
    assert "hi" not in captured["args"]
    assert b"Sam's message (empty = act on the opening move): hi." in captured["proc"].stdin.data


def test_failed_claude_task_reports_readable_error_not_stream_json(claude, monkeypatch):
    lines = [
        json.dumps({"type": "system", "subtype": "hook_started", "hook_id": "h"}).encode() + b"\n",
        json.dumps({"type": "assistant", "message": {
            "content": [{"type": "text", "text": "Teams session expired."}]}}).encode() + b"\n",
    ]

    class Stream:
        def __init__(self, chunks):
            self._chunks = list(chunks)

        async def read(self, _n):
            return self._chunks.pop(0) if self._chunks else b""

    class Proc:
        returncode = 1
        stdout = Stream(lines)
        stderr = Stream([])
        stdin = Stdin()

        async def wait(self):
            return 1

    async def fake_create(*_cmd, **_kwargs):
        return Proc()

    monkeypatch.setattr(appmod.asyncio, "create_subprocess_exec", fake_create)
    status, _, error, _ = asyncio.run(scheduler.run_task(
        task_config.TaskConfig(id="x", skill="skill", harness="claude", dir=str(claude)), idle_timeout=1,
    ))
    assert status == "error"
    assert error == "Teams session expired."


def test_expired_claude_signin_reports_login_instruction(claude, monkeypatch):
    lines = [
        json.dumps({"type": "system", "subtype": "hook_started", "hook_id": "h"}).encode() + b"\n",
        json.dumps({"type": "assistant", "message": {
            "content": [{"type": "text", "text": "Failed to authenticate: OAuth session expired and could not be refreshed"}]}}).encode() + b"\n",
    ]

    class Stream:
        def __init__(self, chunks):
            self._chunks = list(chunks)

        async def read(self, _n):
            return self._chunks.pop(0) if self._chunks else b""

    class Proc:
        returncode = 1
        stdout = Stream(lines)
        stderr = Stream([])
        stdin = Stdin()

        async def wait(self):
            return 1

    async def fake_create(*_cmd, **_kwargs):
        return Proc()

    monkeypatch.setattr(appmod.asyncio, "create_subprocess_exec", fake_create)
    status, _, error, _ = asyncio.run(scheduler.run_task(
        task_config.TaskConfig(id="x", skill="skill", harness="claude", dir=str(claude)), idle_timeout=1,
    ))
    assert status == "error"
    assert error == claude_code.CLAUDE_SIGNIN_MESSAGE


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
