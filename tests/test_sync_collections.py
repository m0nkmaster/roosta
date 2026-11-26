"""The gardener's collection sync only adds members its index's frontmatter asks for."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "src/roosta/skills/workspace-gardener/sync-collections.py"


def put(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    return file


def run(root, *args):
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=root,
                          capture_output=True, text=True, check=True)
    return done.stdout


def seed(root):
    put(root, "WORKSPACE.md", "# Workspace\n\n- [AI](collections/ai.md)\n- [Incidents](collections/incidents.md)\n"
        "- [Projects](collections/projects.md)\n- [Plain](collections/plain.md)\n")
    put(root, "collections/ai.md", "---\ntitle: AI\ncollect_tag: ai\nexclude: [../notes/skip.md]\n---\n\n"
        "# AI\n\nMy intro.\n\n- [Curated, untagged](../notes/curated.md)\n- [Gone](../notes/gone.md)\n")
    put(root, "collections/incidents.md", "---\ncollect_tag: incidents\ncollect_order: newest-first\n---\n\n"
        "- [Index](../incidents/README.md)\n- [Old](../incidents/2026-01-01-old.md)\n")
    put(root, "collections/projects.md", "---\ncollect_path: projects/*/README.md\ncollect_order: alphabetical\n---\n\n"
        "- [Alpha](../projects/alpha/README.md)\n- [Zulu](../projects/zulu/README.md)\n")
    put(root, "collections/plain.md", "# Plain\n\n- [Curated](../notes/curated.md)\n")
    put(root, "notes/curated.md", "# Curated\n")
    put(root, "notes/tagged.md", "---\ntitle: Tagged note\ntags: [ai, other]\n---\n")
    put(root, "notes/block.md", "---\ntags:\n  - ai\n---\n# Block list\n")
    put(root, "notes/skip.md", "---\ntags: [ai]\n---\n")
    put(root, "notes/near-miss.md", "---\ntags: [ai-governance]\n---\n")
    put(root, "private/secret.md", "---\ntags: [ai]\n---\n")
    put(root, ".hidden/x.md", "---\ntags: [ai]\n---\n")
    put(root, "incidents/README.md", "# Incidents\n")
    put(root, "incidents/2026-01-01-old.md", "---\ntags: [incidents]\n---\n# Old\n")
    put(root, "incidents/2026-03-01-new.md", "---\ntags: [incidents]\n---\n# New\n")
    for name in ("alpha", "mike", "zulu"):
        put(root, f"projects/{name}/README.md", f"# {name.title()}\n")


def test_dry_run_reports_without_writing(tmp_path):
    seed(tmp_path)
    before = (tmp_path / "collections/ai.md").read_text()
    report = json.loads(run(tmp_path, "--json"))
    assert report["written"] is False
    assert (tmp_path / "collections/ai.md").read_text() == before
    ai = next(r for r in report["collections"] if r["index"] == "collections/ai.md")
    assert ai["added"] == ["- [Block list](../notes/block.md)", "- [Tagged note](../notes/tagged.md)"]
    assert ai["missing"] == ["- [Gone](../notes/gone.md)"]


def test_write_adds_only_and_respects_order_and_exclusions(tmp_path):
    seed(tmp_path)
    run(tmp_path, "--write")
    ai = (tmp_path / "collections/ai.md").read_text()
    assert "My intro." in ai and "[Curated, untagged]" in ai and "[Gone]" in ai
    assert "(../notes/skip.md)" not in ai and "near-miss" not in ai and "secret" not in ai and ".hidden" not in ai
    incidents = (tmp_path / "collections/incidents.md").read_text().splitlines()
    members = [line for line in incidents if line.startswith("- [")]
    assert members == ["- [Index](../incidents/README.md)", "- [New](../incidents/2026-03-01-new.md)",
                       "- [Old](../incidents/2026-01-01-old.md)"]
    projects = [line for line in (tmp_path / "collections/projects.md").read_text().splitlines()
                if line.startswith("- [")]
    assert [p.split("]")[0][3:] for p in projects] == ["Alpha", "Mike", "Zulu"]
    assert (tmp_path / "collections/plain.md").read_text() == "# Plain\n\n- [Curated](../notes/curated.md)\n"


def test_second_run_is_idempotent(tmp_path):
    seed(tmp_path)
    run(tmp_path, "--write")
    snapshot = {p: p.read_text() for p in (tmp_path / "collections").iterdir()}
    run(tmp_path, "--write")
    assert {p: p.read_text() for p in (tmp_path / "collections").iterdir()} == snapshot


def test_path_glob_star_stays_in_one_folder(tmp_path):
    seed(tmp_path)
    put(tmp_path, "projects/mike/reports/README.md", "# Nested\n")
    run(tmp_path, "--write")
    assert "reports" not in (tmp_path / "collections/projects.md").read_text()
