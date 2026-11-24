import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


spec = importlib.util.spec_from_file_location('release', Path(__file__).parents[1] / 'scripts/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in release.VERSION_FILES + ['desktop/INSTALL.txt']:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(release.ROOT / name, target)
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    return tmp_path


def test_prepare_updates_all_versions_and_generates_only_current_notes(project):
    previous = release.check()
    release.prepare('9.0.0', ['One useful change', 'Another change'])
    assert release.check('v9.0.0') == '9.0.0'
    notes = release.release_notes()
    assert '- One useful change\n- Another change' in notes
    assert f'## {previous}' not in notes and 'Install Roosta' in notes
    lock = json.loads((project / 'desktop/package-lock.json').read_text())
    assert lock['packages']['']['devDependencies']


@pytest.mark.parametrize('version,notes', [('0.0.1', ['x']), ('9.0.0-rc1', ['x']), ('9.0.0', []), ('9.0.0', ['x\n## 10.0.0'])])
def test_invalid_prepare_changes_nothing(project, version, notes):
    before = {p: (project / p).read_bytes() for p in release.VERSION_FILES}
    with pytest.raises(ValueError): release.prepare(version, notes)
    assert before == {p: (project / p).read_bytes() for p in release.VERSION_FILES}


@pytest.mark.parametrize('file', ['desktop/package.json', 'desktop/package-lock.json', 'src/roosta/CHANGELOG.md'])
def test_check_rejects_drift(project, file):
    target = project / file
    target.write_text(target.read_text().replace(release.check(), '9.0.0', 1))
    with pytest.raises(ValueError): release.check()


def test_ship_refuses_dirty_tree_before_tagging_or_pushing(project, monkeypatch):
    calls = []
    def run(*args):
        calls.append(args)
        return ' M unrelated.txt'
    monkeypatch.setattr(release, 'run', run)
    with pytest.raises(ValueError, match='Commit your changes'):
        release.ship(None, [])
    assert calls == [('git', 'status', '--porcelain')]


def test_ship_prepares_only_release_files_and_pushes_branch_and_tag_atomically(project, monkeypatch):
    calls = []
    def run(*args):
        calls.append(args)
        if args == ('git', 'branch', '--show-current'): return 'main'
        if args == ('git', 'rev-parse', 'HEAD'): return 'abc'
        if args[:3] == ('gh', 'run', 'list'): return json.dumps([{'headSha':'abc', 'databaseId':42, 'url':'https://ci.invalid/42'}])
        if args[:3] == ('gh', 'release', 'view'): return '{"isDraft":false,"url":"https://release.invalid"}'
        return ''
    monkeypatch.setattr(release, 'run', run)
    monkeypatch.setattr(release.subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 0))
    release.ship('9.0.0', ['Release automation'])
    assert ('gh', 'auth', 'status', '--hostname', 'github.com') in calls
    assert ('git', 'add', '--', *release.VERSION_FILES) in calls
    assert ('git', 'push', '--atomic', 'origin', 'main', 'refs/tags/v9.0.0') in calls
    assert release.check() == '9.0.0'


def test_ship_reports_a_published_release_even_when_a_job_fails(project, monkeypatch, capsys):
    def run(*args):
        if args == ('git', 'branch', '--show-current'): return 'main'
        if args == ('git', 'rev-parse', 'HEAD'): return 'abc'
        if args[:3] == ('gh', 'run', 'list'): return json.dumps([{'headSha':'abc', 'databaseId':42, 'url':'https://ci.invalid/42'}])
        if args[:3] == ('gh', 'release', 'view'): return '{"isDraft":false,"url":"https://release.invalid"}'
        return ''
    monkeypatch.setattr(release, 'run', run)
    monkeypatch.setattr(release.subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 1))
    release.ship(None, [])
    captured = capsys.readouterr()
    assert 'Published https://release.invalid' in captured.out
    assert 'missing assets' in captured.err


@pytest.fixture
def assets(project):
    directory = project / 'artifacts'
    directory.mkdir()
    version = release.check()
    for arch in ('arm64', 'x64'):
        name = f'Roosta-{version}-{arch}.dmg'
        (directory / name).write_bytes(arch.encode())
        (directory / (name + '.sha256')).write_text(f'{hashlib.sha256(arch.encode()).hexdigest()}  {name}\n')
    for name in (f'roosta-{version}-py3-none-any.whl', f'roosta-{version}.tar.gz'):
        (directory / name).write_bytes(b'package')
    return directory


def test_artifacts_require_arm64_and_matching_checksums_with_intel_optional(assets):
    assert len(release.artifacts(assets)) == 6
    dmg = next(assets.glob('*.dmg'))
    dmg.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='Checksum'): release.artifacts(assets)
    dmg.unlink()
    with pytest.raises(ValueError, match='arm64 DMG'): release.artifacts(assets)


def test_artifacts_accept_missing_intel_but_reject_a_partial_set(assets):
    version = release.check()
    for path in assets.glob('Roosta-*-x64.dmg*'): path.unlink()
    assert len(release.artifacts(assets)) == 4
    (assets / f'Roosta-{version}-x64.dmg').write_bytes(b'intel')
    with pytest.raises(ValueError, match='must be complete'): release.artifacts(assets)
    (assets / 'stray.txt').write_text('x')
    with pytest.raises(ValueError, match='arm64 DMG'): release.artifacts(assets)


def test_published_release_is_verified_never_overwritten(assets, monkeypatch):
    calls = []
    remote = [{'name':p.name, 'digest':'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()} for p in assets.iterdir()]
    def run(*args):
        calls.append(args)
        if args[:3] == ('gh', 'repo', 'view'): return 'owner/repo'
        if args[:2] == ('gh', 'api'):
            return json.dumps([[{'tag_name':'v'+release.check(), 'draft':False, 'assets':remote, 'html_url':'https://release.invalid'}]])
        pytest.fail('A published release must not be mutated')
    monkeypatch.setattr(release, 'run', run)
    release.publish(assets)
    remote.append({'name': 'later.dmg', 'digest': 'sha256:' + '0' * 64})
    release.publish(assets)
    remote[0]['digest'] = 'wrong'
    with pytest.raises(ValueError, match='refusing to overwrite'): release.publish(assets)


def test_failed_upload_keeps_release_draft(assets, monkeypatch):
    calls = []
    def run(*args):
        calls.append(args)
        if args[:3] == ('gh', 'repo', 'view'): return 'owner/repo'
        if args[:2] == ('gh', 'api'): return '[[]]'
        if args[:3] == ('gh', 'release', 'upload'):
            raise subprocess.CalledProcessError(1, args)
        return ''
    monkeypatch.setattr(release, 'run', run)
    with pytest.raises(subprocess.CalledProcessError): release.publish(assets)
    assert any(args[:3] == ('gh', 'release', 'create') and '--draft' in args for args in calls)
    assert not any(args[:3] == ('gh', 'release', 'edit') for args in calls)


@pytest.mark.parametrize('corrupt', [False, True])
def test_publish_checks_uploaded_hashes_and_preserves_newer_latest(assets, monkeypatch, corrupt):
    calls = []
    uploaded = [{'name':p.name, 'digest':'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()} for p in assets.iterdir()]
    if corrupt: uploaded[0]['digest'] = 'wrong'
    def run(*args):
        calls.append(args)
        if args[:3] == ('gh', 'repo', 'view'): return 'owner/repo'
        if args[:2] == ('gh', 'api'): return '[[{"tag_name":"v9.0.0","draft":false,"prerelease":false}]]'
        if args[:3] == ('gh', 'release', 'view') and args[-1] == 'assets':
            return json.dumps({'assets':uploaded})
        return ''
    monkeypatch.setattr(release, 'run', run)
    if corrupt:
        with pytest.raises(ValueError, match='remains a draft'): release.publish(assets)
        assert not any(args[:3] == ('gh', 'release', 'edit') for args in calls)
    else:
        release.publish(assets)
        assert any(args[:3] == ('gh', 'release', 'edit') and '--latest=false' in args for args in calls)


def test_pypi_hash_mismatch_is_not_hidden_by_skip_existing(assets, monkeypatch):
    from io import BytesIO
    monkeypatch.setattr(release.urllib.request, 'urlopen', lambda *args, **kwargs: BytesIO(b'{"urls":[]}'))
    with pytest.raises(ValueError, match='PyPI contents differ'): release.verify_pypi(assets)
