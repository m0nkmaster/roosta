import asyncio
import json
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient
import pytest

from roosta import app, updates
from roosta.updates import read_json


@pytest.fixture(autouse=True)
def running_version(monkeypatch):
    monkeypatch.setattr(updates, "__version__", "1.9.0")


def release(tag="v1.10.0", **fields):
    return {"tag_name": tag, "draft": False, "prerelease": False, **fields}


def package():
    return {"info": {"name": "roosta", "version": "1.10.0", "requires_python": ">=3.11"},
            "urls": [{"filename": "roosta-1.10.0-py3-none-any.whl", "yanked": False,
                      "requires_python": ">=3.11"}]}


@pytest.mark.parametrize("running,latest,state", [
    ("1.9.1", "v1.10.0", "available"), ("1.10.0", "v1.10.0", "current"),
    ("2.0.0.dev1", "v1.10.0", "current"), ("1.9.1", "v1.10.0rc1", "failed"),
    ("1.9.1", "v99.0.0/../../run", "failed"),
])
def test_stable_versions(monkeypatch, running, latest, state):
    monkeypatch.setattr(updates, "__version__", running)
    read = AsyncMock(return_value=release(latest))
    monkeypatch.setattr(updates, "read_json", read)
    monkeypatch.setattr(updates, "installation", lambda: "source")
    result = asyncio.run(updates.ReleaseChecks().refresh())
    assert result["state"] == state
    read.assert_awaited_once_with(updates.LATEST)
    if state == "available":
        assert "checkout" in result["guidance"] and "command" not in result


@pytest.mark.parametrize("bad", [release(draft=True), release(prerelease=True), {}, [], TimeoutError()])
def test_release_failure_then_retry(monkeypatch, bad):
    monkeypatch.setattr(updates, "read_json", AsyncMock(side_effect=[bad, release("v0.0.1")]))
    async def run():
        checks = updates.ReleaseChecks()
        assert (await checks.refresh())["state"] == "failed"
        assert (await checks.refresh())["state"] == "current"
    asyncio.run(run())


@pytest.mark.parametrize("change", ["missing", "wrong_version", "incompatible", "file_python",
                                    "yanked", "no_wheel", "invalid", "timeout"])
def test_unconfirmed_python_release_never_offers_command(monkeypatch, change):
    data = package()
    if change == "missing":
        data = {}
    elif change == "wrong_version":
        data["info"]["version"] = "1.9.0"
    elif change == "incompatible":
        data["info"]["requires_python"] = ">=42"
    elif change == "file_python":
        data["urls"][0]["requires_python"] = "<3"
    elif change == "yanked":
        data["urls"][0]["yanked"] = True
    elif change == "no_wheel":
        data["urls"] = []
    elif change == "invalid":
        data["info"]["requires_python"] = "bad"
    else:
        data = TimeoutError()
    monkeypatch.setattr(updates, "read_json", AsyncMock(side_effect=[release(), data]))
    monkeypatch.setattr(updates, "installation", lambda: "uv")
    result = asyncio.run(updates.check())
    assert result["state"] == "available" and "PyPI" in result["error"]
    assert "command" not in result


@pytest.mark.parametrize("kind,marker,contents", [
    ("venv", "", ""), ("uv", "uv-receipt.toml", '[[tool.requirements]]\nname="roosta"'),
    ("pipx", "pipx_metadata.json", '{"main_package":{"package":"roosta"}}'),
    ("unknown", "uv-receipt.toml", "bad"), ("unknown", "pipx_metadata.json", "{}"),
])
def test_running_installation_owns_guidance(monkeypatch, tmp_path, kind, marker, contents):
    root = tmp_path / "site-packages" / "roosta"
    monkeypatch.setattr(updates.paths, "APP_ROOT", root)
    dist = Mock()
    dist.read_text.return_value = None
    dist.locate_file.return_value = root
    monkeypatch.setattr(updates.metadata, "distribution", lambda name: dist)
    monkeypatch.setattr(updates.sys, "prefix", str(tmp_path))
    monkeypatch.setenv("ASSISTANT_DESKTOP", "1")  # The shell may attach to this runner.
    monkeypatch.setattr(updates.util, "find_spec", lambda name: True)
    if marker:
        (tmp_path / marker).write_text(contents)
    assert updates.installation() == kind
    read = AsyncMock(side_effect=[release(), package()])
    monkeypatch.setattr(updates, "read_json", read)
    result = asyncio.run(updates.check())
    assert read.await_args.args == ("https://pypi.org/pypi/roosta/1.10.0/json",)
    assert result.get("command") == (None if kind == "unknown" else "roosta update")
    assert "Restart Roosta" in result["restart"] and "installer" not in result
    dist.read_text.return_value = json.dumps({"dir_info": {"editable": True}})
    assert updates.installation() == "source"


@pytest.mark.parametrize("machine,arch", [("arm64", "arm64"), ("x86_64", "x64"), ("other", None)])
def test_bundle_download_uses_fixed_release_url(monkeypatch, machine, arch):
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    monkeypatch.setattr(updates.platform, "machine", lambda: machine)
    name = f"Roosta-1.10.0-{arch}.dmg"
    read = AsyncMock(return_value=release(assets=[{"name": name, "browser_download_url": "https://invalid"}]))
    monkeypatch.setattr(updates, "read_json", read)
    result = asyncio.run(updates.check())
    if arch:
        assert result["installer"] == f"{updates.RELEASES}/download/v1.10.0/{name}"
    else:
        assert "installer" not in result and result["error"]
    read.assert_awaited_once()


def test_background_and_manual_checks_share_request_and_stop(monkeypatch):
    async def run():
        entered, finish, repeated = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def check():
            if entered.is_set():
                repeated.set()
            entered.set()
            await finish.wait()
            return {"state": "current"}
        mock = AsyncMock(side_effect=check)
        monkeypatch.setattr(updates, "check", mock)
        monkeypatch.setattr(updates, "INTERVAL", 0.01)
        checks = updates.ReleaseChecks()
        loop = asyncio.create_task(checks.run())
        await asyncio.wait_for(entered.wait(), 1)
        manual = asyncio.create_task(checks.refresh())
        await asyncio.sleep(0)
        finish.set()
        assert await manual == {"state": "current"}
        mock.assert_awaited_once()
        await asyncio.wait_for(repeated.wait(), 1)
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop
    asyncio.run(run())


def test_notice_is_public_but_settings_are_local(monkeypatch):
    checks = updates.ReleaseChecks()
    checks.result = {"latest": "1.10.0", "notes": "notes", "guidance": "private path"}
    monkeypatch.setattr(app.app.state, "release_checks", checks, raising=False)
    for method in ("get", "post"):
        remote = TestClient(app.app, base_url="http://localhost", client=("192.0.2.1", 123))
        assert getattr(remote, method)("/api/settings/updates").status_code == 403
        local = TestClient(app.app, base_url="http://localhost", client=("127.0.0.1", 123))
        assert getattr(local, method)("/api/settings/updates", headers={"Origin": "https://invalid"}).status_code == 403
    assert remote.get("/api/updates").json() == {"latest": "1.10.0", "notes": "notes"}
    assert local.get("/api/settings/updates").json()["version"] == app.__version__
    assert local.post("/api/settings/updates").json()["state"] == "failed"


@pytest.mark.parametrize("status,body,valid", [
    (200, b'{"value": 1}', True), (200, b'[]', False), (200, b'{', False),
    (302, b'', False), (403, b'{}', False), (200, b' ' * (512 * 1024) + b'{}', False),
])
def test_bounded_public_metadata_transport(monkeypatch, status, body, valid):
    import httpx

    async def respond(request):
        assert request.url == updates.LATEST and "Authorization" not in request.headers
        return httpx.Response(status, stream=httpx.ByteStream(body))

    # Call the real reader with a transport that cannot open a socket.
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    if valid:
        assert asyncio.run(read_json(updates.LATEST)) == {"value": 1}
    else:
        with pytest.raises((httpx.HTTPStatusError, ValueError)):
            asyncio.run(read_json(updates.LATEST))


def test_dashboard_release_controls():
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node") or pytest.skip("node not available")
    subprocess.run([node, "--test", Path(__file__).with_name("update-ui.cjs")], check=True)
