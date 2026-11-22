import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from roosta import cli, paths, skills


def make_core(root: Path, body: str = "v1") -> Path:
    core = root / "core"
    (core / "actor").mkdir(parents=True)
    (core / "actor" / "SKILL.md").write_text(f"---\nname: actor\n---\n{body}\n")
    return core


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_FILE", tmp_path / "config" / "roosta.json")


def test_init_creates_a_workspace_without_clobbering(tmp_path):
    target = tmp_path / "ws"
    assert cli.init(target, check=False) == 0
    for name in ("AGENTS.md", "PROFILE.md", "PRIORITIES.md", "CONTEXT.md", "TOOLS.md",
                 ".roosta/tasks.yaml", ".roosta/connectors.yaml", ".roosta/operating-model.md",
                 ".roosta/skills.lock.json", "projects/README.md", ".mcp.json"):
        assert (target / name).is_file(), name
    assert (target / "CLAUDE.md").resolve() == (target / "AGENTS.md").resolve()
    assert (target / ".claude" / "skills").resolve() == (target / ".agents" / "skills").resolve()
    assert ".roosta/state/" in (target / ".gitignore").read_text().splitlines()
    assert (target / ".git").is_dir()
    import subprocess
    status = subprocess.run(["git", "status", "--porcelain"], cwd=target, capture_output=True, text=True)
    log = subprocess.run(["git", "log", "--format=%s"], cwd=target, capture_output=True, text=True)
    if log.returncode == 0:  # git may lack a user.name in CI; init then only warns
        assert log.stdout.strip() == "chore: initialise Roosta workspace" and status.stdout == ""
    assert json.loads(cli.CONFIG_FILE.read_text())["workspace"] == str(target.resolve())

    (target / "AGENTS.md").write_text("mine\n")
    assert cli.init(target, check=False) == 0          # re-running is safe
    assert (target / "AGENTS.md").read_text() == "mine\n"


def test_init_refuses_a_full_folder_unless_adopting(tmp_path):
    (tmp_path / "notes.md").write_text("existing")
    assert cli.init(tmp_path, check=False) == 1
    assert cli.init(tmp_path, adopt=True, check=False) == 0
    assert (tmp_path / "notes.md").read_text() == "existing"
    assert (tmp_path / ".roosta" / "tasks.yaml").is_file()


def test_skills_sync_updates_untouched_skills_and_keeps_edited_ones(tmp_path):
    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    report = skills.sync(core, ws)
    assert report.installed == ["actor"]
    installed = ws / ".agents" / "skills" / "actor" / "SKILL.md"

    (core / "actor" / "SKILL.md").write_text("---\nname: actor\n---\nv2\n")
    assert skills.sync(core, ws).updated == ["actor"]
    assert installed.read_text().endswith("v2\n")

    installed.write_text("my edit\n")
    (core / "actor" / "SKILL.md").write_text("---\nname: actor\n---\nv3\n")
    report = skills.sync(core, ws)
    assert report.modified == ["actor"] and installed.read_text() == "my edit\n"
    lock = json.loads((ws / ".roosta" / "skills.lock.json").read_text())
    assert lock["skills"]["actor"]["modified"] is True
    assert lock["skills"]["actor"]["available"] == skills.tree_hash(core / "actor")


def test_skills_sync_treats_an_adopted_edit_as_the_users(tmp_path):
    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    (ws / ".agents" / "skills" / "actor").mkdir(parents=True)
    (ws / ".agents" / "skills" / "actor" / "SKILL.md").write_text("Locally edited skill\n")
    assert skills.sync(core, ws).modified == ["actor"]


def test_shipped_core_skills_carry_frontmatter():
    for skill in paths.CORE_SKILLS_DIR.iterdir():
        if skill.is_dir():
            text = (skill / "SKILL.md").read_text()
            assert text.startswith("---\n") and f"name: {skill.name}\n" in text, skill.name


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.skipif(os.environ.get("ROOSTA_SKIP_E2E") == "1", reason="end-to-end disabled")
def test_fresh_init_starts_with_ai_connection_before_workspace_setup(tmp_path):
    """A fresh workspace can connect AI before starting the AI-led interview."""
    ws = tmp_path / "ws"
    assert cli.init(ws, check=False) == 0
    (ws / ".roosta" / "tasks.yaml").write_text("tasks: []\n")   # no model runs in CI
    port = free_port()
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PATH": str(tmp_path / "empty-bin")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "roosta.cli", "start", "--workspace", str(ws), "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 30
        board = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/board", timeout=2) as response:
                    board = json.load(response)
                break
            except OSError:
                time.sleep(0.3)
        assert board is not None, "runner did not start"
        ids = [item["id"] for item in board["document"]["items"]]
        assert "roosta-ai-setup" in ids and "roosta-setup" not in ids
        card = next(i for i in board["document"]["items"] if i["id"] == "roosta-ai-setup")
        assert card["title"] == "Connect your AI" and card["action_owner"] == "user"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/profile", timeout=2) as response:
            assert json.load(response)["user"] == "the user"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_roosta_has_its_own_port():
    """7667 spells R-O-O-S on a phone keypad; it must stay in step across the CLI, the app and the desktop shell."""
    root = Path(__file__).resolve().parent.parent
    assert cli.DEFAULT_PORT == 7667
    assert paths.PORT == 7667 and paths.BASE_URL == "http://127.0.0.1:7667"
    assert 'const BASE_URL = "http://127.0.0.1:7667";' in (root / "desktop" / "src" / "main.js").read_text()


def test_init_without_git_does_not_invoke_developer_tools(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("desktop init must not invoke Git")
    monkeypatch.setattr(cli.subprocess, "run", unexpected)
    assert cli.init(tmp_path / "desktop", check=False, initialise_git=False) == 0
    assert (tmp_path / "desktop" / ".roosta" / "tasks.yaml").exists()


def test_core_skills_have_a_single_source():
    # The repo-root .agents/skills copy drifted from the shipped skills, and the runner prefers
    # a task directory's .agents/skills, so a task run in a Roosta checkout loaded stale skills.
    repo = Path(__file__).resolve().parents[1]
    if not (repo / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files", ".agents", ".claude"], cwd=repo,
                             capture_output=True, text=True, check=True).stdout
    assert tracked == "", "core skills belong only in src/roosta/skills"
