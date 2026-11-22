"""Offline page fixtures for collection navigation and mixed-star reviews."""
import json
import re

import pytest

from chrome_probe import run_probe
from test_columns import STATIC, chrome_path
from test_workspace_collections import CLIENT, OTHER, PROJECT, seed
from roosta import pulse, workspace


def fixture_page(directory, name):
    root = directory / "vault"
    seed(root)
    catalogue = workspace.build_catalogue(root)
    client = pulse.entity_id(CLIENT)
    snapshot = pulse.build_pulse(root, [], {}, 0, 0, {})
    briefs = {s["name"]: pulse.project_brief(root, s["name"]) for s in snapshot["vault"]["project_signals"]}
    verified = pulse.review_project(root, client, "confirm", reviewer="human:owner")
    data = {"catalogue": catalogue, "pulse": snapshot, "briefs": briefs, "verified": verified,
            "after": pulse.build_pulse(root, [], {}, 0, 0, {}), "client": client,
            "path": CLIENT, "project": PROJECT, "other": OTHER}
    setup = """
window.setInterval = window.requestAnimationFrame = () => 0;
history.replaceState = () => {};
window.marked = {parse: text => text};
let confirmed = false;
window.fetch = async (url, options) => {
  let value;
  if (url === '/api/workspace') value = sample.catalogue;
  else if (url.startsWith('/api/vault-document?')) {
    const path = new URL(url,'https://fixture.invalid').searchParams.get('path');
    value = {path,content:sample.catalogue.files.find(f=>f.path===path).text};
  } else if (url === '/api/pulse') value = confirmed ? sample.after : sample.pulse;
  else if (url.startsWith('/api/constellation/') && !options) {
    const id=url.split('/').pop(); value=confirmed && id===sample.client ? sample.verified : sample.briefs[id];
  }
  else if (url === '/api/constellation/'+sample.client+'/review' && options.method==='POST'
           && JSON.parse(options.body).action==='confirm') { confirmed=true;value=sample.verified; }
  else throw Error('Unexpected fixture request '+url);
  return {ok:true,json:async()=>value};
};
"""
    workspace_probe = """
check(q('#scope-title').textContent==='Clients','Initial collection');
check(rows().join('|')===[sample.path,sample.other].join('|'),'Curated order');
click('[data-collection="collection:projects/README.md"]');
check(rows()[0]===sample.project,'Choose projects');
click('[data-view="topics"]');click('[data-collection="topic:delivery"]');
check(rows()[0]===sample.other,'Topic reading list');
click('[data-view="work"]');click('[data-collection="work:plans"]');
click('[data-preview]');await settle();
const preview=q('#preview article').textContent;
check(preview.includes('Pilot first.') && !preview.includes('Unrelated history.'),'Source section');
check(new URL(q('#open-document').href).searchParams.get('path')===sample.path,'Canonical source');
click('[data-select]');check(new URL(q('#open-chat').href).searchParams.getAll('file').includes(sample.path),'Attachment');
"""
    pulse_probe = """
const search=q('#constellation-search');search.value='Clients Coast';search.dispatchEvent(new Event('input'));
check(q('#constellation-detail').textContent.includes('1 of 3 stars match'),'Mixed collection search');
click('[data-filter="stale"]');click('[data-project]');await settle();
check(q('#constellation-detail').textContent.includes('Coast account'),'Select star');
check(q('#constellation-detail').textContent.includes('verified'),'Date source');
click('[data-zoom="in"]');click('#review-start');click('[data-review-action="confirm"]');await settle();
check(confirmed,'Confirm selected page');
click('[data-review-nav="exit"]');search.dispatchEvent(new Event('input'));
click('[data-project]');await settle();
check(q('#constellation-detail').textContent.includes('Human-checked'),'Updated drawer');
"""
    source = (STATIC / f"{name}.html").read_text()
    source = re.sub(r'<script src="(?:https://[^"]+|/static/nav-count.js)"[^>]*></script>', '', source)
    source = source.replace('/static/', STATIC.as_uri() + '/')
    setup = 'const sample=' + json.dumps(data).replace('<', r'\u003c') + ';' + setup
    source = source.replace('<head>', '<head><script>' + setup + '</script>')
    probe = """
const q=s=>document.querySelector(s),click=s=>q(s).click(),check=(ok,hint)=>{if(!ok)throw Error(hint);};
const rows=()=>Array.from(document.querySelectorAll('[data-preview]'),b=>b.dataset.preview);
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
window.addEventListener('load',async()=>{
  let error=null;
  try {
    await settle();
    PROBE
    check(document.documentElement.scrollWidth<=document.documentElement.clientWidth,'Horizontal overflow');
  } catch(e){error=e.message;}
  const out=document.createElement('pre');out.id='collection-result';out.hidden=true;
  out.textContent=JSON.stringify({error});document.body.appendChild(out);
});
""".replace('PROBE', workspace_probe if name == 'workspace' else pulse_probe)
    page = directory / (name + '.html')
    page.write_text(source.replace('</body>', '<script>' + probe + '</script></body>'))
    return page


@pytest.mark.parametrize('name', ['workspace', 'pulse'])
@pytest.mark.parametrize('width', [1440, 480])
def test_collection_interactions(tmp_path, name, width):
    page = fixture_page(tmp_path, name)
    result = run_probe(chrome_path(), page, width, 900, 'collection-result')
    assert result['error'] is None, result
