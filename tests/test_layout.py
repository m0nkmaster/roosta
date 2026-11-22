"""Render real page CSS without the live runner, polling or external scripts."""
from pathlib import Path
import re
import shutil

import pytest

from chrome_probe import run_probe


STATIC = Path(__file__).parents[1] / 'src/roosta/static'


@pytest.fixture
def chrome():
    chrome = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
    if not chrome:
        mac = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        if mac.is_file():
            chrome = str(mac)
    if not chrome:
        pytest.skip('Chrome or Chromium is required for layout checks')
    return chrome


@pytest.mark.parametrize('name,width,height', [('settings', 1600, 600), ('assistant', 650, 400)])
def test_page_fills_width_and_bottom_controls_remain_reachable(chrome, tmp_path, name, width, height):
    source = (STATIC / f'{name}.html').read_text()
    source = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', source, flags=re.I)
    source = source.replace('/static/', STATIC.as_uri() + '/')
    probe = """
if (document.body.classList.contains('assistant-page')) {
  document.getElementById('pane').innerHTML = '<div class="conversation-header">Chat</div>' +
    '<div class="logwrap"><div class="log">' + '<div class="msg"><div class="bubble">A message to read.</div></div>'.repeat(40) +
    '</div></div><form class="form"><textarea class="input form-control"></textarea><button class="btn btn-primary">Send</button></form>';
} else {
  document.querySelectorAll('details').forEach(el => el.open = true);
}
const main = document.querySelector('main,.main');
for (const el of [main, document.querySelector('.logwrap')]) {
  if (el) el.scrollTo({top:el.scrollHeight, behavior:'instant'});
}
window.scrollTo({top:document.scrollingElement.scrollHeight, behavior:'instant'});
const composer = document.querySelector('.form');
const log = document.querySelector('.logwrap');
const result = {
  // clientWidth/Height exclude classic scrollbars (Linux and some macOS runners).
  width:document.documentElement.clientWidth, height:document.documentElement.clientHeight, mainWidth:main.getBoundingClientRect().width,
  mainBottom:main.getBoundingClientRect().bottom,
  composerBottom:composer?.getBoundingClientRect().bottom,
  logHeight:log?.clientHeight, logRemaining:log ? log.scrollHeight-log.clientHeight-log.scrollTop : null,
};
const output = document.createElement('pre');
output.id = 'layout-result'; output.textContent = JSON.stringify(result);
document.body.appendChild(output);
"""
    source = source.replace('</body>', '<script>' + probe + '</script></body>')
    page = tmp_path / 'page.html'
    page.write_text(source)
    result = run_probe(chrome, page, width, height, "layout-result")
    if name == 'settings':
        assert result['mainWidth'] == pytest.approx(result['width'], abs=1), result
        assert result['mainBottom'] <= result['height'] + 1, result
    else:
        assert result['composerBottom'] <= result['height'] + 1, result
        assert result['logHeight'] > 0 and abs(result['logRemaining']) <= 1, result


def test_chat_code_copy_after_rerender(chrome, tmp_path):
    assistant = (STATIC / 'assistant.html').read_text()
    page_html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', assistant, flags=re.I)
    renderer = assistant[assistant.index('const esc='):assistant.index('const ctas=')]
    listener = assistant[assistant.index("markdownCopy.watch("):assistant.index('function showDocPane')]
    # Supply parsed Markdown locally. Exercise Roosta's sanitizer and clipboard event path.
    probe = r"""
const marked = {parse: source => source};
let copied = [];
function copyEvent() {
  const event = new Event('copy', {bubbles:true, cancelable:true});
  event.clipboardData = {setData: (type, text) => copied.push(text)};
  document.dispatchEvent(event);
  return event.defaultPrevented;
}
document.execCommand = command => command === 'copy' && copyEvent();
const pane = document.getElementById('pane');
pane.innerHTML = '<article class="msg ai"><div class="who">Assistant</div><div class="bubble"></div></article><textarea></textarea>';
const bubble = pane.querySelector('.bubble');
const sample = '<p>Example</p><pre><code class="language-js" onclick="oops()">  &lt;x&gt; &amp; `v`\\n\t  \n\n' +
  'x'.repeat(200) + '\n</code></pre>';
bubble.innerHTML = md('<pre><code>partial</code></pre>');
bubble.innerHTML = md(sample + '<pre><code>second</code></pre><button class="copy-code">fake</button>');
const buttons = bubble.querySelectorAll('button');
const code = bubble.querySelector('code');
buttons[0].focus();
const focusable = document.activeElement === buttons[0];
buttons[0].querySelector('svg').dispatchEvent(new MouseEvent('click', {bubbles:true}));
buttons[1].click();
const range = document.createRange();
range.setStart(code.firstChild, 0);
range.setEnd(code.firstChild, 4);
window.getSelection().removeAllRanges();
window.getSelection().addRange(range);
copyEvent();
pane.querySelector('textarea').focus();
const nativeInput = !copyEvent();
const bounds = buttons[0].getBoundingClientRect();
const pre = code.parentElement;
const result = {
  count: buttons.length, label: buttons[0].getAttribute('aria-label'), focusable,
  sanitized: !code.attributes.length, copied, nativeInput,
  fits: pre.scrollWidth > pre.clientWidth && bounds.left >= pre.getBoundingClientRect().right &&
    bounds.right <= document.documentElement.clientWidth
};
const output = document.createElement('pre');
output.id = 'code-result';
output.textContent = JSON.stringify(result);
document.body.append(output);
"""
    scripts = '<script>' + '\n'.join([(STATIC / 'markdown-copy.js').read_text(), renderer, listener, probe]) + '</script>'
    page = tmp_path / 'chat-copy.html'
    page.write_text(page_html.replace('/static/', STATIC.as_uri() + '/').replace('</body>', scripts + '</body>'))
    result = run_probe(chrome, page, 520, 600, 'code-result')
    assert result == {
        'count': 2, 'label': 'Copy code', 'focusable': True, 'sanitized': True,
        'copied': ['  <x> & `v`\\n\t  \n\n' + 'x' * 200 + '\n', 'second', '  <x'],
        'nativeInput': True, 'fits': True,
    }


@pytest.mark.parametrize('width', [1280, 390])
def test_settings_account_controls_during_model_discovery(chrome, tmp_path, width):
    # Only the AI panel talks to this in-memory API. Keep the page and its styles intact.
    source = (STATIC / 'settings.html').read_text()
    source = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', source, flags=re.I)
    source = source.replace('/static/', STATIC.as_uri() + '/')
    fixture = Path(__file__).with_name('settings_account_probe.js').read_text()
    setup, interactions = fixture.split('// Run after the actual Settings script.')
    scripts = (setup, (STATIC / 'ai-settings.js').read_text(), interactions)
    page = tmp_path / 'settings.html'
    page.write_text(source.replace('</body>', ''.join('<script>' + js + '</script>' for js in scripts) + '</body>'))
    result = run_probe(chrome, page, width, 800, 'account-result')
    assert result == {'ok': True}, result
