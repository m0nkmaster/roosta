(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const LOOPBACK = /^(localhost|127(\.\d{1,3}){3}|::1|\[::1\])$/i;
  const WILDCARD = /^(0\.0\.0\.0|::|\[::\])$/;
  const FOLDER_ICON = '<svg class="control-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
  const SECOND_SENTENCE = 'Running chats and workers finish first if you wait for them; each workspace keeps its own history and settings.';
  let state, panel = null;
  let browser = {listing: null, error: '', loading: false};
  let draft = {git: true, name: 'workspace', host: '', port: '', confirm: false};
  const busy = new Set();
  const notes = {};
  async function request(url, body) {
    const response = await fetch(url, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    let data = {};
    try { data = await response.json(); } catch (error) { /* keep the status message */ }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : '';
      const failure = new Error(data.error || detail || 'Could not complete that change');
      failure.status = response.status;
      throw failure;
    }
    return data;
  }
  const code = text => `<code>${esc(text)}</code>`;
  const hostPort = (host, port) => (host.includes(':') && !host.startsWith('[') ? `[${host}]` : host) + ':' + port;
  const openHost = host => WILDCARD.test(host) ? '127.0.0.1' : host;
  const parentOf = path => path.replace(/\/[^/]+\/?$/, '') || '/';
  const desktop = () => state.managed_by === 'desktop';
  const note = key => notes[key] ? `<div class="ws-note ${notes[key].error ? 'text-danger' : 'text-secondary'}" role="status" aria-live="polite">${notes[key].html}</div>` : '';
  const button = (act, label, cls = '') => `<button type="button" class="btn ${cls}" data-act="${act}" ${busy.has(act) ? 'disabled' : ''}>${label}</button>`;
  function row(key, title, copy, actions, extra = '') {
    return `<div class="list-group-item" data-row="${key}">
      <div class="setting"><div class="setting-copy"><strong>${title}</strong>${copy.map(line => `<span>${line}</span>`).join('')}</div>
        <div class="setting-actions">${actions}</div></div>${extra}${note(key)}</div>`;
  }
  function crumbs(listing) {
    const home = listing.home;
    const under = listing.path === home || listing.path.startsWith(home.replace(/\/$/, '') + '/');
    const parts = (under ? listing.path.slice(home.length) : listing.path).split('/').filter(Boolean);
    let at = under ? home : '';
    const items = [[under ? 'Home' : '/', under ? home : '/']];
    parts.forEach(part => { at = (at === '/' ? '' : at) + '/' + part; items.push([part, at]); });
    return `<ol class="breadcrumb mb-2">${items.map(([label, path], i) => i === items.length - 1
      ? `<li class="breadcrumb-item active" aria-current="page">${esc(label)}</li>`
      : `<li class="breadcrumb-item"><button type="button" class="btn btn-link p-0" data-go="${esc(path)}">${esc(label)}</button></li>`).join('')}</ol>`;
  }
  function browserHtml() {
    if (!browser.listing) return `<div class="text-secondary">${browser.error ? '' : 'Loading folders…'}</div>${browser.error ? `<div class="text-danger">${esc(browser.error)}</div>` : ''}`;
    const l = browser.listing;
    const items = (l.parent ? [`<button type="button" class="list-group-item list-group-item-action ws-folder" data-go="${esc(l.parent)}">${FOLDER_ICON}<span>.. Up one level</span></button>`] : [])
      .concat(l.folders.map(f => `<button type="button" class="list-group-item list-group-item-action ws-folder" data-go="${esc(f.path)}">${FOLDER_ICON}<span class="ws-folder-name">${esc(f.name)}</span>${f.workspace ? '<span class="badge bg-blue-lt ms-auto">Roosta workspace</span>' : ''}</button>`));
    return `${crumbs(l)}<div class="list-group ws-browser ${browser.loading ? 'ws-loading' : ''}">${items.join('')}${l.folders.length ? '' : '<div class="list-group-item text-secondary">No folders inside.</div>'}</div>
      ${l.truncated ? `<div class="text-secondary small mt-1">Showing the first ${l.folders.length} folders.</div>` : ''}
      ${browser.error ? `<div class="text-danger small mt-1">${esc(browser.error)}</div>` : ''}`;
  }
  function nameProblem() {
    const name = draft.name.trim();
    if (!name) return {text: '', blocked: true};
    if (/[\\/]/.test(name) || name.startsWith('.')) return {text: 'Use a plain folder name, without slashes or a leading dot.', blocked: true};
    if (browser.listing?.folders.some(f => f.name.toLowerCase() === name.toLowerCase()))
      return {text: 'A folder with that name already exists here. Open it instead.', blocked: true};
    return {text: '', blocked: false};
  }
  function newPath() {
    const base = browser.listing.path.replace(/\/$/, '');
    return base + '/' + draft.name.trim();
  }
  function openStatus() {
    const l = browser.listing;
    if (!l) return {html: '', primary: ''};
    if (l.path === state.workspace) return {html: 'This is your current workspace.', primary: '<button type="button" class="btn btn-primary" disabled>Open this workspace</button>'};
    if (l.is_workspace) return {html: `${code(l.path)} is a Roosta workspace.`, primary: button('submit-open', 'Open this workspace', 'btn-primary')};
    return {html: `${code(l.path)} is not a Roosta workspace yet. Roosta will add its files beside yours; nothing is overwritten.`, git: true,
      primary: button('submit-adopt', 'Use this folder', 'btn-primary')};
  }
  const gitBox = () => `<label class="form-check mt-2 mb-0"><input class="form-check-input" type="checkbox" data-draft="git" ${draft.git ? 'checked' : ''}><span class="form-check-label">Create a Git repository</span></label>`;
  function folderPanel() {
    const cancel = button('cancel', 'Cancel', 'btn-ghost-secondary');
    if (panel === 'open') {
      const s = openStatus();
      return `<div class="ws-panel"><p class="mb-2">Choose the folder Roosta should use.</p>${browserHtml()}
        <p class="mt-3 mb-0" id="ws-status">${s.html}</p>${s.git ? gitBox() : ''}
        <div class="ws-panel-actions">${s.primary}${cancel}</div></div>`;
    }
    if (panel === 'new') {
      const p = nameProblem();
      return `<div class="ws-panel"><p class="mb-2">Choose where to put it, then name it.</p>${browserHtml()}
        <label class="form-label mt-3" for="ws-name">Name</label>
        <input class="form-control" id="ws-name" maxlength="100" autocomplete="off" spellcheck="false" value="${esc(draft.name)}">
        <div class="text-danger small mt-1" id="ws-name-problem">${esc(p.text)}</div>
        <p class="mt-2 mb-0" id="ws-status">${browser.listing && !p.blocked ? `Roosta will create ${code(newPath())} with its starter files.` : ''}</p>${gitBox()}
        <div class="ws-panel-actions"><button type="button" class="btn btn-primary" data-act="submit-create" id="ws-create" ${p.blocked || !browser.listing || busy.has('submit-create') ? 'disabled' : ''}>Create workspace</button>${cancel}</div></div>`;
    }
    return '';
  }
  function skillsRow() {
    const s = state.skills;
    const lines = [`${s.core.length} skills follow the installed Roosta ${esc(state.version)}.`];
    if (s.extensions.length) lines.push(`Workspace extensions: ${esc(s.extensions.join(', '))}.`);
    for (const [name, reason] of Object.entries(s.forks)) lines.push(`Fork · ${esc(name)} · ${esc(reason)}`);
    for (const [name, locations] of Object.entries(s.review)) lines.push(`Review ${esc(name)} copies in ${locations.map(code).join(', ')}.`);
    if (s.pending.length) lines.push(`Review unmigrated paths: ${s.pending.map(code).join(', ')}.`);
    lines.push(...s.problems.map(esc));
    if (s.archive) lines.push('Recovery copies: ' + code('.roosta/skill-archive/') + '.');
    const names = [...new Set([...Object.keys(s.forks), ...Object.keys(s.review)])];
    const review = names.length || s.pending.length || s.problems.length;
    let action = '';
    if (review) {
      const ask = [`Review my skill customisations with the installed review procedure at ${s.installed_path}/setup/SKILL.md (Reviewing workspace forks), even if setup itself is pinned.`,
        `Installed core: Roosta ${state.version} in ${s.installed_path}.`,
        ...names.map(name => [name, s.forks[name] && `active fork .roosta/skill-forks/${name} (${s.forks[name]})`,
          ...(s.review[name] || [])].filter(Boolean).join(' · ')),
        ...s.pending, ...s.problems,
        'Compare local additions, scripts and references. Show what can follow installed core through an extension. Ask before applying changes.'].join('\n');
      action = `<a class="btn" href="/assistant?item=new&amp;ask=${esc(encodeURIComponent(ask))}">Review customisations</a>`;
    }
    if (Object.values(s.forks).includes('retired from core')) lines.push('Review retired forks to keep or archive them.');
    return row('skills', 'Roosta’s skills', lines, action);
  }
  function serviceRow() {
    const v = state.service;
    let status = ['Off', 'text-secondary'], extra = '';
    if (v.installed && v.active) status = ['On', 'text-success'];
    else if (v.installed) status = ['Not started', 'text-warning'];
    const copy = ['Keep Roosta running in the background and start it when you log in.'];
    if (!v.supported) copy[0] = 'Not available on this platform. See the README.';
    else if (v.installed && !v.active && v.activate) copy.push(`To start it, run: ${code(v.activate)}`);
    if (v.supported && v.installed && (v.workspace !== state.workspace || v.port !== state.port))
      copy.push(`It is set up for ${code(v.workspace || 'an unknown workspace')} on port ${esc(v.port ?? 'unknown')}.`);
    return row('service', `Start at login <small class="${status[1]}">· ${status[0]}</small>`, copy,
      v.supported ? button('service', v.installed ? 'Set up again' : 'Turn on') : '', extra);
  }
  function addressRow() {
    const s = state;
    const copy = [`Roosta is open at ${code('http://' + hostPort(s.host, s.port))}. Change it only if another device needs to reach Roosta.`];
    if ((s.saved_host && s.saved_host !== s.host) || (s.saved_port && s.saved_port !== s.port))
      copy.push(`Changes to ${code('http://' + hostPort(s.saved_host || s.host, s.saved_port || s.port))} the next time you run ${code('roosta start')}.`);
    let form = '';
    if (panel === 'address') {
      const network = draft.host.trim() !== '' && !LOOPBACK.test(draft.host.trim());
      form = `<div class="ws-panel"><div class="row g-2">
        <div class="col-sm-8"><label class="form-label" for="addr-host">Host</label><input class="form-control" id="addr-host" data-draft="host" autocomplete="off" spellcheck="false" value="${esc(draft.host)}"></div>
        <div class="col-sm-4"><label class="form-label" for="addr-port">Port</label><input class="form-control" id="addr-port" data-draft="port" type="number" min="1024" max="65535" value="${esc(draft.port)}"></div></div>
        <p class="text-secondary small mt-2 mb-0">Used the next time ${code('roosta start')} runs without --host or --port. Keep 127.0.0.1 unless other devices need to reach Roosta.</p>
        <label class="form-check mt-2 mb-0" id="addr-confirm-wrap" ${network ? '' : 'hidden'}><input class="form-check-input" type="checkbox" data-draft="confirm" ${draft.confirm ? 'checked' : ''}><span class="form-check-label">Anyone on your network will be able to open Roosta, read your workspace and start chats. I understand.</span></label>
        <div class="ws-panel-actions">${button('submit-address', 'Save address', 'btn-primary')}${button('cancel', 'Cancel', 'btn-ghost-secondary')}</div></div>`;
    }
    return row('address', 'Web address', copy, panel === 'address' ? '' : button('address', 'Change'), form);
  }
  function render() {
    const s = state, remembered = s.remembered && s.remembered !== s.workspace;
    const rows = [
      row('folder', 'Workspace folder',
        [`${code(s.workspace)} Your notes, skills and schedule live here.`].concat(remembered ? [`Opens ${code(s.remembered)} after Roosta restarts.`] : []),
        panel === 'open' || panel === 'new' ? '' : button('open', 'Open another folder') + button('new', 'New workspace'), folderPanel()),
      skillsRow(),
    ];
    if (!desktop()) rows.push(serviceRow(), addressRow());
    $('ws-rows').innerHTML = rows.join('');
  }
  function unavailable(error) {
    $('ws-rows').innerHTML = `<div class="list-group-item text-secondary">${error.status === 404 ? 'Restart Roosta to use these settings.' : `Workspace settings are unavailable: ${esc(error.message)}`}</div>`;
  }
  async function browse(path) {
    browser.loading = true; browser.error = '';
    if (browser.listing) render();
    try {
      browser.listing = await request('/api/settings/folders' + (path ? '?path=' + encodeURIComponent(path) : ''));
    } catch (error) { browser.error = error.message; }
    browser.loading = false;
    render();
    const list = document.querySelector('.ws-browser');
    if (list) list.scrollTop = 0;
  }
  function openPanel(name) {
    panel = name; browser = {listing: null, error: '', loading: false};
    delete notes.folder; delete notes.address;
    if (name === 'address') { draft.host = state.saved_host || state.host; draft.port = state.saved_port || state.port; draft.confirm = false; }
    render();
    if (name === 'open') browse(parentOf(state.workspace));
    if (name === 'new') browse('');
  }
  async function act(name) {
    const key = name.startsWith('submit-') ? (name === 'submit-address' ? 'address' : 'folder') : name;
    busy.add(name); render();
    try {
      if (name === 'submit-open' || name === 'submit-adopt' || name === 'submit-create') {
        const action = {'submit-open': 'select', 'submit-adopt': 'adopt', 'submit-create': 'create'}[name];
        const path = name === 'submit-create' ? newPath() : browser.listing.path;
        const result = await request('/api/settings/workspace', {action, path, git: draft.git});
        state.remembered = result.workspace; panel = null;
        const tail = state.managed_by === 'desktop' ? `Quit and reopen Roosta to switch. ${SECOND_SENTENCE}`
          : state.managed_by === 'service' ? `Start at login is set up for the old workspace. Run ${code('roosta start --workspace ' + result.workspace)}, then set up Start at login again from there.`
          : `Stop Roosta and run ${code('roosta start')} to switch. ${SECOND_SENTENCE}`;
        notes.folder = {html: result.restart_required ? tail : 'That is already your workspace.'};
      } else if (name === 'submit-address') {
        const result = await request('/api/settings/address', {host: draft.host.trim(), port: Number(draft.port), confirm_network: draft.confirm});
        state.saved_host = result.saved_host; state.saved_port = result.saved_port; panel = null;
        notes.address = {html: `Saved. Stop Roosta and start it again, then open ${code('http://' + hostPort(openHost(result.saved_host), result.saved_port) + '/settings')}.`};
      } else if (name === 'service') {
        const result = await request('/api/settings/service', {});
        state.service = result.service;
        notes.service = {html: `Almost done. Run this in a terminal: ${code(result.service.activate)}`};
      }
    } catch (error) { notes[key] = {html: esc(error.message), error: true}; }
    busy.delete(name); render();
  }
  function refreshFolderText() {
    const status = $('ws-status'), create = $('ws-create'), problem = $('ws-name-problem');
    if (!status || !browser.listing) return;
    if (panel === 'new') {
      const p = nameProblem();
      problem.textContent = p.text; create.disabled = p.blocked;
      status.innerHTML = p.blocked ? '' : `Roosta will create ${code(newPath())} with its starter files.`;
    }
  }
  document.addEventListener('click', event => {
    const target = event.target.closest('#workspace-card [data-act], #workspace-card [data-go]');
    if (!target) return;
    event.preventDefault();
    if (target.dataset.go !== undefined) return browse(target.dataset.go);
    const name = target.dataset.act;
    if (name === 'cancel') { panel = null; render(); return; }
    if (name === 'open' || name === 'new' || name === 'address') return openPanel(name);
    act(name);
  });
  document.addEventListener('input', event => {
    if (!event.target.closest('#workspace-card')) return;
    if (event.target.id === 'ws-name') { draft.name = event.target.value; refreshFolderText(); return; }
    const key = event.target.dataset.draft;
    if (!key) return;
    draft[key] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    if (key === 'host') {
      const wrap = $('addr-confirm-wrap'), host = draft.host.trim();
      wrap.hidden = host === '' || LOOPBACK.test(host);
    }
  });
  (async () => {
    try { state = await request('/api/settings/workspace'); render(); }
    catch (error) { unavailable(error); }
  })();
})();
