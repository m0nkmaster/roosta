// Textareas expose LF even when the file uses CRLF or mixed line endings.
function editedSource(raw, value){
  const previous=raw.replace(/\r\n?/g,'\n');
  if(previous===value) return raw;
  let start=0, end=previous.length, nextEnd=value.length;
  while(start<end && start<nextEnd && previous[start]===value[start]) start++;
  while(end>start && nextEnd>start && previous[end-1]===value[nextEnd-1]){end--;nextEnd--;}
  // Map the changed textarea span back to byte-preserving source line endings.
  let rawStart=start, rawEnd=end, extra=0;
  for(const match of raw.matchAll(/\r\n/g)){
    const offset=match.index-extra;
    extra++;
    if(offset>=end) break;
    if(offset<start) rawStart++;
    rawEnd++;
  }
  const removed=raw.slice(rawStart,rawEnd).match(/\r\n|\r|\n/g)||[];
  const ending=raw.match(/\r\n|\r|\n/)?.[0]||'\n';
  let i=0;
  const inserted=value.slice(start,nextEnd).replace(/\n/g,()=>removed[i++]||ending);
  return raw.slice(0,rawStart)+inserted+raw.slice(rawEnd);
}

function renderDraftPreview(preview, draft, render){
  const text=draft.replace(/\r\n?/g,'\n');
  const block=/^\uFEFF?---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|$)/.exec(text);
  // Show the fenced metadata verbatim, even while its YAML is incomplete.
  if(!block || !/^[^\s#][^\n]*?:(?:[ \t]|$)/m.test(block[1])){
    preview.innerHTML=render(draft);
    return;
  }
  preview.innerHTML=render(text.slice(block[0].length));
  const metadata=document.createElement('pre');
  metadata.setAttribute('aria-label','Frontmatter');
  metadata.textContent=block[0].trimEnd();
  preview.prepend(metadata);
}

function documentEditor(host, reader, render, reload){
  host.classList.add('document-editor');
  host.innerHTML=`<button type="button" class="btn btn-sm" data-edit>Edit</button>
    <span role="status"></span>
    <section hidden aria-label="Edit Markdown">
      <div class="editor-path"></div>
      <div class="editor-tools">
        <button type="button" class="btn btn-sm" data-source aria-pressed="true">Source</button>
        <button type="button" class="btn btn-sm" data-preview-draft aria-pressed="false">Preview</button>
        <button type="button" class="btn btn-sm btn-primary" data-save>Save</button>
        <button type="button" class="btn btn-sm btn-ghost-secondary" data-cancel>Cancel</button>
        <button type="button" class="btn btn-sm" data-copy>Copy draft</button>
      </div>
      <textarea class="form-control" aria-label="Markdown source" spellcheck="false"></textarea>
      <article class="prose" hidden></article>
    </section>`;
  const q=s=>host.querySelector(s), edit=q('[data-edit]'), panel=q('section'), field=q('textarea');
  const status=q('[role=status]'), preview=q('article'), save=q('[data-save]');
  let path='', title='', generation=0, original='', draft='', revision='', saving=false;
  const active=()=>!panel.hidden;
  const dirty=()=>active()&&draft!==original;
  const unload=e=>{if(dirty()){e.preventDefault();e.returnValue=true;}};
  window.addEventListener('beforeunload',unload);
  function reset(){
    generation++;
    panel.hidden=true;reader.hidden=false;edit.disabled=false;
    edit.hidden=!path || !/\.md$/i.test(path);
    status.textContent=path&&edit.hidden?'Only workspace Markdown files can be edited.':'';
    draft=original=field.value='';preview.replaceChildren();
  }
  function leave(){
    if(saving || (dirty()&&!window.confirm('Discard unsaved changes to '+path+'?'))) return false;
    reset();return true;
  }
  function mode(source){
    field.hidden=!source;preview.hidden=source;
    q('[data-source]').setAttribute('aria-pressed',String(source));
    q('[data-preview-draft]').setAttribute('aria-pressed',String(!source));
    if(source) field.focus();
    else renderDraftPreview(preview,draft,render);
  }
  async function request(options){
    const response=await fetch('/api/workspace/document-source?path='+encodeURIComponent(path),options);
    const data=await response.json();
    if(!response.ok) throw new Error(data.error||data.detail||'Check your connection and try again.');
    return data;
  }
  edit.onclick=async()=>{
    const ticket=++generation;
    edit.disabled=true;status.textContent='Loading source…';
    try{
      const data=await request({cache:'no-store'});
      if(ticket!==generation) return;
      original=draft=data.content;revision=data.revision;field.value=draft;
      panel.hidden=false;reader.hidden=true;edit.hidden=true;
      q('.editor-path').textContent=title && title!==path ? title+' · '+path : path;status.textContent='Editing';save.disabled=true;mode(true);
    }catch(error){
      if(ticket===generation){edit.disabled=false;status.textContent='Editing unavailable. '+error.message;}
    }
  };
  field.oninput=()=>{
    draft=field.value===original.replace(/\r\n?/g,'\n') ? original : editedSource(draft,field.value);
    status.textContent=dirty()?'Unsaved changes':'Editing';save.disabled=!dirty();
  };
  q('[data-source]').onclick=()=>mode(true);
  q('[data-preview-draft]').onclick=()=>mode(false);
  q('[data-copy]').onclick=()=>markdownCopy.copyMarkdown(draft,'Draft copied');
  q('[data-cancel]').onclick=()=>{if(leave()){edit.focus();reload();}};
  save.onclick=async()=>{
    if(saving||!dirty()) return;
    saving=true;save.disabled=true;field.readOnly=true;q('[data-cancel]').disabled=true;
    status.textContent='Saving…';
    try{
      await request({method:'PUT',headers:{'Content-Type':'text/plain;charset=UTF-8','If-Match':'"'+revision+'"'},body:draft});
      reset();status.textContent='Saved';edit.focus();reload();
    }catch(error){
      save.disabled=false;status.textContent='Unsaved changes. '+error.message+' Your draft is available to copy or retry.';
    }finally{saving=false;field.readOnly=false;q('[data-cancel]').disabled=false;}
  };
  reset();
  return {active,leave,setPath(value,label=''){title=label;if(value!==path){path=value;reset();}}};
}
