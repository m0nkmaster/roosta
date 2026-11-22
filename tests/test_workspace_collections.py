"""Curated navigation and review exercise the same disposable Markdown workspace."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from roosta import app as api
from roosta import pulse, workspace
from roosta.cli import copy_skeleton


def put(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    return file


CLIENT = "Clients/North Coast/Acme.md"
PROJECT = "projects/launch/README.md"
OTHER = "Partners/Acme.md"


def seed(root):
    old = (datetime.now(timezone.utc) - timedelta(days=60)).date()
    put(root, "WORKSPACE.md", "# Workspace\n- [Clients](Clients/README.md)\n- [Projects](projects/README.md)")
    put(root, "Clients/README.md", "# Clients\n\nActive engagements.\n\n"
        "- [Coast](<North Coast/Acme.md>)\n- [Partner](../Partners/Acme.md)\n- [Again](North%20Coast/Acme.md)\n")
    put(root, "projects/README.md", "# Projects\n- [Launch](launch/README.md)\n- [Partner](../Partners/Acme.md)")
    put(root, CLIENT, f"---\nstatus: active\nlast_updated: {old}\ntags: [delivery]\n"
        f"verified:  # source checks\n- by: process:check\n  at: {old}\nstale_after: {old}\n---\n"
        "# Coast account\n\nRenewal discussions.\n\n- [Brief](brief.md)\n\n## Delivery sequence\n\nPilot first.\n"
        "\n## Decisions\n\nRetain offline access.\n\n## Background\n\nUnrelated history.\n")
    put(root, "Clients/North Coast/brief.md", "# Reader notes")
    put(root, OTHER, "# Partner account")
    put(root, PROJECT, "---\nstatus: completed\ntags: [delivery]\n---\n# Launch")
    put(root, "topics/delivery.md", "# Delivery notes\n\nCommon shipping constraints.\n\n- [Partner](../Partners/Acme.md)")
    put(root, "Plans.md", "# Plans\n- [Delivery sequence](Clients/North%20Coast/Acme.md#delivery-sequence)")


def test_membership_is_ordered_visible_and_shared(tmp_path):
    seed(tmp_path)
    put(tmp_path, "private/secret.md", "secret")
    put(tmp_path, ".hidden/doc.md", "hidden")
    outside = put(tmp_path.parent, tmp_path.name + "-outside.md", "outside")
    (tmp_path / "Clients/link.md").symlink_to(outside)
    (tmp_path / "Clients/alias").symlink_to(tmp_path / "Partners", target_is_directory=True)
    with (tmp_path / "Clients/README.md").open("a") as f:
        for path in ["../private/secret.md", "../.hidden/doc.md", "link.md", "alias/Acme.md",
                     "../../" + outside.name, "missing.md", "https://host/doc.md", "//host/doc.md"]:
            f.write(f"- [Ignore]({path})\n")
        f.write("```md\n- [Example](North%20Coast/brief.md)\n```\n<!--\n- [Hidden](North%20Coast/brief.md)\n-->")
    data = workspace.build_catalogue(tmp_path)
    groups = [c for c in data["collections"] if c["group"] == "collections"]
    assert [(c["title"], c["paths"]) for c in groups] == [("Clients", [CLIENT, OTHER]), ("Projects", [PROJECT, OTHER])]
    signals = pulse.scan_vault(tmp_path)["project_signals"]
    assert [s["path"] for s in signals] == [CLIENT, OTHER, PROJECT]
    assert len({s["name"] for s in signals}) == 3
    assert signals[1]["collections"] == ["Clients", "Projects"]
    assert [p["path"] for p in signals[0]["pages"]] == ["Clients/North Coast/brief.md"]
    assert signals[-1]["name"] == "launch"


def test_cross_cutting_sections_and_topic_order(tmp_path):
    seed(tmp_path)
    sections = {c["id"]: c for c in workspace.build_catalogue(tmp_path)["collections"]}
    topic = sections["topic:delivery"]
    assert topic["paths"] == [OTHER, CLIENT, PROJECT]
    assert topic["summary"] == "Common shipping constraints."
    assert sections["work:plans"]["sections"] == {CLIENT: "## Delivery sequence\n\nPilot first."}
    assert sections["work:decisions"]["sections"] == {CLIENT: "## Decisions\n\nRetain offline access."}


def test_fallback_and_empty_index(tmp_path):
    put(tmp_path, "notes/incidental.md", "noise")
    put(tmp_path, "CONTEXT.md", "context")
    assert [s["path"] for s in pulse.scan_vault(tmp_path)["project_signals"]] == ["CONTEXT.md"]
    put(tmp_path, PROJECT, "# Launch")
    assert pulse.project_brief(tmp_path, "launch")["path"] == PROJECT
    assert not (tmp_path / "WORKSPACE.md").exists()
    put(tmp_path, "WORKSPACE.md", "# Nothing selected")
    assert pulse.scan_vault(tmp_path)["project_signals"] == []
    with pytest.raises(FileNotFoundError):
        pulse.review_project(tmp_path, "launch", "confirm")


def test_attention_and_review_use_selected_page_only(tmp_path, monkeypatch):
    seed(tmp_path)
    monkeypatch.setattr(api.paths, "WORKSPACE", tmp_path)
    monkeypatch.setattr(api.profile, "load", lambda: type("Profile", (), {"reviewer": "human:owner"})())
    star = pulse.scan_vault(tmp_path)["project_signals"][0]
    assert star["stale"] and star["expired"] and star["verification_due"] and star["age_days"] >= 60
    for path in ["WORKSPACE.md", "Clients/README.md", CLIENT, "Clients/North Coast/brief.md"]:
        with (tmp_path / path).open("a") as f:
            f.write("\n")
    assert pulse.scan_vault(tmp_path)["project_signals"][0]["last_activity"] == star["last_activity"]
    page = tmp_path / CLIENT
    body = page.read_bytes().partition(b"\n---\n")[2]
    response = asyncio.run(api.api_constellation_review(star["name"], {"action": "confirm"}))
    assert response.status_code == 200
    detail = json.loads(response.body)
    assert detail["path"] == CLIENT and detail["provenance"]["verified"][0]["by"] == "human:owner"
    assert page.read_bytes().endswith(body)
    fresh = pulse.scan_vault(tmp_path)["project_signals"][0]
    assert fresh["attention_basis"] == "verified" and fresh["age_days"] < 1
    assert not (fresh["stale"] or fresh["expired"] or fresh["verification_due"])
    assert pulse.review_project(tmp_path, star["name"], "status", "paused")["status"] == "paused"
    page.unlink()
    page.symlink_to(tmp_path / OTHER)
    assert asyncio.run(api.api_constellation_review(star["name"], {"action": "confirm"})).status_code == 404
    assert (tmp_path / OTHER).read_text() == "# Partner account"


def test_scaffold_and_adoption(tmp_path):
    tmp_path = tmp_path / "fresh"
    tmp_path.mkdir()
    skeleton = Path(workspace.__file__).parent / "skeleton"
    copy_skeleton(skeleton, tmp_path)
    assert [s["path"] for s in pulse.scan_vault(tmp_path)["project_signals"]] == ["PRIORITIES.md", "CONTEXT.md"]
    (tmp_path / "WORKSPACE.md").unlink()
    copy_skeleton(skeleton, tmp_path)
    assert not (tmp_path / "WORKSPACE.md").exists()


def test_review_preserves_flow_verification_and_exact_body(tmp_path):
    page = put(tmp_path, PROJECT, "")
    body = b"\r\n# Notes\r\nAn older line.\n"
    page.write_bytes(b"---\r\nstatus: active\r\nverified: [{by: process:review, at: 2020-01-02}]\r\n---" + body)
    result = pulse.review_project(tmp_path, "launch", "confirm")
    assert [entry["by"] for entry in result["provenance"]["verified"]] == ["human:user", "process:review"]
    assert page.read_bytes().split(b"\r\n---", 1)[1] == body
    page.write_text("---\nverified: [broken\n---\n# Notes")
    with pytest.raises(ValueError):
        pulse.review_project(tmp_path, "launch", "confirm")
    assert page.read_text().startswith("---\nverified: [broken")


def test_workspace_preview_revalidates_target(tmp_path, monkeypatch):
    monkeypatch.setattr(api.paths, "WORKSPACE", tmp_path)
    page = put(tmp_path, CLIENT, "# Client")
    assert asyncio.run(api.api_vault_document(CLIENT, visible=True)).status_code == 200
    page.unlink()
    page.symlink_to(put(tmp_path, "private/source.md", "Secret"))
    assert asyncio.run(api.api_vault_document(CLIENT, visible=True)).status_code == 400


def test_nested_relationships_and_fenced_examples(tmp_path):
    seed(tmp_path)
    with (tmp_path / CLIENT).open("a") as f:
        f.write("\n## Related\n| [Partner](../../Partners/Acme.md) | Shared renewal |\n")
    with (tmp_path / PROJECT).open("a") as f:
        f.write("\n## Plan\n\n```md\n## Decisions\nExample only.\n```\nShip on Tuesday.\n")
    data = pulse.scan_vault(tmp_path)
    signals = {s["path"]: s for s in data["project_signals"]}
    assert signals[CLIENT]["related"] == [signals[OTHER]["name"]]
    assert signals[OTHER]["related"] == [signals[CLIENT]["name"]]
    groups = {c["id"]: c for c in workspace.build_catalogue(tmp_path)["collections"]}
    assert "Example only." in groups["work:plans"]["sections"][PROJECT]
    assert PROJECT not in groups["work:decisions"]["paths"]


def test_symlinked_index_does_not_restore_unselected_projects(tmp_path):
    seed(tmp_path)
    (tmp_path / "WORKSPACE.md").unlink()
    (tmp_path / "WORKSPACE.md").symlink_to(tmp_path / "Clients/README.md")
    assert not pulse.scan_vault(tmp_path)["project_signals"]
    with pytest.raises(FileNotFoundError):
        pulse.project_brief(tmp_path, "launch")
