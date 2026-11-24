"""Workspace navigation and explicit file context, using a temporary vault only."""

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from roosta import chat_items
from roosta import app as appmod
from roosta import workspace as wmod


def put(root, path, content='# A document\nSome context.'):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_catalogue_searches_documents_without_hidden_or_runtime_content(tmp_path):
    put(tmp_path, 'projects/example/README.md', '# Example project\nSearchable details.')
    put(tmp_path, 'notes/brief.md')
    for path in ['private/secret.md', '.git/history.md', '.roosta/state/test.md',
                 'code/repo.md', 'notes/.secret.md', 'cache/cached.md']:
        put(tmp_path, path)
    put(tmp_path, 'notes/plain.txt')
    put(tmp_path, 'notes/alias.md').unlink()
    (tmp_path / 'notes/alias.md').symlink_to(tmp_path / 'private/secret.md')
    (tmp_path / 'linked').symlink_to(tmp_path / 'projects', target_is_directory=True)
    put(tmp_path, 'bad.md').write_bytes(b'\xff')
    put(tmp_path, 'big.md', 'x' * (wmod.MAX_DOCUMENT_BYTES + 1))

    result = wmod.build_catalogue(tmp_path)
    assert {file['path'] for file in result['files']} == {'projects/example/README.md', 'notes/brief.md'}
    example = next(file for file in result['files'] if file['path'].endswith('README.md'))
    assert example['title'] == 'Example project'
    assert 'Searchable details.' in example['text']
    assert example['size'] > 0 and example['modified']
    assert result['skipped'] == 2 and result['indexed_at']


@pytest.mark.parametrize('path', ['../outside.md', '/outside.md', '.hidden.md',
                                  'private/note.md', 'Private/note.md', 'dashboard/note.md', 'code/note.md',
                                  'notes/../note.md', 'notes\\note.md', 'notes/note.txt', None])
def test_context_rejects_paths_outside_visible_markdown(tmp_path, path):
    with pytest.raises((ValueError, OSError)):
        wmod.context_documents(tmp_path, [path])


def test_context_checks_symlink_targets_and_deduplicates(tmp_path):
    put(tmp_path, 'notes/note.md', '# Note\nFull body with metadata.')
    put(tmp_path, 'private/secret.md')
    (tmp_path / 'escape.md').symlink_to(tmp_path.parent / 'outside.md')
    (tmp_path / 'secret.md').symlink_to(tmp_path / 'private/secret.md')
    (tmp_path / 'alias.md').symlink_to(tmp_path / 'notes/note.md')
    for path in ['escape.md', 'secret.md']:
        with pytest.raises(ValueError):
            wmod.context_documents(tmp_path, [path])
    assert wmod.context_documents(tmp_path, ['notes/note.md', 'alias.md']) == [
        {'path': 'notes/note.md', 'content': '# Note\nFull body with metadata.'}]


def test_context_limits_and_deleted_files(tmp_path):
    put(tmp_path, 'a.md', 'a' * (wmod.MAX_CONTEXT_BYTES // 2 + 1))
    put(tmp_path, 'b.md', 'b' * (wmod.MAX_CONTEXT_BYTES // 2))
    with pytest.raises(ValueError, match='192 KB'):
        wmod.context_documents(tmp_path, ['a.md', 'b.md'])
    for invalid in ['a.md', ['a.md'] * 9, None]:
        with pytest.raises(ValueError, match='up to 8'):
            wmod.context_documents(tmp_path, invalid)
    with pytest.raises(FileNotFoundError):
        wmod.context_documents(tmp_path, ['missing.md'])


def test_catalogue_api_does_not_cache_contents(tmp_path, monkeypatch):
    put(tmp_path, 'notes/test.md', '# Local document\nSearch me.')
    monkeypatch.setattr(appmod.paths, 'WORKSPACE', tmp_path)
    response = asyncio.run(appmod.api_workspace())
    assert response.headers['cache-control'] == 'no-store'
    assert json.loads(response.body)['files'][0]['path'] == 'notes/test.md'


def test_chat_receives_full_context_and_rejects_invalid_files(tmp_path, monkeypatch):
    body = '---\ntitle: Context\n---\n# Full contents\nDo not summarise this away.'
    put(tmp_path, 'notes/context.md', body)
    seen = []

    def start_turn(item_id, item, message):
        seen.append((item_id, item, message))
        return SimpleNamespace(queued=True, position=1)

    monkeypatch.setattr(appmod.paths, 'WORKSPACE', tmp_path)
    monkeypatch.setattr(appmod, 'chat_router', SimpleNamespace(start_turn=start_turn))
    monkeypatch.setattr(appmod, 'setup_item', lambda *_: None)  # AI is connected
    request = {'item_id': 'chat:0123456789ab', 'message': 'Compare this', 'context_paths': ['notes/context.md']}
    response = asyncio.run(appmod.api_board_chat(request))
    assert response.status_code == 202
    assert seen[0][1]['context_documents'] == [{'path': 'notes/context.md', 'content': body}]
    assert seen[0][2] == 'Compare this'
    assert 'context_documents' not in chat_items.GENERAL_CHAT_ITEM
    for paths in [['private/secret.md'], ['missing.md'], 'notes/context.md', ['notes/context.md'] * 9]:
        response = asyncio.run(appmod.api_board_chat({**request, 'context_paths': paths}))
        assert response.status_code == 400
    assert len(seen) == 1
    response = asyncio.run(appmod.api_board_chat({**request, 'context_paths': []}))
    assert response.status_code == 202 and seen[-1][1]['context_documents'] == []


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for JavaScript check')
def test_search_ranking_literal_terms_and_safe_highlighting():
    source = (Path(__file__).resolve().parent.parent / 'src/roosta/static/workspace.js').read_text()
    helpers = source[:source.index('const params=')]
    check = r'''
const assert=require('node:assert/strict');
const files=[
 {path:'notes/a.md',title:'Alpha',text:'Review the launch plan for C++.',modified:'2026-11-03'},
 {path:'projects/b.md',title:'Launch plan',text:'An alpha release. C++',modified:'2026-11-01'},
 {path:'notes/c.md',title:'Other',text:'No match.',modified:'2026-11-06'}
].map(file=>({...file,search:[file.title,file.path,file.text].join('\n').toLowerCase()}));
assert.deepEqual(searchTerms('ALPHA "launch plan" C++'),['alpha','launch plan','c++']);
assert.deepEqual(searchFiles(files,'"launch plan" alpha','').map(f=>f.path),['notes/a.md','projects/b.md']);
assert.deepEqual(searchFiles(files,'"launch plan"','').map(f=>f.path),['projects/b.md','notes/a.md']);
assert.deepEqual(searchFiles(files,'C++',new Set(['notes/a.md','notes/c.md'])).map(f=>f.path),['notes/a.md']);
assert.equal(searchFiles(files,'[a-z]+','').length,0);
assert.equal(highlightText('<script>alpha & alpha</script>',['alpha']), '&lt;script&gt;<mark>alpha</mark> &amp; <mark>alpha</mark>&lt;/script&gt;');
assert.equal(highlightText('banana',['ana','banana']),'<mark>banana</mark>');
assert.equal(searchFiles(files,'missing','').length,0);
assert.equal(searchFiles(files,'',new Set()).length,0);
'''
    result = subprocess.run(['node', '-e', helpers + check], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_workspace_linked_from_every_page():
    static = Path(__file__).resolve().parent.parent / 'src/roosta/static'
    # Every page renders the shared nav from nav-count.js.
    assert "['/workspace', 'Workspace']" in (static / 'nav-count.js').read_text()
    for name in ['assistant', 'index', 'pulse', 'document', 'workspace']:
        assert '/static/nav-count.js' in (static / f'{name}.html').read_text()
    assert "'/workspace'" in (static / 'document.html').read_text()


def test_meaningful_collections_use_titles_status_and_shared_tags(tmp_path):
    put(tmp_path, 'projects/service-a/README.md', '''---
title: Atlas
status: blocked
tags: [sdk, ai, ai, unique-tag]
people: [Alex Example]
---
# Atlas

## Overview

A **gradual rollout** of the [new SDK](https://example.test).

## Key decisions

Keep existing clients supported.
''')
    put(tmp_path, 'projects/service-a/plan.md', '# Plan\n\nRoll out to a small cohort.')
    put(tmp_path, 'notes/sdk-notes.md', '---\ntitle: SDK lessons\ntags:\n  - sdk\n---\n# SDK lessons\n\nNotes from the pilot.')
    put(tmp_path, 'projects/completed/README.md', '---\ntitle: Previous project\nstatus: completed\n---\n# Previous project')
    put(tmp_path, 'notes/no-metadata.md', '# A useful reference\n\nNotes that mention Atlas, with no declared tags.')
    result = wmod.build_catalogue(tmp_path)
    collections = {collection['id']: collection for collection in result['collections']}
    project = collections['project:service-a']
    assert project['title'] == 'Atlas' and project['status'] == 'blocked'
    assert project['summary'] == 'A gradual rollout of the new SDK.'
    assert set(project['paths']) == {'projects/service-a/README.md', 'projects/service-a/plan.md'}
    assert collections['topic:sdk']['title'] == 'SDK'
    assert set(collections['topic:sdk']['paths']) == set(project['paths']) | {'notes/sdk-notes.md'}
    assert 'topic:unique-tag' not in collections and 'topic:ai' not in collections
    assert 'projects/service-a/README.md' in collections['work:decisions']['paths']
    assert 'projects/service-a/plan.md' in collections['work:plans']['paths']
    plan = next(file for file in result['files'] if file['path'].endswith('/plan.md'))
    assert plan['title'] == 'Atlas — Plan' and plan['kind'] == 'Plan'
    assert plan['project'] == 'Atlas' and 'people' not in plan
    assert not any(c['group'] == 'people' for c in result['collections'])


def test_metadata_errors_do_not_break_navigation(tmp_path):
    put(tmp_path, 'notes/bad.md', '---\ntags: [unterminated\n---\n# Readable despite invalid metadata\n\nThe body is still available.')
    put(tmp_path, 'notes/unexpected.md', '---\ntitle: {nested: title}\ntags: [null, 42, {bad: value}]\npeople: invalid\nstatus: [active]\n---\n# Normal heading')
    result = wmod.build_catalogue(tmp_path)
    assert len(result['files']) == 2 and result['skipped'] == 0
    bad = next(file for file in result['files'] if file['path'].endswith('bad.md'))
    assert bad['title'] == 'Readable despite invalid metadata'
    assert bad['summary'] == 'The body is still available.'
    assert next(file for file in result['files'] if file['path'].endswith('unexpected.md'))['title'] == 'Normal heading'
    assert not any(collection['group'] == 'topics' for collection in result['collections'])
    assert wmod.document_summary('# Heading\n\n' + 'A word ' * 100, {}).endswith('…')


def test_vault_links_resolve_wikilinks_and_relative_markdown_links():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    static = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"
    helper = (static / "vault-markdown.js").read_text()
    paths = ["PRIORITIES.md", "projects/app-name/README.md", "projects/app-name/notes/plan.md",
             "projects/other/README.md"]
    source = ("[[app-name]] [[plan|the plan]] [[missing]] [p](notes/plan.md) "
              "[o](../other/README.md#x) [x](../../../etc.md) [w](https://e.com/a.md) [n](gone.md)")
    js = (f"{helper}\nprocess.stdout.write(wikiLinks({json.dumps(source)},"
          f"{json.dumps(paths)},'projects/app-name/README.md'));")
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout
    doc = "/document?path="
    assert f"[app-name]({doc}projects%2Fapp-name%2FREADME.md)" in out
    assert f"[the plan]({doc}projects%2Fapp-name%2Fnotes%2Fplan.md)" in out
    assert " missing " in out
    assert f"[p]({doc}projects%2Fapp-name%2Fnotes%2Fplan.md)" in out
    assert f"[o]({doc}projects%2Fother%2FREADME.md)" in out
    assert "[x](../../../etc.md)" in out
    assert "[w](https://e.com/a.md)" in out
    assert "[n](gone.md)" in out
    page = (static / "document.html").read_text()
    assert "wikiLinks(data.content,await vaultPaths(data.content),data.path)" in page
    assert "keepLinksInPage(article,params)" in page
