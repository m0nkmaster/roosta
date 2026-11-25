// Exercise the shipped Settings handlers with a disposable DOM, clock and API.
const assert = require('node:assert/strict');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    options:[], value:'', dataset:{}, addEventListener(name, fn) { this[name] = fn; },
    querySelector: selector => element(id + selector),
  });
  return elements.get(id);
}
global.window = element('window');
global.document = Object.assign(element('document'), {getElementById:element, querySelectorAll:() => []});
element('ai-provider').value = 'openai';
element('ai-provider').options.push('openai');
let poll;
global.setTimeout = fn => { poll = fn; return 1; };
global.clearTimeout = () => { poll = null; };
const state = {default:'', connections:[], jobs:{}, engines:{}, affected:{},
  providers:{openai:{billing:'OpenAI', label:'OpenAI'}}};
let transientFailure = false;
global.fetch = async (url, options) => {
  let data;
  if (url === '/api/ai/connections' && !options.method) {
    if (transientFailure) { transientFailure = false; throw Error('Status unavailable'); }
    data = state;
  } else if (url === '/api/ai/connections') {
    const body = JSON.parse(options.body);
    data = {id:'chosen', provider:'openai', label:'My account', auth:'api_key', connected:true, tested:false};
    state.connections.push(data);
    if (body.default_if_unset) state.default = data.id;
  } else if (url.startsWith('/api/ai/models?')) {
    data = {models:[]};
  } else if (url === '/api/ai/operations') {
    assert.deepEqual(JSON.parse(options.body), {id:'pi', operation:'install'});
    state.jobs.pi = {status:'running', operation:'install'};
    data = {};
  } else throw Error('Unexpected request ' + url);
  return {ok:true, json:async () => structuredClone(data)};
};
require('../src/roosta/static/ai-settings.js');
(async () => {
  await new Promise(setImmediate);
  element('ai-key').value = 'fixture-key';
  assert.match(element('ai-form').querySelector('button[type="submit"]').textContent || '', /default/i);
  await element('ai-form').submit({preventDefault(){}, submitter:{}});
  assert.match(element('ai-current').innerHTML, /My account/);
  assert.equal(element('ai-key').value, '');
  await document.click({target:{closest:() => ({dataset:{id:'pi', op:'install'}})}});
  assert.equal(typeof poll, 'function');
  const tick = async () => { const callback = poll; poll = null; await callback(); };
  transientFailure = true;
  await tick();
  assert.equal(typeof poll, 'function', 'a temporary status failure lost the completion poll');
  assert.match(element('ai-message').textContent, /retry/i);
  state.workspace_setup_ready = true;
  state.jobs.pi.status = 'success';
  state.engines.pi = {installed:true, version:'1.2.3'};
  await tick();
  assert.match(element('ai-engines').innerHTML, /Installed by Roosta 1.2.3/);
  assert.equal(element('setup-notice').hidden, false);
  assert.equal(element('ai-message').textContent, '');
  assert.equal(poll, null);
  // Other windows and external installers change local state without a running Settings job.
  state.connections[0].connected = false;
  state.workspace_setup_ready = false;
  await window.focus();
  assert.equal(element('setup-notice').hidden, true);
  assert.match(element('ai-current').innerHTML, /Disconnected/);
  assert.equal(poll, null);
})().catch(error => { console.error(error); process.exitCode = 1; });
