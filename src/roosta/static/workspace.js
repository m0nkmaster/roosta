const $=id=>document.getElementById(id);
const escapeHtml=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function searchTerms(query){
  return [...new Set((query.match(/"[^"]+"|\S+/g)||[]).map(term=>term.replace(/^"|"$/g,'').toLowerCase()).filter(Boolean))];
}
function searchFiles(files,query,paths=null){
  const terms=searchTerms(query);
  return files.filter(file=>(!paths||paths.has(file.path))&&terms.every(term=>file.search.includes(term)))
    .map(file=>({file,score:terms.reduce((score,term)=>score+(file.title.toLowerCase().includes(term)?10:0)+(file.path.toLowerCase().includes(term)?5:0),0)}))
    .sort((a,b)=>b.score-a.score||b.file.modified.localeCompare(a.file.modified)||a.file.path.localeCompare(b.file.path))
    .map(result=>result.file);
}
function highlightText(text,terms){
  const lower=text.toLowerCase(),ranges=[];
  for(const term of terms){
    let at=0;
    while(term&&(at=lower.indexOf(term,at))!==-1){ranges.push([at,at+term.length]);at+=term.length;}
  }
  ranges.sort((a,b)=>a[0]-b[0]);
  const merged=[];
  for(const range of ranges){
    const last=merged[merged.length-1];
    if(last&&range[0]<=last[1]) last[1]=Math.max(last[1],range[1]);else merged.push([...range]);
  }
  let out='',at=0;
  for(const [start,end] of merged){out+=escapeHtml(text.slice(at,start))+'<mark>'+escapeHtml(text.slice(start,end))+'</mark>';at=end;}
  return out+escapeHtml(text.slice(at));
}
function snippet(text,terms){
  const flat=text.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/,'').replace(/\s+/g,' '),lower=flat.toLowerCase();
  const matches=terms.map(term=>lower.indexOf(term)).filter(at=>at>=0);
  const start=Math.max(0,(matches.length?Math.min(...matches):0)-65);
  return (start?'…':'')+flat.slice(start,start+220)+(flat.length>start+220?'…':'');
}

const params=new URLSearchParams(location.search);
const editor=documentEditor($('editor'),$('preview'),safeMarkdown,loadWorkspace);
const state={files:[],collections:[],view:params.get('view')||(params.has('q')||params.has('path')?'all':'collections'),collection:params.get('collection')||'',path:params.get('path')||'',selected:new Set(),preview:null,request:0};
try{const saved=JSON.parse(sessionStorage.getItem('workspace-selection')||'[]');if(Array.isArray(saved)) state.selected=new Set(saved.filter(p=>typeof p==='string').slice(0,8));}catch(error){}
if(params.has('item')) state.selected=new Set(params.getAll('file').slice(0,8));
$('search').value=params.get('q')||'';
function notice(message){$('notice').textContent=message;}
function updateUrl(){
  const url=new URL(location.href);
  for(const [key,value] of [['q',$('search').value],['view',state.view],['collection',state.collection],['path',state.path]]){
    if(value) url.searchParams.set(key,value);else url.searchParams.delete(key);
  }
  url.searchParams.delete('folder');
  history.replaceState(null,'',url);
}
const views={
  collections:{title:'Collections',summary:'Pages chosen in your workspace.'},
  all:{title:'All knowledge',summary:'Search every visible Markdown document in your workspace.'},
  projects:{title:'Projects',summary:'The work in progress and its supporting plans, notes and decisions.'},
  topics:{title:'Topics',summary:'Shared subjects, connected across projects and documents through their tags.'},
  work:{title:'Decisions & plans',summary:'Find agreements, proposals and the plans for what comes next.'}
};
function currentCollection(){return state.collections.find(collection=>collection.id===state.collection);}
function scopePaths(){
  const collection=currentCollection();
  if(collection) return new Set(collection.paths);
  return state.view==='all'?null:new Set(state.collections.filter(collection=>collection.group===state.view).flatMap(collection=>collection.paths));
}
function statusBadge(status){
  const colors={active:'success',blocked:'danger',paused:'warning',completed:'secondary'};
  return colors[status]?`<span class="badge bg-${colors[status]}-lt">${escapeHtml(status)}</span>`:'';
}
function renderCollections(){
  $('views').innerHTML=Object.entries(views).filter(([key])=>key!=='projects'||state.view==='projects').map(([key,view])=>{
    const count=key==='all'?state.files.length:state.collections.filter(collection=>collection.group===key).length;
    return `<button type="button" class="nav-link ${state.view===key?'active':''}" data-view="${key}" ${state.view===key?'aria-current="true"':''}><span>${view.title}</span><span class="small text-secondary">${count}</span></button>`;
  }).join('');
  const group=state.view==='all'?'collections':state.view;
  const collections=state.collections.filter(collection=>collection.group===group);
  $('collection-label').textContent=views[group].title;
  $('collections').innerHTML=collections.length?collections.map(collection=>`<button type="button" class="list-group-item list-group-item-action collection-item ${state.collection===collection.id?'active':''}" data-collection="${escapeHtml(collection.id)}" ${state.collection===collection.id?'aria-current="true"':''}>
    <span class="collection-title">${escapeHtml(collection.title)}</span>
    ${collection.summary?`<span class="collection-summary">${escapeHtml(collection.summary)}</span>`:''}
    <span class="collection-meta">${statusBadge(collection.status)}<span>${collection.paths.length} document${collection.paths.length===1?'':'s'}</span></span></button>`).join('')
    :'<div class="navigator-empty small">No collections yet.<br>Add a list of collection links to WORKSPACE.md.</div>';
  const collection=currentCollection(),scope=collection||views[state.view];
  $('scope-title').textContent=scope.title;
  $('scope-summary').textContent=scope.summary||'Explore the documents collected here.';
  $('scope-status').innerHTML=statusBadge(scope.status);
  $('scope-overview').hidden=!collection?.overview;
  $('scope-overview').onclick=()=>collection?.overview&&previewFile(collection.overview);
}
function renderResults(){
  const start=performance.now(),terms=searchTerms($('search').value);
  const results=searchFiles(state.files,$('search').value,scopePaths());
  const collection=currentCollection();
  const ordered=collection && (collection.ordered||['collections','topics'].includes(collection.group));
  if(!terms.length && ordered){
    const order=new Map(collection.paths.map((path,i)=>[path,i]));
    results.sort((a,b)=>order.get(a.path)-order.get(b.path));
  }
  const sections=collection?.sections||{};
  $('result-count').textContent=`${results.length} document${results.length===1?'':'s'}`;
  $('search-time').textContent=terms.length?`${Math.max(1,Math.round(performance.now()-start))} ms`: ordered?'Index order':'Most recent';
  $('results').innerHTML=results.length?results.map(file=>`<div class="list-group-item result-row" aria-current="${file.path===state.path}">
    <input class="form-check-input" type="checkbox" data-select="${escapeHtml(file.path)}" aria-label="Select ${escapeHtml(file.title)} for chat" ${state.selected.has(file.path)?'checked':''}>
    <button class="result-open" type="button" data-preview="${escapeHtml(file.path)}"><div class="result-title">${highlightText(file.title,terms)}</div><div class="result-purpose" title="${escapeHtml(file.path)}">${highlightText([file.project,file.kind].filter(Boolean).join(' · '),terms)}</div><div class="result-snippet">${highlightText(terms.length?snippet(file.text,terms):(sections[file.path]||file.summary||snippet(file.text,[])).slice(0,240),terms)}</div></button></div>`).join('')
    :'<div class="navigator-empty">No matching documents.<br><span class="small">Try fewer words or choose All knowledge.</span></div>';
  renderPreview();updateUrl();
}
function renderPreview(){
  if(!state.preview) return;
  const terms=searchTerms($('search').value);
  const project=state.collections.find(c=>c.group==='projects'&&c.overview&&c.overview!==state.preview.path&&c.paths.includes(state.preview.path));
  const section=currentCollection()?.sections?.[state.preview.path];
  $('preview').innerHTML=`<div class="preview-copy prose">${project?`<button type="button" class="btn btn-sm btn-ghost-primary mb-2 px-1" data-project="${escapeHtml(project.id)}">↑ ${escapeHtml(project.title)}</button>`:''}<div class="preview-path mb-3">${escapeHtml(state.preview.path)}</div><article>${safeMarkdown(wikiLinks(section||state.preview.content,state.files.map(file=>file.path),state.preview.path))}</article></div>`;
  if(!terms.length) return;
  const walker=document.createTreeWalker($('preview').querySelector('article'),NodeFilter.SHOW_TEXT),nodes=[];
  while(walker.nextNode()) nodes.push(walker.currentNode);
  for(const node of nodes){
    if(!terms.some(term=>node.textContent.toLowerCase().includes(term))) continue;
    const template=document.createElement('template');template.innerHTML=highlightText(node.textContent,terms);node.replaceWith(template.content);
  }
  const first=$('preview').querySelector('mark');
  if(first && !editor.active()){
    const scroll=$('preview').parentElement;
    scroll.scrollTop+=first.getBoundingClientRect().top-scroll.getBoundingClientRect().top-80;
  }
}
async function previewFile(path){
  if(path===state.path && editor.active()) return;
  if(!editor.leave()) return;
  editor.setPath('');
  state.path=path;state.preview=null;const request=++state.request;
  $('open-document').hidden=true;$('chat-document').hidden=true;$('copy-document').hidden=true;
  $('preview').innerHTML='<div class="navigator-empty">Loading document…</div>';
  renderResults();
  try{
    const response=await fetch('/api/vault-document?path='+encodeURIComponent(path)+'&visible=true');
    const data=await response.json();if(request!==state.request) return;
    if(!response.ok) throw new Error(data.error||'Could not open document.');
    editor.setPath(path,data.title);state.preview=data;renderPreview();
    $('open-document').href='/document?'+new URLSearchParams({path,from:location.pathname+location.search});
    $('open-document').hidden=false;$('chat-document').hidden=false;$('copy-document').hidden=false;
  }catch(error){if(request===state.request) $('preview').textContent=error.message;}
}
function chatUrl(paths,question,item=params.get('item')||'new'){
  const query=new URLSearchParams({item,from:'workspace'});
  paths.forEach(path=>query.append('file',path));
  if(question.trim()) query.set('ask',question.trim());
  return '/assistant?'+query;
}
function renderSelection(){
  const files=state.files.filter(file=>state.selected.has(file.path)),size=files.reduce((sum,file)=>sum+file.size,0);
  $('selection-count').textContent=files.length?`${files.length} file${files.length===1?'':'s'} for context`:'Chat about anything';
  $('selection-help').textContent=files.length?`${Math.ceil(size/1024)} KB · Full contents are included when you send.`:'Choose files for direct context, or start with a question.';
  $('selected-files').innerHTML=files.map(file=>`<button class="btn btn-sm" type="button" data-remove="${escapeHtml(file.path)}" title="Remove ${escapeHtml(file.path)}">${escapeHtml(file.title)} <span aria-hidden="true">×</span></button>`).join('');
  $('clear-selection').hidden=!files.length;
  $('open-chat').href=chatUrl([...state.selected],$('question').value);
  $('open-chat').textContent=files.length?`Chat with ${files.length} file${files.length===1?'':'s'} →`:'Open in Assistant →';
  try{sessionStorage.setItem('workspace-selection',JSON.stringify([...state.selected]));}catch(error){}
}
function selectFile(path,selected){
  notice('');
  if(selected){
    const paths=new Set([...state.selected,path]);
    if(paths.size>8){notice('Choose up to 8 files for one conversation.');return false;}
    const bytes=state.files.filter(file=>paths.has(file.path)).reduce((sum,file)=>sum+file.size,0);
    if(bytes>192*1024){notice('Selected files exceed the 192 KB context limit. Choose fewer files.');return false;}
    state.selected.add(path);
  }else state.selected.delete(path);
  renderSelection();return true;
}
async function loadWorkspace(){
  $('refresh').disabled=true;$('index-status').textContent='Reading workspace…';notice('');
  try{
    const response=await fetch('/api/workspace',{cache:'no-store'});
    if(!response.ok) throw new Error('Could not read the workspace. Try Refresh.');
    const data=await response.json();
    state.files=data.files.map(file=>({...file,search:[file.title,file.project,...(file.topics||[]),file.path,file.text].join('\n').toLowerCase()}));
    const paths=new Set(state.files.map(file=>file.path));
    state.selected=new Set([...state.selected].filter(path=>paths.has(path)));
    state.collections=data.collections||[];
    if(!Object.hasOwn(views,state.view)) state.view='all';
    if(state.collection&&!currentCollection()) state.collection='';
    if(!state.collection && state.view==='collections') state.collection=state.collections.find(c=>c.group==='collections')?.id||'';
    if(currentCollection()) state.view=currentCollection().group;
    $('index-status').textContent=`${state.files.length} Markdown documents · Local search`;
    if(data.skipped) notice(`${data.skipped} unreadable or oversized document${data.skipped===1?' was':'s were'} skipped.`);
    renderCollections();renderResults();renderSelection();
    if(editor.active()) return;
    if(paths.has(state.path)) previewFile(state.path);
    else if(state.path){editor.setPath('');state.path='';state.preview=null;$('preview').textContent='This document is no longer available.';$('open-document').hidden=true;$('chat-document').hidden=true;$('copy-document').hidden=true;updateUrl();}
  }catch(error){$('index-status').textContent='Workspace unavailable';notice(error.message);$('results').textContent='Use Refresh to try again.';}
  finally{$('refresh').disabled=false;}
}
$('search').addEventListener('input',renderResults);
$('clear-search').onclick=()=>{$('search').value='';renderResults();$('search').focus();};
$('refresh').onclick=loadWorkspace;
$('reveal-workspace').onclick=async()=>{
  notice('');
  try{
    const response=await fetch('/api/workspace/reveal',{method:'POST'});
    if(!response.ok) notice((await response.json().catch(()=>({}))).error||(response.status===403?'Open folder works only on the computer running Roosta.':'Could not open the workspace folder.'));
  }catch(error){notice('Could not reach Roosta to open the workspace folder.');}
};
$('views').onclick=event=>{
  const button=event.target.closest('[data-view]');if(!button) return;
  if(!clearPreview()) return;
  state.view=button.dataset.view;state.collection='';
  if(state.view==='collections'){const first=state.collections.find(c=>c.group==='collections');if(first)return openCollection(first.id);}
  renderCollections();renderResults();
};
function clearPreview(){
  if(!editor.leave()) return false;
  editor.setPath('');
  ++state.request;state.preview=null;state.path='';
  $('preview').innerHTML='<div class="navigator-empty">Choose a document to read it here.</div>';
  $('open-document').hidden=true;$('chat-document').hidden=true;$('copy-document').hidden=true;
  return true;
}
function openCollection(id){
  if(!clearPreview()) return;
  state.collection=id;state.view=currentCollection().group;
  renderCollections();renderResults();
  const overview=currentCollection().overview;if(overview) previewFile(overview);
}
$('collections').onclick=event=>{const button=event.target.closest('[data-collection]');if(button) openCollection(button.dataset.collection);};
markdownCopy.watch('#preview article');
$('copy-document').onclick=()=>state.preview&&markdownCopy.copyMarkdown(state.preview.content.trim()+'\n','Document copied as Markdown');
$('preview').addEventListener('click',event=>{
  const button=event.target.closest('[data-project]');if(button) return openCollection(button.dataset.project);
  // Vault links preview in place; modifier clicks still open the full document in a new tab.
  const link=event.target.closest('a[href]'),url=link&&new URL(link.href);
  if(!url||url.origin!==location.origin||url.pathname!=='/document'||event.metaKey||event.ctrlKey||event.shiftKey) return;
  event.preventDefault();previewFile(url.searchParams.get('path'));
});
$('results').onclick=event=>{const button=event.target.closest('[data-preview]');if(button) previewFile(button.dataset.preview);};
$('results').onchange=event=>{if(event.target.dataset.select&&!selectFile(event.target.dataset.select,event.target.checked)) event.target.checked=false;};
$('results').onkeydown=event=>{
  if(!['ArrowDown','ArrowUp'].includes(event.key)||!event.target.matches('[data-preview]')) return;
  const buttons=[...$('results').querySelectorAll('[data-preview]')],at=buttons.indexOf(event.target)+(event.key==='ArrowDown'?1:-1);
  if(buttons[at]){event.preventDefault();buttons[at].focus();}
};
$('selected-files').onclick=event=>{const button=event.target.closest('[data-remove]');if(button){selectFile(button.dataset.remove,false);renderResults();}};
$('clear-selection').onclick=()=>{state.selected.clear();notice('');renderSelection();renderResults();};
$('question').oninput=renderSelection;
$('chat-document').onclick=()=>{
  if(!state.preview) return;
  if(!selectFile(state.path,true)) return;
  location.href=chatUrl([...state.selected],$('question').value||'Help me understand this document.', 'doc:'+state.path);
};
document.addEventListener('keydown',event=>{
  const typing=event.target.matches('input,textarea,[contenteditable="true"]');
  if(((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k')||(event.key==='/'&&!typing)){
    event.preventDefault();$('search').focus();$('search').select();
  }
  if(event.key==='ArrowDown'&&event.target===$('search')){event.preventDefault();$('results').querySelector('[data-preview]')?.focus();}
});
loadWorkspace();
