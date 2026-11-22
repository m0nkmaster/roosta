import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from urllib.parse import unquote, urlsplit

import pytest

from roosta import cli, cli_update, doctor, paths, skills, updates


@pytest.fixture
def upgrade(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_update, "__version__", "1.2.0")
    monkeypatch.setattr(cli_update.metadata, "version", lambda _: "1.2.0")
    dist = Mock()
    dist.read_text.return_value = "pip\n"
    monkeypatch.setattr(cli_update.metadata, "distribution", lambda _: dist)
    monkeypatch.setattr(updates, "stable_release", AsyncMock(return_value=("1.3.0", {})))
    monkeypatch.setattr(updates, "python_release", AsyncMock(return_value=True))
    monkeypatch.setattr(updates, "installation", lambda: "venv")
    monkeypatch.setattr(cli_update.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(cli_update.sys, "executable", str(tmp_path / "bin/python"))
    (tmp_path / "pyvenv.cfg").touch()
    monkeypatch.setattr(subprocess, "run", Mock())
    monkeypatch.setattr(subprocess, "check_output", Mock(return_value="1.3.0\n"))
    return tmp_path


@pytest.mark.parametrize("kind", ["uv", "pipx", "venv", "uv-venv"])
def test_update_targets_current_install(upgrade, kind, monkeypatch, capsys):
    home = upgrade / "custom tools"
    prefix = home / "venvs/roosta" if kind == "pipx" else home / "roosta"
    prefix.mkdir(parents=True)
    (prefix / "pyvenv.cfg").touch()
    bins = upgrade / "custom bin"
    if kind == "pipx":
        (prefix / "bin").mkdir()
        (prefix / "bin/roosta").touch()
        bins.mkdir()
        (bins / "roosta").symlink_to(prefix / "bin/roosta")
        monkeypatch.setattr(cli_update.sys, "argv", [str(bins / "roosta")])
        monkeypatch.setenv("PIPX_BIN_DIR", "/other/bin")
    if kind == "uv":
        (prefix / "uv-receipt.toml").write_text(f'[[tool.entrypoints]]\ninstall-path = "{bins}/roosta"')
    if kind == "uv-venv":
        cli_update.metadata.distribution("roosta").read_text.return_value = "uv"
    monkeypatch.setattr(cli_update.shutil, "which", lambda name: "/tools/" + name)
    monkeypatch.setenv("UV_TOOL_DIR", "/other")
    monkeypatch.setenv("PIPX_HOME", "/other")
    monkeypatch.setattr(cli_update.sys, "prefix", str(prefix))
    python = str(prefix / "bin/python")
    monkeypatch.setattr(cli_update.sys, "executable", python)
    monkeypatch.setattr(updates, "installation", lambda: kind)

    def install(argv, *, env, cwd, **kwargs):
        manager = {"venv": "pip", "uv-venv": "uv"}.get(kind, kind)
        assert f"Installing Roosta 1.3.0 using {manager}..." in capsys.readouterr().out
        assert kwargs["timeout"] and kwargs["check"] and Path(cwd).is_dir()
        if kind == "uv":
            assert argv == ["/tools/uv", "tool", "upgrade", "roosta==1.3.0"]
            assert env["UV_TOOL_DIR"] == str(home) and env["UV_TOOL_BIN_DIR"] == str(bins)
        elif kind == "pipx":
            assert argv == ["/tools/pipx", "upgrade", "roosta"] and env["PIPX_HOME"] == str(home)
            assert env["PIPX_BIN_DIR"] == str(bins)
            assert Path(unquote(urlsplit(env["PIP_CONSTRAINT"]).path)).read_text() == "roosta==1.3.0\n"
        elif kind == "venv":
            assert argv == [python, "-I", "-m", "pip", "--isolated", "install", "--upgrade", "roosta==1.3.0"]
        else:
            assert argv == ["/tools/uv", "pip", "install", "--python", python, "--upgrade", "roosta==1.3.0"]

    subprocess.run.side_effect = install
    assert cli.main(["update", "--check"]) == 0
    subprocess.run.assert_not_called()
    assert cli.main(["update"]) == 0
    assert subprocess.check_output.call_args.args[0][:2] == [python, "-I"]
    assert "Verified installed version: 1.3.0" in capsys.readouterr().out


@pytest.mark.parametrize("version", ["1.2.0", "1.1.0"])
def test_no_downgrade_or_reinstall(upgrade, monkeypatch, version):
    monkeypatch.setattr(updates, "stable_release", AsyncMock(return_value=(version, {})))
    assert cli.main(["update"]) == 0
    updates.python_release.assert_not_awaited()
    subprocess.run.assert_not_called()


@pytest.mark.parametrize("problem", ["source", "mac", "unknown", "uv", "no-wheel", "invalid", "timeout",
                                     "metadata", "verification", "installer", "install-timeout", "missing-manager"])
def test_failed_update(upgrade, monkeypatch, capsys, problem):
    if problem in ("source", "mac", "unknown", "uv"):
        monkeypatch.setattr(updates, "installation", lambda: problem)
    elif problem == "no-wheel":
        updates.python_release.return_value = False
    elif problem in ("invalid", "timeout"):
        updates.stable_release.side_effect = KeyError("SECRET") if problem == "invalid" else TimeoutError()
    elif problem == "metadata":
        monkeypatch.setattr(cli_update.metadata, "version", lambda _: "0.1")
    elif problem == "verification":
        subprocess.check_output.return_value = "1.2.0"
    elif problem == "missing-manager":
        prefix = upgrade / "venvs/roosta"
        prefix.mkdir(parents=True)
        (prefix / "pyvenv.cfg").touch()
        monkeypatch.setattr(updates, "installation", lambda: "pipx")
        monkeypatch.setattr(cli_update.sys, "prefix", str(prefix))
        monkeypatch.setattr(cli_update.shutil, "which", lambda _: None)
    else:
        subprocess.run.side_effect = (subprocess.CalledProcessError(2, "SECRET") if problem == "installer"
                                      else subprocess.TimeoutExpired("SECRET", 1))
    assert cli.main(["update"]) == 1
    if problem not in ("verification", "installer", "install-timeout"):
        subprocess.run.assert_not_called()
    output = capsys.readouterr().out
    assert "SECRET" not in output
    if problem == "verification":
        assert "Verified installed version: 1.2.0" in output


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    ws = root / ".roosta"
    ws.mkdir(parents=True)
    (ws / "tasks.yaml").write_text("tasks: []")
    (ws / "connectors.yaml").write_text("connectors: []")
    for name in ("AGENTS.md", "PROFILE.md"):
        (root / name).touch()
    (root / ".agents/skills").mkdir(parents=True)
    monkeypatch.setattr(cli, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cli, "service_status", Mock(return_value={"installed": False}))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ROOSTA_WORKSPACE", str(root))
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("unexpected command")))
    monkeypatch.setattr(updates, "read_json", AsyncMock(side_effect=AssertionError("unexpected request")))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/bin/git" if name == "git" else None)
    return root


def snapshot(root):
    return {p.relative_to(root): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in root.rglob("*")}


def test_doctor_offline_read_only(workspace, capsys):
    before = snapshot(workspace)
    assert cli.main(["doctor", "--json", "--offline"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    report = json.loads(output.out)
    by_name = {row["name"]: row for row in report["checks"]}
    assert "ROOSTA_WORKSPACE" in by_name["Workspace selection"]["detail"]
    assert by_name["git"]["status"] == "PASS"
    assert by_name["pi"]["status"] == by_name["Local endpoint"]["status"] == by_name["Latest stable"]["status"] == "SKIP"
    assert snapshot(workspace) == before
    updates.read_json.assert_not_awaited()


def test_doctor_saved_then_cwd(workspace, monkeypatch, capsys):
    monkeypatch.delenv("ROOSTA_WORKSPACE")
    monkeypatch.chdir(workspace.parent)
    cli.CONFIG_FILE.write_text(json.dumps({"workspace": str(workspace)}))
    assert cli.main(["doctor", "--offline"]) == 0
    assert "from saved config" in capsys.readouterr().out
    cli.CONFIG_FILE.write_text('{"SECRET":')
    assert cli.main(["doctor", "--offline"]) == 0
    text = capsys.readouterr().out
    assert "current directory" in text and "Repair workspace" in text and "Summary" in text and "SECRET" not in text
    assert cli.main(["doctor", "--offline", "--workspace", str(workspace / "missing")]) == 1
    assert "from --workspace" in capsys.readouterr().out


def test_malformed_worker_connectors_accounts(workspace, capsys):
    cfg = workspace / ".roosta"
    (cfg / "tasks.yaml").write_text("tasks:\n- {id: SECRET, skill: absent}\n- {id: SECRET, skill: setup, dir: absent}")
    (cfg / "connectors.yaml").write_text("connectors:\n- {id: bad_SECRET, check: run-SECRET}")
    (cfg / "state").mkdir()
    (cfg / "state/ai-connections.json").write_text('{"connections":[{"id":"SECRET"}]}')
    assert cli.main(["doctor", "--offline", "--json"]) == 1
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err
    assert all(x in out.out for x in ("unique", "working directory", "referenced skill", "Connector 1", "Repair ai-connections"))
    (cfg / "tasks.yaml").write_text("tasks: [SECRET")
    (cfg / "connectors.yaml").write_text("connectors: SECRET")
    assert cli.main(["doctor", "--offline"]) == 1
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err and "Repair tasks.yaml" in out.out


def test_doctor_account_and_lock_drift(workspace, capsys):
    cfg = workspace / ".roosta"
    skills.sync(paths.CORE_SKILLS_DIR, workspace)
    (workspace / ".agents/skills/setup/SKILL.md").write_text("local edit")
    state = cfg / "state"
    state.mkdir()
    state.joinpath("ai-connections.json").write_text(json.dumps({
        "default": "a"*32, "connections": [
            {"id": "a"*32, "connected": False, "provider": "anthropic", "auth": "system"},
            {"id": "b"*32, "connected": True, "provider": "openai", "auth": "api_key", "credential_ref": "SECRET"}]}))
    assert cli.main(["doctor", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "1 disconnected" in out and "WARN  pi " in out and "WARN  Core skills" in out and "SECRET" not in out


def test_doctor_refuses_linked_config(workspace, capsys):
    tasks = workspace / ".roosta/tasks.yaml"
    tasks.unlink()
    tasks.symlink_to(workspace.parent / "auth.json")
    assert cli.main(["doctor", "--offline"]) == 1
    assert "Repair tasks.yaml" in capsys.readouterr().out


def test_doctor_missing_git_and_online_loopback(workspace, monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    release = {"tag_name": "v1.3.0", "draft": False, "prerelease": False}
    monkeypatch.setattr(updates, "read_json", AsyncMock(side_effect=[release, {"version": "0.12.0", "workspace": str(workspace)}]))
    assert cli.main(["doctor", "--json"]) == 1
    checks = {r["name"]: r for r in json.loads(capsys.readouterr().out)["checks"]}
    assert checks["git"]["status"] == "FAIL" and "0.12.0" in checks["Local endpoint"]["detail"]
    assert checks["Runner workspace"]["status"] == "PASS"
    assert [c.args[0] for c in updates.read_json.await_args_list] == [
        updates.LATEST, "http://127.0.0.1:7667/api/settings/workspace"]


@pytest.mark.parametrize("markers", [
    {"uv-receipt.toml": '[[tool.requirements]]\nname="another-tool"'},
    {"pipx_metadata.json": '{"main_package":{"package":"another-tool"}}'},
    {"uv-receipt.toml": "", "pipx_metadata.json": "{}"},
    {"uv-receipt.toml": "not a receipt"},
])
def test_foreign_or_ambiguous_receipts_are_manual(tmp_path, monkeypatch, markers):
    package = tmp_path / "lib/roosta"
    monkeypatch.setattr(updates.paths, "APP_ROOT", package)
    monkeypatch.setattr(updates.sys, "prefix", str(tmp_path))
    dist = Mock()
    monkeypatch.setattr(updates.metadata, "distribution", lambda _: dist)
    dist.read_text.return_value = None
    dist.locate_file.return_value = package
    for name, text in markers.items():
        (tmp_path / name).write_text(text)
    assert updates.installation() == "unknown"


def test_workspace_manager_is_never_run(workspace, monkeypatch):
    fake = workspace / "tools/uv"
    monkeypatch.setattr(updates.paths, "WORKSPACE", workspace)
    monkeypatch.setattr(cli_update.shutil, "which", lambda _: str(fake))
    with pytest.raises(cli_update.UpdateError, match="outside the workspace"):
        cli_update.manager_binary("uv")
    subprocess.run.assert_not_called()


def test_doctor_worker_needs_missing_runtime(workspace, capsys):
    (workspace / ".roosta/tasks.yaml").write_text("tasks: [{id: writer, skill: setup, harness: claude}]")
    assert cli.main(["doctor", "--offline"]) == 1
    text = capsys.readouterr().out
    assert "FAIL  claude" in text and "SKIP  pi" in text


@pytest.mark.parametrize("response", [
    {"version": "SECRET", "workspace": "/workspace"},
    {"version": doctor.__version__, "workspace": 123},
    {"version": doctor.__version__, "workspace": "relative/SECRET"},
    {"version": doctor.__version__},
    [],
])
def test_doctor_malformed_runner_metadata(workspace, monkeypatch, response, capsys):
    monkeypatch.setattr(updates, "stable_release", AsyncMock(return_value=(doctor.__version__, {})))
    monkeypatch.setattr(updates, "read_json", AsyncMock(return_value=response))
    assert cli.main(["doctor", "--json"]) == 0
    output = capsys.readouterr()
    assert "SECRET" not in output.out + output.err
    checks = {r["name"]: r for r in json.loads(output.out)["checks"]}
    assert checks["Local endpoint"]["status"] == "WARN"
    assert "Runner workspace" not in checks


@pytest.mark.parametrize("selection,expected", [("alias", "PASS"), ("other", "WARN"), ("none", "SKIP")])
def test_doctor_compares_runner_workspace(workspace, monkeypatch, selection, expected):
    path = workspace.parent / "SECRET"
    if selection == "alias":
        path.symlink_to(workspace, target_is_directory=True)
    monkeypatch.setattr(updates, "read_json", AsyncMock(return_value={"workspace": str(path), "version": doctor.__version__}))
    checks = []
    doctor.service_checks(None if selection == "none" else workspace, {}, lambda *r: checks.append(r), False)
    assert checks[-1][:2] == ("Runner workspace", expected)
    assert "SECRET" not in str(checks)


@pytest.mark.parametrize("offline,active,expected,detail", [
    (False, True, "PASS", "Active"), (False, False, "WARN", "Inactive"),
    (False, None, "WARN", "Unknown"), (True, None, "SKIP", "Offline"),
])
def test_doctor_user_service_status(workspace, monkeypatch, offline, active, expected, detail):
    cli.service_status.return_value = {"installed": True, "active": active, "workspace": str(workspace), "port": 8123}
    read = AsyncMock(return_value={"version": doctor.__version__, "workspace": str(workspace)})
    monkeypatch.setattr(updates, "read_json", read)
    checks = []
    doctor.service_checks(workspace, {}, lambda *r: checks.append(r), offline)
    cli.service_status.assert_called_once_with(workspace, probe=not offline)
    assert any(n == "Service status" and s == expected and detail in d for n, s, d in checks)
    if offline:
        read.assert_not_awaited()
        assert checks[-1][:2] == ("Local endpoint", "SKIP")
    else:
        read.assert_awaited_once_with("http://127.0.0.1:8123/api/settings/workspace")


def test_doctor_online_without_package_metadata(workspace, monkeypatch, capsys):
    monkeypatch.setattr(doctor.metadata, "version", Mock(side_effect=doctor.metadata.PackageNotFoundError))
    release = {"tag_name": "v1.3.0", "draft": False, "prerelease": False}
    runner = {"version": doctor.__version__, "workspace": str(workspace)}
    monkeypatch.setattr(updates, "read_json", AsyncMock(side_effect=[release, runner]))
    assert cli.main(["doctor", "--json"]) == 0
    checks = {r["name"]: r for r in json.loads(capsys.readouterr().out)["checks"]}
    assert checks["Roosta"]["status"] == "WARN" and "1.3.0" in checks["Latest stable"]["detail"]
    assert checks["Runner workspace"]["status"] == "PASS"


@pytest.mark.parametrize("field,value", [("idle_timeout", ".nan"), ("max_timeout", ".inf"), ("idle_timeout", "-.inf")])
def test_doctor_rejects_nonfinite_yaml_timeouts(workspace, field, value, capsys):
    (workspace / ".roosta/tasks.yaml").write_text(f"tasks: [{{id: writer, skill: setup, {field}: {value}}}]")
    assert cli.main(["doctor", "--offline"]) == 1
    assert f"Correct {field}" in capsys.readouterr().out
