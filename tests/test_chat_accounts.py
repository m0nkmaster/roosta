import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from roosta import ai_backend, ai_connections, app, chat


OLD_SESSION = "11111111-1111-4111-8111-111111111111"
NEW_SESSION = "22222222-2222-4222-8222-222222222222"
MISSING_ACCOUNT = "d" * 32


@pytest.fixture
def chat_accounts(tmp_path, monkeypatch):
    default = {"id": "a" * 32, "provider": "openai", "connected": True, "label": "Work"}
    data = {"default": default["id"], "connections": [default]}
    monkeypatch.setattr(ai_connections, "load", lambda: data)
    monkeypatch.setattr(ai_connections, "CONNECTIONS_DIR", tmp_path)
    monkeypatch.setattr(ai_connections, "default_model", lambda *args, **kwargs: "work-model")
    new = AsyncMock(return_value=NEW_SESSION)
    run = Mock()
    run.parse.return_value = {"kind": "text", "text": "All set."}
    prepare = Mock(return_value=run)
    prompts = []

    async def stream(run, prompt):
        prompts.append(prompt)
        yield "reply"

    monkeypatch.setattr(ai_backend, "new_session", new)
    monkeypatch.setattr(ai_backend, "prepare", prepare)
    monkeypatch.setattr(ai_backend, "stream", stream)
    return data, new, prepare, prompts


def test_old_chat_model_change_binds_the_default_account(tmp_path, monkeypatch, chat_accounts):
    """A chat saved before named accounts takes a model without an error and moves to the default."""
    data = chat_accounts[0]
    item = "chat:123456789abc"
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps({item: OLD_SESSION}))
    history = chat.ConversationHistoryStore(tmp_path / "history.json")
    history.append(item, "user", "Focus on the November launch")
    monkeypatch.setattr(app, "chat_router", chat.ChatRouter(chat.SessionMap(path), str(tmp_path),
                                                           persistent_history=history))
    validate = AsyncMock()
    monkeypatch.setattr(app, "validate_model", validate)
    response = asyncio.run(app.api_ai_chat_model({"item_id": item, "model": "fast-model"}))
    assert response.status_code == 200
    validate.assert_awaited_once_with("openai", "fast-model", data["default"], "")
    restored = chat.SessionMap(path)
    assert restored.selected(item) == data["default"] and restored.model(item) == "fast-model"


@pytest.mark.parametrize("binding", [None, OLD_SESSION, "legacy:cursor", "", "default", MISSING_ACCOUNT])
def test_turn_recovers_missing_account_and_retains_context(tmp_path, monkeypatch, chat_accounts, binding):
    data, new, prepare, prompts = chat_accounts
    item = "chat:123456789abc"
    path = tmp_path / "sessions.json"
    record = {"session_id": OLD_SESSION, "connection": binding, "model": "old-model"}
    if binding == OLD_SESSION:
        record = OLD_SESSION
    path.write_text(json.dumps({item: record} if binding is not None else {}))
    topics = chat.TopicStore(tmp_path / "topics.json")
    topics.begin(item, {"title": "Launch"}, OLD_SESSION)
    topics.finish(item, "Retained launch plan" if binding else None)
    history = chat.ConversationHistoryStore(tmp_path / "history.json")
    history.append(item, "user", "Focus on the November launch")
    original = history.read(item)
    router = chat.ChatRouter(chat.SessionMap(path), str(tmp_path), topic_store=topics, persistent_history=history)
    monkeypatch.setattr(app, "chat_router", router)
    monkeypatch.setattr(app, "setup_item", lambda _: None)
    before = path.read_bytes()
    router.reset_context(item, "preview", None, "")
    router._sessions.selected(item)
    response = asyncio.run(app.api_ai_chat_model({"item_id": item, "model": "unused"}))
    assert response.status_code == 400
    assert path.read_bytes() == before
    account = data["default"]

    async def send():
        response = await app.api_board_chat({"item_id": item, "message": "Continue"})
        events = [json.loads(line.removeprefix("data: ")) async for line in response.body_iterator]
        assert "reply_end" in [event["kind"] for event in events]

    asyncio.run(send())
    new.assert_awaited_once_with(account, str(tmp_path))
    prepare.assert_called_once_with(account, str(tmp_path), session_id=NEW_SESSION, model="work-model")
    assert ("Retained launch plan" if binding else "Focus on the November launch") in prompts[0]
    assert history.read(item)[:1] == original
    restored = chat.SessionMap(path)
    assert restored.selected(item) == account and restored.get(item) == NEW_SESSION
    assert restored.model(item) == ""
    assert topics.get(item)["session_id"] == NEW_SESSION

    data["default"] = ""
    monkeypatch.setattr(app, "chat_router", chat.ChatRouter(restored, str(tmp_path), topic_store=topics,
                                                           persistent_history=history))
    asyncio.run(send())
    new.assert_awaited_once()
    assert prepare.call_args.args[0] == account
    assert prepare.call_args.kwargs["session_id"] == NEW_SESSION


@pytest.mark.parametrize("condition,reason", [
    ("no default", "Settings"), ("deleted default", "Settings"), ("disconnected default", "Settings"),
    ("disconnected pin", "reconnect"), ("pending approval", "approval"), ("sender in flight", "approval"),
])
def test_unavailable_recovery_preserves_state(tmp_path, chat_accounts, condition, reason):
    data, new, prepare, prompts = chat_accounts
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps({"item": {"session_id": OLD_SESSION, "connection": MISSING_ACCOUNT, "model": "old"}}))
    topics = chat.TopicStore(tmp_path / "topics.json")
    topics.begin("item", {"title": "Launch"}, OLD_SESSION)
    history = chat.ConversationHistoryStore(tmp_path / "history.json")
    history.append("item", "user", "Original")
    router = chat.ChatRouter(chat.SessionMap(path), str(tmp_path), topic_store=topics, persistent_history=history)
    if condition == "no default":
        data["default"] = ""
    elif condition == "deleted default":
        data["default"] = "f" * 32
    elif condition == "disconnected default":
        data["connections"][0]["connected"] = False
    elif condition == "disconnected pin":
        data["connections"].append({**data["connections"][0], "id": MISSING_ACCOUNT, "connected": False})
    elif condition == "pending approval":
        router._paused["draft"] = {"connection": MISSING_ACCOUNT, "item_id": "item"}
    else:
        router._sending[object()] = "item"
    paths = (path, topics._path, history._path)
    original = [p.read_bytes() for p in paths]

    async def turn():
        return [e async for e in router.run_turn("item", {}, "Continue")]

    error, = asyncio.run(turn())
    assert error["kind"] == "error" and reason in error["payload"]["reason"]
    assert [p.read_bytes() for p in paths] == original
    new.assert_not_called()
    prepare.assert_not_called()
    assert not prompts


def test_auth_failure_on_existing_pin_never_dispatches_to_default(tmp_path, chat_accounts):
    data, new, prepare, prompts = chat_accounts
    pin = {**data["connections"][0], "id": "b" * 32}
    data["connections"].append(pin)
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps({"item": {"connection": pin["id"], "session_id": OLD_SESSION, "model": "pinned"}}))
    before = path.read_bytes()
    router = chat.ChatRouter(chat.SessionMap(path), str(tmp_path))
    prepare.side_effect = ValueError("Sign in again in Settings.")

    async def turn():
        return [e async for e in router.run_turn("item", {}, "Continue")]

    error, = asyncio.run(turn())
    assert error["payload"]["reason"] == "Sign in again in Settings."
    prepare.assert_called_once_with(pin["id"], str(tmp_path), session_id=OLD_SESSION, model="pinned")
    new.assert_not_called()
    assert not prompts and path.read_bytes() == before
