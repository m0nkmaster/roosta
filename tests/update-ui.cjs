// Run the shipped scripts against a small DOM and an in-memory API.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const path = require('node:path');
const settle = () => new Promise(resolve => setImmediate(resolve));
const script = name => readFileSync(path.join(__dirname, '../src/roosta/static', name), 'utf8');

function element() {
  return {
    children: [], dataset: {}, textContent: '',
    append(...items) { this.children.push(...items); },
    appendChild(item) { this.append(item); return item; },
    replaceChildren(...items) { this.children = items; },
    remove() { this.removed = true; },
    setAttribute() {},
  };
}

test('Settings retries a failed check and shows the verified command and release notes', async () => {
  const nodes = Object.fromEntries(['check-updates', 'update-status', 'update-details', 'running-version']
    .map(id => [id, element()]));
  let state = {state: 'failed', error: 'Could not check GitHub Releases.'};
  const methods = [];
  vm.runInNewContext(script('updates.js'), {
    document: {getElementById: id => nodes[id], createElement: element},
    setInterval() {},
    fetch: async (url, {method}) => {
      assert.equal(url, '/api/settings/updates');
      methods.push(method);
      return {ok: true, json: () => ({version: '1.0.0', ...state})};
    },
  });
  await settle();
  const button = nodes['check-updates'];
  assert.equal(nodes['running-version'].textContent, 'Running version 1.0.0');
  assert.match(button.textContent, /retry/i);
  state = {state: 'available', latest: '1.1.0', notes: 'release', command: 'roosta update'};
  await button.onclick();
  assert.match(nodes['update-status'].textContent, /1\.1\.0/);
  const children = nodes['update-details'].children.flatMap(el => el.children);
  assert.ok(children.some(el => el.href === 'release'));
  assert.ok(children.some(el => el.textContent === 'roosta update'));
  state = {state: 'current'};
  await button.onclick();
  assert.match(nodes['update-status'].textContent, /up to date/);
  assert.equal(nodes['update-details'].children.length, 0);
  assert.deepEqual(methods, ['GET', 'POST', 'POST']);
});

test('dismissing a release notice survives navigation in the session', async () => {
  const shown = [];
  const header = {
    querySelector: selector => selector === 'nav.workspace-nav' ? element() : {},
    hasAttribute: () => true,
    after: el => shown.push(el),
  };
  const store = new Map();
  const storage = {getItem: k => store.get(k), setItem: (k, v) => store.set(k, v)};
  let latest = '1.2.0';
  const context = {
    document: {
      readyState: 'complete', createElement: element,
      querySelector: selector => selector === 'header.workspace-header' ? header : null,
      querySelectorAll: () => [],
    },
    location: {pathname: '/assistant'}, window: {addEventListener() {}},
    localStorage: storage, sessionStorage: storage, setInterval() {},
    fetch: async url => ({ok: true, json: () => url === '/api/pages' ? [] : {latest, notes: 'release'}}),
  };
  const visit = async () => { vm.runInNewContext(script('nav-count.js'), context); await settle(); };
  await visit();
  assert.equal(shown.length, 1);
  const dismiss = shown[0].children.find(child => child.textContent === 'Dismiss');
  dismiss.onclick();
  assert.ok(shown[0].removed);
  await visit();
  assert.equal(shown.length, 1);
  latest = '1.3.0';
  await visit();
  assert.equal(shown.length, 2);
});
