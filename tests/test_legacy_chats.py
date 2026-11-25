import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from roosta import ai_backend, ai_connections, app, chat


@pytest.mark.parametrize("binding", [
    "11111111-1111-4111-8111-111111111111",
    {"connection": "legacy:cursor", "session_id": "11111111-1111-4111-8111-111111111111"},
    "ses_invalid",
])
def test_legacy_turn_waits_for_explicit_named_account(tmp_path, monkeypatch, binding):
    item = "chat:123456789abc"
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps({item: binding}))
    sessions = chat.SessionMap(path)
    topics = chat.TopicStore(tmp_path / "topics.json")
    topics.begin(item, {"title": "Chat"}, "previous")
    topics.finish(item, "Retained summary")
    history = chat.ConversationHistoryStore(tmp_path / "history.json")
    history.append(item, "user", "Plan the launch")
    router = chat.ChatRouter(sessions, str(tmp_path), topic_store=topics, persistent_history=history)
    monkeypatch.setattr(app, "chat_router", router)
    original = [p.read_bytes() for p in (path, topics._path, history._path)]
    assert app.legacy_chat_choices() == [{"id": item, "title": "Plan the launch"}]

    account = {"id": "a" * 32, "provider": "openai", "connected": True, "label": "Work"}
    monkeypatch.setattr(ai_connections, "load", lambda: {"default": "", "connections": [account]})
    monkeypatch.setattr(ai_connections, "CONNECTIONS_DIR", tmp_path)
    monkeypatch.setattr(ai_connections, "selected_model", lambda provider: "chosen")
    new = AsyncMock(return_value="22222222-2222-4222-8222-222222222222")
    run = Mock()
    run.parse.return_value = None
    prepare = Mock(return_value=run)
    prompts = []

    async def stream(run, prompt):
        prompts.append(prompt)
        yield "reply"

    monkeypatch.setattr(ai_backend, "new_session", new)
    monkeypatch.setattr(ai_backend, "prepare", prepare)
    monkeypatch.setattr(ai_backend, "stream", stream)

    async def turn():
        return [event async for event in router.run_turn(item, {"title": "Launch"}, "Continue")]

    blocked, = asyncio.run(turn())
    assert blocked["kind"] == "error" and "Settings" in blocked["payload"]["reason"]
    new.assert_not_called()
    prepare.assert_not_called()
    assert not prompts

    def bind(key, chat_id=item):
        return asyncio.run(app.api_ai_chat_connection({"item_id": chat_id, "connection": key})).status_code

    for malformed in ("", None, {}, "default", "bogus"):
        assert bind(malformed) == 400
    for malformed in (" ", {}, "x" * 201, "\0"):
        assert bind(account["id"], malformed) == 400
    account["connected"] = False
    assert bind(account["id"]) == 400
    account["connected"] = True
    router._active_runs[item] = object()
    assert bind(account["id"]) == 409
    router._active_runs.clear()
    router._paused["approval"] = {"item_id": item}
    assert bind(account["id"]) == 409
    router._paused.clear()
    assert [p.read_bytes() for p in (path, topics._path, history._path)] == original

    assert bind(account["id"]) == 200
    assert not app.legacy_chat_choices()
    assert sessions.get(item) is None
    assert [p.read_bytes() for p in (topics._path, history._path)] == original[1:]
    monkeypatch.setattr(app, "setup_item", lambda _: {"id": app.AI_SETUP_ITEM_ID})

    async def board_turn():
        response = await app.api_board_chat({"item_id": item, "message": "Continue"})
        assert response.status_code == 200
        return [event async for event in response.body_iterator]

    assert asyncio.run(board_turn())
    new.assert_awaited_once_with(account["id"], str(tmp_path))
    prepare.assert_called_once_with(account["id"], str(tmp_path), session_id=new.return_value, model="chosen")
    assert len(prompts) == 1 and "Retained summary" in prompts[0]
    assert chat.SessionMap(path).get(item) == new.return_value
