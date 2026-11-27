import asyncio
import json

from roosta import app as appmod
from roosta import pages, paths


def make_page(root, name, html="<title>Reading list</title><h1>Hi</h1>"):
    page = root / name
    page.mkdir(parents=True)
    (page / "index.html").write_text(html)
    return page


def test_custom_pages_are_listed_and_served_inside_their_folder(tmp_path, monkeypatch):
    pages_dir = tmp_path / "pages"
    page = make_page(pages_dir, "reading-list")
    (page / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    make_page(pages_dir, "Bad Name")
    monkeypatch.setattr(paths, "PAGES_DIR", pages_dir)

    assert pages.custom_pages() == [{"name": "reading-list", "title": "Reading list", "url": "/pages/reading-list/"}]
    ok = asyncio.run(appmod.custom_page("reading-list", ""))
    assert str(ok.path).endswith("reading-list/index.html")
    assert asyncio.run(appmod.custom_page("reading-list", "app.js")).media_type == "text/javascript"
    for bad in ("../../secret.txt", "../reading-list/index.html", "missing.js"):
        assert asyncio.run(appmod.custom_page("reading-list", bad)).status_code == 404
    assert asyncio.run(appmod.custom_page("..", "")).status_code == 404


def test_workspace_page_replaces_the_shipped_one(tmp_path):
    assert pages.page_file("pulse", tmp_path).name == "pulse.html"
    make_page(tmp_path, "pulse", "<title>My pulse</title>")
    assert pages.page_file("pulse", tmp_path) == tmp_path / "pulse" / "index.html"
    # It keeps the shipped nav link rather than adding a second one.
    assert pages.custom_pages(tmp_path) == []


def test_workspace_files_returns_frontmatter_without_bodies(tmp_path):
    readme = tmp_path / "projects" / "atlas" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("---\ntitle: Atlas\nstatus: active\n---\n# Atlas\n\nSecret body.\n")
    (tmp_path / ".roosta").mkdir()
    (tmp_path / ".roosta" / "x.md").write_text("hidden")
    files = pages.workspace_files("**/*.md", tmp_path)
    assert [f["path"] for f in files] == ["projects/atlas/README.md"]
    assert files[0]["frontmatter"] == {"title": "Atlas", "status": "active"}
    assert "Secret body" not in json.dumps(files)
    for bad in ("", "/etc/*.md", "../*.md"):
        try:
            pages.workspace_files(bad, tmp_path)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_page_data_serves_only_json_a_skill_wrote(tmp_path, monkeypatch):
    data = tmp_path / "people"
    data.mkdir()
    (data / "roster.json").write_text('{"people": []}')
    (data / "notes.txt").write_text("x")
    monkeypatch.setattr(pages, "PAGE_DATA_DIR", tmp_path)
    assert str(asyncio.run(appmod.api_page_data("people", "roster.json")).path).endswith("roster.json")
    assert asyncio.run(appmod.api_page_data("people", "notes.txt")).status_code == 404
    assert asyncio.run(appmod.api_page_data("people", "../people/roster.json")).status_code == 404
