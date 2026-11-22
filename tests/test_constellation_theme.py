"""Paint one frame with local page assets, synthetic projects and no polling."""
from pathlib import Path
import re

import pytest

from chrome_probe import run_probe
from test_columns import STATIC, chrome_path


def fixture_page(directory: Path, full=False):
    source = (STATIC / 'pulse.html').read_text()
    source = re.sub(r'<script src="(?:https://[^"]+|/static/nav-count.js)"[^>]*></script>', '', source)
    shell = (STATIC / 'shell.css').read_text()
    source = source.replace('<link rel="stylesheet" href="/static/shell.css">', '<style>' + shell + '</style>')
    source = source.replace('/static/', STATIC.as_uri() + '/')
    source = source.replace("location.pathname === '/constellation'", str(full).lower())
    setup = """
window.setInterval = window.requestAnimationFrame = () => 0;
const projects = [
  {name:'Inbox', active_board_items:2, age_days:0, related:['Updates']},
  {name:'Updates', recent_edits:3, age_days:2},
  {name:'Waiting', stale:true, age_days:90},
  {name:'Library', age_days:12},
  {name:'Archive', status:'paused', age_days:60},
];
window.fetch = async path => {
  if (path !== '/api/pulse') throw Error('Unexpected fixture request ' + path);
  return {json:async () => ({vault:{project_signals:projects, projects:5, markdown_files:12, words:2400, skills:2},
    activity:{today_runs:0, running_now:0}, board:{cleared_today:0, board_active:2}})};
};
"""
    source = source.replace('<head>', '<head><style>#theme-result {display:none}</style><script>' + setup + '</script>')
    probe = """
function check(value, message) { if (!value) throw Error(message); }
const rootStyle = getComputedStyle(document.documentElement);
function checkPixel(x, y, token) {
  const hex = rootStyle.getPropertyValue(token).trim();
  const rgb = hex.slice(1).match(/../g).map(channel => parseInt(channel, 16));
  const px = ctx.getImageData(Math.floor(x * devicePixelRatio), Math.floor(y * devicePixelRatio), 1, 1).data;
  check(px[3] > 160 && rgb.every((v, i) => Math.abs(v - px[i]) <= 4), token + ': ' + px);
}
function probe() {
  const original = nodes, links = edges;
  const schemes = ['purple','slate','midnight','forest','charcoal','light'];
  const backgrounds = new Set();
  for (const scheme of schemes) {
    roostaTheme.set(scheme);
    check(roostaTheme.scheme() === scheme, scheme);
    drawConstellation();
    backgrounds.add(getComputedStyle(canvas).backgroundImage);
    for (const [name, token] of Object.entries({
      Inbox:'--signal-amber', Updates:'--signal-cyan', Waiting:'--signal-coral', Library:'--console-secondary',
    })) {
      const n = nodes.find(n => n.name === name);
      checkPixel(n.x, n.drawY, token);
    }
  }
  check(backgrounds.size === schemes.length, 'Distinct scheme backgrounds');
  const star = nodes.find(n => n.name === 'Inbox');
  zoomAt(2, star.x, star.y);
  const transform = JSON.stringify(view);
  document.querySelector('[data-filter=attention]').click();
  selectedName = star.name;
  localStorage.setItem('roosta-theme', 'forest');
  dispatchEvent(new StorageEvent('storage', {key:'roosta-theme'}));
  check(roostaTheme.scheme() === 'forest', 'Storage change');
  drawConstellation();
  checkPixel(star.x * view.scale + view.x, star.drawY * view.scale + view.y, '--console-text');
  check(nodes === original && edges === links && selectedName === star.name &&
    filterMode === 'attention' && JSON.stringify(view) === transform, 'View or topology changed');
  selectedName = null;
  document.querySelector('[data-filter=all]').click();
  zoomAt(0, 0, 0);
  roostaTheme.set(new URLSearchParams(location.search).get('scheme') || 'light');
  drawConstellation();
  const bounds = canvas.getBoundingClientRect();
  const drawer = document.getElementById('constellation-detail').getBoundingClientRect();
  const viewport = document.documentElement.clientWidth;
  const mainWidth = document.querySelector('.pulse-main').getBoundingClientRect().width;
  check(Math.abs(mainWidth - viewport) <= 1 && document.documentElement.scrollWidth <= viewport, 'Pulse width');
  check(bounds.width > 0 && bounds.right <= viewport, 'Canvas bounds');
  check(innerWidth <= 900 ? drawer.top >= bounds.bottom : drawer.left >= bounds.right, 'Drawer placement');
}
refresh().then(() => {
  let error = null;
  try { probe(); } catch (e) { error = e.message; }
  const out = document.createElement('pre');
  out.id = 'theme-result';
  out.textContent = JSON.stringify({error}); document.body.appendChild(out);
});
"""
    boot = '        refresh();\n        resizeCanvas();\n        drawConstellation();'
    assert boot in source
    page = directory / ('fullscreen.html' if full else 'pulse.html')
    page.write_text(source.replace(boot, probe))
    return page


def test_constellation_repaints_without_losing_view(tmp_path):
    chrome = chrome_path()
    if not chrome:
        pytest.skip('Chrome or Chromium is required for canvas checks')
    result = run_probe(chrome, fixture_page(tmp_path), 1440, 900, 'theme-result')
    assert result['error'] is None, result
