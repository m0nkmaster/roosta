const allowedTags=new Set([
  'A','BLOCKQUOTE','BR','CODE','DEL','EM','H1','H2','H3','H4','H5','H6','HR',
  'LI','OL','P','PRE','STRONG','TABLE','TBODY','TD','TH','THEAD','TR','UL'
]);
function safeMarkdown(source){
  const template=document.createElement('template');
  template.innerHTML=marked.parse(String(source||''));
  [...template.content.querySelectorAll('*')].forEach(element=>{
    if(!allowedTags.has(element.tagName)){
      element.replaceWith(document.createTextNode(element.textContent||''));
      return;
    }
    const href=element.tagName==='A'?element.getAttribute('href'):null;
    [...element.attributes].forEach(attribute=>element.removeAttribute(attribute.name));
    if(element.tagName==='A'){
      if(!href) return;
      try{
        const url=new URL(href,location.origin);
        if(!['http:','https:'].includes(url.protocol)) throw new Error('unsafe link');
        element.href=url.toString();
        element.target='_blank';
        element.rel='noopener';
      }catch(error){ element.removeAttribute('href'); }
    }
  });
  return template.innerHTML;
}
// Obsidian [[target#heading|label]]: a bare project slug, a workspace path or a file stem anywhere.
function resolveWikilink(target,paths){
  const t=target.trim().replace(/\.md$/,'');
  return paths.find(p=>p===t+'.md')||paths.find(p=>p==='projects/'+t+'/README.md')||paths.find(p=>p.endsWith('/'+t+'.md'))||paths.find(p=>p.endsWith('/'+t+'/README.md'));
}
// Resolve ./x.md or ../x.md against the folder of the document being shown.
function resolveRelative(target,base){
  const parts=String(base||'').split('/').slice(0,-1);
  let decoded;
  try{decoded=decodeURIComponent(target);}catch(error){return '';}
  for(const part of decoded.split('/')){
    if(part==='..'){ if(!parts.length) return ''; parts.pop(); }
    else if(part&&part!=='.') parts.push(part);
  }
  return parts.join('/');
}
function wikiLinks(markdown,paths,base='',from=''){
  const href=path=>`/document?path=${encodeURIComponent(path)}`+(from?'&from='+encodeURIComponent(from):'');
  return String(markdown||'').replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g,(_,target,label)=>{
    const path=resolveWikilink(target,paths),text=(label||target).trim();
    return path?`[${text}](${href(path)})`:text;
  }).replace(/\]\((?!\w+:|\/|#)(?:<([^>\n]+\.md)(?:#[^>]*)?>|([^)\s#]+\.md)(?:#[^)\s]*)?)\)/gi,(link,angle,raw)=>{
    const target=angle||raw;
    const path=resolveRelative(target,base);
    return paths.includes(path)?`](${href(path)})`:link;
  });
}
