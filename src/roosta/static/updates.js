(() => {
  const button = document.getElementById('check-updates');
  const status = document.getElementById('update-status');
  const details = document.getElementById('update-details');
  let previous;
  function line(text) {
    const el = document.createElement('p');
    el.textContent = text;
    details.appendChild(el);
    return el;
  }
  function link(text, url) {
    const a = document.createElement('a');
    a.href = url;
    a.textContent = text;
    line('').appendChild(a);
  }
  async function load(manual = false) {
    if (button.disabled) return;
    button.disabled = true;
    if (manual) status.textContent = 'Checking for updates…';
    try {
      const response = await fetch('/api/settings/updates', {method: manual ? 'POST' : 'GET'});
      if (!response.ok) throw new Error(response.status === 403
        ? 'Open Settings on the computer running Roosta to check for updates.' : 'Could not check for updates.');
      const data = await response.json();
      const snapshot = JSON.stringify(data);
      if (!manual && previous === snapshot && data.state !== 'checking') return;
      previous = snapshot;
      document.getElementById('running-version').textContent = 'Running version ' + data.version;
      details.replaceChildren();
      button.textContent = data.error ? 'Retry update check' : 'Check for updates';
      if (data.state === 'checking') {
        status.textContent = 'Checking for updates…';
        setTimeout(() => load(), 1500);
      } else if (data.state === 'available') {
        status.textContent = 'Roosta ' + data.latest + ' is available.';
        link('Release notes', data.notes);
        if (data.error) line(data.error);
        else {
          line('Let active workers and chats finish before updating. ' + data.guidance);
          if (data.command) line('').appendChild(document.createElement('code')).textContent = data.command;
          if (data.installer) link('Download the installer for this Mac', data.installer);
          if (data.restart) line(data.restart);
          line('Confirm the running version here. Your workspace, chats and settings stay in place. Installed core skills update with Roosta. Review pinned forks in Workspace settings.');
        }
      } else {
        status.textContent = data.state === 'current' ? 'Roosta is up to date.' : data.error;
      }
    } catch (error) {
      previous = undefined;
      details.replaceChildren();
      status.textContent = error.message;
      button.textContent = 'Retry update check';
    } finally {
      button.disabled = false;
    }
  }
  button.onclick = () => load(true);
  load();
  setInterval(() => { if (!document.hidden) load(); }, 60000);
})();
