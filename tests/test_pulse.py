import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


from roosta.pulse import (
    activity_stats,
    artefact_links,
    board_stats,
    build_pulse,
    command_mood,
    frontmatter_field,
    frontmatter_text,
    markdown_title,
    project_brief,
    provenance,
    related_projects,
    review_project,
    running_workloads,
    scan_vault,
)


@pytest.mark.parametrize(
    "content, stem, expected",
    [
        ("---\ntitle: Team OKRs\nstatus: active\n---\n\n# Team OKRs\n", "README", "Team OKRs"),
        ("# Stand-up notes\n\nBody", "2026-07-30-standup", "Stand-up notes"),
        ("Plain note without a heading.", "plain-note", "Plain Note"),
    ],
)
def test_markdown_title(content, stem, expected):
    assert markdown_title(content, stem) == expected


def test_frontmatter_field_reads_scalars():
    content = "---\ntitle: Platform Roadmap\nstatus: active\nowner: Sam Example\n---\n\n# Body\n"
    assert frontmatter_field(content, "status") == "active"
    assert frontmatter_field(content, "owner") == "Sam Example"
    assert frontmatter_field(content, "missing") == ""
    assert frontmatter_field("# No frontmatter", "status") == ""


def test_related_projects_only_resolves_known_projects():
    content = (
        "# Roadmap\n\n"
        "Body mentions [[decoy]] outside the section.\n\n"
        "## Related\n\n"
        "| [[team-structure]] | The reorg |\n"
        "| [[pat-evans]] | A person note, not a project |\n"
        "| [team-okrs](../team-okrs/README.md) | Ladders up |\n"
        "| [[team-structure]] | Repeated |\n\n"
        "## Links\n\n[[another-project]]\n"
    )
    known = {"team-structure", "team-okrs", "decoy", "another-project"}
    assert related_projects(content, known) == ["team-structure", "team-okrs"]
    assert related_projects("# No related section", known) == []


def test_scan_vault_project_graph_and_staleness(tmp_path):
    projects = tmp_path / "projects"
    for name in ("platform-roadmap", "team-structure", "old-thing"):
        (projects / name).mkdir(parents=True)
    (projects / "platform-roadmap" / "README.md").write_text(
        "---\ntitle: Roadmap\nstatus: active\nowner: Sam Example\n---\n\n"
        "## Related\n\n| [[team-structure]] | Premise |\n"
    )
    (projects / "team-structure" / "README.md").write_text(
        "---\ntitle: Team structure\nstatus: paused\n---\n"
    )
    stale = projects / "old-thing" / "README.md"
    stale.write_text("---\ntitle: Old thing\nstatus: active\n---\n")
    old = datetime.now(timezone.utc) - timedelta(days=45)
    os.utime(stale, (old.timestamp(), old.timestamp()))

    result = scan_vault(tmp_path)
    signals = {signal["name"]: signal for signal in result["project_signals"]}
    assert signals["platform-roadmap"]["status"] == "active"
    assert signals["platform-roadmap"]["owner"] == "Sam Example"
    assert signals["platform-roadmap"]["related"] == ["team-structure"]
    # `## Related` is meant to be bidirectional, so a half-written pair still links.
    assert signals["team-structure"]["related"] == ["platform-roadmap"]
    assert signals["platform-roadmap"]["stale"] is False
    assert signals["old-thing"]["stale"] is True
    assert signals["old-thing"]["age_days"] >= 45
    assert result["stale_projects"] == 1


def test_scan_vault_does_not_flag_parked_projects_as_stale(tmp_path):
    readme = tmp_path / "projects" / "shipped" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("---\ntitle: Shipped\nstatus: completed\n---\n")
    old = datetime.now(timezone.utc) - timedelta(days=200)
    os.utime(readme, (old.timestamp(), old.timestamp()))

    result = scan_vault(tmp_path)
    assert result["project_signals"][0]["stale"] is False
    assert result["stale_projects"] == 0


def test_scan_vault_hot_files_include_title(tmp_path):
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    readme = tmp_path / "projects" / "demo" / "README.md"
    readme.write_text("---\ntitle: Demo project\n---\n\n# Demo\n")
    result = scan_vault(tmp_path)
    assert len(result["hot_files"]) == 1
    assert result["hot_files"][0]["title"] == "Demo project"
    assert result["hot_files"][0]["path"] == "projects/demo/README.md"


def test_scan_vault_counts_projects_and_skips_roosta_config(tmp_path, monkeypatch):
    from roosta import paths

    core = tmp_path / ".installed"
    monkeypatch.setattr(paths, "CORE_SKILLS_DIR", core)
    for directory in (core / "actor", core / "sender", tmp_path / ".roosta/skill-forks/actor",
                      tmp_path / ".cursor/skills/custom"):
        directory.mkdir(parents=True)
        (directory / "SKILL.md").touch()

    (tmp_path / "projects" / "team-okrs").mkdir(parents=True)
    (tmp_path / "projects" / "team-okrs" / "README.md").write_text("# OKRs\n\nhello world")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "note.md").write_text("one two three four")
    (tmp_path / ".roosta").mkdir(exist_ok=True)
    (tmp_path / ".roosta" / "secret.md").write_text("should not count")
    (tmp_path / ".claude" / "skills" / "actor").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "actor" / "SKILL.md").write_text("skill")

    result = scan_vault(tmp_path)
    assert result["projects"] == 1
    assert result["project_names"] == ["team-okrs"]
    assert result["project_signals"][0]["name"] == "team-okrs"
    assert result["project_signals"][0]["title"] == "OKRs"
    assert result["project_signals"][0]["recent_edits"] == 1
    assert result["project_signals"][0]["last_activity"]
    assert result["markdown_files"] == 2
    assert result["words"] >= 6
    assert result["skills"] == 3


def test_activity_stats_today_only():
    now = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)
    entries = [
        {"started": "2026-07-30T10:00:00+00:00", "kind": "skill", "status": "success", "duration": 12.5},
        {"started": "2026-07-29T10:00:00+00:00", "kind": "skill", "status": "success", "duration": 99},
        {"started": "2026-07-30T11:00:00+00:00", "kind": "skill", "status": "error", "duration": 3},
        {"started": "2026-07-30T12:00:00+00:00", "kind": "skill", "status": "running", "duration": 0},
    ]
    stats = activity_stats(entries, now)
    assert stats["today_runs"] == 3
    assert stats["today_success"] == 1
    assert stats["today_errors"] == 1
    assert stats["running_now"] == 1
    assert stats["today_ai_seconds"] == 15.5


def test_board_stats_cleared_today():
    today = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    handled = {
        "a": {"at": today.isoformat(), "result": "done"},
        "b": {"at": yesterday.isoformat(), "result": "old"},
    }
    stats = board_stats(handled, board_active=2, board_later=1, health={"ok": False, "degraded": [{}, {}]})
    assert stats["cleared_today"] == 1
    assert stats["board_active"] == 2
    assert stats["sensors_ok"] is False
    assert stats["degraded_sensors"] == 2


@pytest.mark.parametrize(
    "health,activity,board,vault,code",
    [
        ({"ok": False, "degraded": [{}]}, {}, {}, {}, "sensor_fog"),
        ({"ok": True}, {"running_now": 1}, {}, {}, "agents_active"),
        ({"ok": True}, {}, {"board_active": 0, "board_later": 0}, {}, "all_clear"),
        ({"ok": True}, {}, {"cleared_today": 4}, {}, "productive_orbit"),
        ({"ok": True}, {"today_errors": 2}, {}, {}, "turbulence"),
        ({"ok": True}, {}, {}, {"recent_files_7d": 20}, "vault_alive"),
    ],
)
def test_command_mood_priority(health, activity, board, vault, code):
    mood = command_mood(
        {"recent_files_7d": 0, "projects": 1, "words": 1000, **vault},
        {"running_now": 0, "today_errors": 0, **activity},
        {
            "sensors_ok": health.get("ok", True),
            "degraded_sensors": len(health.get("degraded", [])),
            "board_active": 1,
            "board_later": 0,
            "cleared_today": 0,
            **board,
        },
    )
    assert mood["code"] == code


def test_build_pulse_shape(tmp_path):
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    (tmp_path / "projects" / "demo" / "README.md").write_text("# Demo")
    payload = build_pulse(
        tmp_path,
        activity_entries=[],
        handled={},
        board_active=0,
        board_later=0,
        health={"ok": True, "degraded": []},
        now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        active_project_refs=["projects/demo", "projects/demo"],
    )
    assert payload["mood"]["code"] == "all_clear"
    assert payload["vault"]["projects"] == 1
    assert payload["vault"]["project_signals"][0]["active_board_items"] == 2
    assert payload["running"] == []
    assert "generated_at" in payload


def test_running_workloads_dedupes_task_and_activity():
    entries = [
        {"status": "running", "kind": "skill", "label": "assistant", "source": "scheduled",
         "started": "2026-07-30T10:00:00+00:00"},
    ]
    tasks = [
        {"id": "assistant", "skill": "assistant", "status": "running", "last_run": "2026-07-30T10:00:00+00:00"},
        {"id": "teams-actions-watch", "skill": "teams-actions-watch", "status": "idle", "queued": True},
    ]
    chats = [{
        "id": "item-1",
        "title": "Reply to Andre",
        "project_ref": "projects/team-okrs",
    }]
    running = running_workloads(tasks, entries, chats)
    assert len(running) == 3
    assert running[0]["kind"] == "skill"
    assert running[1]["kind"] == "task"
    assert running[1]["status"] == "queued"
    assert running[2]["kind"] == "chat"
    assert running[2]["action"] == "open"
    assert running[2]["href"] == "/assistant?item=item-1"
    assert running[2]["project_ref"] == "projects/team-okrs"
    assert running[0]["action"] == "trace"
    assert "href" not in running[0]


def test_build_pulse_includes_running_from_activity_only(tmp_path):
    payload = build_pulse(
        tmp_path,
        activity_entries=[{"status": "success", "kind": "skill", "label": "old"}],
        handled={},
        board_active=0,
        board_later=0,
        health={"ok": True, "degraded": []},
        running_activity=[
            {"status": "running", "kind": "skill", "label": "workspace-gardener",
             "source": "manual", "started": "2026-07-30T16:53:13+00:00"},
        ],
    )
    assert len(payload["running"]) == 1
    assert payload["running"][0]["name"] == "workspace-gardener"


def test_frontmatter_text_flattens_values_for_search():
    content = ("---\ntitle: Team OKRs\ntags: [okr, planning]\npeople:\n  - Dana Ross\n---\n\n"
               "# Body is not searched\n")
    text = frontmatter_text(content)
    assert "okr" in text and "planning" in text and "Dana Ross" in text
    assert "Body" not in text
    assert frontmatter_text("# No frontmatter") == ""


def test_scan_vault_exposes_project_keywords(tmp_path):
    readme = tmp_path / "projects" / "team-okrs" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("---\ntitle: Team OKRs\ntags: [airtable]\n---\n")
    signal = scan_vault(tmp_path)["project_signals"][0]
    assert "airtable" in signal["keywords"]


NOW = datetime.now(timezone.utc)
TODAY = NOW.date().isoformat()


def _readme(tmp_path, slug, text):
    readme = tmp_path / "projects" / slug / "README.md"
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(text)
    return readme


def test_provenance_states_and_due():
    past = (NOW - timedelta(days=1)).date().isoformat()
    future = (NOW + timedelta(days=10)).date().isoformat()
    human = f"---\nstatus: active\nverified:\n  - {{ by: human:sam-example, at: {past} }}\nstale_after: {future}\n---\n"
    agent = f"---\nstatus: active\nverified:\n  - {{ by: vault-gardener/claude-opus-5-5, at: {past} }}\nstale_after: {past}\n---\n"
    assert provenance(human, TODAY) | {"verified": None} == {
        "verified": None, "stale_after": future, "state": "human", "due": False, "expired": False}
    assert provenance(agent, TODAY)["state"] == "machine"
    assert provenance(agent, TODAY)["due"] is True
    assert provenance("---\nstatus: active\n---\n", TODAY)["due"] is True
    # Completed projects are reference material and never fall due.
    assert provenance("---\nstatus: completed\n---\n", TODAY)["due"] is False


def test_artefact_links_labels_and_dedupes():
    content = ("See [PROJ-9360](https://example.atlassian.net/browse/PROJ-9360) and PROJ-9360 again, "
               "plus PROJ-1 bare, [doc](https://docs.google.com/document/d/abc/edit), "
               "https://github.com/acme/app/pull/199.")
    links = artefact_links(content)
    kinds = [link["kind"] for link in links]
    assert kinds.count("Jira") == 2
    assert {"Google Doc", "GitHub"} <= set(kinds)
    assert any(link["label"] == "PROJ-1" and link["url"].endswith("/browse/PROJ-1") for link in links)
    assert all(not link["url"].endswith(".") for link in links)


def test_project_brief_sections_and_recent_files(tmp_path):
    _readme(tmp_path, "demo", "---\ntitle: Demo\nstatus: active\nlast_updated: 2026-11-01\n---\n\n"
            "## Overview\n\nFirst para.\n\nSecond para.\n\n## Current state\n\n- Shipped it\n\n## Links\n")
    (tmp_path / "projects" / "demo" / "notes.md").write_text("x")
    brief = project_brief(tmp_path, "demo")
    assert brief["title"] == "Demo"
    assert brief["overview"] == "First para."
    assert brief["current_state"] == "- Shipped it"
    assert {f["name"] for f in brief["recent_files"]} == {"README.md", "notes.md"}
    assert brief["recent_files"][0]["path"].startswith("projects/demo/")


@pytest.mark.parametrize("slug", ["../etc", "demo/../../x", "Demo", "", "a_b"])
def test_project_brief_rejects_bad_slugs(tmp_path, slug):
    with pytest.raises(ValueError):
        project_brief(tmp_path, slug)


def test_review_status_change_only_touches_frontmatter(tmp_path):
    body = "\n# Demo\n\nstatus: active is body text, not a key\n"
    readme = _readme(tmp_path, "demo", f"---\ntitle: Demo\nstatus: active\nlast_updated: 2026-01-01\nstale_after: 2026-02-01\n---\n{body}")
    brief = review_project(tmp_path, "demo", "status", "completed", now=NOW)
    text = readme.read_text()
    assert brief["status"] == "completed"
    assert "status: completed" in text and f"last_updated: {TODAY}" in text
    assert "stale_after" not in text.split("---")[1]
    assert text.endswith(body)
    with pytest.raises(ValueError):
        review_project(tmp_path, "demo", "status", "deleted", now=NOW)


def test_review_confirm_adds_newest_human_entry_once(tmp_path):
    readme = _readme(tmp_path, "demo", "---\ntitle: Demo\nstatus: paused\nverified:\n"
                     "  - { by: vault-gardener/claude-opus-5-5, at: 2026-01-01 }\nowner: Sam\n---\n\n# Demo\n")
    review_project(tmp_path, "demo", "confirm", now=NOW, reviewer="human:sam-example")
    brief = review_project(tmp_path, "demo", "confirm", now=NOW, reviewer="human:sam-example")
    prov = brief["provenance"]
    assert [entry["by"] for entry in prov["verified"]] == ["human:sam-example", "vault-gardener/claude-opus-5-5"]
    assert prov["stale_after"] == (NOW + timedelta(days=90)).date().isoformat()
    assert prov["state"] == "human" and prov["due"] is False
    assert "owner: Sam" in readme.read_text()


def test_review_confirm_creates_block_and_reviews_plain_markdown(tmp_path):
    readme = _readme(tmp_path, "demo", "---\ntitle: Demo\nstatus: active\n---\n")
    review_project(tmp_path, "demo", "confirm", now=NOW)
    text = readme.read_text()
    assert f"verified:\n  - {{ by: human:user, at: {TODAY} }}" in text
    assert f"stale_after: {(NOW + timedelta(days=30)).date().isoformat()}" in text
    _readme(tmp_path, "bare", "# No frontmatter\n")
    assert review_project(tmp_path, "bare", "confirm", now=NOW)["provenance"]["state"] == "human"
    with pytest.raises(ValueError):
        review_project(tmp_path, "demo", "delete", now=NOW)


def test_build_pulse_lists_board_items_per_project(tmp_path):
    _readme(tmp_path, "demo", "---\nstatus: active\n---\n")
    payload = build_pulse(
        tmp_path, activity_entries=[], handled={}, board_active=1, board_later=0,
        health={"ok": True, "degraded": []},
        active_project_items=[{"id": "item-1", "title": "Reply to Phil", "project_ref": "projects/demo"}],
    )
    signal = payload["vault"]["project_signals"][0]
    assert signal["active_board_items"] == 1
    assert signal["board_items"] == [{"id": "item-1", "title": "Reply to Phil"}]
    assert signal["verification_due"] is True and signal["provenance"] == "unverified"


def _pulse_functions(*names):
    import re as _re
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "pulse.html").read_text()
    found = [_re.search(rf"        function {name}\(.*?\n        }}\n", html, _re.S) for name in names]
    assert all(found), names
    return "".join(match.group(0) for match in found)


def test_review_queue_orders_board_then_drift_then_unverified():
    import json, shutil, subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    sample = [
        {"name": "fresh-unverified", "age_days": 1, "verification_due": True, "provenance": "unverified"},
        {"name": "old-drift", "age_days": 90, "stale": True},
        {"name": "new-drift", "age_days": 40, "stale": True, "verification_due": True, "provenance": "unverified"},
        {"name": "board", "age_days": 5, "active_board_items": 2},
        {"name": "fine", "age_days": 2},
        {"name": "older-unverified", "age_days": 20, "verification_due": True, "provenance": "machine"},
    ]
    js = (_pulse_functions("reviewReason", "reviewQueue")
          + f"const nodes = {json.dumps(sample)};"
          "process.stdout.write(JSON.stringify([reviewQueue(), nodes.map(reviewReason)]));")
    queue, reasons = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert queue == ["board", "old-drift", "new-drift", "fresh-unverified", "older-unverified"]
    assert reasons[2] == "drifting 40d · never verified"
    assert reasons[5] == "verification expired"


def test_full_screen_toggle_links_back_to_pulse_before_any_selection():
    import json, re, shutil, subprocess
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "pulse.html").read_text()
    full_block = re.search(r"        if \(FULL\) \{\n(.*?)\n        \}\n", html, re.S).group(1)
    assert "full.href = fullToggleHref(true, pendingFocus);" in full_block
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    js = (_pulse_functions("fullToggleHref")
          + "process.stdout.write(JSON.stringify([fullToggleHref(true, null), fullToggleHref(true, 'a b'),"
          " fullToggleHref(false, null), fullToggleHref(false, 'x')]));")
    out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out == ["/pulse", "/pulse?focus=a%20b", "/constellation", "/constellation?focus=x"]


def test_drawer_resolves_relative_links_against_selected_source(tmp_path):
    _readme(tmp_path, "demo", "## Overview\nSee [notes](notes.md) and [missing](gone.md).")
    (tmp_path / "projects/demo/notes.md").write_text("Notes")
    assert project_brief(tmp_path, "demo")["linked_paths"] == ["projects/demo/notes.md"]


def test_scan_vault_lists_project_pages_only(tmp_path):
    _readme(tmp_path, "agentx", "---\ntitle: AgentX\n---\n")
    (tmp_path / "projects" / "agentx" / "notes.md").write_text("# AgentX notes\n")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "standalone.md").write_text("[[agentx]]\n")
    vault = scan_vault(tmp_path)
    assert "entities" not in vault
    signals = {s["name"]: s for s in vault["project_signals"]}
    assert [page["path"] for page in signals["agentx"]["pages"]] == ["projects/agentx/notes.md"]
    assert signals["agentx"]["pages"][0]["title"] == "AgentX notes"


def test_detail_panel_does_not_carry_the_chip_attribute():
    # The drawer's click handler routes any `[data-project]` ancestor to selectProject,
    # so the panel itself carrying it swallowed every review and nav click.
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "pulse.html").read_text()
    assert "panel.dataset.project" not in html
