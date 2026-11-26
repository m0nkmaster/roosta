"""Account UI decisions without a live account or browser."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_account_actions_and_escaped_content():
    if not shutil.which('node'):
        pytest.skip('Node is required for UI checks')
    source = (Path(__file__).parents[1] / 'src/roosta/static/ai-settings.js').read_text()
    helpers = source[source.index('  function software'):source.index('  async function load')]
    escape = source[source.index('  const esc'):source.index('  let state')]
    subprocess.run(['node', '-e', escape + helpers + """
const assert = require('node:assert/strict');
const state = {jobs:{}, engines:{claude:{installed:true}, pi:{installed:true}}, connections:[], affected:{}, default:'account'};
let c = {id:'account', label:'<script>bad</script>', connected:true, tested:true, auth:'cli', provider:'openai', signed_in:true};
let html = connectionRow(c);
assert(!html.includes('<script>'));
assert(html.includes('&lt;script&gt;'));
assert(!html.includes('data-default'));
assert(html.includes('Used for new chats'));
state.connections = [c];
assert(currentAI().includes('Runs through Pi'));
c.provider = 'anthropic'; c.auth = 'system';
assert(currentAI().includes('existing Claude Code login'));
state.default = '';
assert(currentAI().includes('Claude Code found'));
state.connections = [];
assert(currentAI().includes('Connect your AI'));
state.default = 'other';
c.provider = 'openai'; c.auth = 'cli';
assert(connectionRow(c).includes('Use as default'));
c.tested = false;
assert(connectionRow(c).includes('data-default'));
for (const [job, text] of [
  [{operation:'test',status:'running',run_id:'own'}, 'Testing connection'],
  [{operation:'test',status:'interrupted'}, 'cancelled'],
  [{operation:'test',status:'error',error:'Rate limited'}, 'failed'],
  [{operation:'login',status:'success'}, 'Sign-in completed'],
  [{operation:'login',status:'interrupted'}, 'Sign-in interrupted'],
  [{operation:'login',status:'error'}, 'Sign-in failed'],
]) {
  state.jobs.account = job;
  html = connectionRow(c);
  assert(html.includes(text));
  assert(!/data-default="account"[^>]*disabled/.test(html));
  assert.equal(html.includes('Cancel test'), job.status === 'running');
  assert(!html.includes('Working'));
}
delete state.jobs.account;
c.signed_in = false;
html = connectionRow(c);
assert(html.includes('>Sign in</button>'));
assert(!html.includes('data-op="test"'));
state.engines.pi.installed = false;
html = connectionRow(c);
assert(html.includes('Install Pi'));
assert(!html.includes('>Sign in</button>'));
state.jobs.pi = {operation:'install',status:'running'};
assert(connectionRow(c).includes('install · running'));
assert(/data-op="install"[^>]*disabled/.test(connectionRow(c)));
state.jobs.pi = {operation:'install',status:'error',error:'Download & retry'};
assert(connectionRow(c).includes('Download &amp; retry'));
c.connected = false;
html = connectionRow(c);
assert(html.includes('Reconnect'));
assert(!html.includes('data-op="test"'));
state.affected.account = {workers:[], chats:['one'], pending_approvals:[]};
assert(connectionRow(c).includes('1 chat'));
assert(!connectionRow(c).includes('1 chats'));
assert(!connectionRow(c).includes('Showing the latest'));
state.affected.account = {workers:[], chats:['a','b'], chat_count:25, chat_titles:{}, pending_approvals:[]};
html = connectionRow(c);
assert(html.includes('25 chats'));
assert(html.includes('Showing the latest 2 of 25 chats.'));
"""], check=True)


def test_model_choice_lives_in_settings_only():
    static = Path(__file__).parents[1] / 'src/roosta/static'
    assistant = (static / 'assistant.html').read_text()
    settings = (static / 'settings.html').read_text()
    for control in ('ai-backend', 'ai-model', 'ai-effort', 'model-refresh', 'loadBackend'):
        assert control not in assistant
    assert 'id="settings-model"' in settings
    assert '<details class="mb-3" id="account-setup">' in settings


def test_settings_effort_restores_supported_choice_and_hides_for_other_models():
    if not shutil.which('node'):
        pytest.skip('Node is required for UI checks')
    source = (Path(__file__).parents[1] / 'src/roosta/static/ai-settings.js').read_text()
    helper = source[source.index('  async function loadEfforts'):source.index('  async function loadModels')]
    escape = source[source.index('  const esc'):source.index('  let state')]
    subprocess.run(['node', '-e', escape + helper + """
const assert = require('node:assert/strict');
const elements = {'settings-model':{value:JSON.stringify(['account','model'])},
  'settings-effort':{}, 'settings-effort-field':{}, 'model-message':{}};
const $ = id => elements[id];
const modelVersion = 1;
let levels = ['low','high','xhigh'];
async function request(url) { assert(url.includes('/api/ai/efforts?')); return {levels}; }
(async () => {
  await loadEfforts('xhigh');
  assert.equal($('settings-effort').value, 'xhigh');
  assert.equal($('settings-effort').disabled, false);
  assert.equal($('settings-effort-field').hidden, false);
  await loadEfforts('unsupported');
  assert.equal($('settings-effort').value, '');
  levels = [];
  await loadEfforts();
  assert.equal($('settings-effort-field').hidden, true);
})().catch(e => { console.error(e); process.exitCode = 1; });
"""], check=True)


def test_installed_software_offers_terminal_and_update():
    if not shutil.which('node'):
        pytest.skip('Node is required for UI checks')
    source = (Path(__file__).parents[1] / 'src/roosta/static/ai-settings.js').read_text()
    helper = source[source.index('  function engineRow'):source.index('  function software')]
    escape = source[source.index('  const esc'):source.index('  let state')]
    subprocess.run(['node', '-e', escape + helper + """
const assert = require('node:assert/strict');
const state = {jobs:{}, terminal_available:true, engines:{pi:{installed:true,source:'managed',version:'1.5.2'}}};
const engine = {id:'pi',name:'Pi',for:'other providers'};
let html = engineRow(engine);
assert(html.includes('Installed by Roosta'));
assert(html.includes('Open in Terminal'));
assert(!html.includes('Repair'));
assert(html.includes('data-engine-details="pi"><summary>Updates</summary>'));
assert(html.includes('Update to latest'));
state.jobs.pi = {status:'running',operation:'install'};
assert(/data-terminal="pi"[^>]*disabled/.test(engineRow(engine)));
state.engines.pi.source = 'yours';
assert(engineRow(engine).includes('Update to latest'));
state.terminal_available = false;
assert(!engineRow(engine).includes('Open in Terminal'));
state.engines.pi.installed = false;
assert(engineRow(engine).includes('>Install</button>'));
"""], check=True)


def test_first_run_setup_card_opens_settings_without_an_ai_turn():
    static = Path(__file__).parents[1] / 'src/roosta/static'
    board = (static / 'assistant.html').read_text()
    assert "const aiSetup=id==='roosta-ai-setup';" in board
    assert 'href="/settings">Open AI settings</a>' in board
    assert "class=\"form ${aiSetup?'d-none':''}\"" in board
    assert "activeId==='roosta-ai-setup'&&!items.some" in board
    settings = (static / 'settings.html').read_text()
    assert 'id="setup-notice"' in settings and 'id="setup-continue"' in settings and 'Continue workspace setup' in settings
    assert 'id="ai-continue"' not in settings
    assert settings.index('id="setup-notice"') < settings.index('id="current-ai-title"')
    assert 'id="setup-missing"' in settings and 'Your AI is ready' not in settings
    script = (static / 'ai-settings.js').read_text()
    assert "$('setup-notice').hidden = !state.workspace_setup_ready;" in script
    assert "$('setup-missing').textContent = 'Still missing: ' + (state.workspace_setup_missing || []).join(', ') + '.';" in script


def test_settings_first_account_and_install_poll():
    if not shutil.which('node'):
        pytest.skip('Node is required for UI checks')
    subprocess.run(['node', Path(__file__).with_name('settings_onboarding_probe.js')], check=True)
