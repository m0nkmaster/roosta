const account = (id, provider, auth) => ({id, provider, auth, label:id, connected:true, tested:false, billing:'Test account'});
const config = {
  default:'', jobs:{}, connections:[account('Claude', 'anthropic', 'system'), account('ChatGPT', 'openai', 'cli')],
  providers:{anthropic:{billing:'Anthropic'}, openai:{billing:'OpenAI'}},
  engines:{claude:{installed:true}, pi:{installed:true}}, affected:{},
};
const modelResponses = [];
let pollSettings;
window.setTimeout = fn => { pollSettings = fn; return 1; };
window.clearTimeout = () => { pollSettings = null; };
function response(data) { return {ok:true, json:async () => structuredClone(data)}; }
window.fetch = async (url, options) => {
  if (url === '/api/ai/connections') return response(config);
  if (url.startsWith('/api/ai/models?')) return new Promise(resolve => modelResponses.push(resolve));
  if (url.startsWith('/api/ai/efforts?')) return response({levels:[]});
  const body = JSON.parse(options.body);
  if (url === '/api/ai/default' && Object.keys(body).join() === 'connection') {
    config.default = body.connection;
  } else if (url === '/api/ai/operations' && body.operation === 'test') {
    config.jobs[body.id] = {operation:'test', status:'running', run_id:'this-test'};
  } else if (url === '/api/ai/operations/Claude/cancel' && body.run_id === 'this-test') {
    config.jobs.Claude.status = 'interrupted';
  } else {
    throw Error('Unexpected API call ' + url);
  }
  return response({});
};

// Run after the actual Settings script.
(async () => {
  const q = selector => document.querySelector(selector);
  const assert = (value, message) => { if (!value) throw Error(message); };
  async function until(predicate, message) {
    for (let i = 0; i < 100; i++) {
      if (predicate()) return;
      await Promise.resolve();
    }
    throw Error(message);
  }
  function click(selector) {
    const button = q(selector);
    assert(button && !button.disabled && button.getClientRects().length, 'Unavailable ' + selector);
    button.click();
  }
  const test = '[data-op="test"][data-id="Claude"]';
  const cancel = '[data-cancel-test="Claude"]';
  const details = '[data-account-details="ChatGPT"]';
  const software = '[data-engine-details="claude"]';
  let result;
  try {
    await until(() => modelResponses.length === 2, 'Did not list both untested accounts');
    assert(q('#ai-provider').value === 'anthropic', 'Expected Claude as initial service');
    assert(q('#ai-connections').textContent.includes('Untested'), 'Missing untested status');
    const heading = getComputedStyle(q('.ai-account-heading'));
    assert(heading.display === 'flex', 'Missing Settings styles');
    assert(heading.flexDirection === (innerWidth <= 540 ? 'column' : 'row'), 'Incorrect responsive layout');
    q(details).open = true;
    click(details + ' [data-change]');
    q('#ai-label').closest('details').open = true;
    q('#ai-label').value = 'Unsaved account name';
    q('#ai-runtime-details').open = true;
    q(software).open = true;
    q('#model-settings').open = true;
    click(test);
    await until(() => q(cancel) && pollSettings, 'Test controls or poll blocked on model listing');
    const buttons = [q(cancel), q('[data-default="Claude"]')];
    for (const button of buttons) {
      const rect = button.getBoundingClientRect();
      assert(rect.left >= 0 && rect.right <= document.documentElement.clientWidth, 'Button outside viewport');
    }
    click('[data-default="Claude"]');
    await until(() => q('#ai-current').textContent.includes('Testing connection'), 'Default change blocked');
    click(cancel);
    await until(() => q('#ai-current').textContent.includes('cancelled'), 'Cancellation blocked');
    assert(!q(cancel) && !pollSettings && !q('#ai-message').textContent.includes('Working'), 'Stale operation');
    click(test);
    await until(() => q(cancel) && pollSettings, 'Retry blocked');
    config.jobs.Claude = {operation:'test', status:'error', error:'Rate limited'};
    await pollSettings();
    assert(!q(cancel) && q('#ai-current').textContent.includes('failed'), 'Failure status missing');
    assert(q('#ai-connections').textContent.includes('Rate limited'), 'Failure reason missing');
    assert(!q('#ai-connections').textContent.includes('run claude and sign in'), 'Incorrect repair advice');
    assert(!q('#ai-message').textContent.includes('Working'), 'Stale working message');
    assert(q('#ai-label').value === 'Unsaved account name' && !q('#ai-form').hidden, 'Edit was reset');
    for (const selector of [details, software, '#ai-runtime-details', '#model-settings', '#ai-form details']) {
      assert(q(selector).open, 'Disclosure closed ' + selector);
    }
    // Complete newest listings first, then stale responses from the prior default.
    const latest = modelResponses.splice(-2);
    latest.forEach(resolve => resolve(response({models:[{id:'fresh',label:'Fresh model'}], default:'fresh'})));
    await until(() => !q('#settings-model').disabled, 'Model selector unavailable');
    modelResponses.forEach(resolve => resolve(response({models:[{id:'old',label:'Stale model'}]})));
    for (let i = 0; i < 20; i++) await Promise.resolve();
    assert(q('#settings-model').value === JSON.stringify(['Claude','fresh']), 'Stale catalogue replaced current default');
    assert(q('#settings-model').querySelectorAll('optgroup').length === 2, 'Missing connected account models');
    result = {ok:true};
  } catch (e) { result = {error:String(e)}; }
  const output = document.createElement('pre');
  output.id = 'account-result';
  output.textContent = JSON.stringify(result);
  document.body.appendChild(output);
})();
