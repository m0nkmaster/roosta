// Copy rendered vault Markdown back out as Markdown. Pages register the
// elements that hold rendered documents with watch(selector); highlighting
// inside one (or Cmd+C) copies the selection as Markdown. copyMarkdown(text)
// backs each page's Copy button. Needs Turndown and its GFM plugin loaded first.
//
// Copies go through document.execCommand('copy') because the desktop app
// denies the async Clipboard API's permission; navigator.clipboard is the
// fallback for browsers where execCommand is unavailable.
(function(){
  const roots=[];
  const INLINE_TAGS=new Set(['A','CODE','DEL','EM','STRONG']);
  const BLOCK_SELECTOR='p,li,ul,ol,h1,h2,h3,h4,h5,h6,table,tr,pre,blockquote,dl,dt,dd,hr';
  let turndown=null,pending=null,toastTimer=null;

  function converter(){
    if(turndown||typeof TurndownService==='undefined') return turndown;
    turndown=new TurndownService({headingStyle:'atx',codeBlockStyle:'fenced',bulletListMarker:'-',emDelimiter:'*',hr:'---'});
    if(typeof turndownPluginGfm!=='undefined') turndown.use(turndownPluginGfm.gfm);
    // Vault style: "- item" and "1. item", not Turndown's padded "-   item".
    turndown.addRule('listItem',{filter:'li',replacement:(content,node)=>{
      const parent=node.parentNode;
      let marker='- ';
      if(parent&&parent.nodeName==='OL'){
        const start=Number(parent.getAttribute('start'))||1;
        marker=(start+[...parent.children].indexOf(node))+'. ';
      }
      content=content.replace(/^\n+/,'').replace(/\n+$/,'\n').replace(/\n/gm,'\n'+' '.repeat(marker.length));
      return marker+content+(node.nextSibling&&!/\n$/.test(content)?'\n':'');
    }});
    return turndown;
  }

  // Text fields keep the browser's own copy.
  const isField=el=>!!(el&&el.closest&&el.closest('input,textarea,select,[contenteditable=""],[contenteditable="true"]'));
  // The registered root holding a non-empty selection, with its range.
  function selectionInRoot(){
    if(isField(document.activeElement)) return null;
    const selection=window.getSelection();
    if(!selection||selection.isCollapsed||!selection.rangeCount) return null;
    const range=selection.getRangeAt(0);
    let node=range.commonAncestorContainer;
    if(node.nodeType!==Node.ELEMENT_NODE) node=node.parentElement;
    for(const selector of roots){
      const root=node&&node.closest(selector);
      if(root) return {root,range};
    }
    return null;
  }

  // A phrase inside one block copies as inline Markdown (keeping bold, code
  // and links); a selection across blocks rebuilds its surroundings (list,
  // table, quote) so partial lists and tables keep their structure.
  function selectionMarkdown(range,root){
    let ancestor=range.commonAncestorContainer;
    if(ancestor.nodeType!==Node.ELEMENT_NODE) ancestor=ancestor.parentElement;
    const md=converter();
    if(!md||ancestor.closest('pre')) return range.toString();
    let node=range.cloneContents();
    const inline=!node.querySelector(BLOCK_SELECTOR);
    for(;ancestor&&ancestor!==root&&root.contains(ancestor);ancestor=ancestor.parentElement){
      if(inline&&!INLINE_TAGS.has(ancestor.tagName)) continue;
      const wrapper=ancestor.cloneNode(false);
      // Selected rows keep the header so they still form a Markdown table.
      if(ancestor.tagName==='TABLE'&&ancestor.tHead&&!node.querySelector('thead'))
        wrapper.append(ancestor.tHead.cloneNode(true));
      wrapper.append(node);
      node=wrapper;
    }
    const holder=document.createElement('div');
    holder.append(node);
    holder.querySelectorAll('.copy-code').forEach(button=>button.remove());
    holder.querySelectorAll('mark').forEach(mark=>mark.replaceWith(...mark.childNodes));
    // In-app document links become vault paths, which mean something once pasted.
    holder.querySelectorAll('a[href]').forEach(link=>{
      try{
        const url=new URL(link.getAttribute('href'),location.origin);
        if(url.origin!==location.origin) return;
        if(url.pathname==='/document'&&url.searchParams.get('path'))
          link.setAttribute('href',url.searchParams.get('path'));
        else if(url.hash) link.setAttribute('href',url.hash);
      }catch(error){}
    });
    // Frontmatter properties render as a <dl>, which Markdown has no syntax for.
    holder.querySelectorAll('dl').forEach(list=>{
      const block=document.createElement('p');
      [...list.querySelectorAll('dt')].forEach((term,index)=>{
        if(index) block.append(document.createElement('br'));
        block.append(`${term.textContent}: ${term.nextElementSibling?.textContent||''}`);
      });
      list.replaceWith(block);
    });
    return md.turndown(holder.innerHTML).trim();
  }

  function toast(message){
    let el=document.getElementById('markdown-copy-toast');
    if(!el){
      el=document.createElement('div');
      el.id='markdown-copy-toast';
      el.setAttribute('role','status');
      el.setAttribute('aria-live','polite');
      el.style.cssText='position:fixed;left:50%;bottom:1.5rem;transform:translateX(-50%);z-index:2000;'
        +'background:#161b22;border:1px solid #30363d;color:#e6edf3;padding:.4rem .8rem;font-size:.78rem;'
        +'border-radius:4px;pointer-events:none;transition:opacity .15s;opacity:0';
      document.body.append(el);
    }
    el.textContent=message;
    el.style.opacity='1';
    clearTimeout(toastTimer);
    toastTimer=setTimeout(()=>{ el.style.opacity='0'; },1400);
  }

  async function copyMarkdown(text,message='Copied as Markdown'){
    if(!text) return false;
    pending=text;
    let copied=false;
    try{ copied=document.execCommand('copy'); }catch(error){}
    pending=null;
    if(!copied&&navigator.clipboard){
      try{ await navigator.clipboard.writeText(text); copied=true; }catch(error){}
    }
    toast(copied?message:'Copy failed');
    return copied;
  }

  document.addEventListener('copy',event=>{
    if(!event.clipboardData) return;
    let text=pending;
    if(text===null){
      const found=selectionInRoot();
      if(!found) return;
      text=selectionMarkdown(found.range,found.root);
      toast('Selection copied as Markdown');
    }
    event.preventDefault();
    event.clipboardData.setData('text/plain',text);
  });
  document.addEventListener('mouseup',event=>{
    // Only a highlight that ends in a document counts, so clicking a Copy
    // button with text still selected does not re-copy the selection.
    const target=event.target instanceof Element?event.target:event.target?.parentElement;
    if(!target||target.closest('.copy-code')||isField(target)||!roots.some(selector=>target.closest(selector))) return;
    // Wait a tick so a click that clears the selection is seen as collapsed.
    setTimeout(()=>{
      const found=selectionInRoot();
      if(found) copyMarkdown(selectionMarkdown(found.range,found.root),'Selection copied as Markdown');
    },0);
  });

  window.markdownCopy={
    watch(selector){ if(!roots.includes(selector)) roots.push(selector); },
    copyMarkdown,
    selectionMarkdown,
  };
})();
