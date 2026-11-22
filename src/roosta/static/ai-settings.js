(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let state, poll, editing = null, formOpen = false;
  let loadVersion = 0, modelVersion = 0, modelKey;
  async function request(url, body) {
    const response = await fetch(url, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save AI settings');
    return data;
  }
  function message(text, error = false) {
    $('ai-message').className = text ? `alert ${error ? 'alert-danger' : 'alert-info'} mb-3` : '';
    $('ai-message').textContent = text;
  }
  function authOptions(provider) {
    const options = [];
    if (provider === 'anthropic') {
      options.push({value:'system', label:'Use Claude Code’s existing login on this computer'});
      if (editing?.auth === 'cli') options.push({value:'cli', label:'Claude account · including enterprise'});
      options.push({value:'api_key', label:'API key · API billing'});
    } else if (provider === 'openai') {
      options.push({value:'cli', label:'Sign in with ChatGPT · including enterprise'});
      options.push({value:'api_key', label:'API key · API billing'});
    }
    return options;
  }
  function providerChanged() {
    const provider = $('ai-provider').value, info = state.providers[provider];
    $('ai-billing').textContent = info.billing;
    $('ai-label').value = provider === 'anthropic' ? 'Claude Code' : provider === 'openai' ? 'ChatGPT' : info.label;
    $('ai-key-link').href = info.key_url;
    const options = authOptions(provider);
    $('ai-auth-wrap').hidden = !options.length;
    $('ai-auth').innerHTML = options.map(o => `<option value="${o.value}">${esc(o.label)}</option>`).join('');
    if (editing && options.some(o => o.value === editing.auth)) $('ai-auth').value = editing.auth;
    authChanged();
  }
  function authChanged() {
    const provider = $('ai-provider').value, local = provider === 'ollama';
    const auth = local ? 'local' : ($('ai-auth').value || 'api_key');
    $('ai-key-wrap').hidden = auth !== 'api_key';
    $('ai-key').required = auth === 'api_key';
    $('ai-key').value = '';
    $('ai-signin').hidden = auth !== 'cli';
    if (provider === 'openai' && !editing && ['ChatGPT', 'OpenAI'].includes($('ai-label').value)) $('ai-label').value = auth === 'cli' ? 'ChatGPT' : 'OpenAI';
    if (auth === 'cli') {
      $('ai-signin').textContent = 'Sign in with ' + (provider === 'openai' ? 'ChatGPT' : 'Claude') + ' in a browser on this computer. Choose your organisation account if applicable; access depends on its policy. Roosta never asks for subscription tokens.';
      $('ai-billing').textContent = (provider === 'openai' ? 'ChatGPT' : 'Claude') + ' account · your organisation or subscription plan; access depends on organisation policy.';
    } else if (auth === 'system') {
      $('ai-billing').textContent = 'Roosta uses Claude Code and its existing login on this computer. If you already use Claude Code, there is no separate account or API key to set up.';
    } else if (!local) {
      $('ai-billing').textContent = state.providers[provider].billing;
    }
  }
  function showForm(show) {
    formOpen = show;
    $('ai-form').hidden = !show;
    $('ai-add-toggle').hidden = show;
  }
  function engineRow(engine) {
    const d = state.engines?.[engine.id] || {}, job = state.jobs[engine.id];
    let status, action = '';
    if (d.installed) { status = d.source === 'yours' ? `Using your ${engine.name} ${esc(d.version)}` : `Installed by Roosta ${esc(d.version)}`; action = `<button class="btn btn-sm btn-link" data-op="install" data-id="${engine.id}" ${job?.status === 'running' ? 'disabled' : ''}>Update to latest</button>`; }
    else { status = 'Not installed'; action = `<button class="btn btn-sm" data-op="install" data-id="${engine.id}" ${job?.status === 'running' ? 'disabled' : ''}>Install</button>`; }
    return `<div class="list-group-item px-0 d-flex align-items-center justify-content-between gap-2">
      <div><strong>${engine.name}</strong> <span class="text-secondary">· for ${engine.for}</span>
        <div class="text-secondary">${status}${job ? ` · ${esc(job.status)}` : ''}</div>
        ${job?.error ? `<p class="text-danger mb-0">${esc(job.error)}</p>` : ''}
      </div><div class="d-flex flex-column align-items-end gap-2">
        ${d.installed && state.terminal_available ? `<button class="btn btn-sm" data-terminal="${engine.id}" ${job?.status === 'running' ? 'disabled' : ''}>Open in Terminal</button>` : ''}
        ${d.installed && action ? `<details class="small" data-engine-details="${engine.id}"><summary>Updates</summary><p class="text-secondary mt-2 mb-2">Download the latest release from the publisher; your other installations are kept.</p>${action}</details>` : action}
      </div></div>`;
  }
  function software(c) {
    return c.provider === 'anthropic' ? 'Claude Code' : 'Pi';
  }
  function accountExplanation(c) {
    return c.auth === 'system'
      ? 'Uses your existing Claude Code login on this computer. No separate Roosta sign-in or API key.'
      : `Runs through ${software(c)} on this computer. ${c.billing}`;
  }
  function currentAI() {
    const c = state.connections.find(c => c.id === state.default);
    if (c) return `<strong>${esc(c.label)}</strong> <span class="${statusColor(c)} small">· ${esc(statusLine(c))}</span>
      <p class="mt-2 mb-0">${esc(accountExplanation(c))}</p>
      <p class="text-secondary small mt-2 mb-0">Default for new chats and workers that follow the default. Existing chats keep their account.</p>`;
    const existing = state.connections.find(c => c.auth === 'system' && c.connected);
    if (!existing && state.connections.some(c => c.connected)) {
      return '<strong>Choose your default AI account</strong><p class="mt-2 mb-0">Select Use as default beside the account you want for new chats and workers.</p>';
    }
    return existing
      ? '<strong>Claude Code found on this computer</strong><p class="mt-2 mb-0">Roosta can use your existing Claude Code login. Choose Use as default below to use this account.</p>'
      : '<strong>Connect your AI to get started</strong><p class="mt-2 mb-0">Choose Claude, ChatGPT or another supported service below.</p>';
  }
  function statusColor(c) {
    if (state.jobs[c.id]?.status === 'error') return 'text-danger';
    return c.connected && c.tested && (!state.jobs[c.id] || state.jobs[c.id].status === 'success')
      ? 'text-success' : 'text-secondary';
  }
  function statusLine(c) {
    if (!c.connected) return 'Disconnected';
    const job = state.jobs[c.id];
    if (job?.operation === 'test') {
      if (job.status === 'running') return job.cancelling ? 'Cancelling test…' : 'Testing connection…';
      if (job.status === 'error') return 'Connection test failed';
      if (job.status === 'interrupted') return 'Connection test cancelled';
    }
    if (job?.operation === 'login') {
      if (job.status === 'running') return 'Complete sign-in in your browser';
      if (job.status === 'error') return 'Sign-in failed';
      if (job.status === 'interrupted') return 'Sign-in interrupted';
      if (job.status === 'success') return 'Sign-in completed · untested';
    }
    if (c.signed_in === false) return 'Not signed in';
    if (c.tested) return 'Connection test passed';
    return c.signed_in ? 'Signed in · untested' : 'Untested';
  }
  function connectionRow(c) {
    const engine = c.provider === 'anthropic' ? 'claude' : 'pi';
    const installed = state.engines?.[engine]?.installed;
    const job = state.jobs[engine]?.status === 'running' ? state.jobs[engine] : state.jobs[c.id];
    const busy = job?.status === 'running';
    const status = job?.operation === 'install' && busy ? 'install · running' : statusLine(c);
    const test = state.jobs[c.id];
    const testing = test?.operation === 'test' && test.status === 'running';
    const affected = state.affected[c.id];
    const isDefault = state.default === c.id;
    const action = (label, attribute, primary = false) =>
      `<button class="btn btn-sm ${primary ? 'btn-primary' : ''}" ${attribute} ${busy ? 'disabled' : ''}>${label}</button>`;
    const op = (name, label, primary = false) => action(label, `data-op="${name}" data-id="${esc(c.id)}"`, primary);
    const chatTotal = affected ? affected.chat_count ?? affected.chats.length : 0;
    const usage = affected ? [
      [affected.workers.length, 'worker'], [chatTotal, 'chat'], [affected.pending_approvals.length, 'pending approval'],
    ].filter(([n]) => n).map(([n, label]) => `${n} ${label}${n === 1 ? '' : 's'}`).join(', ') : '';
    return `<article class="list-group-item px-0">
      <div class="ai-account-heading">
        <div><h3>${esc(c.label)} ${isDefault ? '<span class="badge ms-1">Default</span>' : ''}</h3>
          <div class="text-secondary small mt-1">${esc(accountExplanation(c))}</div></div>
        <span class="small ${statusColor(c)}" role="status">${esc(status)}</span>
      </div>
      ${job?.error || state.jobs[engine]?.error ? `<p class="text-danger mt-2 mb-0">${esc(job?.error || state.jobs[engine].error)}</p>` : ''}
      <div class="ai-account-actions">
        ${!c.connected ? action('Reconnect', `data-change="${esc(c.id)}"`, true) :
          !installed ? action(`Install ${software(c)}`, `data-op="install" data-id="${engine}"`, true) :
          c.auth === 'cli' && c.signed_in === false ? op('login', 'Sign in', true) :
          ''}
        ${c.connected && !isDefault ? `<button class="btn btn-sm btn-primary" data-default="${esc(c.id)}">Use as default</button>` : ''}
        ${c.connected && isDefault ? '<span class="text-secondary small">Used for new chats and workers that follow the default.</span>' : ''}
        ${testing ? `<button class="btn btn-sm" data-cancel-test="${esc(c.id)}" data-run="${esc(test.run_id)}" ${test.cancelling ? 'disabled' : ''}>Cancel test</button>` :
          c.connected && installed && c.signed_in !== false ? op('test', 'Test connection') : ''}
      </div>
      <details class="ai-account-details" data-account-details="${esc(c.id)}">
        <summary class="small">Manage account${usage ? ` · ${usage}` : ''}</summary>
        <div class="d-flex gap-2 flex-wrap mt-2">
          ${action('Edit account', `data-change="${esc(c.id)}"`)}
          ${c.connected ? `${c.auth === 'cli' ? op('login', 'Sign in again') : ''}
          <button class="btn btn-sm btn-ghost-secondary" data-disconnect="${esc(c.id)}" ${busy ? 'disabled' : ''}>Disconnect</button>` : ''}
        </div>
        ${usage ? `<p class="text-secondary small mt-2">Disconnecting leaves this work waiting for a replacement account.</p><ul class="small">${affected.workers.map(id => `<li><a href="/runner?task=${encodeURIComponent(id)}">Worker: ${esc(id)}</a></li>`).join('')}${affected.chats.map(id => `<li><a href="/assistant?item=${encodeURIComponent(id)}">${esc(affected.chat_titles?.[id] || id)}</a></li>`).join('')}</ul>${chatTotal > affected.chats.length ? `<p class="text-secondary small mb-0">Showing the latest ${affected.chats.length} of ${chatTotal} chats.</p>` : ''}` : '<p class="text-secondary small mt-2 mb-0">No chats, workers or pending approvals use this account.</p>'}
      </details>
    </article>`;
  }
  async function loadEfforts(effort = '', version = modelVersion) {
    const model = $('settings-model'), select = $('settings-effort');
    select.disabled = true;
    $('settings-effort-field').hidden = true;
    select.innerHTML = '<option value="">Default</option>';
    if (!model.value) return;
    const value = model.value;
    const [connection, name] = JSON.parse(value);
    try {
      const data = await request(`/api/ai/efforts?connection=${encodeURIComponent(connection)}&model=${encodeURIComponent(name)}`);
      if (version !== modelVersion || model.value !== value) return;
      select.innerHTML += data.levels.map(level => `<option value="${esc(level)}">${esc(level)}</option>`).join('');
      select.value = data.levels.includes(effort) ? effort : '';
      $('settings-effort-field').hidden = !data.levels.length;
      select.disabled = false;
    } catch (e) {
      if (version === modelVersion && model.value === value) $('model-message').textContent = e.message;
    }
  }
  async function loadModels() {
    const version = ++modelVersion;
    const select = $('settings-model');
    select.disabled = true;
    $('settings-effort-field').hidden = true;
    const accounts = state.connections.filter(c => c.connected);
    if (!accounts.length) {
      select.innerHTML = '<option>Connect an account to choose a model</option>';
      $('model-message').textContent = '';
      return;
    }
    const listings = await Promise.all(accounts.map(async c => {
      try { return {c, data:await request(`/api/ai/models?connection=${encodeURIComponent(c.id)}`)}; }
      catch (e) { return {c, data:{models:[], error:e.message}}; }
    }));
    if (version !== modelVersion) return;
    select.innerHTML = '<option value="" disabled>Choose a model</option>' + listings.map(({c, data}) =>
      `<optgroup label="${esc(c.label)}">${data.models.map(m => `<option value="${esc(JSON.stringify([c.id,m.id]))}">${esc(m.label)}</option>`).join('')}</optgroup>`).join('');
    const current = listings.find(({c}) => c.id === state.default);
    const model = current && state.model_choice?.provider === current.c.provider ? state.model_choice.model : current?.data.default;
    select.value = JSON.stringify([state.default, model]);
    if (select.selectedIndex < 0) select.value = '';
    select.disabled = !listings.some(({data}) => data.models.length);
    $('model-message').textContent = listings.filter(({data}) => data.error).map(({c,data}) => `${c.label}: ${data.error}`).join(' ');
    await loadEfforts(state.model_choice?.effort || '');
  }
  async function saveModel(effort = '') {
    const select = $('settings-model');
    select.disabled = true;
    $('settings-effort').disabled = true;
    try {
      const [connection, model] = JSON.parse(select.value);
      await request('/api/ai/default', {connection, model, effort});
      modelKey = undefined;
      await load();
      $('model-message').textContent = 'Model settings saved.';
    } catch (e) {
      await loadModels();
      $('model-message').textContent = e.message;
    }
  }
  $('settings-model').addEventListener('change', () => saveModel());
  $('settings-effort').addEventListener('change', () => saveModel($('settings-effort').value));
  async function load() {
    const version = ++loadVersion;
    const next = await request('/api/ai/connections');
    if (version !== loadVersion) return;
    const firstLoad = !state;
    state = next;
    if (!$('ai-provider').options.length) {
      const names = {anthropic:'Claude', openai:'ChatGPT / OpenAI', openrouter:'OpenRouter', ollama:'Local models (Ollama)'};
      $('ai-provider').innerHTML = ['anthropic', 'openai', 'openrouter', 'ollama'].filter(id => state.providers[id]).map(id => `<option value="${id}">${names[id]}</option>`).join('');
      providerChanged();
    }
    $('ai-current').innerHTML = currentAI();
    $('setup-notice').hidden = !state.workspace_setup_ready;
    $('setup-missing').textContent = 'Still missing: ' + (state.workspace_setup_missing || []).join(', ') + '.';
    const engines = [{id:'claude', name:'Claude Code', for:'Anthropic models'}, {id:'pi', name:'Pi', for:'OpenAI, OpenRouter and local models'}];
    const openEngines = new Set([...document.querySelectorAll('[data-engine-details][open]')].map(el => el.dataset.engineDetails));
    $('ai-engines').innerHTML = engines.map(engineRow).join('');
    document.querySelectorAll('[data-engine-details]').forEach(el => { el.open = openEngines.has(el.dataset.engineDetails); });
    const openAccounts = new Set([...document.querySelectorAll('[data-account-details][open]')].map(el => el.dataset.accountDetails));
    $('ai-connections').innerHTML = state.connections.map(connectionRow).join('') || '<p class="text-secondary">Add your first account to get started. Existing conversations are retained.</p>';
    document.querySelectorAll('[data-account-details]').forEach(el => { el.open = openAccounts.has(el.dataset.accountDetails); });
    showForm(formOpen || (firstLoad && !state.connections.some(c => c.connected)));
    if (firstLoad && !state.default) $('account-setup').open = true;
    const key = JSON.stringify([state.default, state.model_choice, state.connections, state.engines,
      Object.entries(state.jobs).filter(([, job]) => job.status !== 'running')]);
    if (key !== modelKey) {
      modelKey = key;
      loadModels().catch(e => { if (modelKey === key) $('model-message').textContent = e.message; });
    }
    clearTimeout(poll);
    if (Object.values(state.jobs).some(j => j.status === 'running')) poll = setTimeout(() => load().catch(e => message(e.message, true)), 1500);
  }
  $('ai-provider').addEventListener('change', providerChanged);
  $('ai-auth').addEventListener('change', authChanged);
  $('ai-add-toggle').addEventListener('click', () => { showForm(true); $('ai-provider').focus(); });
  function resetForm() {
    editing = null;
    $('ai-provider').disabled = false;
    $('ai-auth').disabled = false;
    $('ai-form-title').textContent = 'Add account';
    $('ai-form').querySelector('button[type="submit"]').textContent = 'Add account';
    providerChanged();
    showForm(false);
  }
  $('ai-cancel').addEventListener('click', () => { resetForm(); message(''); $('ai-add-toggle').focus(); });
  $('ai-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const provider = $('ai-provider').value;
      const auth = provider === 'ollama' ? 'local' : ['anthropic', 'openai'].includes(provider) ? ($('ai-auth').value || 'api_key') : 'api_key';
      const c = await request(editing ? `/api/ai/connections/${editing.id}/change` : '/api/ai/connections', {provider, auth, label:$('ai-label').value, api_key:$('ai-key').value});
      $('ai-key').value = '';
      resetForm();
      message(`Saved ${c.label}. Select Use as default to use this account for new chats and workers.`);
      await load();
    } catch (e) { message(e.message, true); }
    finally { button.disabled = false; }
  });
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-op], [data-cancel-test], [data-terminal], [data-default], [data-disconnect], [data-change]');
    if (!button) return;
    if (button.dataset.change) {
      const c = state.connections.find(c => c.id === button.dataset.change);
      editing = c; showForm(true); $('ai-form-title').textContent = 'Edit account'; $('ai-provider').value = c.provider; providerChanged();
      $('ai-provider').disabled = true; $('ai-auth').value = c.auth; $('ai-auth').disabled = true; authChanged();
      $('ai-label').value = c.label;
      $('ai-key').required = c.auth === 'api_key' && !c.connected;
      $('ai-form').querySelector('button[type="submit"]').textContent = 'Save connection';
      message('Changes apply to every chat and worker using this connection. Leave the key blank to keep it. Testing after saving is optional.');
      $('ai-label').focus(); return;
    }
    button.disabled = true;
    try {
      if (button.dataset.terminal) {
        await request('/api/ai/terminal', {id:button.dataset.terminal});
        message('Opened in Terminal. This is a standalone session using the tool’s own login and settings.');
      } else if (button.dataset.cancelTest) {
        await request(`/api/ai/operations/${button.dataset.cancelTest}/cancel`, {run_id:button.dataset.run});
        message('');
      } else if (button.dataset.op) {
        await request('/api/ai/operations', {id:button.dataset.id, operation:button.dataset.op});
        message('');
      } else if (button.dataset.default) {
        await request('/api/ai/default', {connection:button.dataset.default});
        message('Default changed. Existing chats and workers retain their account choices.');
      } else {
        await request(`/api/ai/connections/${button.dataset.disconnect}/disconnect`, {});
        message('Disconnected. Choose a replacement explicitly for affected chats and workers.');
      }
      await load();
    } catch (e) { message(e.message, true); button.disabled = false; }
  });
  load().catch(e => message(e.message, true));
})();
