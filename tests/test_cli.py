import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from roosta import cli, paths, skills


def migrate_at_startup(core, workspace):
    with skills.ownership_lock(workspace, "skill-runner", wait=True):
        return skills.migrate(core, workspace)


def make_core(root: Path, body: str = "v1") -> Path:
    core = root / "core"
    (core / "actor").mkdir(parents=True)
    (core / "actor" / "SKILL.md").write_text(f"---\nname: actor\n---\n{body}\n")
    return core


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_FILE", tmp_path / "config" / "roosta.json")


@pytest.mark.parametrize("resource", ["board", "tasks"])
def test_snapshot_reads_only_local_runner(resource, monkeypatch, capsys):
    import httpx

    monkeypatch.setenv("ROOSTA_PORT", "7812")
    payload = {"document": {"items": [], "later": []}} if resource == "board" else []

    def get(url, **options):
        assert url == f"http://127.0.0.1:7812/api/{resource}"
        assert options["trust_env"] is False and options["follow_redirects"] is False
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    assert cli.main(["snapshot", resource]) == 0
    assert json.loads(capsys.readouterr().out) == payload
    if resource == "board":
        payload = {"document": {}}
        assert cli.main(["snapshot", resource]) == 1
        output = capsys.readouterr()
        assert not output.out and "document.items" in output.err
    monkeypatch.setenv("ROOSTA_PORT", "7812@example.com")
    assert cli.main(["snapshot", resource]) == 1
    assert not capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["snapshot", "board/refresh"])


def test_usage_reads_the_running_workspace_over_saved_config(tmp_path, monkeypatch, capsys):
    def workspace_with_events(name, count):
        root = tmp_path / name
        log = root / ".roosta" / "state" / "cache" / "product-usage.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text("".join(
            json.dumps({"at": _now_iso(), "event": "item_opened", "properties": {}}) + "\n"
            for _ in range(count)
        ))
        return root

    running = workspace_with_events("running", 3)
    saved = workspace_with_events("saved", 1)
    cli.write_config({"workspace": str(saved)})
    monkeypatch.setenv("ROOSTA_WORKSPACE", str(running))
    assert cli.main(["usage"]) == 0
    assert json.loads(capsys.readouterr().out)["events"] == 3
    assert cli.main(["usage", "--workspace", str(saved)]) == 0
    assert json.loads(capsys.readouterr().out)["events"] == 1
    monkeypatch.setenv("ROOSTA_WORKSPACE", "   ")
    assert cli.main(["usage"]) == 0
    assert json.loads(capsys.readouterr().out)["events"] == 1
    monkeypatch.delenv("ROOSTA_WORKSPACE")
    assert cli.main(["usage"]) == 0
    assert json.loads(capsys.readouterr().out)["events"] == 1


def _now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def test_init_creates_a_workspace_without_clobbering(tmp_path):
    target = tmp_path / "ws"
    assert cli.init(target, check=False) == 0
    for name in ("AGENTS.md", "PROFILE.md", "PRIORITIES.md", "CONTEXT.md", "TOOLS.md",
                 ".roosta/tasks.yaml", ".roosta/connectors.yaml", "projects/README.md", ".mcp.json"):
        assert (target / name).is_file(), name
    assert not (target / ".agents/skills/actor").exists()
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


def test_core_upgrades_and_extensions_follow_installed_files(tmp_path, monkeypatch):
    core = make_core(tmp_path)
    workspace = tmp_path / "workspace"
    ws = workspace / ".roosta"
    ws.mkdir(parents=True)
    monkeypatch.setattr(paths, "CORE_SKILLS_DIR", core)
    args = ["--workspace", str(workspace)]
    assert cli.main(["skills", "extend", "actor", *args]) == 0
    extension = ws / "skill-extensions/actor.md"
    extension.write_text("Use our team’s terms")
    assert cli.main(["skills", "fork", "actor", *args]) == 0
    fork = ws / "skill-forks/actor"
    (fork / "SKILL.md").write_text("pinned edition")
    (core / "actor/helper.py").write_text("improved helper")
    assert skills.status(core, workspace)["forks"] == {"actor": "core update available"}
    assert str(fork / "SKILL.md") in skills.instructions("actor", workspace, workspace)
    assert cli.main(["skills", "use-core", "actor", *args]) == 0
    assert (ws / "skill-archive/forks/actor/SKILL.md").read_text() == "pinned edition"
    assert skills.find_skill_files("actor", workspace, workspace, core) == [core / "actor/SKILL.md"]
    assert str(extension) in skills.instructions("actor", workspace, workspace)
    assert extension.read_text() == "Use our team’s terms"


@pytest.mark.parametrize("linked_forks", [False, True])
def test_pi_discovers_only_skills_the_prompt_does_not_route(tmp_path, monkeypatch, linked_forks):
    from roosta import pi_agent

    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    monkeypatch.setattr(paths, "CORE_SKILLS_DIR", core)
    monkeypatch.setattr(paths, "WORKSPACE", ws)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    forks = tmp_path / "elsewhere" if linked_forks else ws / skills.FORKS
    (forks / "pinned").mkdir(parents=True)
    (forks / "pinned/SKILL.md").write_text("fork")
    (forks / "broken").mkdir()  # incomplete fork: routed as unavailable, never replaced by a copy
    if linked_forks:
        (ws / ".roosta").mkdir(parents=True)
        (ws / skills.FORKS).symlink_to(forks)
    for name in ("actor", "pinned", "broken", "custom"):
        (ws / ".agents/skills" / name).mkdir(parents=True)
        (ws / ".agents/skills" / name / "SKILL.md").write_text("workspace copy")

    problems = []
    routed = skills.routed(ws, problems)
    prompt = skills.instructions("actor", ws, ws)
    args = pi_agent.pi_args("pi", {"provider": "openai"}, "m", tmp_path / "pi", "sid", str(ws))
    offered = [args[i + 1] for i, arg in enumerate(args) if arg == "--skill"]

    assert routed == (["actor"] if linked_forks else ["actor", "broken", "pinned"])
    assert bool(problems) is linked_forks and (f"Review {skills.FORKS}:" in prompt) is linked_forks
    assert all(f"{name}: " in prompt for name in routed)
    expected = {"custom"} | ({"pinned", "broken"} if linked_forks else set())
    assert offered == [str(ws / ".agents/skills" / name / "SKILL.md") for name in sorted(expected)]


@pytest.mark.parametrize("lock", [None, "[]", "{broken", '{"skills":{"actor":"invalid"}}'])
def test_unverifiable_legacy_trees_survive_including_claude(tmp_path, lock):
    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    (ws / ".roosta").mkdir(parents=True)
    if lock:
        (ws / ".roosta/skills.lock.json").write_text(lock)
    for group in (".agents", ".claude"):
        skill = ws / group / "skills/actor"
        shutil.copytree(core / "actor", skill)
        (skill / "helper.py").write_text(group)
    assert len(migrate_at_startup(core, ws)) == 2
    assert migrate_at_startup(core, ws) == []
    assert (ws / skills.FORKS / "actor/helper.py").read_text() == ".agents"
    assert (ws / skills.ARCHIVE / "review-claude/actor/helper.py").read_text() == ".claude"
    assert skills.status(core, ws)["review"] == {"actor": [".roosta/skill-archive/review-claude/actor"]}


def test_clean_missing_and_retired_legacy_skills(tmp_path):
    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    shipped = core / "actor"
    old = ws / ".agents/skills/actor"
    shutil.copytree(shipped, old)
    retired = old.with_name("retired")
    shutil.copytree(shipped, retired)
    records = {name: {"hash": skills.tree_hash(old)} for name in ("actor", "missing", "retired")}
    (ws / ".roosta").mkdir()
    (ws / ".roosta/skills.lock.json").write_text(json.dumps({"skills": records}))
    (shipped / "SKILL.md").write_text("latest")
    shutil.copytree(shipped, core / "missing")
    migrate_at_startup(core, ws)
    assert skills.status(core, ws)["core"] == ["actor", "missing"]
    assert skills.status(core, ws)["forks"] == {"retired": "retired from core"}
    assert (ws / skills.ARCHIVE / ".agents/actor/SKILL.md").read_text().endswith("v1\n")
    assert not old.exists() and not old.with_name("missing").exists()


@pytest.mark.parametrize("link", [".agents", ".roosta", ".agents/skills/actor/helper.py"])
def test_migration_refuses_symlinks_before_touching_their_targets(tmp_path, link):
    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    outside.mkdir()
    source = ws / link
    source.parent.mkdir(parents=True)
    source.symlink_to(outside, target_is_directory=True)
    if link.endswith("helper.py"):
        (source.parent / "SKILL.md").write_text("legacy")
    if link == ".roosta":  # No trustworthy location for workspace runtime metadata.
        with pytest.raises(ValueError, match="linked"):
            migrate_at_startup(core, ws)
    else:
        assert any("Review" in message for message in migrate_at_startup(core, ws))
        report = skills.status(core, ws)
        assert report["problems"] or report["pending"]
    assert source.is_symlink() and not list(outside.iterdir())


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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/runner/identity", timeout=2) as response:
            assert json.load(response) == {"service": "roosta", "pid": proc.pid}
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


def test_start_binds_workspace_and_port_before_loading_paths(tmp_path):
    workspace = tmp_path / "selected"
    (workspace / ".roosta").mkdir(parents=True)
    check = """
import sys
from pathlib import Path
from types import SimpleNamespace
from roosta import cli
def run(*args, **kwargs):
    from roosta import paths
    assert paths.WORKSPACE == Path(sys.argv[1]) and paths.PORT == 8777
sys.modules["uvicorn"] = SimpleNamespace(run=run)
raise SystemExit(cli.main(["start", "--workspace", sys.argv[1], "--port", "8777"]))
"""
    subprocess.run([sys.executable, "-c", check, str(workspace)], check=True)


def test_clean_primary_and_unknown_secondary_follow_upgrades(tmp_path):
    core = make_core(tmp_path)
    ws = tmp_path / "workspace"
    agents = ws / ".agents/skills/actor"
    shutil.copytree(core / "actor", agents)
    old = ws / ".claude/skills/actor"
    shutil.copytree(agents, old)
    (old / "SKILL.md").write_text("possibly stale Windows copy")
    (ws / ".roosta").mkdir()
    (ws / ".roosta/skills.lock.json").write_text(json.dumps({"skills": {"actor": {"hash": skills.tree_hash(agents)}}}))
    (core / "actor/SKILL.md").write_text("next release")
    migrate_at_startup(core, ws)
    report = skills.status(core, ws)
    assert report["forks"] == {} and report["core"] == ["actor"]
    archived, = report["review"]["actor"]
    assert (ws / archived / "SKILL.md").read_text() == "possibly stale Windows copy"
    assert migrate_at_startup(core, ws) == []


def test_pointer_refresh_preserves_owner_files(tmp_path, monkeypatch):
    core = make_core(tmp_path)
    ws = tmp_path / "workspace"
    pointer = ws / ".roosta/operating-model.md"
    pointer.parent.mkdir(parents=True)
    (ws / "AGENTS.md").write_text("Read .roosta/operating-model.md. My own rules.")
    legacy = "# Previously shipped model\n"
    import hashlib
    monkeypatch.setattr(skills, "LEGACY_MODELS", {hashlib.sha256(legacy.encode()).hexdigest()})
    pointer.write_text(legacy)
    migrate_at_startup(core, ws)
    assert "roosta skills instructions" in pointer.read_text()
    assert (ws / skills.ARCHIVE / "model/operating-model.md").read_text() == legacy
    assert "My own rules" in (ws / "AGENTS.md").read_text()
    pointer.write_text("my operating rules")
    migrate_at_startup(core, ws)
    assert pointer.read_text() == "my operating rules"
    assert any("operating-model.md" in issue for issue in skills.status(core, ws)["problems"])


def test_standalone_and_project_skill_paths(tmp_path, monkeypatch, capsys):
    ws = tmp_path / "workspace"
    core = make_core(tmp_path)
    monkeypatch.setattr(paths, "CORE_SKILLS_DIR", core)
    fork = skills.manage("fork", "actor", ws, core)
    extra = skills.manage("extend", "actor", ws, core)
    assert cli.main(["skills", "instructions", "actor", "--workspace", str(ws)]) == 0
    output = capsys.readouterr().out.rstrip()
    assert output == skills.instructions("actor", ws, ws).rstrip()
    assert str(fork / "SKILL.md") in output and str(extra) in output
    project = ws / "projects/local/.agents/skills/report/SKILL.md"
    project.parent.mkdir(parents=True)
    project.write_text("local")
    assert str(project) in skills.instructions("report", "projects/local", ws)


def test_retired_fork_archives_without_interrupting_active_turns(tmp_path):
    core = make_core(tmp_path)
    ws = tmp_path / "workspace"
    fork = skills.manage("fork", "actor", ws, core)
    (core / "actor").rename(tmp_path / "retired")
    with skills.ownership_lock(ws, "skill-runner", wait=False):
        decision = skills.manage("use-core", "actor", ws, core)
        assert decision.is_file() and fork.is_dir()
        assert "restart" in skills.status(core, ws)["forks"]["actor"]
        assert cli.main(["skills", "sync", "--workspace", str(ws)]) == 0
        assert fork.is_dir()
    migrate_at_startup(core, ws)
    assert not decision.exists() and not fork.exists()
    (tmp_path / "retired").rename(core / "actor")
    assert skills.find_skill_files("actor", ws, ws, core) == [core / "actor/SKILL.md"]
    assert (ws / skills.status(core, ws)["review"]["actor"][0] / "SKILL.md").exists()


def test_bad_entry_and_bad_metadata_leave_other_skills_available(tmp_path):
    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    fork = skills.manage("fork", "actor", ws, core)
    (ws / ".agents/skills/actor").mkdir(parents=True)
    (fork / skills.BASE).write_bytes(b"\xff")
    shutil.copytree(core / "actor", core / "sender")
    migrate_at_startup(core, ws)
    report = skills.status(core, ws)
    assert report["pending"] == [".agents/skills/actor"]
    assert report["forks"]["actor"] == "needs review" and report["problems"]
    assert skills.find_skill_files("sender", ws, ws, core) == [core / "sender/SKILL.md"]


def test_concurrent_legacy_migration_keeps_a_single_complete_fork(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    legacy = ws / ".agents/skills/actor"
    shutil.copytree(core / "actor", legacy)
    (legacy / "helper.py").write_text("my helper")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: migrate_at_startup(core, ws), range(8)))
    assert any(results) and not legacy.exists()
    assert (ws / skills.FORKS / "actor/helper.py").read_text() == "my helper"
    assert not skills.status(core, ws)["review"]


def test_manual_sync_and_adopt_leave_running_legacy_worker_files_in_place(tmp_path):
    ws = tmp_path / "legacy"
    helper = ws / ".agents/skills/setup/helper.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("worker still needs this")
    (helper.parent / "SKILL.md").write_text("old worker")
    config = ws / ".roosta"
    config.mkdir()
    model = config / "operating-model.md"
    model.write_text("existing operating model")
    # A 0.16 worker already running has never created or acquired an ownership lock.
    assert cli.main(["skills", "sync", "--workspace", str(ws)]) == 0
    assert cli.init(ws, adopt=True, check=False, initialise_git=False) == 0
    assert helper.read_text() == "worker still needs this"
    assert model.read_text() == "existing operating model"
    assert not (ws / skills.ARCHIVE).exists() and not (ws / skills.FORKS).exists()


def test_orphan_archive_decision_does_not_apply_to_restored_legacy_tree(tmp_path):
    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    original = skills.manage("fork", "actor", ws, core)
    (original / "local.md").write_text("original")
    archived = skills.manage("use-core", "actor", ws, core)
    # Crash after archiving, before removing the old decision.
    decision = ws / ".roosta/skill-decisions/actor"
    decision.parent.mkdir()
    decision.touch()
    restored = ws / ".agents/skills/actor"
    restored.mkdir(parents=True)
    (restored / "SKILL.md").write_text("restored custom instructions")
    migrate_at_startup(core, ws)
    assert (original / "SKILL.md").read_text() == "restored custom instructions"
    assert (archived / "local.md").read_text() == "original"
    assert not decision.exists()
    assert migrate_at_startup(core, ws) == []


def test_pointer_symlink_loop_only_blocks_pointer_migration(tmp_path):
    core = make_core(tmp_path)
    ws = tmp_path / "ws"
    pointer = ws / ".roosta/operating-model.md"
    pointer.parent.mkdir(parents=True)
    pointer.symlink_to(pointer.name)
    migrate_at_startup(core, ws)
    assert pointer.is_symlink()
    assert any("operating-model.md" in issue for issue in skills.status(core, ws)["problems"])
    assert skills.find_skill_files("actor", ws, ws, core) == [core / "actor/SKILL.md"]
