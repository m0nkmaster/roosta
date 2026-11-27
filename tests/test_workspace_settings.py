import json
import platform
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from roosta import app, cli, paths, workspace_settings

STATIC = Path(app.paths.STATIC_DIR)


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    workspace = tmp_path / 'active'
    (workspace / '.roosta').mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setattr(cli, 'CONFIG_FILE', tmp_path / 'config' / 'roosta.json')
    monkeypatch.setattr(cli, 'preflight', lambda: [])
    monkeypatch.setattr(paths, 'WORKSPACE', workspace)
    monkeypatch.setattr(paths, 'ROOSTA_DIR', workspace / '.roosta')
    monkeypatch.setattr(paths, 'PORT', 7667)
    for name in ('ASSISTANT_DESKTOP', 'XPC_SERVICE_NAME', 'INVOCATION_ID', 'ROOSTA_HOST'):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def fake_probe(argv):
        calls.append(argv)
        assert argv[0] in ('launchctl', 'systemctl'), argv
        return False

    monkeypatch.setattr(cli, '_probe', fake_probe)
    return type('Env', (), {'home': home, 'workspace': workspace, 'tmp': tmp_path, 'calls': calls})


@pytest.fixture
def client(env):
    with TestClient(app.app, base_url='http://localhost', client=('127.0.0.1', 1234)) as c:
        yield c


def saved():
    return json.loads(cli.CONFIG_FILE.read_text())


def test_get_reports_workspace_address_and_managers(env, client, monkeypatch):
    monkeypatch.setattr(platform, 'system', lambda: 'Other')
    response = client.get('/api/settings/workspace')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['workspace'] == str(env.workspace) and data['port'] == 7667 and data['host'] == '127.0.0.1'
    assert data['remembered'] == '' and data['saved_port'] is None and data['saved_host'] == ''
    assert data['managed_by'] == 'terminal' and data['service']['supported'] is False
    assert 'actor' in data['skills']['core'] and data['skills']['forks'] == {}
    monkeypatch.setenv('ASSISTANT_DESKTOP', '1')
    assert client.get('/api/settings/workspace').json()['managed_by'] == 'desktop'
    monkeypatch.delenv('ASSISTANT_DESKTOP')
    monkeypatch.setenv('XPC_SERVICE_NAME', cli.LAUNCHD_LABEL)
    assert client.get('/api/settings/workspace').json()['managed_by'] == 'service'
    monkeypatch.delenv('XPC_SERVICE_NAME')
    monkeypatch.setattr(app.sys, 'platform', 'linux')
    monkeypatch.setenv('INVOCATION_ID', 'abc')
    assert client.get('/api/settings/workspace').json()['managed_by'] == 'service'


def test_settings_identifies_forks_separately_from_installed_core(env, client):
    fork = env.workspace / ".roosta/skill-forks/actor"
    fork.mkdir(parents=True)
    (fork / "SKILL.md").write_text("custom")
    report = client.get('/api/settings/workspace').json()['skills']
    assert report["forks"] == {"actor": "legacy copy, review against installed core"}
    assert "actor" not in report["core"] and "sender" in report["core"]


def test_settings_endpoints_are_local_only(env):
    with TestClient(app.app, base_url='http://localhost', client=('192.0.2.10', 1234)) as remote:
        assert remote.get('/api/settings/workspace').status_code == 403
    with TestClient(app.app, base_url='http://localhost', client=('127.0.0.1', 1234)) as local:
        assert local.post('/api/settings/address', json={}, headers={'Origin': 'https://attacker.invalid'}).status_code == 403


def test_select_requires_an_absolute_existing_workspace(env, client):
    other = env.tmp / 'other'
    (other / '.roosta').mkdir(parents=True)
    plain = env.tmp / 'plain'
    plain.mkdir()
    relative = client.post('/api/settings/workspace', json={'action': 'select', 'path': 'notes'})
    assert relative.status_code == 400 and relative.json()['error'] == 'Enter the full path to the folder.'
    assert client.post('/api/settings/workspace', json={'action': 'select', 'path': ''}).status_code == 400
    assert client.post('/api/settings/workspace', json={'action': 'select', 'path': 'x' * 1025}).status_code == 400
    assert client.post('/api/settings/workspace', json={'action': 'select', 'path': str(env.tmp / 'a.txt')}).status_code == 400
    (env.tmp / 'a.txt').write_text('file')
    assert client.post('/api/settings/workspace', json={'action': 'select', 'path': str(env.tmp / 'a.txt')}).status_code == 400
    refused = client.post('/api/settings/workspace', json={'action': 'select', 'path': str(plain)})
    assert refused.status_code == 400 and 'is not a Roosta workspace' in refused.json()['error']
    assert not cli.CONFIG_FILE.exists()
    ok = client.post('/api/settings/workspace', json={'action': 'select', 'path': str(other)})
    assert ok.status_code == 200
    assert ok.json() == {'workspace': str(other.resolve()), 'active': str(env.workspace), 'restart_required': True, 'message': ''}
    assert saved()['workspace'] == str(other.resolve())
    same = client.post('/api/settings/workspace', json={'action': 'select', 'path': str(env.workspace)})
    assert same.json()['restart_required'] is False


def test_create_and_adopt_use_roosta_init(env, client):
    target = env.tmp / 'fresh'
    created = client.post('/api/settings/workspace', json={'action': 'create', 'path': str(target), 'git': False})
    assert created.status_code == 200, created.text
    assert (target / '.roosta').is_dir() and not (target / '.git').exists()
    assert 'workspace ready' in created.json()['message'] and created.json()['restart_required'] is True
    assert saved()['workspace'] == str(target.resolve())

    full = env.tmp / 'notes'
    full.mkdir()
    (full / 'mine.md').write_text('keep')
    refused = client.post('/api/settings/workspace', json={'action': 'create', 'path': str(full), 'git': False})
    assert refused.status_code == 400 and 'already has files' in refused.json()['error']
    assert not (full / '.roosta').exists()
    adopted = client.post('/api/settings/workspace', json={'action': 'adopt', 'path': str(full), 'git': False})
    assert adopted.status_code == 200 and (full / 'mine.md').read_text() == 'keep' and (full / '.roosta').is_dir()
    missing = client.post('/api/settings/workspace', json={'action': 'adopt', 'path': str(env.tmp / 'nope'), 'git': False})
    assert missing.status_code == 400
    assert client.post('/api/settings/workspace', json={'action': 'delete', 'path': str(full)}).status_code == 400


def test_address_validation_and_confirmation(env, client, monkeypatch):
    post = lambda **body: client.post('/api/settings/address', json=body)
    assert post(host='127.0.0.1', port=1023).status_code == 400
    assert post(host='127.0.0.1', port=True).status_code == 400
    assert post(host='127.0.0.1', port='7667').status_code == 400
    assert post(host='not a host', port=7000).status_code == 400
    assert post(host='', port=7000).status_code == 400
    exposed = post(host='0.0.0.0', port=7000)
    assert exposed.status_code == 400 and exposed.json()['needs_confirmation'] is True
    assert post(host='0.0.0.0', port=7000, confirm_network='yes').status_code == 400
    assert not cli.CONFIG_FILE.exists()
    ok = post(host='0.0.0.0', port=7000, confirm_network=True)
    assert ok.status_code == 200 and ok.json() == {'saved_host': '0.0.0.0', 'saved_port': 7000, 'restart_required': True}
    assert post(host='localhost', port=7001).json()['saved_host'] == 'localhost'
    assert saved()['host'] == 'localhost' and saved()['port'] == 7001
    data = client.get('/api/settings/workspace').json()
    assert (data['saved_host'], data['saved_port']) == ('localhost', 7001)
    monkeypatch.setenv('ASSISTANT_DESKTOP', '1')
    assert post(host='127.0.0.1', port=7000).status_code == 409


def test_address_preserves_the_remembered_workspace(env):
    cli.remember_workspace(env.workspace)
    cli.remember_address('127.0.0.1', 7000)
    assert saved() == {'workspace': str(env.workspace), 'host': '127.0.0.1', 'port': 7000}
    cli.CONFIG_FILE.write_text('[]')
    assert cli.read_config() == {}


def test_start_uses_saved_address_and_flags_win(env, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, 'start', lambda workspace, host, port: seen.append((workspace, host, port)) or 0)
    cli.main(['start', '--workspace', str(env.workspace)])
    assert seen[-1][1:] == ('127.0.0.1', cli.DEFAULT_PORT)
    cli.remember_address('localhost', 7000)
    cli.main(['start', '--workspace', str(env.workspace)])
    assert seen[-1][1:] == ('localhost', 7000)
    cli.main(['start', '--workspace', str(env.workspace), '--host', '127.0.0.2', '--port', '7100'])
    assert seen[-1][1:] == ('127.0.0.2', 7100)
    cli.write_config({'host': '', 'port': 70000})
    cli.main(['start', '--workspace', str(env.workspace)])
    assert seen[-1][1:] == ('127.0.0.1', cli.DEFAULT_PORT)


def test_service_install_writes_the_unit_and_reports_status(env, client, monkeypatch):
    monkeypatch.setattr(platform, 'system', lambda: 'Darwin')
    before = client.get('/api/settings/workspace').json()['service']
    plist = env.home / 'Library' / 'LaunchAgents' / 'dev.roosta.runner.plist'
    assert before['supported'] and before['platform'] == 'macos' and before['installed'] is False
    assert before['path'] == str(plist) and before['active'] is None
    assert before['activate'] == f'launchctl load -w {plist}'
    response = client.post('/api/settings/service', json={})
    assert response.status_code == 200, response.text
    service = response.json()['service']
    assert plist.is_file() and f'Wrote {plist}' in response.json()['message']
    assert service['installed'] and service['workspace'] == str(env.workspace) and service['port'] == 7667
    assert service['active'] is False
    assert env.calls == [['launchctl', 'list', 'dev.roosta.runner']]


def test_service_status_on_linux_and_active_probe(env, monkeypatch):
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    unit = env.home / '.config' / 'systemd' / 'user' / 'roosta.service'
    assert cli.service_install(env.workspace, 7000) == 0
    monkeypatch.setattr(cli, '_probe', lambda argv: argv == ['systemctl', '--user', 'is-active', '--quiet', 'roosta'])
    status = cli.service_status(env.workspace)
    assert status['path'] == str(unit) and status['installed'] and status['active'] is True
    assert (status['workspace'], status['port']) == (str(env.workspace), 7000)
    assert status['activate'] == 'systemctl --user enable --now roosta'



def test_probe_maps_exit_codes_and_failures(monkeypatch):
    def run(code):
        return lambda argv, **kw: subprocess.CompletedProcess(argv, code)

    def broken(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr(subprocess, 'run', run(0))
    assert cli._probe(['x']) is True
    monkeypatch.setattr(subprocess, 'run', run(3))
    assert cli._probe(['x']) is False
    monkeypatch.setattr(subprocess, 'run', broken)
    assert cli._probe(['x']) is None
    monkeypatch.setattr(subprocess, 'run', lambda argv, **kw: (_ for _ in ()).throw(FileNotFoundError()))
    assert cli._probe(['x']) is None


def test_service_refused_for_desktop_and_unsupported_platforms(env, client, monkeypatch):
    monkeypatch.setattr(platform, 'system', lambda: 'Windows')
    unsupported = client.post('/api/settings/service', json={})
    assert unsupported.status_code == 400
    monkeypatch.setattr(platform, 'system', lambda: 'Darwin')
    monkeypatch.setenv('ASSISTANT_DESKTOP', '1')
    assert client.post('/api/settings/service', json={}).status_code == 409
    assert not (env.home / 'Library').exists() and env.calls == []


def test_settings_page_has_the_workspace_card_and_escapes_server_text():
    page = (STATIC / 'settings.html').read_text()
    assert 'aria-labelledby="workspace-title"' in page and 'Workspace and runner' in page
    assert page.count('<script src="/static/ai-settings.js" defer>') == 1
    assert '<script src="/static/workspace-settings.js" defer></script>' in page
    assert 'manage your workspace and notifications, and adjust your appearance' in page
    assert (page.index('id="account-setup"') < page.index('id="workspace-title"')
            < page.index('id="notifications-title"') < page.index('>Appearance<'))
    script = (STATIC / 'workspace-settings.js').read_text()
    assert re.search(r'const esc = value =>', script)
    assert '${s.workspace}' not in script and '${code(s.workspace)}' in script
    assert 'const code = text => `<code>${esc(text)}</code>`' in script


def test_folder_browser_lists_sorted_visible_subfolders(env, client):
    root = env.tmp / 'browse'
    for name in ('beta', 'Alpha', '.hidden', 'gamma'):
        (root / name).mkdir(parents=True)
    (root / 'gamma' / '.roosta').mkdir()
    (root / 'file.md').write_text('x')
    (root / 'link').symlink_to(root / 'beta', target_is_directory=True)
    (root / 'broken').symlink_to(root / 'missing', target_is_directory=True)
    data = client.get('/api/settings/folders', params={'path': str(root)})
    assert data.status_code == 200 and data.headers['cache-control'] == 'no-store'
    data = data.json()
    assert [f['name'] for f in data['folders']] == ['Alpha', 'beta', 'gamma', 'link']
    assert [f['workspace'] for f in data['folders']] == [False, False, True, False]
    assert data['folders'][0]['path'] == str(root.resolve() / 'Alpha')
    assert data['path'] == str(root.resolve()) and data['parent'] == str(root.resolve().parent)
    assert data['is_workspace'] is False and data['is_empty'] is False and data['truncated'] is False
    assert data['home'] == str(env.home)
    assert client.get('/api/settings/folders', params={'path': str(root / 'Alpha')}).json()['is_empty'] is True
    assert client.get('/api/settings/folders', params={'path': str(env.workspace)}).json()['is_workspace'] is True


def test_folder_browser_defaults_to_home_and_stops_at_root(env, client):
    (env.home / 'notes').mkdir()
    data = client.get('/api/settings/folders').json()
    assert data['path'] == str(env.home.resolve()) and [f['name'] for f in data['folders']] == ['notes']
    assert client.get('/api/settings/folders', params={'path': '/'}).json()['parent'] is None


def test_folder_browser_keeps_listing_when_a_child_marker_is_unreadable(env, client, monkeypatch):
    (env.home / 'protected').mkdir()
    original = Path.is_dir

    def is_dir(path):
        if path == env.home / 'protected' / '.roosta':
            raise PermissionError
        return original(path)

    monkeypatch.setattr(Path, 'is_dir', is_dir)
    response = client.get('/api/settings/folders')
    assert response.status_code == 200
    assert response.json()['folders'] == [
        {'name': 'protected', 'path': str(env.home / 'protected'), 'workspace': False}]


def test_folder_browser_rejects_bad_paths(env, client, monkeypatch):
    assert client.get('/api/settings/folders', params={'path': 'relative'}).status_code == 400
    assert client.get('/api/settings/folders', params={'path': 'x' * 1025}).status_code == 400
    missing = client.get('/api/settings/folders', params={'path': str(env.tmp / 'nope')})
    assert missing.status_code == 400 and missing.json()['error'] == 'That folder does not exist.'
    (env.tmp / 'a.txt').write_text('x')
    assert client.get('/api/settings/folders', params={'path': str(env.tmp / 'a.txt')}).status_code == 400

    def denied(directory):
        raise PermissionError

    monkeypatch.setattr(app.os, 'scandir', denied)
    blocked = client.get('/api/settings/folders', params={'path': str(env.tmp)})
    assert blocked.status_code == 400 and blocked.json()['error'] == 'Roosta cannot read that folder.'


def test_folder_browser_caps_the_listing(env, client, monkeypatch):
    for name in ('a', 'b', 'c'):
        (env.tmp / 'many' / name).mkdir(parents=True)
    monkeypatch.setattr(workspace_settings, 'FOLDER_LIST_LIMIT', 2)
    data = client.get('/api/settings/folders', params={'path': str(env.tmp / 'many')}).json()
    assert [f['name'] for f in data['folders']] == ['a', 'b'] and data['truncated'] is True


def test_folder_browser_is_local_only(env):
    with TestClient(app.app, base_url='http://localhost', client=('192.0.2.10', 1234)) as remote:
        assert remote.get('/api/settings/folders').status_code == 403
    with TestClient(app.app, base_url='http://localhost', client=('127.0.0.1', 1234)) as local:
        assert local.get('/api/settings/folders', headers={'Origin': 'https://attacker.invalid'}).status_code == 403


def test_open_folder_reveals_only_the_active_workspace_and_only_locally(env, monkeypatch):
    opened = []
    monkeypatch.setattr(app.sys, 'platform', 'darwin')
    monkeypatch.setattr(app, 'launch_detached', opened.append)
    with TestClient(app.app, base_url='http://localhost', client=('127.0.0.1', 1234)) as local:
        response = local.post('/api/workspace/reveal', json={'path': '/etc'})
        assert response.status_code == 200 and response.json() == {'opened': str(env.workspace)}
        assert opened == [['open', str(env.workspace)]]
        assert local.post('/api/workspace/reveal', headers={'Origin': 'https://attacker.invalid'}).status_code == 403
        monkeypatch.setattr(app.sys, 'platform', 'linux')
        monkeypatch.setattr(app.shutil, 'which', lambda name: None)
        assert local.post('/api/workspace/reveal').status_code == 400
    with TestClient(app.app, base_url='http://localhost', client=('192.0.2.10', 1234)) as remote:
        assert remote.post('/api/workspace/reveal').status_code == 403
    assert len(opened) == 1
    html = (STATIC / 'workspace.html').read_text()
    assert 'id="reveal-workspace"' in html and '/api/workspace/reveal' in (STATIC / 'workspace.js').read_text()


def test_notifications_default_on_and_save_to_the_desktop_config(env, client, monkeypatch):
    data = client.get('/api/settings/notifications').json()
    assert data == {'enabled': True, 'managed_by': 'terminal'}
    cli.remember_workspace(env.workspace)
    response = client.post('/api/settings/notifications', json={'enabled': False})
    assert response.status_code == 200 and response.json()['enabled'] is False
    assert saved() == {'workspace': str(env.workspace), 'notifications': False}
    assert cli.notifications_enabled() is False
    monkeypatch.setenv('ASSISTANT_DESKTOP', '1')
    assert client.get('/api/settings/notifications').json() == {'enabled': False, 'managed_by': 'desktop'}
    assert client.post('/api/settings/notifications', json={'enabled': True}).json()['enabled'] is True
    assert saved()['notifications'] is True and cli.notifications_enabled() is True


def test_notifications_reject_non_boolean_choices(env, client):
    for body in ({}, {'enabled': 'false'}, {'enabled': 0}, {'enabled': None}):
        assert client.post('/api/settings/notifications', json=body).status_code == 400
    assert not cli.CONFIG_FILE.exists()


def test_notifications_setting_is_local_only(env):
    with TestClient(app.app, base_url='http://localhost', client=('192.0.2.10', 1234)) as remote:
        assert remote.get('/api/settings/notifications').status_code == 403
        assert remote.post('/api/settings/notifications', json={'enabled': False}).status_code == 403
    with TestClient(app.app, base_url='http://localhost', client=('127.0.0.1', 1234)) as local:
        assert local.post('/api/settings/notifications', json={'enabled': False},
                          headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    assert not cli.CONFIG_FILE.exists()


def test_settings_page_has_the_notifications_switch_and_manual_macos_guidance():
    page = (STATIC / 'settings.html').read_text()
    assert 'id="notifications-enabled"' in page and 'role="switch"' in page
    assert "fetch('/api/settings/notifications'" in page
    assert 'Apple menu → System Settings → Notifications → Roosta' in page
    assert 'Allow notifications' in page and 'Send Test Notification' in page


def test_foreign_host_is_refused_everywhere(monkeypatch):
    """DNS rebinding names the attacker's domain in Host; only IPs, localhost and the saved host pass."""
    monkeypatch.delenv('ROOSTA_HOST', raising=False)
    client = TestClient(app.app, base_url='http://localhost', client=('127.0.0.1', 1234))
    assert client.get('/api/profile', headers={'Host': 'attacker.example:7667'}).status_code == 403
    assert client.post('/api/board/chat', json={'item_id': 'chat:0123456789ab'},
                       headers={'Host': 'attacker.example'}).status_code == 403
    for host in ('localhost:7667', '127.0.0.1:7667', '[::1]:7667', '192.168.1.20:7667'):
        assert client.get('/api/profile', headers={'Host': host}).status_code == 200, host
    monkeypatch.setenv('ROOSTA_HOST', 'studio.local')
    assert client.get('/api/profile', headers={'Host': 'studio.local:7667'}).status_code == 200


def test_chat_model_change_without_chats_says_how_to_fix(monkeypatch):
    async def unavailable():
        return None

    monkeypatch.setattr(app, 'chat_router', None)
    monkeypatch.setattr(app, '_start_chat_router', unavailable)
    client = TestClient(app.app, base_url='http://localhost', client=('127.0.0.1', 1234))
    response = client.post('/api/ai/chat-model', json={'item_id': 'chat:0123456789ab', 'model': 'x'})
    assert response.status_code == 503
    assert 'Settings' in response.json()['error']
