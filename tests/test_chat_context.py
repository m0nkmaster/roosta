import asyncio
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from roosta import app, chat


@pytest.fixture(autouse=True)
def connected(fake_chat_connection):
    return fake_chat_connection


def use_sessions(monkeypatch, create):
    async def new_session(_connection, _workspace):
        return await create()
    monkeypatch.setattr(chat.ai_backend, "new_session", new_session)


def router_at(directory):
    return chat.ChatRouter(chat.SessionMap(directory / "sessions.json"), str(directory),
                           handled_path=directory / "handled.json",
                           topic_store=chat.TopicStore(directory / "topics.json"),
                           persistent_history=chat.ConversationHistoryStore(directory / "history.json"))


def context(router, item, mode="preview", revision=None, handoff=""):
    return router.reset_context(item, mode, revision, handoff)


def capture_turns(monkeypatch):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append((args[args.index("--resume") + 1], args[-1]))

        async def lines():
            yield b'{"type":"assistant","message":{"content":[{"type":"text","text":"Received."}]}}\n'

        async def wait():
            return 0

        return SimpleNamespace(stdout=lines(), returncode=0, wait=wait)

    monkeypatch.setattr(chat.asyncio, "create_subprocess_exec", spawn)
    return calls


@pytest.mark.parametrize(("item", "mode"), [
    ("inbox-item", "fresh"), ("worker:research", "summary"),
    ("doc:notes/design.md", "fresh"), ("chat:123456789abc", "summary"),
])
def test_reset_restarts_only_selected_context(tmp_path, monkeypatch, item, mode):
    router = router_at(tmp_path)
    old = str(uuid.uuid4())
    router._sessions.connection(item)
    router._sessions.set(item, old)
    router._sessions.set_model(item, "chosen-model")
    router._sessions.bind("other", "c" * 32)
    router._sessions.set("other", old)
    router._topics.begin(item, {"title": "Subject"}, old)
    router._topics.finish(item, "old rolling summary")
    router.mark_handled(item, "Resolved")
    # Pre-dates message timestamps and segment metadata.
    messages = [{"role": "user", "text": "private old text"}]
    (tmp_path / "history.json").write_text(json.dumps({item: messages, "other": messages}))
    revision = context(router, item)["revision"]
    accepted = "Keep the decision\nAsk Sam next"
    result = context(router, item, mode, revision, accepted if mode == "summary" else "")
    assert result["history"] == messages
    assert result["boundaries"][0]["end"] == 1
    fresh = str(uuid.uuid4())

    async def create():
        return fresh

    use_sessions(monkeypatch, create)
    router = router_at(tmp_path)
    # A second preview before the first new turn must never seed from archived messages.
    preview = context(router, item)
    assert "private old text" not in preview["handoff"]
    assert router.known_item(item)["title"] == "Subject"
    assert router._sessions.model(item) == "chosen-model"
    assert router._sessions.connection(item) == "c" * 32
    assert router._sessions.get("other") == old
    assert router.handled()[item]["result"] == "Resolved"
    assert router.conversation_history("other") == messages
    calls = capture_turns(monkeypatch)

    async def turn():
        current = {"id": item, "title": "Subject", "voice": "current worker instructions",
                   "documents": [{"path": "notes/design.md"}]}
        return [e async for e in router.run_turn(item, current, "new question")]

    asyncio.run(turn())
    sid, prompt = calls[0]
    assert sid == fresh
    assert all(s in prompt for s in ("new question", "current worker instructions", "notes/design.md"))
    assert "old rolling summary" not in prompt and "private old text" not in prompt
    assert (accepted if mode == "summary" else "No earlier summary.") in prompt
    assert router.conversation_history(item)[0] == messages[0]
    assert not router._topics.get(item).get("needs_session")
    assert router_at(tmp_path)._sessions.get(item) == fresh


def test_preview_cancel_stale_and_atomic_failure(tmp_path, monkeypatch):
    router = router_at(tmp_path)
    monkeypatch.setattr(app, "chat_router", router)
    item = "chat:123456789abc"
    router._persistent_history.append(item, "user", "recent fact")

    def request(mode, **fields):
        response = asyncio.run(app.api_chat_context({"item_id": item, "mode": mode, **fields}))
        return response.status_code, json.loads(response.body)

    status, preview = request("preview")
    assert status == 200
    assert all(s in preview["handoff"] for s in ("Decisions", "recent fact", "Open questions", "Next steps"))
    assert not (tmp_path / "topics.json").exists()
    router._persistent_history.append(item, "assistant", "new fact")
    assert request("summary", revision=preview["revision"], handoff="edited")[0] == 409
    revision = request("preview")[1]["revision"]
    assert request("summary", revision=revision, handoff=" ")[0] == 400
    assert request("fresh", revision=revision)[0] == 200
    revision = request("preview")[1]["revision"]
    before = {p: p.read_bytes() for p in tmp_path.glob("*.json")}

    def fail_replace(*_):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", fail_replace)
    assert request("summary", revision=revision, handoff="retry")[0] == 500
    assert before == {p: p.read_bytes() for p in tmp_path.glob("*.json")}
    assert not list(tmp_path.glob("*.tmp"))
    assert request("preview")[1]["revision"] == revision


def test_session_creation_queue_and_senders_exclude_reset(tmp_path, monkeypatch):
    calls = capture_turns(monkeypatch)
    item = "inbox-item"

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        sid = str(uuid.uuid4())

        async def create():
            entered.set()
            await release.wait()
            return sid

        use_sessions(monkeypatch, create)
        router = router_at(tmp_path)
        router._sessions.connection(item)
        router._sessions.set(item, str(uuid.uuid4()))
        revision = context(router, item)["revision"]
        context(router, item, "fresh", revision)
        router.start_turn(item, {"id": item}, "one")
        await entered.wait()
        assert router.start_turn(item, {"id": item}, "two").queued
        with pytest.raises(RuntimeError, match="Finish"):
            context(router, item, "fresh", revision)
        release.set()
        while item in router.active_items():
            await router._active_runs[item]
        assert [session for session, _ in calls] == [sid, sid]

        entered.clear()
        release.clear()

        async def sender(*_):
            entered.set()
            await release.wait()
            return {"ok": True}

        monkeypatch.setattr(router, "_send_approved", sender)
        router._paused["r"] = {"item_id": item, "action": {"kind": "message", "draft": "yes", "target": "Sam"}}
        with pytest.raises(RuntimeError, match="Finish"):
            context(router, item)
        approving = asyncio.create_task(router.approve("r", True, None))
        await entered.wait()
        approving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await approving
        with pytest.raises(RuntimeError, match="Finish"):
            context(router, item)
        release.set()
        await asyncio.gather(*router._sending)
        assert context(router, item)["revision"]

    asyncio.run(exercise())


def test_rotation_after_missing_summary_is_visible_and_marks_stale(tmp_path, monkeypatch):
    item = "inbox"
    fresh = str(uuid.uuid4())

    async def create():
        return fresh

    use_sessions(monkeypatch, create)
    router = router_at(tmp_path)
    sid = str(uuid.uuid4())
    router._sessions.connection(item)
    router._sessions.set(item, sid)
    router._topics.begin(item, {}, sid)
    router._topics.finish(item, "older state")
    for _ in range(chat.TOPIC_SESSION_TURNS - 1):
        router._topics.finish(item, None)
    calls = capture_turns(monkeypatch)

    async def turn():
        return [e async for e in router.run_turn(item, {}, "continue")]

    asyncio.run(turn())
    assert calls[0][0] == fresh
    assert "Possibly outdated or incomplete: older state" in calls[0][1]
    record = router_at(tmp_path)._topics.get(item)
    assert record["turns"] == 1 and record["refreshed_at"]
    assert not record.get("boundaries") and not record["summary_current"]


def test_chat_menu_edit_cancel_failure_reload_and_expand():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(chat.__file__).parent / "static/assistant.html").read_text()
    functions = []
    for name in ("openContextDialog", "contextRequest", "syncConversation", "renderHistory", "renderMessages"):
        functions.append(re.search(rf"(?:async )?function {name}\(.*?\n\}}", html, re.S)[0])
    js = r"""
const assert=require('node:assert/strict');
class Element{
  constructor(tag){this.tag=tag; this.children=[]; this.dataset={}; this.open=false;}
  appendChild(el){this.children.push(el);}
  replaceChildren(...els){this.children=els;}
  querySelector(){return null;}
  insertAdjacentHTML(_,html){this.children.push(html);}
  focus(){}
  showModal(){this.open=true;}
  close(){this.open=false;}
}
const ids={}, document={createElement:tag=>new Element(tag),
  getElementById:id=>ids[id]??=new Element(id)};
const activeId='doc:notes/a.md', activeChats=new Set(), pendingApprovals={};
let boardRequest=1, appliedBoardRequest=1;
const message=text=>({role:'user',text});
const old=[message('first segment')], next=message('second segment');
const chatHistories={[activeId]:old}, chatContexts={}, log=new Element('div');
const convos={[activeId]:{seeded:true,log,historyCount:1}};
const scrollLog=()=>{}, stamp=()=>'', attachmentsHtml=()=>'', esc=s=>s;
const clearQueuedNotes=()=>{};
let calls=[], failure='', revision='r1';
const boundaries=[{end:1,at:'2026-11-19T12:00:00Z'}];
const fetch=async(url,options)=>{
  assert.equal(url,'/api/chats/context');
  const body=JSON.parse(options.body); calls.push(body);
  assert.equal(body.item_id,activeId);
  const preview=body.mode==='preview';
  return {ok:preview||!failure,json:async()=>preview?{revision,handoff:'Draft'}
    :failure?{error:failure}:{boundaries,history:old}};
};
(async()=>{
  const get=name=>document.getElementById('context-'+name);
  const dialog=get('dialog'), accept=get('accept'), field=get('handoff');
  await openContextDialog(activeId,'summary');
  assert.equal(field.value,'Draft');
  field.value='Discard me'; get('cancel').onclick();
  assert.equal(dialog.open,false);
  assert.deepEqual(calls.map(c=>c.mode),['preview']);
  assert.deepEqual(chatContexts,{});
  await openContextDialog(activeId,'summary');
  field.value='Only this edited decision';
  for(failure of ['Conversation changed','Could not save']){
    await accept.onclick();
    assert.equal(get('error').textContent,failure);
    assert.equal(dialog.open,true);
    assert.equal(field.value,'Only this edited decision');
    assert.equal(calls.at(-1).revision,'r1');
    assert.equal(log.children.length,0);
  }
  get('cancel').onclick(); revision='r2'; failure='';
  await openContextDialog(activeId,'summary');
  field.value='Reviewed edit'; await accept.onclick();
  assert.equal(calls.at(-1).revision,'r2'); assert.equal(calls.at(-1).handoff,'Reviewed edit');
  assert.equal(dialog.open,false);
  const details=log.children[0];
  assert.equal(details.tag,'details'); assert.equal(details.open,false);
  assert.equal(details.children[0].tag,'summary');
  assert.match(details.children[0].textContent,/Previous conversation.*2026/);
  details.open=true;
  assert.match(details.children[1],/first segment/);
  chatHistories[activeId]=[...old,next];
  chatContexts[activeId].refreshed_at='2026-11-19T15:00Z';
  syncConversation(activeId);
  assert.equal(get('refreshed').hidden,false);
  assert.equal(details.open,true); assert.match(log.children[1],/second segment/);
  const reloaded=new Element('div'); renderHistory(reloaded,activeId);
  assert.equal(reloaded.children[0].open,false); assert.match(reloaded.children[1],/second segment/);
  await openContextDialog(activeId,'fresh'); assert.equal(field.hidden,true);
  await accept.onclick(); assert.equal(calls.at(-1).handoff,'');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run([node, "-e", "\n".join(functions) + js], check=True)


def test_archive_restore_preserves_segments_and_stable_subject(tmp_path, monkeypatch):
    item = "chat:123456789abc"
    router = router_at(tmp_path)
    monkeypatch.setattr(app, "chat_router", router)
    monkeypatch.setattr(app, "CHAT_HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(app, "ARCHIVED_CHATS_FILE", tmp_path / "archive.json")
    router._persistent_history.append(item, "user", "Original chat subject")
    preview = context(router, item)
    context(router, item, "fresh", preview["revision"])
    snapshot = context(router, item)
    archived = asyncio.run(app.api_chats_archive({"item_id": item, "title": "Original chat subject"}))
    assert json.loads(archived.body)["archived"]
    closed = json.loads(asyncio.run(app.api_chats_archived()).body)
    assert closed[0]["id"] == item
    assert closed[0]["title"] == "Original chat subject"
    restored = asyncio.run(app.api_chats_restore({"item_id": item}))
    assert json.loads(restored.body)["restored"]
    assert context(router_at(tmp_path), item) == snapshot
