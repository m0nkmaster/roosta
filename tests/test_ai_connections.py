import asyncio
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from roosta import paths, scheduler, skills
from roosta import ai_settings
from roosta import board
from roosta import task_config
from roosta import ai_backend, ai_connections as connections, ai_runtime, app, chat, pi_agent


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(connections, 'CONNECTIONS_FILE', tmp_path / 'connections.json')
    monkeypatch.setattr(connections, 'CONNECTIONS_DIR', tmp_path / 'accounts')
    monkeypatch.setattr(ai_backend, 'mcp_config', lambda workspace: {'mcpServers': {}})
    monkeypatch.setattr(ai_runtime, 'find', lambda runtime: f'/managed/{runtime}')
    monkeypatch.setattr(ai_runtime, 'model_catalog', lambda provider: ['gpt-5.4', 'gpt-5-mini', 'openai/gpt-5.4'])
    monkeypatch.setattr(ai_runtime, 'default_model', lambda provider: {'openai': 'gpt-5.4', 'openrouter': 'openai/gpt-5.4'}.get(provider, ''))
    secrets = {}
    class Vault:
        def get_password(self, service, key): return secrets.get(key)
        def set_password(self, service, key, value): secrets[key] = value
        def delete_password(self, service, key): secrets.pop(key, None)
    monkeypatch.setattr(connections, '_vault', lambda: Vault())
    def create(provider='openai', key='first-test-key', tested=True, **kwargs):
        c = connections.create({'provider': provider, 'api_key': key, **kwargs})
        return connections.update(c['id'], tested=tested)
    return create, secrets


@pytest.mark.parametrize('provider,model', [
    ('openrouter', 'anthropic/claude-sonnet-4'), ('openrouter', 'anthropic/new-model'),
    ('openrouter', 'openrouter/auto'), ('openrouter', 'bad model;'), ('openai', '-flag'),
])
def test_anthropic_and_automatic_routing_cannot_reach_pi(provider, model):
    with pytest.raises(ValueError):
        connections.runtime(provider, model)


@pytest.mark.parametrize("provider", ["anthropic", "openai", "cursor"])
@pytest.mark.parametrize("obsolete_cli", [False, True])
def test_worker_invokes_serving_cli(accounts, tmp_path, monkeypatch, provider, obsolete_cli):
    workspace = tmp_path / "selected office"
    (workspace / ".roosta").mkdir(parents=True)
    cwd = tmp_path / "worker project"
    cwd.mkdir()
    (cwd / "roosta.py").write_text("raise RuntimeError('wrong package')")
    if obsolete_cli:
        old = tmp_path / "roosta"
        old.write_text("#!/bin/sh\nexit 42\n")
        old.chmod(0o755)
    monkeypatch.setattr(ai_backend.cursor_agent, "agent_path", lambda _: str(tmp_path))
    runtime = tmp_path / "runtime with spaces"
    runtime.symlink_to(Path(sys.executable).parent, target_is_directory=True)
    monkeypatch.setattr(sys, "executable", str(runtime / Path(sys.executable).name))
    monkeypatch.setattr(paths, "WORKSPACE", workspace)
    monkeypatch.setattr(paths, "PORT", 18765)
    account = accounts[0](provider)
    run = ai_backend.prepare(account["id"], str(cwd))
    assert run.env["ROOSTA_PORT"] == "18765"
    assert shutil.which("roosta", path=run.env["PATH"]) == str(paths.APP_ROOT / "worker-bin/roosta")

    def invoke(*args):
        return subprocess.check_output(["roosta", *args], cwd=cwd, env=run.env, text=True).strip()

    assert invoke("skills", "path") == str(paths.CORE_SKILLS_DIR)
    assert "actor" in json.loads(invoke("skills", "status"))["core"]
    assert "snapshot" in invoke("snapshot", "board", "--help")


def test_connections_keep_secrets_out_of_metadata_and_argv(accounts, tmp_path, monkeypatch):
    create, secrets = accounts
    first, second = create(label='Work'), create(key='second-test-key', label='Personal')
    monkeypatch.setenv('OPENAI_API_KEY', 'inherited-key')
    monkeypatch.setenv('CURSOR_API_KEY', 'inherited-cursor-key')
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'inherited-token')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://wrong-account.invalid')
    monkeypatch.setenv('CLAUDE_CODE_USE_BEDROCK', '1')
    a, b = (ai_backend.prepare(c['id'], str(tmp_path)) for c in (first, second))
    assert a.env['OPENAI_API_KEY'] == 'first-test-key'
    assert b.env['OPENAI_API_KEY'] == 'second-test-key'
    assert a.env['PI_CODING_AGENT_DIR'] != b.env['PI_CODING_AGENT_DIR']
    assert a.session_id != b.session_id
    for run in (a, b):
        assert 'CURSOR_API_KEY' not in run.env
        assert 'OPENAI_BASE_URL' not in run.env
        assert 'ANTHROPIC_AUTH_TOKEN' not in run.env
        assert 'CLAUDE_CODE_USE_BEDROCK' not in run.env
        assert run.secret not in repr(run) and run.secret not in ' '.join(run.args)
    persisted = connections.CONNECTIONS_FILE.read_text()
    assert 'test-key' not in persisted and 'inherited' not in persisted
    assert connections.CONNECTIONS_FILE.stat().st_mode & 0o777 == 0o600
    assert len(secrets) == 2


def test_claude_accounts_have_separate_auth_and_sessions(accounts, tmp_path):
    create, _ = accounts
    a, b = [create('anthropic', auth='cli') for _ in range(2)]
    runs = [ai_backend.prepare(c['id'], str(tmp_path)) for c in (a, b)]
    assert all(r.backend == 'claude' for r in runs)
    assert runs[0].env['CLAUDE_CONFIG_DIR'] != runs[1].env['CLAUDE_CONFIG_DIR']
    assert all('ANTHROPIC_API_KEY' not in r.env for r in runs)
    assert all(r.args[r.args.index('--permission-mode') + 1] == 'dontAsk' for r in runs)
    assert all(r.env['CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST'] == '1' for r in runs)


@pytest.mark.parametrize('profile', ['safe', 'unrestricted'])
def test_claude_package_and_private_permissions(accounts, tmp_path, monkeypatch, profile):
    account = accounts[0]('anthropic', auth='cli')
    package = tmp_path / 'checkout/src/roosta'
    package.mkdir(parents=True)
    alias = tmp_path / 'installed'
    alias.symlink_to(package)
    monkeypatch.setattr(paths, 'APP_ROOT', alias)
    monkeypatch.setattr(ai_runtime, 'RUNTIME_ROOT', tmp_path / 'checkout/.roosta/runtimes')
    projects = connections.directory(account['id']) / 'claude/projects/test'
    projects.mkdir(parents=True)
    settings = {}
    for editable in (False, True):
        workspace = package.parents[1] if editable else tmp_path / 'office'
        sid = ''
        for flag in ('--session-id', '--resume'):
            run = ai_backend.prepare(account['id'], str(workspace), profile=profile, session_id=sid)
            assert run.args[run.args.index(flag) + 1] == run.session_id
            sid = run.session_id
            (projects / f'{sid}.jsonl').touch()
            settings[editable] = Path(run.args[run.args.index('--settings') + 1])
            permissions = json.loads(settings[editable].read_text())['permissions']
            assert 'Read' in permissions['allow']
            for tool in ('Read', 'Edit', 'Write'):
                rule = f'{tool}(/{package.resolve()}/**)'
                assert (rule in permissions['deny']) == (not editable and tool != 'Read')
                for root in (connections.CONNECTIONS_DIR, ai_runtime.RUNTIME_ROOT):
                    assert f'{tool}(/{root.resolve()}/**)' in permissions['deny']
    assert settings[False] != settings[True]


def test_untested_default_works_and_disconnect_never_falls_back(accounts):
    create, _ = accounts
    a, b = create(tested=False), create()
    connections.set_default(a['id'])
    connections.update(a['id'], connected=False)
    with pytest.raises(ValueError, match='disconnected'):
        connections.get()
    assert connections.load()['default'] == a['id']
    assert connections.get(b['id'])['id'] == b['id']


def test_chats_pin_account_across_default_change_and_restart(accounts, tmp_path):
    create, _ = accounts
    a, b = create(), create()
    for c in (a, b): connections.update(c['id'], tested=True)
    connections.set_default(a['id'])
    sessions = chat.SessionMap(tmp_path / 'sessions.json')
    assert sessions.connection('chat:111111111111') == a['id']
    sessions.set('chat:111111111111', '11111111-1111-4111-8111-111111111111')
    connections.set_default(b['id'])
    restored = chat.SessionMap(sessions._path)
    assert restored.connection('chat:111111111111') == a['id']
    assert restored.connection('chat:222222222222') == b['id']
    restored.bind('chat:111111111111', b['id'])
    assert restored.get('chat:111111111111') is None


def test_default_change_does_not_adopt_legacy_chats(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    old, new = create(), create()
    connections.set_default(old['id'])
    path = tmp_path / 'sessions.json'
    sid = '11111111-1111-4111-8111-111111111111'
    path.write_text(json.dumps({'bare': sid, 'cursor': {'session_id': sid, 'connection': 'legacy:cursor'},
                                'named': {'session_id': sid, 'connection': old['id']}}))
    sessions = chat.SessionMap(path)
    monkeypatch.setattr(app, 'chat_router', chat.ChatRouter(sessions, str(tmp_path)))
    original = path.read_bytes()
    assert sessions.selected('cursor') == 'legacy:cursor'
    assert asyncio.run(app.api_ai_default({'connection': new['id']})).status_code == 200
    assert path.read_bytes() == original
    restored = chat.SessionMap(path)
    assert restored.legacy_items() == ['bare', 'cursor']
    assert restored.get('bare') == restored.get('cursor') == sid
    assert restored.connection('named') == old['id']
    assert restored.connection('new') == new['id']


def test_invalid_metadata_and_symlink_fail_closed(accounts, tmp_path):
    create, _ = accounts
    c = create()
    connections.CONNECTIONS_DIR.mkdir()
    connections.directory(c['id']).symlink_to(tmp_path)
    with pytest.raises(ValueError): connections.get(c['id'])
    connections.CONNECTIONS_FILE.write_text('broken')
    with pytest.raises(ValueError): connections.load()


def test_pi_errors_override_successful_exit_and_tools_are_not_replies():
    line = json.dumps({'type':'message_end', 'message':{'role':'assistant','stopReason':'error','errorMessage':'401 invalid key','content':[]}})
    assert pi_agent.failure(line) == '401 invalid key'
    assert 'reconnect' in ai_backend.repair_message(pi_agent.failure(line))
    assert pi_agent.parse_line(json.dumps({'type':'tool_execution_start'})) == {'kind':'tool','text':'','name':None}
    assert pi_agent.result_text(line) == ''


def test_pi_policies_under_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    script = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {denied} from './src/roosta/pi_guard.mjs';
const policy = JSON.parse(fs.readFileSync('./src/roosta/cursor-permissions.json')).permissions;
policy.deny.push('Shell(tool:send*)');
assert(denied({toolName:'bash',input:{command:'git status && git push origin main'}},policy));
assert(denied({toolName:'bash',input:{command:'/usr/bin/curl https://example.com'}},policy));
assert.equal(denied({toolName:'bash',input:{command:'rm -rf build && git reset --hard && git clean -fd'}},policy),'');
assert(denied({toolName:'bash',input:{command:'tool send --message hello'}},policy));
assert(denied({toolName:'mcp__slack__sendMessage',input:{}},policy));
assert(denied({toolName:'mcp__jira__addComment',input:{}},policy));
assert(denied({toolName:'read',input:{path:'.env'}},policy));
assert(denied({toolName:'write',input:{path:'nested/key.pem'}},policy));
assert.equal(denied({toolName:'bash',input:{command:'git status'}},policy),'');
assert.equal(denied({toolName:'mcp__slack__get_thread',input:{}},policy),'');
assert.equal(denied({toolName:'mcp__slack__sendMessage',input:{}},{deny:[],unrestricted:true}),'');
assert(denied({toolName:'bash',input:{command:'git status'}},null));
const temporary = fs.mkdtempSync(path.join(os.tmpdir(),'roosta-guard-'));
try {
  const link = path.join(temporary,'innocent.txt');
  fs.symlinkSync(path.join(temporary,'secret.pem'),link);
  assert(denied({toolName:'write',input:{path:link}},policy));
} finally { fs.rmSync(temporary,{recursive:true,force:true}); }

'''
    subprocess.run([node,'--input-type=module','-e',script], check=True, cwd=Path(__file__).resolve().parents[1])


@pytest.mark.parametrize('profile', ['safe', 'unrestricted'])
@pytest.mark.parametrize('editable', [False, True])
def test_pi_package_and_private_permissions(accounts, tmp_path, monkeypatch, profile, editable):
    node = shutil.which('node')
    if not node:
        pytest.skip('node not available')
    account = accounts[0]()
    checkout = tmp_path / 'checkout'
    package = checkout / 'src/roosta'
    package.mkdir(parents=True)
    helper = package / 'skills/workspace-learner/sessions.py'
    helper.parent.mkdir(parents=True)
    helper.touch()
    (package / 'pi_guard.mjs').symlink_to(paths.APP_ROOT / 'pi_guard.mjs')
    monkeypatch.setattr(paths, 'APP_ROOT', package)
    runtime = checkout / '.roosta/runtimes'
    runtime.mkdir(parents=True)
    monkeypatch.setattr(ai_runtime, 'RUNTIME_ROOT', runtime)
    workspace = checkout if editable else tmp_path / 'office'
    workspace.mkdir(exist_ok=True)
    (workspace / 'core').symlink_to(package)
    (package / 'runtime').symlink_to(runtime)
    (runtime / 'data').touch()
    (workspace / 'new-file').symlink_to(package / 'missing')
    script = r'''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const [guard, pkg, accounts, runtime, editable, profile] = process.argv.slice(1);
const handlers = {};
(await import(pathToFileURL(guard))).default({on: (name, fn) => handlers[name] = fn});
function blocked(toolName, value) {
  const input = toolName === 'bash' ? {command: value} : {path: value};
  return Boolean(handlers.tool_call({toolName, input})?.block);
}
for (const name of ['skills/setup/SKILL.md', 'skills/setup/references/starter-tasks.yaml', 'operating-model.md']) {
  assert.equal(blocked('read', pkg + '/' + name), false);
}
for (const tool of ['read', 'edit', 'write']) {
  for (const root of [accounts, runtime, 'core/runtime']) assert(blocked(tool, root + '/data'));
  for (const target of [pkg, 'core/skills/setup/SKILL.md', 'new-file']) {
    assert.equal(blocked(tool, target), tool !== 'read' && editable === 'False');
  }
  assert.equal(blocked(tool, pkg + '-sibling/file'), false);
}
for (const root of [accounts, runtime]) assert(blocked('bash', 'cat ' + root + '/data'));
if (editable === 'False') assert(blocked('bash', 'cat ' + pkg + '/runtime/data'));
assert.equal(blocked('bash', 'python3 ' + pkg + '/skills/workspace-learner/sessions.py status'), false);
for (const resource of ['board', 'tasks']) assert.equal(blocked('bash', 'roosta snapshot ' + resource), false);
assert.equal(blocked('bash', 'git push origin main'), profile === 'safe');
'''
    fresh = ai_backend.prepare(account['id'], str(workspace), profile=profile)
    resumed = ai_backend.prepare(account['id'], str(workspace), profile=profile, session_id=fresh.session_id)
    for run in (fresh, resumed):
        assert run.args[run.args.index('--session-id') + 1] == fresh.session_id
        session_dir = run.args[run.args.index('--session-dir') + 1]
        assert session_dir == str(Path(fresh.env['PI_CODING_AGENT_DIR']) / 'sessions')
        guard = str(package / 'pi_guard.mjs')
        assert ('--extension', guard) in zip(run.args, run.args[1:])
        subprocess.run([node, '--input-type=module', '-e', script, guard, str(package),
                        str(connections.CONNECTIONS_DIR), str(runtime), str(editable), profile],
                       cwd=workspace, env=run.env, check=True)


@pytest.mark.parametrize('layout', ['source', 'site-packages'])
def test_pi_engineer_evidence_scan(tmp_path, layout):
    node = shutil.which('node')
    if not node:
        pytest.skip('node not available')
    package = paths.APP_ROOT
    helper = Path('skills/workspace-learner/sessions.py')
    if layout == 'site-packages':
        package = tmp_path / 'Python Libraries/site-packages/roosta'
        (package / helper).parent.mkdir(parents=True)
        shutil.copyfile(paths.APP_ROOT / helper, package / helper)

    workspace = tmp_path / 'office'
    workspace.mkdir()
    history = workspace / '.roosta/state/assistant/chat-history.json'
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps({'chat:fixture': [
        {'role': 'user', 'text': 'Show the worker schedule'},
        {'role': 'assistant', 'text': 'The engineer runs daily'},
    ]}))
    script = r"""
import assert from 'node:assert/strict';
import {execSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const [guard, pkg] = process.argv.slice(1);
const {denied} = await import(pathToFileURL(guard));
const policy = {deny: [], readOnlyRoot: pkg};
const check = command => denied({toolName: 'bash', input: {command}}, policy);
function run(command) {
  assert.equal(check(command), '');
  return execSync(command, {encoding: 'utf8'});
}
const file = "'" + pkg + "/skills/workspace-learner/sessions.py'";
const helper = 'python3 ' + file;
assert.equal(JSON.parse(run(helper + ' status')).assistant.available, true);
const [row] = JSON.parse(run(helper + ' list 0 --source assistant --newest-first --limit 1 --json'));
assert.equal(row.id, 'chat:fixture');
assert.match(run(helper + ' transcript ' + row.transcript_id + ' --tools'), /The engineer runs daily/);
assert.match(run("grep -F -- 'def cmd_list' " + file), /def cmd_list/);
for (const command of [helper + ' status && echo done', helper + ' status > log', helper + ' status\ntouch log',
                       helper + ' list "$(date)"', helper + ' transcript cc:../file', helper + ' update',
                       'python3 -i ' + file + ' status', 'touch ' + file, 'cat ' + file + ' | sh']) {
  assert(check(command), command);
}
"""
    env = dict(os.environ, HOME=str(tmp_path), ROOSTA_WORKSPACE=str(workspace),
               ASSISTANT_HISTORY=str(history), OC_DB=str(tmp_path / 'absent.db'),
               CLAUDE_PROJECTS_DIR=str(tmp_path / 'claude'), CURSOR_PROJECTS_DIR=str(tmp_path / 'cursor'))
    subprocess.run([node, '--input-type=module', '-e', script, str(paths.APP_ROOT / 'pi_guard.mjs'),
                    str(package)], cwd=workspace, env=env, check=True)


def test_settings_reject_remote_and_cross_origin_requests(accounts):
    with TestClient(app.app, base_url='http://localhost', client=('192.0.2.10',1234)) as client:
        assert client.post('/api/ai/operations/test/cancel', json={}).status_code == 403
        assert client.post('/api/ai/connections', json={}).status_code == 403
        assert client.post('/api/ai/terminal', json={'id':'pi'}).status_code == 403
    with TestClient(app.app, base_url='http://localhost', client=('127.0.0.1',1234)) as client:
        assert client.post('/api/ai/connections', json={}, headers={'Origin':'https://attacker.invalid'}).status_code == 403
        assert client.post('/api/ai/terminal', json={'id':'pi'}, headers={'Origin':'https://attacker.invalid'}).status_code == 403
        assert client.post('/api/ai/connections', json={}, headers={'Host':'attacker.invalid'}).status_code == 403
        for headers in ({'Origin':'https://attacker.invalid'}, {'Host':'attacker.invalid'}):
            assert client.post('/api/ai/operations/test/cancel', json={}, headers=headers).status_code == 403
        assert client.post('/api/ai/operations/test/cancel', json={}).status_code == 409
        response = client.post('/api/ai/connections', json={'provider':'openai','api_key':'test-key'})
        assert response.status_code == 201
        assert 'test-key' not in response.text
        assert response.headers['cache-control'] == 'no-store'


def test_sender_retains_original_account_when_default_changes(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    a, b = create(), create()
    for c in (a,b): connections.update(c['id'], tested=True)
    connections.set_default(b['id'])
    router = chat.ChatRouter(chat.SessionMap(tmp_path/'sessions.json'), str(tmp_path))
    extension = skills.manage('extend', 'sender', tmp_path, paths.CORE_SKILLS_DIR)
    router._paused['send'] = {'connection':a['id'], 'item_id':'x', 'persistent':True,
        'action':{'kind':'message','target':'Slack channel C123','draft':'Hello [AI]'}}
    seen = []
    async def stream(run, prompt, **kwargs):
        assert f"sender: {paths.CORE_SKILLS_DIR / 'sender/SKILL.md'} then read additive instructions at {extension}" in prompt
        seen.append((run.connection['id'], json.loads(run.env['ROOSTA_PI_POLICY'])['unrestricted']))
        yield json.dumps({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':'<task-output>{"status":"success","summary":"Sent"}</task-output>'}]}})
    monkeypatch.setattr(ai_backend,'stream',stream)
    result = asyncio.run(router.approve('send',True,None))
    assert result['sent'] and seen == [(a['id'],True)]


def test_pi_chat_progress_is_transient_and_uses_only_tool_identifiers(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    sessions = chat.SessionMap(tmp_path / "sessions.json")
    account = create(tested=False)
    connections.set_default(account['id'])
    history = chat.ConversationHistoryStore(tmp_path / "history.json")
    router = chat.ChatRouter(sessions, str(tmp_path), persistent_history=history)

    fork = skills.manage("fork", "actor", tmp_path, paths.CORE_SKILLS_DIR)
    extension = skills.manage("extend", "actor", tmp_path, paths.CORE_SKILLS_DIR)

    async def stream(run, prompt):
        assert f"actor: {fork / 'SKILL.md'} then read additive instructions at {extension}" in prompt
        assert run.connection["id"] == account["id"]
        yield json.dumps({"type": "message_update", "assistantMessageEvent":
                          {"type": "thinking_delta", "delta": "private thought"}})
        for phase in ("start", "update", "update", "end"):
            yield json.dumps({"type": "tool_execution_" + phase, "toolName": "read",
                              "args": {"path": "private"}, "partialResult": "private", "result": "private"})
        yield json.dumps({"type": "message_update", "assistantMessageEvent":
                          {"type": "text_delta", "delta": "All clear."}})

    monkeypatch.setattr(ai_backend, "stream", stream)

    async def collect():
        queue = router.start_turn("item", {}, "Check").events
        events = []
        while (event := await queue.get())["kind"] != "_close":
            events.append(event)
        return events

    events = asyncio.run(collect())
    assert [event["label"] for event in events if event["kind"] == "progress"] == [
        "Reply running", "Tool started · read", "Tool running · read", "Tool finished · read"]
    assert "private" not in json.dumps(events)
    assert [message["text"] for message in history.read("item")] == ["Check", "All clear."]
    assert router.active_progress == {}
    assert "private" not in ai_backend.repair_message('{"thinking":"private"}')


def test_parallel_runs_keep_credentials_and_session_directories(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    a, b = create(key='one'), create(key='two')
    runs = [ai_backend.prepare(c['id'], str(tmp_path)) for c in (a,b)]
    # Real child processes inspect only their own supplied environment.
    for run in runs:
        run.args = [sys.executable,'-c', 'import os,json; print(json.dumps({"key":os.environ["OPENAI_API_KEY"],"dir":os.environ["PI_CODING_AGENT_DIR"]}))']
        run.backend = 'claude'
        run.secret = ''
    async def collect(run): return ''.join([line async for line in ai_backend.stream(run,'test',maximum=3)])
    async def both(): return await asyncio.gather(*(collect(run) for run in runs))
    outputs = [json.loads(text) for text in asyncio.run(both())]
    assert [row['key'] for row in outputs] == ['one','two']
    assert outputs[0]['dir'] != outputs[1]['dir']


def test_timeout_reaps_child_and_clears_active_account(accounts, tmp_path):
    create, _ = accounts
    c = create()
    run = ai_backend.prepare(c['id'],str(tmp_path))
    run.backend = 'claude'
    run.args = [sys.executable,'-c','import time; time.sleep(30)']
    async def consume(): return [line async for line in ai_backend.stream(run,'test',idle=.1,maximum=.2)]
    with pytest.raises(ValueError,match='stopped responding'): asyncio.run(consume())
    assert not ai_backend.ACTIVE_CONNECTIONS[c['id']]


def test_a_turn_during_runtime_repair_waits_for_it_instead_of_failing(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    c = create()
    run = ai_backend.prepare(c['id'], str(tmp_path))
    run.backend = 'claude'
    run.args = [sys.executable, '-c', 'print("answered")']
    installing = {'claude'}
    monkeypatch.setattr(ai_runtime, 'INSTALLING', installing)
    monkeypatch.setattr(ai_backend, 'REPAIR_POLL', .01)
    async def finish_repair():
        await asyncio.sleep(.1)
        installing.discard('claude')
    async def consume():
        repair = asyncio.create_task(finish_repair())
        text = ''.join([line async for line in ai_backend.stream(run, 'test', maximum=5)])
        await repair
        return text
    assert 'answered' in asyncio.run(consume())
    # A repair that outlasts the wait still fails with the Settings hint.
    installing.add('claude')
    monkeypatch.setattr(ai_backend, 'REPAIR_WAIT', .05)
    async def stuck(): return [line async for line in ai_backend.stream(run, 'test', maximum=5)]
    with pytest.raises(ValueError, match='being repaired'):
        asyncio.run(stuck())
    assert not ai_backend.ACTIVE_CONNECTIONS[c['id']]


def test_checksum_failure_preserves_existing_runtime(tmp_path, monkeypatch):
    destination = ai_runtime.binary_path(tmp_path,'pi','9.1.0')
    destination.parent.mkdir(); destination.write_text('working')
    monkeypatch.setattr(ai_runtime, 'latest_release', lambda *args: ('9.1.0', 'https://example.invalid/pi', '0' * 64))
    monkeypatch.setattr(ai_runtime.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(b'wrong download'))
    with pytest.raises(ValueError,match='checksum'): ai_runtime.install('pi',tmp_path)
    assert destination.read_text() == 'working'


def test_task_default_is_implicit_and_keeps_its_model(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    c=create(); connections.update(c['id'],tested=True); connections.set_default(c['id'])
    tasks=tmp_path/'tasks.yaml'
    tasks.write_text('tasks:\n  - id: new\n    skill: actor\n  - id: old\n    skill: actor\n    model: old-model\n')
    monkeypatch.setattr(app.paths,'TASKS_FILE',tasks)
    loaded=task_config.load_tasks()
    assert [t.connection for t in loaded] == ['', ''] and loaded[1].model == 'old-model'
    task_config.update_task_fields(tasks,'old',{'connection':c['id']})
    assert 'model: old-model' in tasks.read_text()


def test_generic_action_categories_keep_old_aliases():
    assert board._normalise_action_type('teams',{})=='chat'
    assert board._normalise_action_type('jira_ticket',{})=='ticket'
    assert board._normalise_action_type('chat',{})=='chat'
    assert board._normalise_action_type('ticket',{})=='ticket'


@pytest.mark.parametrize("mismatch", ["model", "effort"])
def test_pi_rejects_fuzzy_model_before_sending_prompt(accounts, tmp_path, mismatch):
    create, _ = accounts
    c = create()
    run = ai_backend.prepare(c['id'],str(tmp_path))
    received = tmp_path / 'received.json'
    script = '''import json,sys
print(json.dumps({'type':'extension_ui_request','method':'notify','message':'roosta-policy-ready'}),flush=True)
line=sys.stdin.readline()
open(sys.argv[1],'w').write(line)
print(json.dumps({'type':'response','id':'roosta-state','success':True,'data':{'model':{'provider':'openrouter','id':'anthropic/claude-sonnet-4'}}}),flush=True)
sys.stdin.read()
'''
    if mismatch == 'effort':
        script = script.replace("'provider':'openrouter','id':'anthropic/claude-sonnet-4'", "'provider':'openai','id':'gpt-5.4'")
    run.args = [sys.executable,'-c',script,str(received), '--thinking', 'high']
    async def consume(): return [line async for line in ai_backend.stream(run,'must never reach the model',maximum=2)]
    with pytest.raises(ValueError,match=f'different {mismatch}'): asyncio.run(consume())
    assert json.loads(received.read_text())['type']=='get_state'
    assert 'must never' not in received.read_text()


def test_pi_missing_policy_never_receives_prompt(accounts, tmp_path):
    create, _ = accounts
    c=create()
    run=ai_backend.prepare(c['id'],str(tmp_path))
    run.args=[sys.executable,'-c','print("extension failed to load")']
    async def consume(): return [line async for line in ai_backend.stream(run,'private prompt',maximum=2)]
    with pytest.raises(ValueError,match='policy did not load'): asyncio.run(consume())


def test_worker_dispatch_uses_connection_and_retains_legacy_model(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    c = create(tested=False)
    connections.set_default(c['id'])
    seen = []
    monkeypatch.setattr(paths, "WORKSPACE", tmp_path)
    extension = skills.manage("extend", "actor", tmp_path, paths.CORE_SKILLS_DIR)
    async def stream(run, prompt, **kwargs):
        assert f"actor: {paths.CORE_SKILLS_DIR / 'actor/SKILL.md'} then read additive instructions at {extension}" in prompt
        seen.append(run)
        yield json.dumps({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':'<task-output>{"status":"success","summary":"Checked"}</task-output>'}]}})
    monkeypatch.setattr(ai_backend,'stream',stream)
    task = task_config.TaskConfig(id='sample', skill='actor', dir=str(tmp_path), model='legacy-model')
    status, output, error, session = asyncio.run(scheduler.run_task(task))
    assert status == 'success' and output['summary'] == 'Checked' and not error
    assert seen[0].connection['id'] == c['id'] and seen[0].backend == 'pi'
    assert session == seen[0].session_id and task.model == 'legacy-model'


def test_plaintext_keyring_fallback_is_rejected(monkeypatch):
    import keyring
    monkeypatch.setattr(keyring,'get_keyring',lambda:object())
    with pytest.raises(ValueError,match='OS credential store'): connections._vault()


def test_mcp_configuration_preserves_project_scopes(tmp_path, monkeypatch):
    home, workspace = tmp_path/'home', tmp_path/'workspace'
    home.mkdir(); workspace.mkdir()
    monkeypatch.setattr(Path,'home',lambda:home)
    (home/'.claude.json').write_text(json.dumps({'mcpServers':{'global':{'command':'global-server'}},'projects':{str(workspace):{'mcpServers':{'local':{'command':'local-server'}}}}}))
    (workspace/'.mcp.json').write_text(json.dumps({'mcpServers':{'project':{'command':'project-server'}}}))
    assert set(ai_backend.mcp_config(str(workspace))['mcpServers']) == {'global','local','project'}


def test_opening_setup_before_connecting_does_not_bind_legacy_account(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    sessions = chat.SessionMap(tmp_path/'sessions.json')
    router = chat.ChatRouter(sessions,str(tmp_path))
    monkeypatch.setattr(app,'chat_router',router)
    monkeypatch.setattr(app,'load_tasks',lambda:[])
    first = json.loads(asyncio.run(app.api_ai_connections(item_id='setup')).body)
    assert first['selected'] == '' and not sessions._connections
    c=create(); connections.set_default(c['id'])
    after = json.loads(asyncio.run(app.api_ai_connections(item_id='setup')).body)
    assert after['selected'] == c['id'] and not sessions._connections
    assert sessions.connection('setup') == c['id']


@pytest.mark.parametrize('provider', ['anthropic', 'openai'])
def test_sign_in_cannot_replace_an_account_with_pending_approval(accounts, tmp_path, monkeypatch, provider):
    create, _ = accounts
    c=create(provider,auth='cli')
    router=chat.ChatRouter(chat.SessionMap(tmp_path/'sessions.json'),str(tmp_path))
    router._paused['send']={'connection':c['id'],'item_id':'x'}
    monkeypatch.setattr(app,'chat_router',router)
    monkeypatch.setattr(app,'load_tasks',lambda:[])
    result=asyncio.run(app.api_ai_operation({'id':c['id'],'operation':'login'}))
    assert result.status_code == 400 and 'pending approvals' in json.loads(result.body)['error']


def test_openai_account_auth_is_shared_between_workspaces_but_never_accounts(accounts, tmp_path, monkeypatch):
    create, secrets = accounts
    first, second = create(auth='cli'), create(auth='cli')
    monkeypatch.setenv('OPENAI_API_KEY', 'wrong-billing-route')
    a = ai_backend.prepare(first['id'], str(tmp_path / 'a'))
    b = ai_backend.prepare(first['id'], str(tmp_path / 'b'))
    other = ai_backend.prepare(second['id'], str(tmp_path / 'a'))
    assert not secrets and 'ChatGPT account' in first['billing']
    for run in (a, b, other):
        assert run.backend == 'pi' and run.args[run.args.index('--provider') + 1] == 'openai'
        assert 'OPENAI_API_KEY' not in run.env and not run.secret
    auth = connections.directory(first['id']) / 'pi/auth.json'
    auth.write_text('{"openai":{"type":"oauth","access":"fake-account-token"}}')
    for run in (a, b):
        linked = Path(run.env['PI_CODING_AGENT_DIR']) / 'auth.json'
        assert linked.is_symlink() and linked.resolve() == auth
        assert 'fake-account-token' in linked.read_text()
    assert 'fake-account-token' not in (Path(other.env['PI_CODING_AGENT_DIR']) / 'auth.json').read_text()
    assert 'fake-account-token' not in connections.CONNECTIONS_FILE.read_text()
    assert auth.stat().st_mode & 0o777 == 0o600
    linked.unlink(); linked.symlink_to(connections.directory(second['id']) / 'pi/auth.json')
    with pytest.raises(ValueError, match='another connection'):
        ai_backend.prepare(first['id'], str(tmp_path / 'b'))
    auth.unlink(); auth.symlink_to(tmp_path / 'outside-auth.json')
    with pytest.raises(ValueError, match='authentication storage'):
        ai_backend.connection_env(first)


@pytest.mark.parametrize('exit_code', [0, 1])
def test_openai_login_uses_private_terminal_and_logout_same_auth_store(accounts, tmp_path, monkeypatch, exit_code):
    create, _ = accounts
    first, second = create(auth='cli'), create(auth='cli')
    other_auth = Path(ai_backend.connection_env(second)['PI_CODING_AGENT_DIR']) / 'auth.json'
    other_auth.write_text('{"untouched":true}')
    binary = tmp_path / 'fake-pi'
    binary.write_text(f'''#!{sys.executable}
import os,sys,pathlib
assert sys.argv[1:3] in (['auth','login'], ['auth','logout'])
assert sys.argv[3:] == ['openai']
assert 'OPENAI_API_KEY' not in os.environ
auth = pathlib.Path(os.environ['PI_CODING_AGENT_DIR']) / 'auth.json'
if sys.argv[2] == 'login':
    assert os.isatty(0) and os.isatty(1)
    print('private-auth-output' * 10000, flush=True)
    if {exit_code} == 0: auth.write_text('{{"openai":{{"type":"oauth","access":"fake"}}}}')
    sys.exit({exit_code})
auth.write_text('{{}}')
''')
    binary.chmod(0o700)
    monkeypatch.setattr(ai_runtime, 'find', lambda runtime: str(binary) if runtime == 'pi' else '')
    monkeypatch.setattr(ai_settings, 'jobs', {})
    monkeypatch.setattr(app, 'chat_router', None)
    monkeypatch.setattr(app, 'load_tasks', lambda: [])
    asyncio.run(ai_settings.run_operation(first['id'], 'login'))
    assert ai_settings.jobs[first['id']]['status'] == ('error' if exit_code else 'success')
    assert 'private-auth-output' not in json.dumps(ai_settings.jobs)
    if not exit_code:
        run = ai_backend.prepare(first['id'], str(tmp_path))
        assert 'fake' in (Path(run.env['PI_CODING_AGENT_DIR']) / 'auth.json').read_text()
        result = asyncio.run(app.api_ai_disconnect(first['id']))
        assert result.status_code == 200
        assert (Path(run.env['PI_CODING_AGENT_DIR']) / 'auth.json').read_text() == '{}'
        assert not connections.get(first['id'], connected=False)['connected']
    assert other_auth.read_text() == '{"untouched":true}'


def test_openai_login_cancellation_reaps_process_and_closes_terminal(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    c = create(auth='cli')
    binary = tmp_path / 'waiting-pi'
    marker = tmp_path / 'pid'
    binary.write_text(f'#!{sys.executable}\nimport os,time,pathlib\npathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n')
    binary.chmod(0o700)
    monkeypatch.setattr(ai_runtime, 'find', lambda runtime: str(binary))
    monkeypatch.setattr(ai_settings, 'jobs', {})
    fds, openpty = [], os.openpty
    def record_terminal():
        pair = openpty(); fds.extend(pair); return pair
    monkeypatch.setattr(os, 'openpty', record_terminal)
    async def cancel():
        task = asyncio.create_task(ai_settings.run_operation(c['id'], 'login'))
        try:
            async with asyncio.timeout(3):
                while not marker.exists(): await asyncio.sleep(.01)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(cancel())
    assert ai_settings.jobs[c['id']]['status'] == 'interrupted'
    with pytest.raises(ProcessLookupError): os.kill(int(marker.read_text()), 0)
    for fd in fds:
        with pytest.raises(OSError): os.fstat(fd)


def test_openai_sign_ins_do_not_compete_for_browser_callback(accounts, monkeypatch):
    create, _ = accounts
    first, second = create(auth='cli'), create(auth='cli')
    monkeypatch.setattr(app, 'chat_router', None)
    monkeypatch.setattr(app, 'load_tasks', lambda: [])
    monkeypatch.setattr(ai_settings, 'jobs', {first['id']: {'operation':'login', 'status':'running'}})
    response = asyncio.run(app.api_ai_operation({'id':second['id'], 'operation':'login'}))
    assert response.status_code == 400 and 'other OpenAI sign-in' in json.loads(response.body)['error']


@pytest.mark.parametrize('runtime', ['claude', 'pi'])
def test_find_uses_newest_install_without_version_locks(runtime, tmp_path, monkeypatch):
    managed = tmp_path / 'managed'
    monkeypatch.setattr(ai_runtime, 'RUNTIME_ROOT', managed)
    user = str(tmp_path / 'user-bin' / runtime)
    monkeypatch.setattr(ai_runtime.shutil, 'which', lambda name: user)
    older = ai_runtime.binary_path(managed, runtime, '1.0.0')
    newer = ai_runtime.binary_path(managed, runtime, '999.1.0')
    for binary in (older, newer):
        binary.parent.mkdir(parents=True)
        binary.write_text('x')
    found = {user: '2.0.0', str(older): '1.0.0', str(newer): '999.1.0'}
    monkeypatch.setattr(ai_runtime, 'version', lambda binary: found.get(binary, ''))
    assert ai_runtime.find(runtime) == str(newer)
    found[user] = '999.1.0'
    assert ai_runtime.find(runtime) == user
    found[user] = '1000.0.0'
    assert ai_runtime.find(runtime) == user
    found[user] = ''
    newer.unlink()
    assert ai_runtime.find(runtime) == str(older)


def test_describe_reports_managed_or_user_install(tmp_path, monkeypatch):
    managed = tmp_path / 'managed'
    monkeypatch.setattr(ai_runtime, 'RUNTIME_ROOT', managed)
    user = str(tmp_path / 'user-bin/claude')
    monkeypatch.setattr(ai_runtime.shutil, 'which', lambda name: user)
    binary = ai_runtime.binary_path(managed, 'claude', '3.0.0')
    binary.parent.mkdir(parents=True)
    binary.write_text('x')
    monkeypatch.setattr(ai_runtime, 'version', lambda b: '3.0.0' if b == str(binary) else '2.1.319')
    assert ai_runtime.describe('claude') == {'installed': True, 'version': '3.0.0', 'source': 'managed'}
    binary.unlink()
    assert ai_runtime.describe('claude')['source'] == 'yours'
    monkeypatch.setattr(ai_runtime, 'version', lambda b: '')
    assert ai_runtime.describe('claude') == {'installed': False, 'version': '', 'source': ''}


def test_ssl_context_falls_back_to_system_certificates(monkeypatch):
    loaded = []
    verify = type('V', (), {'cafile': '/bundled/missing/cert.pem', 'capath': None})()
    monkeypatch.setattr(ai_runtime.ssl, 'get_default_verify_paths', lambda: verify)
    monkeypatch.setattr(Path, 'exists', lambda path: str(path) in ('/etc/ssl/cert.pem', '/bundled/cert.pem'))
    class Context:
        def load_verify_locations(self, cafile): loaded.append(cafile)
    monkeypatch.setattr(ai_runtime.ssl, 'create_default_context', lambda: Context())
    ai_runtime._ssl_context()
    assert loaded == ['/etc/ssl/cert.pem']
    loaded.clear()
    verify.cafile = '/bundled/cert.pem'
    ai_runtime._ssl_context()
    assert loaded == []


def test_system_auth_only_for_anthropic(accounts):
    c = connections.create({'provider': 'anthropic', 'auth': 'system'})
    assert c['auth'] == 'system' and 'Claude Code sign-in' in c['billing']
    with pytest.raises(ValueError):
        connections.create({'provider': 'openai', 'auth': 'system'})


def test_system_connection_uses_the_users_own_claude_login(accounts, tmp_path, monkeypatch):
    c = connections.create({'provider': 'anthropic', 'auth': 'system'})
    connections.update(c['id'], tested=True)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'inherited-key')
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', '/wrong-account')
    run = ai_backend.prepare(c['id'], str(tmp_path), probe=True)
    assert run.backend == 'claude'
    assert 'CLAUDE_CONFIG_DIR' not in run.env
    assert 'CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST' not in run.env
    assert 'ANTHROPIC_API_KEY' not in run.env


def test_system_connection_is_offered_once_and_respects_opt_out(accounts, tmp_path, monkeypatch):
    offered = asyncio.run(connections.offer_system())
    assert offered['auth'] == 'system' and offered['provider'] == 'anthropic'
    assert offered['label'] == 'Claude Code' and not offered['tested']
    assert asyncio.run(connections.offer_system()) is None
    data = connections.load()
    data['connections'] = [c for c in data['connections'] if c['id'] != offered['id']]
    connections.save(data)
    assert asyncio.run(connections.offer_system()) is None
    monkeypatch.setattr(connections, 'CONNECTIONS_FILE', tmp_path / 'fresh.json')
    monkeypatch.setattr(ai_runtime, 'find', lambda runtime: '')
    assert asyncio.run(connections.offer_system()) is None


@pytest.mark.parametrize('choose_during_test', [False, True])
def test_successful_test_respects_default(accounts, monkeypatch, choose_during_test):
    c = connections.create({'provider': 'anthropic', 'auth': 'system'})
    other = accounts[0](tested=False)
    async def stream(run, prompt, **kwargs):
        if choose_during_test:
            assert (await app.api_ai_default({'connection': other['id']})).status_code == 200
        nonce = Path(re.search(r'read (\S+\.txt)', prompt).group(1)).read_text()
        yield json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': nonce}]}}) + '\n'
        yield json.dumps({'type': 'result', 'result': nonce}) + '\n'
    monkeypatch.setattr(ai_backend, 'stream', stream)
    result = asyncio.run(ai_backend.test_connection(c['id']))
    assert result['tested'] and connections.load()['default'] == (other if choose_during_test else c)['id']


def test_login_operation_rejected_for_system_connections(accounts, monkeypatch):
    c = connections.create({'provider': 'anthropic', 'auth': 'system'})
    monkeypatch.setattr(app, 'chat_router', None)
    monkeypatch.setattr(app, 'load_tasks', lambda: [])
    result = asyncio.run(app.api_ai_operation({'id': c['id'], 'operation': 'login'}))
    assert result.status_code == 400 and 'own Claude Code sign-in' in json.loads(result.body)['error']


def test_install_ssl_failure_reports_certificate_error(accounts, monkeypatch):
    import urllib.error
    def fail(runtime, root=None):
        raise urllib.error.URLError(ai_runtime.ssl.SSLError('certificate verify failed'))
    monkeypatch.setattr(ai_runtime, 'install', fail)
    monkeypatch.setattr(ai_settings, 'jobs', {})
    asyncio.run(ai_settings.run_operation('claude', 'install'))
    job = ai_settings.jobs['claude']
    assert job['status'] == 'error' and 'certificates' in job['error']


def test_connections_carry_no_model_and_legacy_model_is_ignored(accounts):
    create, _ = accounts
    c = create('anthropic', auth='system')
    assert 'model' not in c
    data = json.loads(connections.CONNECTIONS_FILE.read_text())
    data['connections'][0]['model'] = 'gpt-5.4'
    connections.CONNECTIONS_FILE.write_text(json.dumps(data))
    assert 'model' not in connections.load()['connections'][0]
    changed = connections.change(c['id'], {'label': 'Renamed', 'model': 'opus'})
    assert 'model' not in changed and 'model' not in connections.get(c['id'])
    assert 'model' not in connections.CONNECTIONS_FILE.read_text()


def test_system_offer_has_no_model(accounts, tmp_path, monkeypatch):
    monkeypatch.setattr(connections, 'CONNECTIONS_FILE', tmp_path / 'fresh.json')
    assert 'model' not in asyncio.run(connections.offer_system())


def test_prepare_model_resolution(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    claude = create('anthropic', auth='system')
    pi = create('openai')
    monkeypatch.delenv('CLAUDE_MODEL', raising=False)
    explicit = ai_backend.prepare(claude['id'], str(tmp_path), model='haiku')
    assert explicit.model == 'haiku' and explicit.args[explicit.args.index('--model') + 1] == 'haiku'
    default = ai_backend.prepare(claude['id'], str(tmp_path))
    assert default.model == '' and '--model' not in default.args and '--effort' not in default.args
    monkeypatch.setenv('CLAUDE_MODEL', 'sonnet')
    assert ai_backend.prepare(claude['id'], str(tmp_path)).model == 'sonnet'
    run = ai_backend.prepare(pi['id'], str(tmp_path), model='gpt-5-mini')
    assert run.model == 'gpt-5-mini' and run.args[run.args.index('--model') + 1] == 'gpt-5-mini'
    assert ai_backend.prepare(pi['id'], str(tmp_path)).model == 'gpt-5.4'
    with pytest.raises(ValueError):
        ai_backend.prepare(claude['id'], str(tmp_path), model='-flag')
    monkeypatch.setattr(ai_runtime, 'default_model', lambda provider: '')
    with pytest.raises(ValueError, match='model in Settings'):
        ai_backend.prepare(pi['id'], str(tmp_path))
    with pytest.raises(ValueError, match='worker in its settings'):
        ai_backend.prepare(pi['id'], str(tmp_path), subject='worker')
    assert ai_backend.prepare(pi['id'], str(tmp_path), model='gpt-5-mini').model == 'gpt-5-mini'


def test_session_map_models_read_old_formats_and_follow_provider(accounts, tmp_path):
    create, _ = accounts
    claude = create('anthropic', auth='system')
    pi = create('openai')
    sid = '11111111-1111-4111-8111-111111111111'
    path = tmp_path / 'sessions.json'
    path.write_text(json.dumps({'old': sid, 'two': {'session_id': sid, 'connection': pi['id']},
                                'three': {'session_id': sid, 'connection': pi['id'], 'model': 'gpt-5-mini'}}))
    sessions = chat.SessionMap(path)
    assert [sessions.model(k) for k in ('old', 'two', 'three')] == ['', '', 'gpt-5-mini']
    sessions.set_model('two', 'gpt-5.4')
    assert chat.SessionMap(path).model('two') == 'gpt-5.4'
    sessions.set_model('two', '')
    assert chat.SessionMap(path).model('two') == ''
    sessions.bind('three', claude['id'])
    assert sessions.model('three') == ''
    sessions.set_model('three', 'opus')
    sessions.bind('three', claude['id'])
    assert sessions.model('three') == 'opus'
    assert chat.SessionMap(path).model('three') == 'opus'


def test_chat_model_endpoint(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    create('anthropic', auth='system')
    pi = create('openai')
    sessions = chat.SessionMap(tmp_path / 'sessions.json')
    router = chat.ChatRouter(sessions, str(tmp_path))
    monkeypatch.setattr(app, 'chat_router', router)
    sessions.bind('chat:111111111111', pi['id'])
    call = lambda model, item='chat:111111111111': asyncio.run(app.api_ai_chat_model({'item_id': item, 'model': model}))
    assert call('gpt-5-mini').status_code == 200 and sessions.model('chat:111111111111') == 'gpt-5-mini'
    assert call('sonnet').status_code == 400 and sessions.model('chat:111111111111') == 'gpt-5-mini'
    assert call('').status_code == 200 and sessions.model('chat:111111111111') == ''
    class Live:
        def done(self): return False
    router._active_runs['chat:111111111111'] = Live()
    assert call('gpt-5-mini').status_code == 409
    router._active_runs.clear()


HANDSHAKE = {'type': 'control_response', 'response': {'response': {'models': [
    {'value': 'default', 'resolvedModel': 'claude-opus-5-5', 'displayName': 'Default (recommended)',
     'description': 'Opus 5.5 \u00b7 Best for everyday, complex tasks', 'supportsEffort': True,
     'supportedEffortLevels': ['low', 'medium', 'high']},
    {'value': 'opus', 'resolvedModel': 'claude-opus-5-5', 'displayName': 'Opus 5.5', 'description': 'Complex work',
     'supportsEffort': True, 'supportedEffortLevels': ['low', 'medium', 'high']},
    {'value': 'claude-haiku-4-5-20251001', 'displayName': 'Haiku 4.5', 'description': 'Fast'}]}}}


def fake_claude(monkeypatch, calls=None, fail=False):
    async def create(*args, **kwargs):
        if calls is not None: calls.append(args)
        class Stdin:
            def write(self, data): pass
            async def drain(self): pass
            def close(self): pass
            def is_closing(self): return False
        class Stdout:
            def __init__(self): self.lines = [] if fail else [(json.dumps(HANDSHAKE) + '\n').encode()]
            async def readline(self): return self.lines.pop(0) if self.lines else b''
        class Proc:
            pid = 0; returncode = 0; stdin = Stdin(); stdout = Stdout()
            async def wait(self): return 0
        return Proc()
    monkeypatch.setattr(ai_backend.asyncio, 'create_subprocess_exec', create)
    async def no_terminate(proc): pass
    monkeypatch.setattr(ai_backend, 'terminate', no_terminate)
    ai_runtime.CLAUDE_MODELS.clear()


def test_claude_handshake_parsed_cached_and_refreshable(accounts, monkeypatch):
    create, _ = accounts
    c = create('anthropic', auth='system')
    calls = []
    fake_claude(monkeypatch, calls)
    first = asyncio.run(ai_backend.claude_models(c['id']))
    assert first['default']['description'].startswith('Opus 5.5')
    assert [m['value'] for m in first['models']] == ['opus', 'claude-haiku-4-5-20251001']
    argv = calls[0]
    assert '--setting-sources' in argv and argv[argv.index('--setting-sources') + 1] == ''
    asyncio.run(ai_backend.claude_models(c['id']))
    assert len(calls) == 1
    asyncio.run(ai_backend.claude_models(c['id'], refresh=True))
    assert len(calls) == 2


def test_claude_models_fall_back_to_aliases_when_handshake_fails(accounts, monkeypatch):
    create, _ = accounts
    c = create('anthropic', auth='system')
    fake_claude(monkeypatch, fail=True)
    listing = asyncio.run(ai_backend.claude_models(c['id']))
    assert listing['fallback'] and [m['value'] for m in listing['models']] == ['fable', 'opus', 'sonnet', 'haiku']
    assert c['id'] not in ai_runtime.CLAUDE_MODELS
    data = json.loads(asyncio.run(app.api_ai_models(connection=c['id'])).body)
    assert [m['id'] for m in data['models']] == ['fable', 'opus', 'sonnet', 'haiku'] and "couldn't list" in data['error']


def test_models_endpoint_lists_default_and_choices(accounts, monkeypatch):
    create, _ = accounts
    claude = create('anthropic', auth='system')
    fake_claude(monkeypatch)
    monkeypatch.delenv('CLAUDE_MODEL', raising=False)
    for connection in (claude['id'],):
        data = json.loads(asyncio.run(app.api_ai_models(connection=connection)).body)
        assert data['default'] == '' and data['default_label'] == 'Opus 5.5'
        assert [m['id'] for m in data['models']] == ['opus', 'claude-haiku-4-5-20251001']
        assert data['models'][0]['efforts'] == ['low', 'medium', 'high'] and data['models'][1]['efforts'] == []
    monkeypatch.setenv('CLAUDE_MODEL', 'opus@high')
    assert json.loads(asyncio.run(app.api_ai_models(connection=claude['id'])).body)['default'] == 'opus@high'
    data = json.loads(asyncio.run(app.api_ai_models(provider='openai')).body)
    assert data['default'] == 'gpt-5.4' and [m['id'] for m in data['models']] == ['gpt-5.4', 'gpt-5-mini', 'openai/gpt-5.4']


def test_model_choices_validate_against_the_harness_list(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    claude, pi = create('anthropic', auth='system'), create('openai')
    fake_claude(monkeypatch)
    check = lambda provider, model, key='', current='': asyncio.run(ai_settings.validate_model(provider, model, key, current))
    check('anthropic', 'opus@high', claude['id'])
    check('anthropic', 'claude-opus-5-5', claude['id'])
    with pytest.raises(ValueError, match="doesn't offer"):
        check('anthropic', 'sonnet', claude['id'])
    with pytest.raises(ValueError, match='effort'):
        check('anthropic', 'claude-haiku-4-5-20251001@high', claude['id'])
    with pytest.raises(ValueError, match='effort'):
        check('anthropic', 'opus@max', claude['id'])
    check('anthropic', 'sonnet', claude['id'], current='sonnet')
    check('openai', 'gpt-5-mini', pi['id'])
    with pytest.raises(ValueError, match="isn't offered"):
        check('openai', 'gpt-4', pi['id'])
    fake_claude(monkeypatch, fail=True)
    check('anthropic', 'haiku', claude['id'])
    with pytest.raises(ValueError):
        check('anthropic', 'claude-opus-5-5', claude['id'])


def test_chat_model_endpoint_checks_the_list_and_effort(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    claude = create('anthropic', auth='system')
    fake_claude(monkeypatch)
    sessions = chat.SessionMap(tmp_path / 'sessions.json')
    monkeypatch.setattr(app, 'chat_router', chat.ChatRouter(sessions, str(tmp_path)))
    sessions.bind('chat:111111111111', claude['id'])
    call = lambda model: asyncio.run(app.api_ai_chat_model({'item_id': 'chat:111111111111', 'model': model})).status_code
    assert call('opus@high') == 200 and sessions.model('chat:111111111111') == 'opus@high'
    assert call('sonnet') == 400
    assert call('opus@max') == 400


def test_account_lists_only_its_latest_ten_chats(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    claude, pi = create('anthropic', auth='system'), create('openai')
    sessions = chat.SessionMap(tmp_path / 'sessions.json')
    topics_path = tmp_path / 'topics.json'
    monkeypatch.setattr(app, 'chat_router', chat.ChatRouter(sessions, str(tmp_path), topic_store=chat.TopicStore(topics_path)))
    monkeypatch.setattr(app, 'load_tasks', lambda: [])
    ids = [f'chat:{n:012d}' for n in range(12)]
    for item in ids:
        sessions._connections[item] = claude['id']
    sessions._connections['chat:other'] = pi['id']
    now = datetime.now(timezone.utc)
    order = [5, 0, 9, 2, 7, 1, 10, 3, 8, 4, 6]
    topics = {ids[n]: {'title': f'Title {n}', 'last_active': (now - timedelta(minutes=rank)).isoformat()}
              for rank, n in enumerate(order)}
    topics['chat:other'] = {'title': 'Other', 'last_active': now.isoformat()}
    topics_path.write_text(json.dumps(topics))
    affected = app.connection_affected(claude['id'])
    assert affected['chat_count'] == 12
    assert affected['chats'] == [ids[n] for n in order[:10]]
    assert ids[11] not in affected['chats'] and 'chat:other' not in affected['chats']
    assert set(affected['chat_titles']) == set(affected['chats'])


def test_connection_workers_pick_a_valid_model(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    claude, pi = create('anthropic', auth='system'), create('openai')
    seen = []
    async def stream(run, prompt, **kwargs):
        seen.append(run.model)
        yield json.dumps({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':'<task-output>{"status":"success","summary":"ok"}</task-output>'}]}}) + '\n'
    monkeypatch.setattr(ai_backend, 'stream', stream)
    for task in (task_config.TaskConfig(id='a', skill='actor', dir=str(tmp_path), connection=claude['id'], model='haiku'),
                 task_config.TaskConfig(id='b', skill='actor', dir=str(tmp_path), connection=pi['id'], model='gpt-5-mini'),
                 task_config.TaskConfig(id='c', skill='actor', dir=str(tmp_path), connection=pi['id'], model='composer-2-fast')):
        asyncio.run(scheduler.run_task(task))
    assert seen == ['haiku', 'gpt-5-mini', 'gpt-5.4']


def test_worker_settings_write_the_connection_model_field(accounts, tmp_path, monkeypatch):
    from test_runner import make_runner
    create, _ = accounts
    claude, pi = create('anthropic', auth='system', tested=False), create('openai', tested=False)
    connections.set_default(pi['id'])
    tasks_file = tmp_path / 'tasks.yaml'
    tasks_file.write_text('tasks:\n  - id: local\n    skill: skill\n')
    task = task_config.TaskConfig(id='local', skill='skill')
    runner = make_runner(tmp_path, [task], lambda _task: None)
    runner._tasks = runner._load_tasks()
    runner._states[task.id] = runner._load_state(task)
    runner._triggers[task.id] = asyncio.Event()
    runner.set_settings('local', {'connection_model': 'gpt-5-mini'})
    assert '    model: gpt-5-mini' in tasks_file.read_text()
    assert 'connection:' not in tasks_file.read_text()
    runner.set_settings('local', {'connection': claude['id'], 'connection_model': 'haiku'})
    assert '    model: haiku' in tasks_file.read_text()
    with pytest.raises(ValueError):
        runner.set_settings('local', {'connection_model': 'bad model;'})
    runner.set_settings('local', {'connection_model': ''})
    assert 'model:' not in tasks_file.read_text()


def test_providers_hardcode_no_models():
    assert all(not {'model', 'models'} & set(info) for info in connections.PROVIDERS.values())


def test_pi_default_comes_from_pis_own_get_state(monkeypatch):
    monkeypatch.setattr(ai_runtime, 'find', lambda runtime: '/managed/pi')
    seen = {}
    def run(args, **kwargs):
        seen.update(env=kwargs['env'], input=kwargs['input'])
        line = json.dumps({'id': 'state', 'type': 'response', 'data': {'model': {'provider': 'openai', 'id': 'gpt-6.1-sol'}}})
        return subprocess.CompletedProcess(args, 0, stdout='noise\n' + line + '\n', stderr='')
    monkeypatch.setattr(ai_runtime.subprocess, 'run', run)
    ai_runtime.default_model.cache_clear()
    try:
        assert ai_runtime.default_model('openai') == 'gpt-6.1-sol'
        assert 'OPENAI_API_KEY' in seen['env']
        assert 'OPENROUTER_API_KEY' not in seen['env']
        assert ai_runtime.default_model('ollama') == ''
    finally:
        ai_runtime.default_model.cache_clear()


def test_cursor_connection_runs_with_its_key_and_private_config(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    cursor = create('cursor')
    monkeypatch.setenv('CURSOR_API_KEY', 'inherited-cursor-key')
    monkeypatch.setattr(ai_backend, 'mcp_config', lambda workspace: {'mcpServers': {workspace: {}}})
    monkeypatch.setattr(ai_backend.ai_runtime, 'find', lambda runtime: '/x/agent' if runtime == 'cursor' else '')
    run = ai_backend.prepare(cursor['id'], str(tmp_path))
    assert run.backend == 'cursor' and run.session_id == ''  # Cursor names its own chat on the first turn
    assert run.args[0] == '/x/agent' and '--model' not in run.args and '--resume' not in run.args
    assert run.env['CURSOR_API_KEY'] == run.secret == 'first-test-key'
    open_ = ai_backend.prepare(cursor['id'], str(tmp_path), model='gpt-6', session_id='chat-1', profile='unrestricted')
    assert open_.args[open_.args.index('--model') + 1] == 'gpt-6' and open_.args[open_.args.index('--resume') + 1] == 'chat-1'
    other = ai_backend.prepare(cursor['id'], str(tmp_path / 'other'))
    shared = connections.directory(cursor['id']) / 'cursor/chats'
    for prepared in (run, open_, other):
        config = Path(prepared.env['CURSOR_CONFIG_DIR'])
        assert config.parent == shared.parent
        assert (config / 'chats').samefile(shared)
        deny = json.loads((config / 'cli-config.json').read_text())['permissions']['deny']
        assert ('Shell(git:push*)' in deny) == (prepared is not open_)
        for root in (connections.CONNECTIONS_DIR.resolve(), ai_runtime.RUNTIME_ROOT.resolve()):
            assert {f'Read({root}/**)', f'Write({root}/**)'} <= set(deny)
        assert json.loads((config / 'mcp.json').read_text()) == {'mcpServers': {prepared.workspace: {}}}


def test_cursor_cancel_during_create_chat_cleans_only_its_run(accounts, tmp_path, monkeypatch):
    cursor = accounts[0]('cursor')
    started = asyncio.Event()

    async def create_chat(binary, env, workspace):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(ai_backend.cursor_agent, 'create_chat', create_chat)

    async def exercise():
        first = ai_backend.prepare(cursor['id'], str(tmp_path))
        turn = asyncio.create_task(anext(ai_backend.stream(first, 'test')))
        await asyncio.wait_for(started.wait(), timeout=5)
        second = ai_backend.prepare(cursor['id'], str(tmp_path))
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
        assert not Path(first.env['CURSOR_CONFIG_DIR']).exists()
        assert (Path(second.env['CURSOR_CONFIG_DIR']) / 'mcp.json').is_file()

    asyncio.run(exercise())


def test_cursor_rejects_redirected_chat_storage(accounts, tmp_path):
    cursor = accounts[0]('cursor')
    ai_backend.connection_env(cursor)
    (connections.directory(cursor['id']) / 'cursor/chats').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='Invalid Cursor chat storage'):
        ai_backend.prepare(cursor['id'], str(tmp_path))


def test_cursor_new_session_uses_selected_key(accounts, tmp_path, monkeypatch):
    cursor = accounts[0]('cursor')
    monkeypatch.setenv('CURSOR_API_KEY', 'inherited-cursor-key')

    async def create_chat(binary, env, workspace):
        assert env['CURSOR_API_KEY'] == 'first-test-key'
        return 'chat-1'

    monkeypatch.setattr(ai_backend.cursor_agent, 'create_chat', create_chat)
    assert asyncio.run(ai_backend.new_session(cursor['id'], str(tmp_path))) == 'chat-1'


def test_signed_in_reads_pi_auth_without_exposing_tokens(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    c = create(auth='cli')
    auth = connections.directory(c['id']) / 'pi/auth.json'
    ai_backend.connection_env(c)
    assert ai_backend.signed_in(c) is False
    auth.write_text('{}')
    assert ai_backend.signed_in(c) is False
    auth.write_text('{"openai":{"type":"oauth","access":"","refresh":"secret-refresh-token"}}')
    assert ai_backend.signed_in(c) is True
    monkeypatch.setattr(app, 'chat_router', None)
    monkeypatch.setattr(app, 'load_tasks', lambda: [])
    response = asyncio.run(app.api_ai_connections())
    row = json.loads(response.body)['connections'][0]
    assert row['signed_in'] is True and 'secret-refresh-token' not in response.body.decode()
    assert 'signed_in' not in json.loads(connections.CONNECTIONS_FILE.read_text())['connections'][0]
    outside = tmp_path / 'outside.json'
    outside.write_text('{"openai":{"refresh":"x"}}')
    auth.unlink(); auth.symlink_to(outside)
    assert ai_backend.signed_in(c) is False


def test_signed_in_is_unknown_for_other_auth_methods(accounts):
    create, _ = accounts
    assert ai_backend.signed_in(create(key='k')) is None
    assert ai_backend.signed_in(create('anthropic', auth='system')) is None
    assert ai_backend.signed_in(create('anthropic', auth='cli')) is None


def test_settings_model_is_saved_and_scoped_to_provider(accounts, monkeypatch):
    create, _ = accounts
    c = create()
    monkeypatch.setattr(app, 'chat_router', None)
    async def ensure():
        pass
    monkeypatch.setattr(app, 'ensure_chat_router', ensure)
    result = asyncio.run(app.api_ai_default({'connection': c['id'], 'model': 'gpt-5-mini'}))
    assert result.status_code == 200
    assert connections.load()['default'] == c['id']
    assert connections.default_model('openai') == 'gpt-5-mini'
    assert connections.selected_model('anthropic') == ''
    assert connections.default_model('openrouter') == 'openai/gpt-5.4'
    before = connections.load()
    for model in ('not-offered', '', ['gpt-5-mini']):
        result = asyncio.run(app.api_ai_default({'connection': c['id'], 'model': model}))
        assert result.status_code == 400
        assert connections.load() == before
    untested = create(tested=False)
    result = asyncio.run(app.api_ai_default({'connection': untested['id'], 'model': 'gpt-5.4'}))
    assert result.status_code == 200
    assert connections.get()['id'] == untested['id']
    assert connections.default_model('openai') == 'gpt-5.4'


def test_settings_effort_validates_and_reaches_both_runtimes(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    pi = create()
    claude = create('anthropic', auth='system')
    monkeypatch.setattr(app, 'chat_router', None)
    async def ensure():
        pass
    async def listing(*args, **kwargs):
        return {'models': [{'value': 'sonnet', 'supportedEffortLevels': ['low', 'high']}], 'default': {}}
    monkeypatch.setattr(app, 'ensure_chat_router', ensure)
    monkeypatch.setattr(ai_backend, 'claude_models', listing)
    monkeypatch.setattr(ai_runtime, 'model_efforts', lambda provider, model: ['low', 'high', 'xhigh'])
    for c, model, effort, flag in [(pi, 'gpt-5.4', 'xhigh', '--thinking'), (claude, 'sonnet', 'high', '--effort')]:
        result = asyncio.run(app.api_ai_default({'connection': c['id'], 'model': model, 'effort': effort}))
        assert result.status_code == 200
        assert connections.selected_effort(c['provider'], model) == effort
        assert connections.selected_effort(c['provider'], 'another-model') == ''
        run = ai_backend.prepare(c['id'], str(tmp_path))
        assert run.args[run.args.index(flag) + 1] == effort
        assert run.args[run.args.index('--model') + 1] == model
        before = connections.load()
        for invalid in ('unsupported', ['high']):
            result = asyncio.run(app.api_ai_default({'connection': c['id'], 'model': model, 'effort': invalid}))
            assert result.status_code == 400
            assert connections.load() == before
        result = asyncio.run(app.api_ai_default({'connection': c['id'], 'model': model, 'effort': ''}))
        assert result.status_code == 200
        assert flag not in ai_backend.prepare(c['id'], str(tmp_path)).args


@pytest.mark.parametrize('levels,expected', [(['low', 'high', 'xhigh'], ['low', 'high', 'xhigh']), (['off'], [])])
def test_pi_effort_discovery_is_offline_and_has_no_prompt(monkeypatch, levels, expected):
    monkeypatch.setattr(ai_runtime, 'find', lambda runtime: '/mock/pi')
    def run(args, **kwargs):
        assert '--offline' in args and '--no-extensions' in args
        assert args[args.index('--model') + 1] == 'gpt-5.4'
        assert json.loads(kwargs['input'])['type'] == 'get_available_thinking_levels'
        assert kwargs['env']['OPENAI_API_KEY'] == 'catalogue-only'
        return subprocess.CompletedProcess(args, 0, json.dumps({'id': 'efforts', 'success': True, 'data': {'levels': levels}}), '')
    monkeypatch.setattr(subprocess, 'run', run)
    assert ai_runtime.model_efforts.__wrapped__('openai', 'gpt-5.4') == expected


def test_terminal_launch_quotes_paths_and_rejects_invalid_requests(accounts, tmp_path, monkeypatch):
    import shlex

    monkeypatch.setattr(app.sys, 'platform', 'darwin')
    workspace = tmp_path / "Work's $(touch nope); folder\nnext"
    binary = "/Applications/AI Tools/Pi's pi"
    monkeypatch.setattr(app.paths, 'WORKSPACE', workspace)
    monkeypatch.setattr(ai_runtime, 'find', lambda runtime: binary)
    seen = []
    async def command(*args):
        seen.append(args)
        return 'opened\n'
    monkeypatch.setattr(ai_settings, 'command_output', command)
    for runtime in ('claude', 'pi'):
        response = asyncio.run(app.api_ai_terminal({'id':runtime}))
        assert response.status_code == 200
        args = seen[-1]
        assert args[:2] == ('/usr/bin/osascript', '-e')
        assert 'do script (item 1 of argv)' in args[2]
        assert str(workspace) not in args[2]
        assert shlex.split(args[3]) == ['cd', '--', str(workspace), '&&', 'exec', binary]
    for invalid in ('other', 'pi; touch nope', [], None):
        assert asyncio.run(app.api_ai_terminal({'id':invalid})).status_code == 400
    assert len(seen) == 2
    monkeypatch.setattr(ai_runtime, 'find', lambda runtime: '')
    assert asyncio.run(app.api_ai_terminal({'id':'pi'})).status_code == 400
    monkeypatch.setattr(app.sys, 'platform', 'linux')
    assert asyncio.run(app.api_ai_terminal({'id':'pi'})).status_code == 400


def test_terminal_launch_handles_installation_and_automation_failure(accounts, monkeypatch):
    monkeypatch.setattr(app.sys, 'platform', 'darwin')
    async def fail(*args):
        return ''
    monkeypatch.setattr(ai_settings, 'command_output', fail)
    response = asyncio.run(app.api_ai_terminal({'id':'pi'}))
    assert response.status_code == 400 and b'automation permissions' in response.body
    monkeypatch.setattr(ai_runtime, 'INSTALLING', {'pi'})
    assert asyncio.run(app.api_ai_terminal({'id':'pi'})).status_code == 409


@pytest.mark.parametrize('runtime', ['pi', 'claude'])
def test_latest_release_uses_publisher_version_and_checksum(runtime, monkeypatch):
    checksum = 'a' * 64
    urls = []
    responses = [
        json.dumps({'tag_name':'v99.2.3', 'assets':[{'name':'pi-darwin-arm64.tar.gz','digest':'sha256:' + checksum}]}).encode()
    ] if runtime == 'pi' else [b'99.2.3\n', json.dumps({'version':'99.2.3','platforms':{'darwin-arm64':{'checksum':checksum}}}).encode()]
    def download(request, **kwargs):
        urls.append(request.full_url)
        return io.BytesIO(responses.pop(0))
    monkeypatch.setattr(ai_runtime.urllib.request, 'urlopen', download)
    release, url, digest = ai_runtime.latest_release(runtime, 'darwin-arm64')
    assert release == '99.2.3' and digest == checksum
    assert ('/v99.2.3/' if runtime == 'pi' else '/99.2.3/') in url
    assert urls[0].endswith('/latest')


@pytest.mark.parametrize('metadata', [
    {'tag_name':'v../../escape','assets':[{'name':'pi-darwin-arm64.tar.gz','digest':'sha256:'+'a'*64}]},
    {'tag_name':'v99.0.0','assets':[{'name':'pi-darwin-arm64.tar.gz','digest':'bad'}]},
    {'tag_name':'v99.0.0','assets':[]},
])
def test_latest_release_rejects_invalid_metadata(metadata, monkeypatch):
    monkeypatch.setattr(ai_runtime.urllib.request, 'urlopen', lambda *a,**k: io.BytesIO(json.dumps(metadata).encode()))
    with pytest.raises(ValueError):
        ai_runtime.latest_release('pi', 'darwin-arm64')


def test_version_detects_replaced_binary_without_restart(tmp_path):
    binary = tmp_path / 'pi'
    binary.write_text('#!/bin/sh\necho 1.0.0\n')
    binary.chmod(0o755)
    assert ai_runtime.version(str(binary)) == '1.0.0'
    binary.write_text('#!/bin/sh\necho 123.0.0\n')
    assert ai_runtime.version(str(binary)) == '123.0.0'


def test_latest_install_verifies_download_and_preserves_previous_version(tmp_path, monkeypatch):
    import hashlib
    import tarfile

    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:gz') as package:
        data = b'#!/bin/sh\necho 99.2.3\n'
        entry = tarfile.TarInfo('pi/pi')
        entry.size = len(data)
        package.addfile(entry, io.BytesIO(data))
    payload = archive.getvalue()
    monkeypatch.setattr(ai_runtime, 'latest_release', lambda *args: ('99.2.3','https://example.invalid/pi',hashlib.sha256(payload).hexdigest()))
    monkeypatch.setattr(ai_runtime.urllib.request, 'urlopen', lambda *a,**k: io.BytesIO(payload))
    previous = ai_runtime.binary_path(tmp_path, 'pi', '1.0.0')
    previous.parent.mkdir()
    previous.write_text('working')
    installed = ai_runtime.install('pi', tmp_path)
    assert installed == str(ai_runtime.binary_path(tmp_path, 'pi', '99.2.3'))
    assert ai_runtime.version(installed) == '99.2.3'
    assert previous.read_text() == 'working'


@pytest.mark.parametrize('existing_claude', [False, True])
def test_first_run_requires_default_before_workspace_setup(accounts, tmp_path, monkeypatch, existing_claude):
    create, _ = accounts
    monkeypatch.setattr(app.profile, 'load', lambda: app.profile.Profile())
    monkeypatch.setattr(app.paths, 'WORKSPACE', tmp_path)
    monkeypatch.setattr(app.paths, 'TASKS_FILE', tmp_path / 'tasks.yaml')
    router = chat.ChatRouter(chat.SessionMap(tmp_path/'sessions.json'), str(tmp_path))
    monkeypatch.setattr(app, 'chat_router', router)
    c = create('anthropic', auth='system', tested=False) if existing_claude else None
    card = board.setup_item(router)
    assert card['id'] == board.AI_SETUP_ITEM_ID
    assert card['action_owner'] == 'user'
    assert ('Claude Code' in card['title']) == existing_claude
    assert 'default account' in card['opening_move']
    assert not router._sessions._connections
    for item in (board.AI_SETUP_ITEM_ID, board.SETUP_ITEM_ID, 'chat:0123456789ab'):
        response = asyncio.run(app.api_board_chat({'item_id':item,'message':'hello'}))
        assert response.status_code == 503
        assert json.loads(response.body)['settings_url'] == '/settings#account-setup'
    assert not router._sessions._map and not router._sessions._connections
    # Cached model output cannot replace the deterministic prerequisite or show workspace setup early.
    monkeypatch.setattr(board, 'board_merges', lambda states, router=None: {})
    monkeypatch.setattr(board, 'roosta_engineer_item', lambda states: None)
    items, _ = board.collect_board_items([
        {'id':board.AI_SETUP_ITEM_ID, 'title':'wrong', 'action_owner':'assistant'},
        {'id':board.SETUP_ITEM_ID, 'title':'too early'},
    ], [], [])
    assert [i['id'] for i in items] == [board.AI_SETUP_ITEM_ID]
    assert items[0]['action_owner'] == 'user'
    # Choosing an untested account unlocks setup.
    assert board.setup_item(router)['id'] == board.AI_SETUP_ITEM_ID
    c = c or create(tested=False)
    connections.set_default(c['id'])
    assert board.setup_item(router)['id'] == board.SETUP_ITEM_ID
    data = json.loads(asyncio.run(app.api_ai_connections()).body)
    assert data['workspace_setup_ready'] is True
    assert data['workspace_setup_missing'] == ['your name in PROFILE.md', 'your priorities in PRIORITIES.md',
                                               'a starter schedule of workers']
    assert not router._sessions._connections
    assert router._sessions.connection(board.SETUP_ITEM_ID) == c['id']
    monkeypatch.setattr(router, 'handled', lambda: {board.SETUP_ITEM_ID: {'result': 'done', 'at': 'now'}})
    data = json.loads(asyncio.run(app.api_ai_connections()).body)
    assert data['workspace_setup_ready'] is False
    assert data['workspace_setup_missing'] == []
    monkeypatch.setattr(router, 'handled', lambda: {})
    # A named user with priorities and a schedule needs nothing, even with setup history present.
    monkeypatch.setattr(app.profile, 'load', lambda: app.profile.Profile(name='Sam'))
    monkeypatch.setattr(router, 'conversation_history', lambda item: [{'role': 'user'}], raising=False)
    (tmp_path / 'PRIORITIES.md').write_text('## My priorities\n\n1. Ship it\n')
    (tmp_path / 'tasks.yaml').write_text('tasks:\n  - id: t\n    skill: actor\n')
    assert board.setup_item(router)['id'] == board.SETUP_ITEM_ID
    data = json.loads(asyncio.run(app.api_ai_connections()).body)
    assert data['workspace_setup_ready'] is False
    assert data['workspace_setup_missing'] == []


def test_claude_detection_runs_before_the_board_and_starts_no_model(accounts, monkeypatch):
    events = []
    monkeypatch.setattr(app.activity, 'compact', lambda *a: None)
    monkeypatch.setattr(app, 'prune_cursor_session_stores', lambda: None)
    async def detect(): events.append('detect')
    monkeypatch.setattr(connections, 'offer_system', detect)
    monkeypatch.setattr(app.runner, 'start', lambda: events.append('runner'))
    async def router(): events.append('router')
    async def stop(): pass
    monkeypatch.setattr(app, '_start_chat_router', router)
    monkeypatch.setattr(app.runner, 'stop', stop)
    monkeypatch.setattr(ai_settings, 'job_tasks', {})
    async def run():
        async with app.lifespan(app.app):
            assert events == ['detect', 'runner', 'router']
    asyncio.run(run())


def test_established_workspace_is_not_forced_through_new_onboarding(accounts, monkeypatch):
    monkeypatch.setattr(app, 'chat_router', None)
    assert app.profile.load().name
    monkeypatch.setattr(board.ai_backend, 'connection_available', lambda *_: True)
    monkeypatch.setattr(board.ai_connections, 'get', lambda *_a, **_k: {'provider': 'anthropic'})
    assert board.setup_item() is None
    monkeypatch.setattr(board.ai_backend, 'connection_available', lambda *_: False)
    assert board.setup_item()['id'] == board.AI_SETUP_ITEM_ID  # workers need an AI connection even after setup


def test_first_run_guard_preserves_existing_conversation(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    c = create()
    monkeypatch.setattr(app.profile, 'load', lambda: app.profile.Profile())
    sessions = chat.SessionMap(tmp_path/'sessions.json')
    item_id = 'chat:0123456789ab'
    sessions.bind(item_id, c['id'])
    sessions.set(item_id, '11111111-1111-4111-8111-111111111111')
    router = chat.ChatRouter(sessions, str(tmp_path))
    monkeypatch.setattr(app, 'chat_router', router)
    monkeypatch.setattr(router, 'start_turn', lambda *args: chat.TurnHandle(queued=True, position=1))
    response = asyncio.run(app.api_board_chat({'item_id':item_id, 'message':'continue'}))
    assert response.status_code == 202
    assert sessions.connection(item_id) == c['id']
    assert sessions.get(item_id) == '11111111-1111-4111-8111-111111111111'


def test_first_run_local_ai_requires_a_model_before_workspace_setup(accounts, monkeypatch):
    create, _ = accounts
    monkeypatch.setattr(app.profile, 'load', lambda: app.profile.Profile())
    c = create('ollama', auth='local')
    connections.set_default(c['id'])
    assert board.setup_item()['id'] == board.AI_SETUP_ITEM_ID
    assert board.setup_item()['title'] == 'Choose your AI model'
    monkeypatch.setattr(ai_runtime, 'default_model', lambda provider: 'local-model')
    assert board.setup_item()['id'] == board.SETUP_ITEM_ID


def test_setup_gaps_read_priorities_and_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(app.profile, 'load', lambda: app.profile.Profile(name='Sam'))
    monkeypatch.setattr(app.paths, 'WORKSPACE', tmp_path)
    monkeypatch.setattr(board, 'load_tasks', lambda: ['task'])
    assert board.setup_gaps() == ['your priorities in PRIORITIES.md']
    skeleton = Path(app.paths.SKELETON_DIR) / 'PRIORITIES.md'
    (tmp_path / 'PRIORITIES.md').write_text(skeleton.read_text())
    assert board.setup_gaps() == ['your priorities in PRIORITIES.md']
    (tmp_path / 'PRIORITIES.md').write_text(skeleton.read_text().replace('\n1.\n', '\n1. Finish the report\n'))
    assert board.setup_gaps() == []
    (tmp_path / 'PRIORITIES.md').write_text('## My priorities\n<!-- - hidden -->\n\n- Second style\n\n## Other\n')
    assert board.setup_gaps() == []
    (tmp_path / 'PRIORITIES.md').write_text('## My priorities\n\n## Other\n1. not mine\n')
    assert board.setup_gaps() == ['your priorities in PRIORITIES.md']
    monkeypatch.setattr(board, 'load_tasks', lambda: [])
    assert board.setup_gaps() == ['your priorities in PRIORITIES.md', 'a starter schedule of workers']
    def broken():
        raise ValueError('bad yaml')
    monkeypatch.setattr(board, 'load_tasks', broken)
    assert board.setup_gaps() == ['your priorities in PRIORITIES.md']


@pytest.fixture
def setup_jobs(monkeypatch):
    monkeypatch.setattr(ai_settings, 'jobs', {})
    monkeypatch.setattr(ai_settings, 'job_tasks', {})


def test_cancel_before_start_and_stale_cancel_after_retry(accounts, setup_jobs, monkeypatch):
    key = accounts[0](tested=False)['id']
    calls = []
    async def probe(key):
        calls.append(key)
        raise ValueError('Diagnostic failed')
    monkeypatch.setattr(ai_backend, 'test_connection', probe)

    async def exercise():
        start = {'id': key, 'operation': 'test'}
        assert (await app.api_ai_operation(start)).status_code == 202
        first = {'run_id': ai_settings.jobs[key]['run_id']}
        assert (await app.api_ai_cancel_test(key, first)).status_code == 200
        assert calls == [] and ai_settings.jobs[key]['status'] == 'interrupted'
        assert (await app.api_ai_cancel_test(key, first)).status_code == 200

        assert (await app.api_ai_operation(start)).status_code == 202
        assert (await app.api_ai_cancel_test(key, first)).status_code == 409
        second = {'run_id': ai_settings.jobs[key]['run_id']}
        await ai_settings.job_tasks[key]
        assert (await app.api_ai_cancel_test(key, second)).status_code == 200
        assert calls == [key] and ai_settings.jobs[key]['status'] == 'error'
        assert (await app.api_ai_default({'connection': key})).status_code == 200
        assert ai_backend.connection_available() and connections.get()['id'] == key
    asyncio.run(exercise())


def test_cancel_joins_probe_process_group_and_preserves_other_work(accounts, setup_jobs, tmp_path, monkeypatch):
    key = accounts[0]('anthropic', auth='system', tested=True)['id']
    marker = tmp_path / 'pids'
    binary = tmp_path / 'probe'
    binary.write_text(f"""#!{sys.executable}
import os, pathlib, signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path({str(marker)!r}).write_text(f'{{os.getpid()}} {{child.pid}}')
time.sleep(30)
""")
    binary.chmod(0o700)
    monkeypatch.setattr(ai_runtime, 'find', lambda runtime: str(binary))
    cleanup_entered, release_cleanup = asyncio.Event(), asyncio.Event()
    kill_group = ai_backend.kill_group
    async def delayed_cleanup(proc):
        cleanup_entered.set()
        await release_cleanup.wait()
        await kill_group(proc)
    monkeypatch.setattr(ai_backend, 'kill_group', delayed_cleanup)

    async def exercise():
        start = {'id': key, 'operation': 'test'}
        other = await asyncio.create_subprocess_exec(sys.executable, '-c', 'import time; time.sleep(30)',
                                                      start_new_session=True)
        ai_backend.LIVE_PROCESSES.add(other)
        try:
            async with asyncio.timeout(8):
                await app.api_ai_operation(start)
                while not marker.exists() or not marker.read_text():
                    await asyncio.sleep(.01)
                run = {'run_id': ai_settings.jobs[key]['run_id']}
                cancel = asyncio.create_task(app.api_ai_cancel_test(key, run))
                await cleanup_entered.wait()
                repeat = asyncio.create_task(app.api_ai_cancel_test(key, run))
                await asyncio.sleep(0)
                assert ai_settings.jobs[key]['status'] == 'running'
                assert (await app.api_ai_operation(start)).status_code == 409
                release_cleanup.set()
                assert all(r.status_code == 200 for r in await asyncio.gather(cancel, repeat))
                assert ai_settings.jobs[key]['status'] == 'interrupted'
                assert connections.get(key)['tested']
                assert not ai_backend.ACTIVE_CONNECTIONS[key]
                assert other.returncode is None and other in ai_backend.LIVE_PROCESSES
                for pid in map(int, marker.read_text().split()):
                    while True:
                        try:
                            os.kill(pid, 0)
                        except ProcessLookupError:
                            break
                        await asyncio.sleep(.01)
        finally:
            release_cleanup.set()
            ai_backend.LIVE_PROCESSES.discard(other)
            await kill_group(other)
    asyncio.run(exercise())


@pytest.mark.parametrize('operation', ['install', 'login'])
def test_only_tests_can_be_cancelled(setup_jobs, operation):
    ai_settings.jobs['other'] = {'status':'running', 'operation':operation, 'run_id':'current'}
    response = asyncio.run(app.api_ai_cancel_test('other', {'run_id':'current'}))
    assert response.status_code == 409 and ai_settings.jobs['other']['status'] == 'running'


def test_account_choice_without_catalogue_and_chat_binding(accounts, tmp_path, monkeypatch):
    key = accounts[0]('anthropic', auth='system', tested=False)['id']
    sessions = chat.SessionMap(tmp_path / 'sessions.json')
    router = chat.ChatRouter(sessions, str(tmp_path))
    monkeypatch.setattr(app, 'chat_router', router)
    def unavailable(*args, **kwargs):
        pytest.fail('Account selection attempted model discovery or a diagnostic')
    monkeypatch.setattr(app, 'validate_model', unavailable)
    monkeypatch.setattr(connections, 'default_model', unavailable)
    monkeypatch.setattr(ai_backend, 'test_connection', unavailable)
    assert asyncio.run(app.api_ai_default({'connection': key})).status_code == 200
    body = {'connection': key, 'item_id':'test-chat'}
    assert asyncio.run(app.api_ai_chat_connection(body)).status_code == 200
    assert sessions.connection('test-chat') == key
    connections.update(key, connected=False)
    assert asyncio.run(app.api_ai_chat_connection(body)).status_code == 400
    assert asyncio.run(app.api_ai_default({'connection': key})).status_code == 400

def test_detecting_claude_during_explicit_default_choice(accounts, monkeypatch):
    other = accounts[0](tested=False)
    searching, proceed = threading.Event(), threading.Event()
    def find(runtime):
        searching.set()
        assert proceed.wait(5)
        return '/managed/claude'
    monkeypatch.setattr(ai_runtime, 'find', find)

    async def exercise():
        detect = asyncio.create_task(connections.offer_system())
        try:
            assert await asyncio.to_thread(searching.wait, 5)
            connections.set_default(other['id'])
        finally:
            proceed.set()
        assert (await detect)['auth'] == 'system'
        assert connections.get()['id'] == other['id']
    asyncio.run(exercise())


def test_cancel_while_subprocess_transport_is_starting(monkeypatch):
    created, deliver = asyncio.Event(), asyncio.Event()
    spawn = asyncio.create_subprocess_exec
    children = []
    async def slow_spawn(*args, **kwargs):
        children.append(await spawn(*args, **kwargs))
        created.set()
        await deliver.wait()
        return children[0]
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', slow_spawn)
    async def exercise():
        task = asyncio.create_task(ai_backend.spawn_group(sys.executable, '-c', 'import time; time.sleep(30)'))
        try:
            await asyncio.wait_for(created.wait(), 3)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            deliver.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
            assert children[0].returncode is not None
            with pytest.raises(ProcessLookupError):
                os.kill(children[0].pid, 0)
        finally:
            deliver.set()
            for child in children:
                if child.returncode is None:
                    await ai_backend.kill_group(child)
    asyncio.run(exercise())


def test_cursor_turn_creates_its_chat_and_takes_the_prompt_as_an_argument(accounts, tmp_path, monkeypatch):
    create, _ = accounts
    run = ai_backend.prepare(create('cursor')['id'], str(tmp_path))
    config = Path(run.env['CURSOR_CONFIG_DIR'])
    store = (config / 'chats').resolve()
    (store / 'existing-chat').touch()
    run.args = [sys.executable, '-c', 'import sys,json; print(json.dumps({"type":"result","result":sys.argv[1:]}))']
    async def create_chat(binary, env, workspace): return 'chat-9'
    monkeypatch.setattr(ai_backend.cursor_agent, 'create_chat', create_chat)
    async def consume(): return ''.join([line async for line in ai_backend.stream(run, 'the prompt', maximum=5)])
    assert json.loads(asyncio.run(consume()))['result'] == ['--resume', 'chat-9', 'the prompt']
    assert run.session_id == 'chat-9'
    assert not config.exists()
    assert (store / 'existing-chat').exists()
    assert connections.engine('cursor') == 'cursor' and connections.runtime('cursor', 'gpt-6') == 'cursor'
    with pytest.raises(ValueError):
        connections.runtime('cursor', 'bad model;')


def test_a_runtime_killed_by_a_signal_says_so(accounts, tmp_path):
    create, _ = accounts
    run = ai_backend.prepare(create()['id'], str(tmp_path))
    run.backend = 'claude'
    run.args = [sys.executable, '-c', 'import os, signal; os.kill(os.getpid(), signal.SIGKILL)']
    async def consume(): return [line async for line in ai_backend.stream(run, 'test', maximum=5)]
    with pytest.raises(ValueError, match='stopped by macOS'):
        asyncio.run(consume())


@pytest.fixture
def onboarding_runtimes(accounts, setup_jobs, tmp_path, monkeypatch):
    monkeypatch.setattr(app.profile, 'load', lambda: app.profile.Profile())
    monkeypatch.setattr(app, 'chat_router', None)
    monkeypatch.setattr(app, 'load_tasks', lambda: [])
    store = tmp_path / '.roosta/state/ai-connections.json'
    monkeypatch.setattr(connections, 'CONNECTIONS_FILE', store)
    installed = set()
    monkeypatch.setattr(ai_runtime, 'find', lambda name: f'/mock/{name}' if name in installed else '')
    monkeypatch.setattr(ai_runtime, 'version', lambda _: '1.0')
    monkeypatch.setattr(ai_backend, 'test_connection', lambda *_: pytest.fail('Unexpected AI test'))
    return installed


@pytest.mark.parametrize('runtime,account', [
    ('claude', {'provider': 'anthropic', 'auth': 'system'}),
    ('cursor', {'provider': 'cursor', 'auth': 'api_key', 'api_key': 'fixture-secret'}),
], ids=['claude-system', 'cursor-api-key'])
def test_first_account_setup_survives_reload_without_testing(onboarding_runtimes, tmp_path, runtime, account):
    installed = onboarding_runtimes
    installed.add(runtime)
    body = {**account, 'default_if_unset': True}
    created = json.loads(asyncio.run(app.api_ai_connection_create(body)).body)
    key = created['id']
    assert key == connections.load()['default']
    # A second window can submit its stale first-account form.
    assert asyncio.run(app.api_ai_connection_create({**body, 'label': 'Second'})).status_code == 201
    assert key == connections.load()['default']

    def check(ready):
        snapshot = asyncio.run(app.api_ai_connections())
        assert snapshot.status_code == 200 and b'fixture-secret' not in snapshot.body
        data = json.loads(snapshot.body)
        assert data['workspace_setup_ready'] is ready
        assert data['default'] == key and not data['connections'][0]['tested']
        assert board.setup_item()['id'] == (board.SETUP_ITEM_ID if ready else board.AI_SETUP_ITEM_ID)

    check(True)
    assert 'fixture-secret' not in connections.CONNECTIONS_FILE.read_text()
    # Cold startup against the same workspace, without a server or a credential store.
    subprocess.run([sys.executable, '-c', """
import asyncio, json, sys
from roosta import app, ai_runtime
runtime, key = sys.argv[1:]
ai_runtime.find = lambda name: f'/mock/{name}' if name == runtime else ''
ai_runtime.version = lambda _: '1.0'
settings = json.loads(asyncio.run(app.api_ai_connections()).body)
assert settings['default'] == key
assert settings['workspace_setup_ready']
board = json.loads(asyncio.run(app.api_board()).body)
assert [item['id'] for item in board['document']['items']] == [app.SETUP_ITEM_ID]
""", runtime, key], check=True, env={**os.environ, 'ROOSTA_WORKSPACE': str(tmp_path),
                        'HOME': str(tmp_path), 'PATH': str(tmp_path / 'empty-bin')})
    installed.clear()
    check(False)
    installed.add(runtime)
    connections.update(key, connected=False)
    check(False)


def test_fresh_claude_install_offers_account_and_cursor_preserves_choice(onboarding_runtimes, monkeypatch):
    monkeypatch.setattr(ai_runtime, 'install', onboarding_runtimes.add)

    async def exercise():
        assert json.loads((await app.api_ai_connections()).body)['connections'] == []
        assert (await app.api_ai_operation({'id': 'claude', 'operation': 'install'})).status_code == 202
        await ai_settings.job_tasks['claude']
        offered = json.loads((await app.api_ai_connections()).body)
        assert offered['jobs']['claude']['status'] == 'success'
        claude, = offered['connections']
        assert (claude['provider'], claude['auth']) == ('anthropic', 'system')
        assert offered['default'] == '' and not offered['workspace_setup_ready']
        assert (await app.api_ai_default({'connection': claude['id']})).status_code == 200
        assert connections.load()['default'] == claude['id']

        onboarding_runtimes.add('cursor')
        response = await app.api_ai_connection_create({
            'provider': 'cursor', 'api_key': 'fixture-secret', 'default_if_unset': True})
        assert response.status_code == 201
        cursor = json.loads(response.body)
        final = json.loads((await app.api_ai_connections()).body)
        assert final['default'] == claude['id'] and final['workspace_setup_ready']
        assert {c['id'] for c in final['connections']} == {claude['id'], cursor['id']}
        assert not any(c['tested'] for c in final['connections'])

    asyncio.run(exercise())


def test_install_finishing_during_settings_snapshot_gets_another_poll(accounts, setup_jobs, monkeypatch):
    job = {'status': 'running', 'operation': 'install'}
    ai_settings.jobs['pi'] = job
    monkeypatch.setattr(ai_runtime, 'find', lambda _: '')
    def describe(name):
        installed = job['status'] == 'success'
        if name == 'pi':
            job['status'] = 'success'
        return {'installed': installed, 'version': ''}
    monkeypatch.setattr(ai_runtime, 'describe', describe)
    def snapshot():
        return json.loads(asyncio.run(app.api_ai_connections()).body)
    first = snapshot()
    assert not first['engines']['pi']['installed'] and first['jobs']['pi']['status'] == 'running'
    final = snapshot()
    assert final['engines']['pi']['installed'] and final['jobs']['pi']['status'] == 'success'


def test_board_recognises_saved_account_and_pending_browser_signin(accounts, monkeypatch):
    monkeypatch.setattr(app.profile, 'load', lambda: app.profile.Profile())
    c = accounts[0]('openai', auth='cli', tested=False)
    assert board.setup_item()['title'] == 'Choose your default AI account'
    connections.set_default(c['id'])
    assert board.setup_item()['title'] == 'Sign in to your AI account'
    auth = connections.directory(c['id']) / 'pi/auth.json'
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps({'openai': {'refresh': 'fixture-only'}}))
    assert board.setup_item()['id'] == board.SETUP_ITEM_ID
