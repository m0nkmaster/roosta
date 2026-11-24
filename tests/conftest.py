import os
import tempfile

import pytest

# Paths are fixed at import, so point Roosta at a throwaway workspace before anything loads it.
# Otherwise the runner's seeded configs (which mirror the user's MCP config) land in the repo.
os.environ["ROOSTA_WORKSPACE"] = tempfile.mkdtemp(prefix="roosta-tests-")

@pytest.fixture(autouse=True)
def isolated_activity_log(tmp_path, monkeypatch):
    """Test runs must not append fake runs to the live activity feed."""
    from roosta import activity_log

    path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(activity_log, "ACTIVITY_FILE", path)
    return path


@pytest.fixture(autouse=True)
def test_profile(monkeypatch):
    """Prompts read the user's profile; tests use a fixed one, never the real PROFILE.md."""
    from roosta import profile

    me = profile.Profile(name="Sam Example", language="British English")
    monkeypatch.setattr(profile, "load", lambda path=None: me)
    return me


@pytest.fixture(autouse=True)
def offline_release_checks(monkeypatch):
    from roosta import updates

    async def offline(url):
        raise OSError("Offline test")

    monkeypatch.setattr(updates, "read_json", offline)


@pytest.fixture
def fake_chat_connection(monkeypatch):
    """A default Cursor connection whose runs go through whatever fake process the test installs.

    Returns the prepared runs, so tests can check the profile, arguments and environment.
    """
    import asyncio
    from roosta import ai_backend, ai_connections, cursor_agent

    connection = {"id": "c" * 32, "label": "Cursor", "provider": "cursor", "auth": "api_key", "connected": True}
    monkeypatch.setattr(ai_connections, "load", lambda: {"default": connection["id"], "connections": [connection]})
    runs = []

    def prepare(connection_id, workspace, *, model="", session_id="", profile="safe", **_kwargs):
        args = cursor_agent.cursor_args(workspace=workspace, session_id=session_id, model=model, binary="agent")
        run = ai_backend.ConnectionRun(connection, ai_backend.CURSOR, args, {"PATH": "/bin"}, workspace,
                                       session_id or "ses_fake", model=model)
        runs.append({"profile": profile, "run": run})
        return run

    async def stream(run, prompt, **_kwargs):
        run.prompt = prompt
        proc = await asyncio.create_subprocess_exec(*run.args, prompt, cwd=run.workspace, env=run.env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        if getattr(proc, "stdout", None) is not None:
            async for raw in proc.stdout:
                yield raw.decode(errors="replace")
        else:
            output, _ = await proc.communicate()
            yield (output or b"").decode(errors="replace")
        if await proc.wait() if hasattr(proc, "wait") else proc.returncode:
            raise ValueError("AI request failed; check the connection in Settings.")

    created = []

    async def new_session(_connection_id, _workspace):
        created.append(1)
        return f"ses_{len(created)}"

    monkeypatch.setattr(ai_backend, "prepare", prepare)
    monkeypatch.setattr(ai_backend, "stream", stream)
    monkeypatch.setattr(ai_backend, "new_session", new_session)
    return runs
