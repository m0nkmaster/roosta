"""Offline page fixtures for collection navigation and mixed-star reviews."""
import json
import os
import re
import shutil

import pytest

from chrome_probe import run_probe
from test_columns import STATIC, chrome_path
from test_workspace_collections import CLIENT, OTHER, PROJECT, seed
from roosta import pulse, workspace


def fixture_page(directory, name):
    root = directory / "workspace"
    seed(root)
    catalogue = workspace.build_catalogue(root)
    client = pulse.entity_id(CLIENT)
    snapshot = pulse.build_pulse(root, [], {}, 0, 0, {})
    briefs = {s["name"]: pulse.project_brief(root, s["name"]) for s in snapshot["workspace"]["project_signals"]}
    verified = pulse.review_project(root, client, "confirm", reviewer="human:owner")
    data = {"catalogue": catalogue, "pulse": snapshot, "briefs": briefs, "verified": verified,
            "after": pulse.build_pulse(root, [], {}, 0, 0, {}), "client": client,
            "path": CLIENT, "project": PROJECT, "other": OTHER}
    setup = """
window.setInterval = window.requestAnimationFrame = () => 0;
history.replaceState = () => {};
let confirmed = false;
window.fetch = async (url, options) => {
  let value;
  if (url === '/api/workspace') value = sample.catalogue;
  else if (url.startsWith('/api/workspace/document?')) {
    const path = new URL(url,'https://fixture.invalid').searchParams.get('path');
    value = {path,content:sample.catalogue.files.find(f=>f.path===path).text};
  } else if (url === '/api/pulse') value = confirmed ? sample.after : sample.pulse;
  else if (url.startsWith('/api/projects/') && !options) {
    const id=url.split('/').pop(); value=confirmed && id===sample.client ? sample.verified : sample.briefs[id];
  }
  else if (url === '/api/projects/'+sample.client+'/review' && options.method==='POST'
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
click('[data-select]');
const attachments=new URL(q('#open-chat').href).searchParams.getAll('file');
check(attachments.length===1 && attachments.includes(sample.path),'Attachment');
"""
    pulse_probe = """
const search=q('#constellation-search');search.value='Clients Coast';search.dispatchEvent(new Event('input'));
check(q('#constellation-detail').textContent.includes('1 of 3 stars match'),'Mixed collection search');
const drawer=q('#constellation-detail');
click('[data-filter="stale"]');
check(q('[data-filter="stale"]').getAttribute('aria-pressed')==='true','Drifting filter selected');
click('#constellation-detail [data-project="'+sample.client+'"]');await settle();
check(drawer.dataset.shown===sample.client && drawer.textContent.includes('Coast account'),'Select matching star');
check(drawer.textContent.includes('verified'),'Date source');
click('[data-zoom="in"]');
search.value='';search.dispatchEvent(new Event('input'));
click('[data-filter="all"]');click('#review-start');
check(drawer.textContent.includes('Review 1 of 2'),'Review starts at the drifting client');
click('[data-review-action="confirm"]');await settle();
check(confirmed && drawer.textContent.includes('Review 2 of 2') && drawer.textContent.includes('Partner account'),
      'Confirmation advances review to the partner');
click('[data-review-nav="prev"]');await settle();
check(drawer.dataset.shown===sample.client && drawer.textContent.includes('Human-checked'),'Return to verified client');
click('[data-review-nav="exit"]');
check(drawer.dataset.shown===sample.client && !q('[data-review-nav="exit"]'),'Exit review with client selected');
"""
    source = (STATIC / f"{name}.html").read_text()
    source = re.sub(r'<script src="(?:https://[^"]+|/static/nav-count.js)"[^>]*></script>', '', source)
    source = source.replace('/static/', STATIC.as_uri() + '/')
    setup = 'const sample=' + json.dumps(data).replace('<', r'\u003c') + ';' + setup
    marked = os.environ.get("ROOSTA_QA_MARKED")
    if marked:
        shutil.copyfile(marked, directory / "marked.umd.js")
        renderer = '<script src="marked.umd.js"></script>'
    else:
        renderer = '<script>window.marked={parse:text=>text};</script>'
    source = source.replace('<head>', '<head><style>#collection-result{display:none}</style>' + renderer + '<script>' + setup + '</script>')
    probe = """
const q=s=>document.querySelector(s),check=(ok,hint)=>{if(!ok)throw Error(hint);};
function click(selector){
  const element=q(selector);
  check(element && !element.disabled,'Expected enabled control '+selector);
  element.click();
}
const rows=()=>Array.from(document.querySelectorAll('[data-preview]'),b=>b.dataset.preview);
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
window.addEventListener('load',async()=>{
  let error=null;
  try {
    await settle();
    PROBE
    check(document.documentElement.scrollWidth<=document.documentElement.clientWidth,'Horizontal overflow');
  } catch(e){error=e.message;}
  const out=document.createElement('pre');out.id='collection-result';
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
