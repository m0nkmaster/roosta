import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from roosta import app, document_editor as editor


RAW = b"\xef\xbb\xbf---\r\ntitle: 'Minutes' # keep\r\ntags: [one, two]\r\n---\r\n# Notes\nBody  "


@pytest.fixture
def doc(tmp_path, monkeypatch):
    monkeypatch.setattr(app.paths, 'WORKSPACE', tmp_path)
    path = tmp_path / 'notes.md'
    path.write_bytes(RAW)
    return path


@pytest.fixture
def client():
    return TestClient(app.app, base_url='http://localhost', client=('127.0.0.1', 1234))


API = '/api/workspace/document-source'


def put(client, path, revision, content=b'Updated', **extra):
    return client.put(API, params={'path': path}, content=content, headers={
        'Content-Type': 'text/plain', 'If-Match': f'"{revision}"', **extra})


def test_raw_round_trip_and_permissions(doc, client):
    doc.chmod(0o640)
    first = client.get(API, params={'path': doc.name})
    assert first.status_code == 200 and first.headers['cache-control'] == 'no-store'
    assert first.json()['content'].encode() == RAW
    revision = first.json()['revision']
    changed = RAW.replace(b'Body', b'New body')
    assert put(client, doc.name, revision, changed).is_success
    assert doc.read_bytes() == changed and doc.stat().st_mode & 0o777 == 0o640
    assert put(client, doc.name, revision).status_code == 409


@pytest.mark.parametrize('name', ['../notes.md', '/tmp/notes.md', 'private/notes.md', '.roosta/doc.md',
                                  'code/notes.md', 'note.txt', 'link.md', 'folder/notes.md', 'hard.md'])
def test_path_policy_for_read_and_save(tmp_path, name, client, monkeypatch):
    root = tmp_path / 'vault'
    root.mkdir()
    (tmp_path / 'notes.md').write_bytes(RAW)
    (root / 'link.md').symlink_to(tmp_path / 'notes.md')
    (root / 'folder').symlink_to(tmp_path, target_is_directory=True)
    os.link(tmp_path / 'notes.md', root / 'hard.md')
    monkeypatch.setattr(app.paths, 'WORKSPACE', root)
    for response in (client.get(API, params={'path': name}), put(client, name, 'a'*64)):
        assert response.status_code in (400, 403), response.text
    assert (tmp_path / 'notes.md').read_bytes() == RAW


def test_unavailable_or_stale(doc, client):
    rev = client.get(API, params={'path': doc.name}).json()['revision']
    doc.write_bytes(b'external')
    assert put(client, doc.name, rev).status_code == 409 and doc.read_bytes() == b'external'
    doc.chmod(0o400)
    assert put(client, doc.name, rev).status_code == 403
    assert client.get(API, params={'path': doc.name}).status_code == 403
    doc.unlink()
    assert put(client, doc.name, rev).status_code == 409
    assert client.get(API, params={'path': doc.name}).status_code == 404
    assert not doc.exists()


def test_local_request_and_input_bounds(doc, client):
    params = {'path': doc.name}
    rev = client.get(API, params=params).json()['revision']
    assert put(client, doc.name, rev, Origin='https://other.example').status_code == 403
    assert put(client, doc.name, rev, **{'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert put(TestClient(app.app, base_url='http://localhost'), doc.name, rev).status_code == 403
    for invalid in ('', 'x'*65, rev.upper(), '*'):
        assert put(client, doc.name, invalid).status_code == 400
    assert put(client, doc.name, rev, **{'Content-Type': 'application/json'}).status_code == 415
    assert put(client, doc.name, rev, b'\xff').status_code == 415
    assert put(client, doc.name, rev, b'x'*(editor.MAX_DOCUMENT_BYTES+1)).status_code == 413
    assert doc.read_bytes() == RAW


def test_simultaneous_saves(doc):
    revision = editor.edit_document(doc.parent, doc.name)['revision']

    def save(content):
        try:
            editor.edit_document(doc.parent, doc.name, revision, content)
        except editor.EditError as error:
            return error.status
        return content

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(save, [b'first', b'second']))
    assert sorted(map(str, outcomes)) == sorted(map(str, [409, doc.read_bytes()]))
    assert not list(doc.parent.glob('.roosta-edit-*'))


@pytest.mark.parametrize('event', ['modify', 'delete', 'link', 'move-directory', 'disk-error'])
def test_changes_during_staging(tmp_path, monkeypatch, event):
    folder = tmp_path / 'notes'
    folder.mkdir()
    target = folder / 'a.md'
    target.write_bytes(RAW)
    other = tmp_path / 'outside'
    other.mkdir()
    (other / target.name).write_bytes(b'outside')
    rev = editor.edit_document(tmp_path, 'notes/a.md')['revision']

    def race(fd):
        if event == 'modify':
            target.write_bytes(b'newer')
        elif event == 'delete':
            target.unlink()
        elif event == 'link':
            target.unlink()
            target.symlink_to(other / target.name)
        elif event == 'move-directory':
            folder.rename(tmp_path / 'moved')
            folder.symlink_to(other, target_is_directory=True)
        else:
            raise PermissionError

    monkeypatch.setattr(os, 'fsync', race)
    with pytest.raises(editor.EditError) as caught:
        editor.edit_document(tmp_path, 'notes/a.md', rev, b'draft')
    assert caught.value.status in (403, 409)
    assert (other / target.name).read_bytes() == b'outside'
    assert not list(tmp_path.rglob('.roosta-edit-*'))
    if event == 'modify':
        assert target.read_bytes() == b'newer'
    elif event == 'delete':
        assert not target.exists()
    elif event == 'disk-error':
        assert target.read_bytes() == RAW


@pytest.mark.parametrize('race', ['overwrite', 'rename', 'delete', 'symlink', 'directory'])
def test_change_at_atomic_exchange(tmp_path, monkeypatch, race):
    folder = tmp_path / 'docs'
    folder.mkdir()
    target = folder / 'a.md'
    target.write_bytes(RAW)
    other = tmp_path / 'other.md'
    other.write_bytes(b'outside')
    rev = editor.edit_document(tmp_path, 'docs/a.md')['revision']
    exchange = editor.exchange

    def race_once(parent, temporary, name):
        monkeypatch.setattr(editor, 'exchange', exchange)
        if race == 'overwrite':
            target.write_bytes(b'last writer')
        elif race == 'rename':
            other.replace(target)
        elif race == 'delete':
            target.unlink()
        elif race == 'symlink':
            target.unlink()
            target.symlink_to(other)
        else:
            folder.rename(tmp_path / 'moved')
            folder.mkdir()
        exchange(parent, temporary, name)

    monkeypatch.setattr(editor, 'exchange', race_once)
    with pytest.raises(editor.EditError) as caught:
        editor.edit_document(tmp_path, 'docs/a.md', rev, b'local')
    assert caught.value.status == 409
    if race == 'overwrite':
        assert target.read_bytes() == b'last writer'
    elif race == 'rename':
        assert target.read_bytes() == b'outside'
    elif race == 'delete':
        assert not target.exists()
    elif race == 'symlink':
        assert target.is_symlink() and other.read_bytes() == b'outside'
    else:
        assert not target.exists() and (tmp_path / 'moved/a.md').read_bytes() == RAW
    assert not list(tmp_path.rglob('.roosta-edit-*'))


def test_edit_source_and_draft_preview():
    import subprocess

    script = (app.paths.STATIC_DIR / 'document-editor.js').read_text()
    subprocess.run(['node', '-e', script + r"""
const assert=require('node:assert/strict');
const front='\uFEFF---\r\ntitle: Test\r\n---\r\n';
for(const [before,after,expected] of [
  ['A\r\nB\nC\rD','A\nC\nD','A\r\nC\rD'],
  [front+'A\nB\rC',front.replaceAll('\r\n','\n')+'A\nC',front+'A\nC'],
  ['A\r\nB\nC\rD','A\nadded\nB\nC\nD','A\r\nadded\r\nB\nC\rD'],
  ['A\r\nB\nC\rD','A\nchanged\nC\nD','A\r\nchanged\nC\rD'],
]) assert.equal(editedSource(before,after),expected);

const parts=new Map();
const element=()=>({setAttribute(){},focus(){},replaceChildren(){},prepend(el){this.metadata=el;}});
const host={classList:{add(){}},querySelector(key){
  if(!parts.has(key)) parts.set(key,element());
  return parts.get(key);
}};
const window={addEventListener(){}}, document={createElement:element,querySelector:key=>host.querySelector(key)};
const raw=front+'A\nB\rC',saved=[];
const fetch=async(_,options)=>{
  if(options.method==='PUT') saved.push(options.body);
  return {ok:true,json:async()=>({content:raw,revision:'revision'})};
};
(async()=>{
  const rendered=[];
  const editor=documentEditor(host,element(),body=>{rendered.push(body);return '<p>Markdown</p>';},()=>{});
  editor.setPath('Notes.md');await parts.get('[data-edit]').onclick();
  const field=parts.get('textarea');
  field.value=raw.replace(/\r\n?/g,'\n').replace('A\nB\nC','A\nC');
  field.oninput();parts.get('[data-preview-draft]').onclick();
  assert.equal(rendered.at(-1),'A\nC'); // YAML never reaches the heading parser.
  assert.match(parts.get('article').metadata.textContent,/title: Test/);
  parts.get('[data-source]').onclick();
  assert.equal(field.value,front.replaceAll('\r\n','\n')+'A\nC');
  await parts.get('[data-save]').onclick();assert.deepEqual(saved,[front+'A\nC']);
  for(const text of ['---\nA paragraph\n---\nNext','---\ntitle: unfinished']){
    renderDraftPreview(element(),text,body=>{assert.equal(body,text);return '';});
  }
  const malformed=element();
  renderDraftPreview(malformed,'---\ntitle: [broken\n---\nBody',body=>{assert.equal(body,'Body');return '';});
  assert.match(malformed.metadata.textContent,/title: \[broken/);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""], check=True)
