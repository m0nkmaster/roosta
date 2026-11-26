import asyncio, json, os, re, shutil, subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from roosta import scheduler
from roosta import workspace
from roosta import chat_items
from roosta import board
from roosta import task_config
from roosta import cursor_agent as camod
from roosta.activity_log import ActivityLog


@pytest.fixture(autouse=True)
def ai_connected(request, monkeypatch):
    """Board tests assume a working AI connection; the setup-card test exercises the real check."""
    if request.node.name != "test_setup_card_survives_setup_writing_the_name":
        monkeypatch.setattr(board, "setup_item", lambda *_: None)
        monkeypatch.setattr(appmod, "setup_item", lambda *_: None)


def test_cursor_result_text_prefers_completed_stream_over_stale_result():
    final = '<task-output>{"summary":"blocked","status":"error","details":{}}</task-output>'
    stdout = "\n".join([
        json.dumps({"type": "result", "result": "Still checking the dashboard tree"}),
        json.dumps({
            "type": "assistant",
            "timestamp_ms": 1,
            "message": {"content": [{"type": "text", "text": final}]},
        }),
    ])

    assert camod.cursor_result_text(stdout) == final


def test_write_config_scrubs_leaked_login_state(tmp_path):
    directory = tmp_path / "cursor-config"
    directory.mkdir()
    (directory / "cli-config.json").write_text(json.dumps({
        "authInfo": {"email": "sam@example.com", "userId": 1}, "refreshToken": "secret", "kept": 1}))
    permissions = {"allow": ["Read(**)"], "deny": ["Shell(git:push*)"]}
    camod.write_config(directory, permissions, {"mcpServers": {"x": {}}})
    written = json.loads((directory / "cli-config.json").read_text())
    assert "authInfo" not in written and "refreshToken" not in written
    assert written["permissions"] == permissions and written["kept"] == 1
    assert json.loads((directory / "mcp.json").read_text()) == {"mcpServers": {"x": {}}}


def test_cursor_permission_profile_allows_local_writes_but_denies_external_actions():
    permissions = json.loads(camod.SAFE_CONFIG_TEMPLATE.read_text())["permissions"]
    assert "Write(**)" in permissions["allow"]
    assert "Read(**/.env*)" in permissions["deny"]
    assert "Shell(gh:pr create*)" in permissions["deny"]
    assert "Shell(git:push*)" in permissions["deny"]
    assert "Mcp(*:*create*)" in permissions["deny"]
    assert not {"Shell(rm)", "Shell(git:reset*)", "Shell(git:clean*)"} & set(permissions["deny"])


def test_connector_write_commands_join_every_policy(tmp_path, monkeypatch):
    """A chat drafting a send could otherwise run the CLI directly and skip the approval card."""
    from roosta import claude_code, paths

    connectors_file = tmp_path / "connectors.yaml"
    connectors_file.write_text(
        "connectors:\n  - id: teams\n    deny:\n      - msteams teams_send_message\n      - [chat, post]\n")
    monkeypatch.setattr(paths, "CONNECTORS_FILE", connectors_file)
    merged = camod.merged_permissions({"deny": ["Shell(rm)"]})
    assert merged["deny"] == ["Shell(rm)", "Shell(chat:post*)", "Shell(msteams:teams_send_message*)"]

    settings = json.loads(claude_code.claude_settings("safe", tmp_path / "claude").read_text())
    assert "Bash(msteams teams_send_message:*)" in settings["permissions"]["deny"]


def test_cursor_args_use_headless_streaming_and_resume():
    args = camod.cursor_args(binary="/x/agent", workspace="/vault", session_id="chat-id", model="gpt-6")
    assert args[0] == "/x/agent"
    assert "--print" in args and "--trust" in args and "--force" in args
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert "--stream-partial-output" in args
    assert args[args.index("--workspace") + 1] == "/vault"
    assert args[args.index("--resume") + 1] == "chat-id"
    assert args[args.index("--model") + 1] == "gpt-6"
    fresh = camod.cursor_args(workspace="/vault")
    assert "--resume" not in fresh and "--model" not in fresh


def test_cursor_create_chat_drops_the_custom_config_dir(tmp_path, monkeypatch):
    captured = {}
    session_id = "33333333-3333-4333-8333-333333333333"

    class Process:
        returncode = 0

        async def communicate(self, input=None):
            return session_id.encode(), b""

    async def fake_exec(*args, **kwargs):
        captured["args"], captured["kwargs"] = args, kwargs
        return Process()

    monkeypatch.setattr(camod.asyncio, "create_subprocess_exec", fake_exec)
    env = {"CURSOR_API_KEY": "key", "CURSOR_CONFIG_DIR": "/private"}
    assert asyncio.run(camod.create_chat("/x/agent", env, str(tmp_path))) == session_id
    assert captured["args"] == ("/x/agent", "create-chat")
    assert captured["kwargs"]["stdin"] == asyncio.subprocess.DEVNULL
    assert captured["kwargs"]["env"] == {"CURSOR_API_KEY": "key"}


from roosta import chat as cmod


def _texts(rows):
    """History rows without their `at` timestamps, for content comparisons."""
    return [{k: v for k, v in row.items() if k != "at"} for row in rows]


def test_parse_line_text_delta():
    ev = camod.parse_chat_line(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hello "}]},'
        '"timestamp_ms":1}'
    )
    assert ev == {"kind": "text", "text": "hello "}


def test_parse_line_ignores_step_and_junk():
    assert camod.parse_chat_line(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"duplicate"}]}}'
    ) is None
    assert camod.parse_chat_line(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"flush"}]},'
        '"timestamp_ms":1,"model_call_id":"call"}'
    ) is None
    assert camod.parse_chat_line('not json') is None


def test_extract_markers_pause():
    txt = 'Here is the draft.\n<<<PAUSE>>>{"kind":"message","summary":"ask Priya","draft":"Hi Priya","target":"Priya"}'
    prose, marker = cmod.extract_marker(txt)
    assert prose.strip() == "Here is the draft."
    assert marker == {"control": "pause", "kind": "message",
                      "summary": "ask Priya", "draft": "Hi Priya", "target": "Priya"}


def test_extract_markers_tolerates_accidental_closing_delimiter():
    txt = 'Here is the draft.\n<<<PAUSE>>>{"kind":"message","draft":"Hi","target":"Priya"}>>>'
    prose, marker = cmod.extract_marker(txt)
    assert prose.strip() == "Here is the draft."
    assert marker == {
        "control": "pause", "kind": "message", "draft": "Hi", "target": "Priya",
    }


def test_extract_markers_done():
    prose, marker = cmod.extract_marker('All set.\n<<<DONE>>>{"result":"Booked the review"}')
    assert prose.strip() == "All set."
    assert marker == {"control": "done", "result": "Booked the review"}


def test_extract_markers_none():
    prose, marker = cmod.extract_marker("just a chat reply")
    assert prose == "just a chat reply" and marker is None


def test_extract_state_marker_carries_compact_topic_summary():
    prose, marker = cmod.extract_marker(
        'Direct answer.\n<<<STATE>>>{"thread_summary":"Magic Mirror awaits leadership alignment."}'
    )
    assert prose.strip() == "Direct answer."
    assert marker == {
        "control": "state",
        "thread_summary": "Magic Mirror awaits leadership alignment.",
    }


def test_normalise_learned_caps_and_validates():
    assert cmod.normalise_learned(None) is None
    assert cmod.normalise_learned({"learned": "nope"}) is None
    out = cmod.normalise_learned({
        "learned": [
            {"path": "projects/foo/README.md", "fact": "Platform uses Kanban, not sprints."},
            {"path": "", "fact": "skip"},
            "bad",
        ]
    })
    assert out == [{"path": "projects/foo/README.md", "fact": "Platform uses Kanban, not sprints."}]


def test_terminal_event_surfaces_learned_on_state_and_done():
    state = cmod.terminal_event({
        "control": "state",
        "thread_summary": "Still open.",
        "learned": [{"path": "CONTEXT.md", "fact": "The platform team owns the UI."}],
    })
    assert state == {
        "kind": "reply_end",
        "payload": {"learned": [{"path": "CONTEXT.md", "fact": "The platform team owns the UI."}]},
    }
    done = cmod.terminal_event({
        "control": "done",
        "result": "Updated note",
        "acted": True,
        "learned": [{"path": "notes/x.md", "fact": "One line."}],
    })
    assert done["kind"] == "done"
    assert done["payload"]["acted"] is True
    assert done["payload"]["learned"] == [{"path": "notes/x.md", "fact": "One line."}]


import json as _json


def test_session_map_roundtrip(tmp_path):
    p = tmp_path / "sessions.json"
    m = cmod.SessionMap(p)
    assert m.get("item-a") is None
    session_id = "11111111-1111-4111-8111-111111111111"
    m.set("item-a", session_id)
    assert m.get("item-a") == session_id
    assert _json.loads(p.read_text())["item-a"] == session_id
    assert cmod.SessionMap(p).get("item-a") == session_id


def test_session_map_tolerates_corrupt(tmp_path):
    p = tmp_path / "sessions.json"
    p.write_text("garbage{")
    m = cmod.SessionMap(p)
    assert m.get("x") is None
    m.set("x", "22222222-2222-4222-8222-222222222222")
    assert m.get("x") == "22222222-2222-4222-8222-222222222222"


def test_session_map_drops_legacy_opencode_ids(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text('{"old-item":"ses_legacy"}')
    assert cmod.SessionMap(path).get("old-item") is None


def test_conversation_history_persists_until_cleared(tmp_path):
    path = tmp_path / "chat-history.json"
    history = cmod.ConversationHistoryStore(path)
    history.append("item-a", "user", "What matters today?")
    history.append("item-a", "assistant", "The launch decision.")
    history.append("chat:0123456789ab", "user", "Keep this separate.")

    reloaded = cmod.ConversationHistoryStore(path)
    assert all(datetime.fromisoformat(row["at"]) for row in reloaded.read("item-a"))
    assert _texts(reloaded.read("item-a")) == [
        {"role": "user", "text": "What matters today?"},
        {"role": "assistant", "text": "The launch decision."},
    ]
    assert _texts(reloaded.read("chat:0123456789ab")) == [
        {"role": "user", "text": "Keep this separate."},
    ]

    history.clear("item-a")
    assert history.read("item-a") == []
    assert history.read("chat:0123456789ab")


def test_conversation_history_hides_control_markers_from_old_replies(tmp_path):
    path = tmp_path / "chat-history.json"
    path.write_text(json.dumps({
        "item-a": [{
            "role": "assistant",
            "text": 'Draft ready.\n<<<PAUSE>>>{"kind":"message","draft":"Hi","target":"A"}>>>',
        }],
    }))

    assert cmod.ConversationHistoryStore(path).read("item-a") == [
        {"role": "assistant", "text": "Draft ready."},
    ]


def test_topic_store_tracks_item_continuity_and_rotates_bounded_sessions(tmp_path):
    store = cmod.TopicStore(tmp_path / "topics.json", max_session_turns=2)
    item = {"title": "Magic Mirror alignment", "situation": "Awaiting Diego",
            "opening_move": "Prepare the leadership discussion",
            "project_ref": "projects/magic-mirror"}
    store.begin("alignment-episode", item, "ses_1")
    store.finish("alignment-episode", "Awaiting Diego; prepare leadership alignment.")
    store.finish("alignment-episode", "Diego replied; leadership alignment is next.")

    record = store.get("alignment-episode")
    assert record["item_id"] == "alignment-episode"
    assert record["project_ref"] == "projects/magic-mirror"
    assert record["turns"] == 2
    assert store.should_rotate("alignment-episode") is True

    store.rotated("alignment-episode", "ses_2")
    assert store.get("alignment-episode")["turns"] == 0
    assert store.get("alignment-episode")["session_id"] == "ses_2"


def test_different_items_from_same_project_use_separate_sessions(tmp_path, fake_chat_connection):

    sessions = cmod.SessionMap(tmp_path / "sessions.json")
    topics = cmod.TopicStore(tmp_path / "topics.json")
    router = cmod.ChatRouter(sessions, "/v", topic_store=topics)
    first = asyncio.run(router._ensure_session(
        "magic-mirror-alignment",
        {"title": "Alignment", "thread_id": "project:magic-mirror",
         "project_ref": "projects/magic-mirror"}))
    second = asyncio.run(router._ensure_session(
        "magic-mirror-launch",
        {"title": "Launch", "thread_id": "project:magic-mirror",
         "project_ref": "projects/magic-mirror"}))

    assert first == "ses_1"
    assert second == "ses_2"
    assert sessions.get("magic-mirror-alignment") == "ses_1"
    assert sessions.get("magic-mirror-launch") == "ses_2"
    assert topics.get("magic-mirror-alignment")["item_id"] == "magic-mirror-alignment"
    assert topics.get("magic-mirror-launch")["item_id"] == "magic-mirror-launch"


def test_item_session_reuses_existing_item_session(tmp_path, fake_chat_connection):

    sessions = cmod.SessionMap(tmp_path / "sessions.json")
    sessions.bind("old-episode", "c" * 32)
    sessions.set("old-episode", "ses_existing")
    router = cmod.ChatRouter(sessions, "/v")

    sid = asyncio.run(router._ensure_session(
        "old-episode", {"title": "AI adoption"}))

    assert sid == "ses_existing"
    assert sessions.get("old-episode") == "ses_existing"


def test_terminal_event_from_marker_pause():
    assert cmod.terminal_event({"control": "pause", "kind": "message",
                                "summary": "s", "draft": "d", "target": "t"}) == {
        "kind": "pause",
        "payload": {"kind": "message", "summary": "s", "draft": "d", "target": "t"},
    }


def test_terminal_event_from_marker_done():
    # plain answer DONE: acted defaults False (does not resolve the item)
    assert cmod.terminal_event({"control": "done", "result": "did it"}) == {
        "kind": "done", "payload": {"result": "did it", "acted": False}}


def test_terminal_event_done_acted_true():
    assert cmod.terminal_event({"control": "done", "result": "wrote note", "acted": True}) == {
        "kind": "done", "payload": {"result": "wrote note", "acted": True}}


def test_terminal_event_none_is_reply_end():
    assert cmod.terminal_event(None) == {"kind": "reply_end"}


def test_terminal_event_state_is_hidden_reply_end():
    assert cmod.terminal_event(
        {"control": "state", "thread_summary": "Strategic topic state."}
    ) == {"kind": "reply_end"}


def test_terminal_event_defer_accepts_bounded_future_time():
    now = datetime(2026, 7, 27, 16, tzinfo=timezone.utc)
    assert cmod.terminal_event({
        "control": "defer",
        "until": "2026-07-30T09:00:00+01:00",
        "reason": "Wait for Diego",
    }, now) == {
        "kind": "defer",
        "payload": {
            "until": "2026-07-30T08:00:00+00:00",
            "reason": "Wait for Diego",
        },
    }


@pytest.mark.parametrize("until", [
    "whenever",
    "2026-07-26T09:00:00+00:00",
    "2028-07-30T09:00:00+00:00",
    "2026-07-30T09:00:00",
])
def test_terminal_event_defer_rejects_unsafe_time(until):
    now = datetime(2026, 7, 27, 16, tzinfo=timezone.utc)
    event = cmod.terminal_event({"control": "defer", "until": until}, now)
    assert event == {"kind": "error", "payload": {"reason": "invalid reminder time"}}


def test_terminal_event_remind_now_when_due_absent_or_null():
    now = datetime(2026, 7, 28, 16, tzinfo=timezone.utc)
    for due in (None, "", "now"):
        marker = {"control": "remind", "title": "Chase the launch sign-off", "body": "b"}
        if due is not None:
            marker["due"] = due
        assert cmod.terminal_event(marker, now) == {
            "kind": "remind",
            "payload": {"title": "Chase the launch sign-off", "body": "b", "due": None},
        }


def test_terminal_event_remind_accepts_bounded_future_due():
    now = datetime(2026, 7, 28, 15, tzinfo=timezone.utc)
    assert cmod.terminal_event({
        "control": "remind", "title": "Stand-up prep", "due": "2026-07-28T17:00:00+01:00",
    }, now) == {
        "kind": "remind",
        "payload": {"title": "Stand-up prep", "body": "", "due": "2026-07-28T16:00:00+00:00"},
    }


def test_reminder_and_notify_bodies_keep_urls_whole_and_cut_prose_on_words():
    sheet = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit#gid=0"
    body = ("Robin shared the capacity plan " * 18) + sheet + " and the other link https://example.com/b"
    assert 0 < body.index(sheet) < cmod.BODY_LIMIT < body.index(sheet) + len(sheet)
    clipped = cmod.clip_body(body)
    assert sheet in clipped and clipped.endswith(sheet + "…")
    prose = cmod.clip_body("word " * 200)
    assert prose.endswith("word…") and len(prose) <= cmod.BODY_LIMIT + 1
    assert cmod.clip_body("short " + sheet) == "short " + sheet
    remind = cmod.terminal_event({"control": "remind", "title": "t", "body": body})
    assert remind["payload"]["body"] == clipped
    assert board.reminder_to_item({"id": "remind-1", "title": "t", "body": body})["why"] == clipped


def test_terminal_event_remind_requires_title():
    assert cmod.terminal_event({"control": "remind", "title": "   "}) == {
        "kind": "error", "payload": {"reason": "reminder needs a title"}}


@pytest.mark.parametrize("due", ["whenever", "2026-07-27T09:00:00+00:00", "2026-07-28T17:00:00"])
def test_terminal_event_remind_rejects_unsafe_due(due):
    now = datetime(2026, 7, 28, 16, tzinfo=timezone.utc)
    assert cmod.terminal_event({"control": "remind", "title": "X", "due": due}, now) == {
        "kind": "error", "payload": {"reason": "invalid reminder time"}}


def test_chatrouter_reminders_roundtrip_and_removal(tmp_path):
    path = tmp_path / "reminders.json"
    cr = cmod.ChatRouter(session_map=cmod.SessionMap(tmp_path / "s.json"),
                         vault="/v", reminders_path=path)
    assert cr.reminders() == []
    rid = cr.add_reminder("Call the vendor", "before 5", "2026-07-28T16:00:00+00:00")
    assert rid.startswith("remind-")
    stored = cmod.ChatRouter(cmod.SessionMap(tmp_path / "s2.json"), "/v",
                             reminders_path=path).reminders()
    assert stored[0]["title"] == "Call the vendor"
    assert stored[0]["due"] == "2026-07-28T16:00:00+00:00"
    cr.remove_reminder(rid)
    assert cr.reminders() == []


def test_chatrouter_mark_handled_clears_matching_reminder(tmp_path):
    reminders = tmp_path / "reminders.json"
    cr = cmod.ChatRouter(session_map=cmod.SessionMap(tmp_path / "s.json"),
                         vault="/v", handled_path=tmp_path / "handled.json",
                         reminders_path=reminders)
    rid = cr.add_reminder("Draft the update")
    cr.mark_handled(rid, "Done")
    assert cr.reminders() == []


def test_run_turn_remind_marker_persists_card_and_ends_reply(monkeypatch, tmp_path, fake_chat_connection):

    class FakeProcess:
        returncode = 0

        def __init__(self):
            async def lines():
                for subtype in ("started", "completed"):
                    yield json.dumps({"type": "tool_call", "subtype": subtype,
                        "tool_call": {"readToolCall": {"args": {"path": "private path"}}}}).encode()
                yield b'{"type":"thinking","text":"private reasoning"}'
                event = {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text":
                        'Added a reminder.\n<<<REMIND>>>{"title":"Chase sign-off","due":null}'}]},
                    "timestamp_ms": 1,
                }
                yield (json.dumps(event) + "\n").encode()
            self.stdout = lines()

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(cmod.asyncio, "create_subprocess_exec", fake_exec)
    router = cmod.ChatRouter(
        cmod.SessionMap(tmp_path / "sessions.json"), "/vault",
        reminders_path=tmp_path / "reminders.json",
    )

    async def run():
        return [event async for event in router.run_turn(
            "item-1", {"id": "item-1"}, "Remind me to chase sign-off")]

    events = asyncio.run(run())
    assert events[-1]["kind"] == "reply_end"
    assert [e["label"] for e in events if e["kind"] == "progress"] == ["Tool started · read", "Tool finished · read"]
    assert "private" not in json.dumps(events)
    reminders = router.reminders()
    assert len(reminders) == 1 and reminders[0]["title"] == "Chase sign-off"


def test_split_due_reminders_partitions_now_and_future():
    now = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
    reminders = [
        {"id": "remind-now", "title": "Now", "due": None},
        {"id": "remind-past", "title": "Past", "due": "2026-07-28T11:00:00+00:00"},
        {"id": "remind-future", "title": "Future", "due": "2026-07-28T17:00:00+00:00"},
        {"id": "remind-broken", "title": "Broken", "due": "not-a-date"},
        {"id": "", "title": "No id", "due": None},
        {"id": "remind-notitle", "title": "", "due": None},
    ]
    due, later = board.split_due_reminders(reminders, now)
    assert {i["id"] for i in due} == {"remind-now", "remind-past", "remind-broken"}
    assert all(i["new"] is True for i in due)
    assert [i["id"] for i in later] == ["remind-future"]
    assert later[0]["snoozed_until"] == "2026-07-28T17:00:00+00:00"
    assert later[0]["new"] is False


def test_board_surfaces_due_reminders_and_parks_future(monkeypatch, fake_chat_connection):
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def handled(self):
            return {}

        def snoozed(self):
            return {}

        def reminders(self):
            return [
                {"id": "remind-due", "title": "Due now", "due": None},
                {"id": "remind-later", "title": "Later",
                 "due": "2099-01-01T09:00:00+00:00"},
            ]

        def conversation_histories(self):
            return {}

        def conversation_history(self, item_id):
            return []

        active_progress = {}

        def active_items(self):
            return []

        def pending_approvals(self):
            return {}

        def record_raised(self, item_ids):
            return {}

    monkeypatch.setattr(appmod, "chat_router", FakeRouter())
    monkeypatch.setattr(appmod.runner, "get_state", lambda _task_id: {
        "last_output": {"details": {"items": []}}})
    monkeypatch.setattr(appmod.runner, "get_states", lambda: [])

    monkeypatch.setattr(board, "setup_item", lambda router: {"id": board.SETUP_ITEM_ID, "title": "Setup"})
    body = json.loads(asyncio.run(appmod.api_board()).body)
    count = json.loads(asyncio.run(appmod.api_board_count()).body)
    pulse = json.loads(asyncio.run(appmod.api_pulse()).body)["board"]
    assert count["items"] == pulse["board_active"] == 2
    assert count["later"] == pulse["board_later"] == 1
    assert [i["id"] for i in body["document"]["items"]] == ["remind-due", board.SETUP_ITEM_ID]
    assert [i["id"] for i in body["document"]["later"]] == ["remind-later"]


def test_notify_with_due_persists_reminder(monkeypatch):
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def __init__(self):
            self.added = None

        def add_reminder(self, title, body="", due=None):
            self.added = (title, body, due)
            return "remind-abc"

    router = FakeRouter()
    monkeypatch.setattr(appmod, "chat_router", router)
    due = (datetime.now(timezone.utc) + timedelta(days=10)).replace(microsecond=0).isoformat()
    ok = asyncio.run(appmod.api_notify(
        {"title": "Ping the team", "body": "at 5", "due": due}))
    assert ok.status_code == 200
    assert json.loads(ok.body)["id"] == "remind-abc"
    assert router.added == ("Ping the team", "at 5", due)
    bad = asyncio.run(appmod.api_notify({"title": "X", "due": "not-a-date"}))
    assert bad.status_code == 400


def test_sender_prompt_carries_action():
    p = cmod.sender_prompt({"kind": "message", "text": "Hi", "target": "Priya"})
    assert "sender" in p and "Hi" in p and "Priya" in p


def test_normalise_sender_action_matches_sender_contract():
    assert cmod.normalise_sender_action(
        {"kind": "message", "draft": "Hi", "target": "Priya"}
    ) == {"kind": "message", "text": "Hi", "target": "Priya"}
    assert cmod.normalise_sender_action(
        {"kind": "action", "summary": "Create PROJ ticket",
         "instruction": "jira --agent issue create --project PROJ ..."}
    ) == {"kind": "action", "summary": "Create PROJ ticket",
          "instruction": "jira --agent issue create --project PROJ ..."}


def test_teams_drafts_send_bare_urls_as_markdown_links():
    text = ("Ticket: https://example.atlassian.net/browse/IECDP-14488\n"
            "Thread: https://teams.cloud.microsoft/l/message/19%3Aabc/1792?x=1.\n"
            "Docs: https://example.com/a and [kept](https://example.com/b)")
    out = cmod.normalise_sender_action(
        {"kind": "message", "draft": text, "target": "SQUAD - Engagement and Impact"})
    assert out["text"] == (
        "Ticket: [IECDP-14488](https://example.atlassian.net/browse/IECDP-14488)\n"
        "Thread: [Teams thread](https://teams.cloud.microsoft/l/message/19%3Aabc/1792?x=1).\n"
        "Docs: [https://example.com/a](https://example.com/a) and [kept](https://example.com/b)")
    email = cmod.normalise_sender_action(
        {"kind": "message", "draft": text, "target": "priya@example.com"})
    assert email["text"] == text


def test_jira_comment_cards_convert_wiki_markup_to_markdown():
    # Jira Cloud accepts Markdown in --body.
    wiki = ('jira --agent comment add PROJ-10589 --body "*Proposed approach:* a data change.\n'
            '# *Confirm the codes* e.g. {{id}} vs {{id-ID}}\n'
            '# Add a migration like [V171|https://github.example.com/V171]\nh2. Notes\n'
            '* a bullet and **already bold**"')
    event = cmod.terminal_event({"control": "pause", "kind": "action",
                                 "summary": "Comment", "instruction": wiki})
    assert event["payload"]["instruction"] == (
        'jira --agent comment add PROJ-10589 --body "**Proposed approach:** a data change.\n'
        '1. **Confirm the codes** e.g. \\`id\\` vs \\`id-ID\\`\n'
        '1. Add a migration like [V171](https://github.example.com/V171)\n## Notes\n'
        '* a bullet and **already bold**"')
    single = cmod.jira_wiki_to_markdown("jira comment add X-1 --body '{{id}}'")
    assert single == "jira comment add X-1 --body '`id`'"
    for untouched in ("jira comment add X-1 --body-format storage --body '{{id}} *b*'",
                      "gh issue create --body '{{id}} *b*'",
                      "jira issue search --jql 'text ~ \"*x*\"'"):
        assert cmod.jira_wiki_to_markdown(untouched) == untouched


@pytest.mark.parametrize("action", [
    {},
    {"kind": "unknown", "draft": "x", "target": "y"},
    {"kind": "message", "draft": "", "target": "Priya"},
    {"kind": "message", "draft": "Hi", "target": ""},
    {"kind": "action", "summary": "", "instruction": "do it"},
    {"kind": "action", "summary": "Do it", "instruction": ""},
])
def test_normalise_sender_action_rejects_invalid_payloads(action):
    assert cmod.normalise_sender_action(action) is None


@pytest.mark.parametrize("body", [{}, {"approved": "false"}, {"approved": 1}, {"approved": None}])
def test_invalid_approval_keeps_the_draft(monkeypatch, tmp_path, body):
    router = cmod.ChatRouter(cmod.SessionMap(tmp_path / "sessions.json"), str(tmp_path))
    router._paused["draft"] = {"item_id": "item", "action": {}}
    monkeypatch.setattr(appmod, "chat_router", router)
    response = asyncio.run(appmod.api_board_approve("draft", body))
    assert response.status_code == 400
    assert "draft" in router._paused
    assert json.loads(asyncio.run(appmod.api_board_approve("draft", {"approved": False})).body)["sent"] is False


@pytest.mark.parametrize("operation", ["append", "clear"])
def test_history_mutations_preserve_unreadable_file(tmp_path, operation):
    path = tmp_path / "history.json"
    path.write_text('{"prior":')
    store = cmod.ConversationHistoryStore(path)
    with pytest.raises(ValueError):
        if operation == "append":
            store.append("new", "user", "hello")
        else:
            store.clear("prior")
    assert path.read_text() == '{"prior":'


def test_history_failure_before_replace_preserves_prior_messages(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    store = cmod.ConversationHistoryStore(path)
    store.append("chat", "user", "first")
    original = path.read_bytes()

    def disk_full(src, dest):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", disk_full)
    with pytest.raises(OSError, match="disk full"):
        store.append("chat", "user", "second")
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_approve_sends_normalised_edited_action(monkeypatch, tmp_path, fake_chat_connection):
    captured = {}


    class FakeProcess:
        returncode = 0

        async def communicate(self, input=None):
            line = {"type": "result", "result": '<task-output>{"status": "success", "summary": ""}</task-output>'}
            return json.dumps(line).encode(), b""

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(cmod.asyncio, "create_subprocess_exec", fake_exec)
    router = cmod.ChatRouter(
        cmod.SessionMap(tmp_path / "sessions.json"), "/vault"
    )
    router._paused["run-1"] = {
        "item_id": "item-1",
        "action": {
            "kind": "message",
            "summary": "Ask Priya",
            "draft": "Original",
            "target": "Priya",
        },
    }

    result = asyncio.run(router.approve("run-1", True, "Edited"))

    assert result == {"ok": True, "sent": True, "kind": "message", "summary": ""}
    prompt = captured["args"][-1]
    assert '"text": "Edited"' in prompt
    assert '"draft"' not in prompt
    assert "--force" in captured["args"]
    assert fake_chat_connection[-1]["profile"] == "unrestricted"


def test_approved_general_chat_action_does_not_close_chat(monkeypatch, tmp_path, fake_chat_connection):

    class FakeProcess:
        returncode = 0

        async def communicate(self, input=None):
            line = {"type": "result", "result": '<task-output>{"status": "success", "summary": ""}</task-output>'}
            return json.dumps(line).encode(), b""

    async def fake_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(cmod.asyncio, "create_subprocess_exec", fake_exec)
    router = cmod.ChatRouter(
        cmod.SessionMap(tmp_path / "sessions.json"),
        "/vault",
        handled_path=tmp_path / "handled.json",
    )
    router._paused["run-general"] = {
        "item_id": "chat:0123456789ab",
        "persistent": True,
        "action": {
            "kind": "message",
            "summary": "Sent update",
            "draft": "Update",
            "target": "Priya",
        },
    }

    result = asyncio.run(router.approve("run-general", True, None))

    assert result == {"ok": True, "sent": True, "kind": "message", "summary": ""}
    assert router.handled() == {}


def _approve_with_sender_output(monkeypatch, tmp_path, output):

    class FakeProcess:
        returncode = 0

        async def communicate(self, input=None):
            line = {"type": "result", "result": f"<task-output>{json.dumps(output)}</task-output>"}
            return json.dumps(line).encode(), b""

    async def fake_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(cmod.asyncio, "create_subprocess_exec", fake_exec)
    router = cmod.ChatRouter(
        cmod.SessionMap(tmp_path / "sessions.json"), "/vault",
        handled_path=tmp_path / "handled.json",
    )
    router._paused["run-ticket"] = {
        "item_id": "chat:0123456789ab",
        "persistent": True,
        "action": {"kind": "action", "summary": "Raise CodeIQ ticket",
                   "instruction": "jira --agent issue create --project PROJ --summary CodeIQ"},
    }
    return asyncio.run(router.approve("run-ticket", True, None))


def test_approved_ticket_create_returns_the_senders_summary(monkeypatch, tmp_path, fake_chat_connection):
    summary = "Created [PROJ-9999](https://example.atlassian.net/browse/PROJ-9999)"
    result = _approve_with_sender_output(
        monkeypatch, tmp_path, {"summary": summary, "status": "success", "details": ""})
    assert result == {"ok": True, "sent": True, "kind": "action", "summary": summary}


def test_sender_reported_error_is_not_sent(monkeypatch, tmp_path, fake_chat_connection):
    result = _approve_with_sender_output(
        monkeypatch, tmp_path, {"summary": "Team UUID unknown", "status": "error", "details": ""})
    assert result["ok"] is True
    assert result["sent"] is False
    assert result["summary"] == "Team UUID unknown"


def test_approval_card_shows_a_readable_preview_with_raw_details_collapsed():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "class=\"card card-body approval-preview\">${md(p.preview||p.draft||'')}" in html
    assert "class=\"approval-raw\"><summary>Show details</summary>" in html
    assert "note.innerHTML=md(out.summary)" in html
    assert "if(verb) return [verb,'Working…','Done ✓',verb+' failed'];" in html
    assert "kind==='message' ? ['Send','Sending…','Sent ✓','Send failed']" in html


def test_pause_marker_carries_a_short_button_verb():
    def pause(verb):
        _, marker = cmod.extract_marker('<<<PAUSE>>>' + json.dumps(
            {"kind": "message", "verb": verb, "summary": "s", "draft": "d", "target": "t"}))
        return cmod.terminal_event(marker)
    good = pause("Reply")
    assert good["payload"]["verb"] == "Reply"
    bad = pause("<b>x</b>")
    assert "verb" not in bad["payload"]


def test_pause_marker_carries_action_preview_and_instruction():
    _, marker = cmod.extract_marker('<<<PAUSE>>>' + json.dumps({
        "kind": "action", "verb": "Create", "summary": "Raise ticket",
        "preview": "**Summary:** CodeIQ tuning", "instruction": "jira --agent issue create ...",
        "target": "PROJ",
    }))
    event = cmod.terminal_event(marker)
    assert event["payload"]["preview"] == "**Summary:** CodeIQ tuning"
    assert event["payload"]["instruction"] == "jira --agent issue create ..."


def test_chat_prompt_requires_direct_reply_before_skill_loading():
    prompt = cmod.CHAT_PROMPT.format(
        item="{}", message="What changed?", now="2026-07-27T16:00:00+00:00",
        summary="Awaiting leadership alignment.", user="Sam", style="Write in British English.")
    direct = prompt.index("direct answer to Sam")
    silent = prompt.index("Never mention skills")
    load = prompt.index("load the 'actor' skill")
    assert direct < load and silent < load
    assert "1-3 short sentences" in prompt
    assert "80 words" in prompt
    assert "AGENTS.md" in prompt
    assert "relative path a Markdown link" in prompt
    assert "direct source links in the first reply" in prompt
    assert "never present memory as evidence" in prompt
    assert "TOOLS.md" in prompt
    assert "Write in British English." in prompt
    assert "What changed?" in prompt
    assert "Awaiting leadership alignment." in prompt


def test_visible_reply_filter_removes_chunked_process_preamble():
    visible = cmod.VisibleReplyFilter()
    assert visible.feed("I'll load the actor ") == ""
    assert visible.feed("skill to handle this properly. ") == ""
    assert visible.feed("Robin owns it.") == "Robin owns it."
    assert visible.feed(" The review is due Friday.") == " The review is due Friday."
    assert visible.finish() == ""


@pytest.mark.parametrize("preamble", [
    "Capturing the Thursday start date, then drafting the squad message and calendar update. ",
    "Fixing the shared header in `shell.css` so it stays pinned across all dashboard pages. ",
    "Loading the actor skill and checking your Jamie chat for context. ",
    "Capturing the correction and finishing the triage assessment. ",
    "Investigating the blank AI Activity section on the skill runner page. ",
    "Updating the project README to record PROJ-9925. ",
    "I'll draft the consolidated one-pager from those four sources and save it to the vault. ",
    "Checking how the gardener is scheduled and whether its mandate needs sharpening. ",
    "Recording that this isn't Sam's action and updating the project note. ",
    "Gathering context on the flags and Sam's requirements. ",
    "Verifying the 626/Stitch situation and stand-up brief before answering. ",
    "Adding Gina's archived-outcomes cluster to the stand-up brief. ",
    "Implementing a runner pre-commit so the engineer no longer stops on a dirty tree. ",
    "Restoring overwritten capture history and appending the new entry. ",
    "All auth preflight checks pass. Reading the live doc to re-verify the target week before pasting.\n\n",
    "Preparing a draft for Jamie. ",
    "Saving this to the note. ",
    "Writing up the steps now. ",
    "Output truncated before summary/description; fetch just those.\n\n",
    "Writing the note now.  ",
    "Drafting Matt's reply now. ",
    "Sonnet would handle this well — worth switching from Opus for tasks like this.\n\n",
])
def test_visible_reply_filter_removes_process_narration_observed_in_live_chats(preamble):
    visible = cmod.VisibleReplyFilter()
    assert visible.feed(preamble) == ""
    assert visible.feed("The change is ready.") == "The change is ready."
    assert visible.finish() == ""


def test_visible_reply_filter_removes_consecutive_process_updates():
    visible = cmod.VisibleReplyFilter()
    assert visible.feed(
        "Implementing a runner pre-commit so the engineer no longer stops on a dirty tree.\n"
    ) == ""
    assert visible.feed(
        "Fixing git command handling - the helper does not expose exit codes.\n"
    ) == ""
    assert visible.feed("Fixed. Restart the Assistant once.") == (
        "Fixed. Restart the Assistant once."
    )


def test_visible_reply_filter_keeps_answers_that_merely_start_like_narration():
    visible = cmod.VisibleReplyFilter()
    answer = "Reading between the lines, Phil wants the date moved."
    assert visible.feed(answer) == answer


def test_visible_reply_filter_keeps_answers_that_end_in_now():
    for answer in ("Nothing is blocking it now.", "Everything is working now.",
                   "Shipping the beta docs depends on the PR approval, so it waits until next week now."):
        visible = cmod.VisibleReplyFilter()
        assert visible.feed(answer) + visible.finish() == answer


def test_visible_reply_filter_keeps_model_advice_the_user_requested():
    answer = "Sonnet would handle this well, so use it for the quick lookups."
    visible = cmod.VisibleReplyFilter()
    assert visible.feed(answer) + visible.finish() == answer


def test_visible_reply_filter_preserves_direct_short_answer():
    visible = cmod.VisibleReplyFilter()
    assert visible.feed("Robin owns it.") == "Robin owns it."
    assert visible.finish() == ""


def test_persistent_chat_is_not_marked_handled_after_acting(monkeypatch, tmp_path, fake_chat_connection):
    captured = {}


    class FakeProcess:
        returncode = 0

        def __init__(self):
            async def lines():
                event = {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text":
                        'Updated.\n<<<DONE>>>{"result":"Updated the note","acted":true}'}]},
                    "timestamp_ms": 1,
                }
                yield (json.dumps(event) + "\n").encode()
            self.stdout = lines()

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        return FakeProcess()

    monkeypatch.setattr(cmod.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(cmod.ai_connections, "default_model",
                        lambda _provider, general=False: "claude-opus-5-thinking-high" if general else "")
    history = cmod.ConversationHistoryStore(tmp_path / "general-history.json")
    router = cmod.ChatRouter(
        cmod.SessionMap(tmp_path / "sessions.json"),
        "/vault",
        handled_path=tmp_path / "handled.json",
        persistent_history=history,
    )

    async def run():
        return [event async for event in router.run_turn(
            "chat:0123456789ab", {"id": "chat:0123456789ab", "persistent": True}, "Update it")]

    events = asyncio.run(run())
    assert events[-1]["kind"] == "done"
    assert events[-1]["payload"]["acted"] is True
    model_index = captured["args"].index("--model")
    assert captured["args"][model_index + 1] == "claude-opus-5-thinking-high"
    assert router.handled() == {}
    assert _texts(history.read("chat:0123456789ab")) == [
        {"role": "user", "text": "Update it"},
        {"role": "assistant", "text": "Updated."},
    ]


def test_item_chat_persists_visible_history(monkeypatch, tmp_path, fake_chat_connection):
    captured = {}


    class FakeProcess:
        returncode = 0

        def __init__(self):
            async def lines():
                event = {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text":
                        'It is waiting on review.\n<<<STATE>>>{"thread_summary":"Waiting on review."}'}]},
                    "timestamp_ms": 1,
                }
                yield (json.dumps(event) + "\n").encode()
            self.stdout = lines()

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(cmod.asyncio, "create_subprocess_exec", fake_exec)
    history = cmod.ConversationHistoryStore(tmp_path / "chat-history.json")
    router = cmod.ChatRouter(
        cmod.SessionMap(tmp_path / "sessions.json"),
        "/vault",
        persistent_history=history,
    )

    async def run():
        return [event async for event in router.run_turn(
            "item-1", {"id": "item-1"}, "What is the status?")]

    asyncio.run(run())

    assert _texts(history.read("item-1")) == [
        {"role": "user", "text": "What is the status?"},
        {"role": "assistant", "text": "It is waiting on review."},
    ]
    assert "--force" in captured["args"]
    assert fake_chat_connection[-1]["profile"] == "safe"


def test_progress_isolated_across_chats_and_queued_turns_after_stop(tmp_path):
    router = cmod.ChatRouter(cmod.SessionMap(tmp_path / "sessions.json"), "/vault")

    async def exercise():
        release = asyncio.Event()

        async def run(item_id, item, message, run_id):
            yield {"kind": "progress", "label": message}
            await release.wait()
            if item_id == "b":
                raise RuntimeError("private diagnostic")
            yield {"kind": "reply_end"}

        router.run_turn = run
        a = router.start_turn("a", {}, "first").events
        b = router.start_turn("b", {}, "other").events
        assert router.start_turn("a", {}, "next").queued
        await asyncio.sleep(0)
        first, other = (router.active_progress[key].copy() for key in ("a", "b"))
        assert first["label"] == "first" and other["label"] == "other"
        router._active_runs["a"].cancel()
        while (event := await a.get())["kind"] != "error":
            assert event["run_id"] == first["run_id"]
        assert event["payload"]["reason"] == "Reply stopped."
        assert (await a.get())["kind"] == "_close"
        await asyncio.sleep(0)
        assert router.active_progress["a"]["label"] == "next"
        assert router.active_progress["a"]["run_id"] != first["run_id"]
        assert router.active_progress["b"] == other
        release.set()
        while router.active_items():
            await asyncio.sleep(0)
        assert router.active_progress == {}
        events = [b.get_nowait() for _ in range(b.qsize())]
        assert [e["kind"] for e in events] == ["progress", "progress", "error", "_close"]
        assert all(e["item_id"] == "b" and e["run_id"] == other["run_id"] for e in events)
        assert "private diagnostic" not in json.dumps(events)

    asyncio.run(exercise())


def test_detached_turn_continues_without_stream_consumer(tmp_path):
    router = cmod.ChatRouter(
        session_map=cmod.SessionMap(tmp_path / "sessions.json"),
        vault="/vault",
    )

    async def exercise():
        release = asyncio.Event()

        async def fake_run(item_id, item, message, run_id):
            await release.wait()
            yield {"kind": "text", "text": "Finished"}

        router.run_turn = fake_run
        handle = router.start_turn("item-1", {"id": "item-1"}, "Continue")
        assert handle.events is not None
        assert not handle.queued
        events = handle.events
        assert router.active_items() == ["item-1"]
        queued = router.start_turn("item-1", {"id": "item-1"}, "Duplicate")
        assert queued.queued is True
        assert queued.position == 1

        release.set()
        while router.active_items():
            await asyncio.sleep(0)

        drained = []
        while not events.empty():
            drained.append(events.get_nowait())
        return drained

    drained = asyncio.run(exercise())
    assert [event["kind"] for event in drained] == ["progress", "text", "_close"]
    assert {event["item_id"] for event in drained} == {"item-1"}
    assert len({event["run_id"] for event in drained}) == 1
    assert drained[1]["text"] == "Finished"


def test_queued_messages_run_after_current_turn(tmp_path):
    router = cmod.ChatRouter(
        session_map=cmod.SessionMap(tmp_path / "sessions.json"),
        vault="/vault",
    )
    seen = []

    async def fake_run(item_id, item, message, run_id):
        seen.append((message, item.get('context_documents')))
        yield {"kind": "text", "text": message.upper()}

    router.run_turn = fake_run

    async def exercise():
        first = router.start_turn("item-1", {"id": "item-1"}, "one")
        assert not first.queued
        second = router.start_turn("item-1", {"id": "item-1", "context_documents": ["second"]}, "two")
        assert second.queued and second.position == 1
        third = router.start_turn("item-1", {"id": "item-1", "context_documents": ["third"]}, "three")
        assert third.queued and third.position == 2
        while router.active_items():
            await asyncio.sleep(0)
        return seen

    assert asyncio.run(exercise()) == [("one", None), ("two", ["second"]), ("three", ["third"])]


from roosta import app as appmod


def test_normalise_board_doc_full():
    raw = {"items": [
        {"id": "ds-session", "thread_id": "jira:PROJ-1",
         "project_ref": "projects/final-mile-results-data",
         "title": "T", "why": "deadline tomorrow",
         "situation": "S", "opening_move": "I'll confirm the review",
         "action_type": "teams_message", "action_owner": "user",
         "action_label": "  Draft   response  ", "new": True}],
        "done_today": [{"text": "Booked it", "at": "2026-06-30T10:00:00Z"}]}
    doc = board.normalise_board_doc(raw)
    assert doc["items"][0]["id"] == "ds-session"
    assert "thread_id" not in doc["items"][0]
    assert doc["items"][0]["project_ref"] == "projects/final-mile-results-data"
    assert doc["items"][0]["action_type"] == "chat"
    assert doc["items"][0]["action_owner"] == "user"
    assert doc["items"][0]["action_label"] == "Draft response"
    assert doc["items"][0]["new"] is True
    assert doc["done_today"][0]["text"] == "Booked it"


def test_normalise_board_doc_defaults_and_garbage():
    doc = board.normalise_board_doc("nonsense")
    assert doc["items"] == [] and doc["done_today"] == []
    doc2 = board.normalise_board_doc({"items": ["bad", {"id": "x"}]})
    assert len(doc2["items"]) == 1
    assert doc2["items"][0]["title"] == "" and doc2["items"][0]["new"] is False
    assert "thread_id" not in doc2["items"][0]
    assert doc2["items"][0]["project_ref"] is None
    assert doc2["items"][0]["action_type"] == "task"
    assert doc2["items"][0]["action_owner"] == "assistant"
    assert doc2["items"][0]["action_label"] == "Take next step"
    assert doc2["items"][0]["links"] == []
    assert doc2["items"][0]["documents"] == []


@pytest.mark.parametrize(("opening_move", "expected"), [
    ("I'll raise this at stand-up tomorrow.", "standup"),
    ("I'll draft the proposal for you.", "document"),
    ("I'll email Jamie with the update.", "email"),
    ("I'll review the current status.", "review"),
])
def test_normalise_board_doc_infers_action_type_for_existing_items(opening_move, expected):
    doc = board.normalise_board_doc({
        "items": [{"id": "old-cache-item", "opening_move": opening_move}]
    })
    assert doc["items"][0]["action_type"] == expected


def test_normalise_board_doc_rejects_unknown_action_type():
    doc = board.normalise_board_doc({
        "items": [{"id": "x", "action_type": "javascript", "opening_move": "Do the thing"}]
    })
    assert doc["items"][0]["action_type"] == "task"


@pytest.mark.parametrize(("raw", "expected"), [
    ("projects/magic-mirror", "projects/magic-mirror"),
    (" projects/team-okrs ", "projects/team-okrs"),
    ("projects/Magic-Mirror", None),
    ("projects/magic-mirror/notes", None),
    ("../projects/magic-mirror", None),
    ("https://example.com/project", None),
])
def test_normalise_project_ref_allows_only_canonical_project_directory(raw, expected):
    assert board._normalise_project_ref(raw) == expected


def test_normalise_board_doc_falls_back_to_specific_action_label():
    doc = board.normalise_board_doc({
        "items": [{"id": "x", "action_type": "standup",
                   "action_owner": "unknown", "action_label": ""}]
    })
    item = doc["items"][0]
    assert item["action_owner"] == "assistant"
    assert item["action_label"] == "Prepare talking point"


def test_normalise_links_keeps_only_http_and_caps():
    links = board._normalise_links([
        {"label": "Open thread", "url": "https://teams.microsoft.com/x"},
        {"label": "Bad", "url": "javascript:alert(1)"},   # unsafe scheme -> dropped
        {"label": "", "url": "http://plain.example/y"},    # blank label -> "Open"
        {"url": "https://a"}, {"url": "https://b"}, {"url": "https://c"},  # push past cap of 4
        "not-a-dict",
    ])
    assert links[0] == {"label": "Open thread", "url": "https://teams.microsoft.com/x"}
    assert links[1] == {"label": "Open", "url": "http://plain.example/y"}
    assert all(l["url"].startswith("http") for l in links)
    assert len(links) == 4


def test_normalise_links_repairs_group_chat_permalink():
    broken = (
        "https://teams.microsoft.com/l/message/"
        "19%3A43cb015486b14dc7ab6a800cbaeecf57%40thread.v2/1789738665402"
        "?tenantId=56b731a8-a2ac-4c32-bf6b-616810e913c6"
        "&parentMessageId=1789738665402&createdTime=1789738665402"
    )
    assert board._normalise_links([{"label": "Open thread", "url": broken}]) == [{
        "label": "Open thread",
        "url": (
            "https://teams.microsoft.com/l/message/"
            "19%3A43cb015486b14dc7ab6a800cbaeecf57%40thread.v2/1789738665402"
            "?tenantId=56b731a8-a2ac-4c32-bf6b-616810e913c6"
            "&context=%7B%22contextType%22%3A%22chat%22%7D"
        ),
    }]


def test_normalise_links_leaves_channel_permalink_unchanged():
    channel = (
        "https://teams.microsoft.com/l/message/"
        "19%3Aabc%40thread.tacv2/1789738665402"
        "?tenantId=tenant&groupId=group&parentMessageId=1789738665402"
    )
    assert board._normalise_links([{"label": "Open thread", "url": channel}])[0]["url"] == channel


def test_normalise_board_doc_carries_links():
    doc = board.normalise_board_doc({"items": [
        {"id": "i", "links": [{"label": "PROJ-1", "url": "https://jira/PROJ-1"},
                              {"label": "x", "url": "ftp://nope"}]}]})
    assert doc["items"][0]["links"] == [{"label": "PROJ-1", "url": "https://jira/PROJ-1"}]


def test_normalise_documents_allows_only_relative_vault_markdown():
    documents = board._normalise_documents([
        {"label": "Open draft", "path": "drafts/2026-07-28-team-rolling-comms.md"},
        {"label": "Escape", "path": "../outside.md"},
        {"label": "Absolute", "path": "/tmp/outside.md"},
        {"label": "Not Markdown", "path": "drafts/data.json"},
        {"label": "Roosta internals", "path": ".roosta/tasks.md"},
        {"label": "Case variant", "path": ".Roosta/EVOLUTION.md"},
    ])
    assert documents == [{
        "label": "Open draft",
        "path": "drafts/2026-07-28-team-rolling-comms.md",
    }]


def test_resolve_vault_markdown_rejects_escape_and_reads_existing_doc(tmp_path):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    document = drafts / "weekly.md"
    document.write_text("# Weekly\n")

    assert workspace.resolve_vault_markdown("drafts/weekly.md", tmp_path) == document
    with pytest.raises(ValueError):
        workspace.resolve_vault_markdown("../outside.md", tmp_path)
    with pytest.raises(FileNotFoundError):
        workspace.resolve_vault_markdown("drafts/missing.md", tmp_path)


def test_resolve_vault_text_opens_roosta_config_but_not_state_or_dotfiles(tmp_path):
    config = tmp_path / ".roosta"
    (config / "state" / "cache").mkdir(parents=True)
    (config / "connectors.yaml").write_text("connectors: []\n")
    (config / "operating-model.md").write_text("# Model\n")
    (config / "state" / "cache" / "secret.json").write_text("{}")
    (config / "tasks.json").symlink_to(config / "state" / "cache" / "secret.json")
    (tmp_path / ".env.json").write_text("{}")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config.yaml").write_text("x")

    assert workspace.resolve_vault_text(".roosta/connectors.yaml", tmp_path) == (config / "connectors.yaml").resolve()
    assert workspace.resolve_vault_text(".roosta/operating-model.md", tmp_path).name == "operating-model.md"
    for bad in (".roosta/state/cache/secret.json", ".roosta/STATE/cache/secret.json",
                ".roosta/tasks.json", ".env.json", ".git/config.yaml",
                ".roosta/../.env.json", ".roosta/.hidden.yaml"):
        with pytest.raises(ValueError):
            workspace.resolve_vault_text(bad, tmp_path)


def test_vault_document_endpoint_returns_markdown(monkeypatch, tmp_path):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "weekly.md").write_text("# Weekly update\n\n* Ready")
    monkeypatch.setattr(appmod.paths, "WORKSPACE", tmp_path)

    response = asyncio.run(appmod.api_vault_document("drafts/weekly.md"))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body == {
        "path": "drafts/weekly.md",
        "title": "Weekly update",
        "content": "# Weekly update\n\n* Ready",
        "properties": [],
    }
    rejected = asyncio.run(appmod.api_vault_document("../outside.md"))
    assert rejected.status_code == 400


def test_vault_document_endpoint_shows_linked_text_files_as_source(monkeypatch, tmp_path):
    project = tmp_path / "projects" / "ai-office-hours"
    project.mkdir(parents=True)
    (project / "confluence-page.storage.html").write_text("<p>Fortnightly ```x```</p>\n")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    (tmp_path / ".roosta" / "state").mkdir(parents=True)
    (tmp_path / ".roosta" / "state" / "x.json").write_text("{}")
    (project / "run.sh").write_text("echo")
    monkeypatch.setattr(appmod.paths, "WORKSPACE", tmp_path)

    body = json.loads(asyncio.run(appmod.api_vault_document(
        "projects/ai-office-hours/confluence-page.storage.html")).body)

    assert body["title"] == "confluence-page.storage.html"
    assert body["content"] == "````html\n<p>Fortnightly ```x```</p>\n````"
    for path in (".claude/settings.json", ".roosta/state/x.json", "../outside.html",
                 "projects/ai-office-hours/run.sh"):
        assert asyncio.run(appmod.api_vault_document(path)).status_code == 400, path
    assert asyncio.run(appmod.api_vault_document("projects/missing.csv")).status_code == 404
    html = (Path(appmod.DASHBOARD_ROOT) / "static" / "assistant.html").read_text()
    assert r"\.(md|html|txt|json|ya?ml|csv)$/i.test(href)" in html


def test_vault_document_endpoint_splits_front_matter_into_properties(monkeypatch, tmp_path):
    project = tmp_path / "projects" / "okrs"
    project.mkdir(parents=True)
    (project / "README.md").write_text(
        "---\ntitle: Team OKRs\nstatus: active\ntags: [okr, planning]\nextra:\n  nested: x\n---\n\n# Heading\n\nBody"
    )
    monkeypatch.setattr(appmod.paths, "WORKSPACE", tmp_path)

    body = json.loads(asyncio.run(appmod.api_vault_document("projects/okrs/README.md")).body)

    assert body["title"] == "Team OKRs"
    assert body["content"] == "# Heading\n\nBody"
    assert body["properties"] == [["title", "Team OKRs"], ["status", "active"], ["tags", "okr, planning"]]
    assert appmod.split_front_matter("---\n: [bad\n---\nBody") == ("---\n: [bad\n---\nBody", [])


def test_board_feed_attaches_draft_document_to_matching_conductor_item():
    conductor = board.normalise_board_doc({"items": [{
        "id": "rolling-comms-2026-07-28",
        "title": "Review Platform rolling comms",
    }]})["items"]
    states = [{
        "id": "rolling-comms",
        "last_output": {"details": {
            "draft": "drafts/2026-07-28-team-rolling-comms.md",
            "items": ["Legacy edit description"],
        }},
    }]

    merged = board.merge_board_feed_items(conductor, states)

    assert merged[0]["documents"] == [{
        "label": "Open draft",
        "path": "drafts/2026-07-28-team-rolling-comms.md",
    }]


def test_board_feed_accepts_cards_from_any_skill():
    states = [
        {"id": "self-chat-commands", "last_run": "2026-11-03T09:00:00",
         "last_output": {"details": {"items": [
             {"id": "self-chat-123", "title": "Handle self-note", "new": True},
         ]}}},
        {"id": "team-wins-watch", "last_run": "2026-11-03T10:00:00",
         "last_output": {"details": {"items": [
             {"id": "celebrate-proj-1", "title": "Quinn shipped Favourites", "new": True},
         ]}}},
        {"id": "roosta-engineer", "last_output": {"details": {"built": []}}},
        {"id": "never-run", "last_output": {}},
    ]

    merged = board.merge_board_feed_items([], states)

    assert [item["id"] for item in merged] == ["self-chat-123", "celebrate-proj-1"]


def test_board_feed_newer_skill_refines_existing_card():
    conductor = board.normalise_board_doc({"items": [{
        "id": "teams-root1", "title": "Reply to Robin", "why": "Robin asked",
        "situation": "Old picture", "new": False,
        "links": [{"label": "Open thread", "url": "https://teams.example/root1"}],
    }]})["items"]
    states = [
        {"id": "assistant", "last_run": "2026-11-03T10:00:00"},
        {"id": "workspace-learner", "last_run": "2026-11-03T11:00:00",
         "last_output": {"details": {"items": [{
             "id": "teams-root1", "situation": "Robin now needs it by Friday", "new": True,
             "links": [{"label": "PROJ-1", "url": "https://example.atlassian.net/browse/PROJ-1"},
                       {"label": "Open thread", "url": "https://teams.example/root1"}],
         }]}}},
        {"id": "teams-actions-watch", "last_run": "2026-11-03T09:00:00",
         "last_output": {"details": {"items": [
             {"id": "teams-root1", "title": "Stale sensor title"},
         ]}}},
    ]

    merged = board.merge_board_feed_items(conductor, states)

    assert len(merged) == 1
    card = merged[0]
    assert card["title"] == "Reply to Robin"  # older run never overwrites newer
    assert card["why"] == "Robin asked"  # fields the update omits are kept
    assert card["situation"] == "Robin now needs it by Friday"
    assert [link["label"] for link in card["links"]] == ["Open thread", "PROJ-1"]
    assert card["new"] is True


def test_board_feed_drops_untitled_update_for_unknown_card():
    states = [{"id": "workspace-gardener", "last_output": {"details": {"items": [
        {"id": "gone-card", "situation": "More context"},
    ]}}}]

    assert board.merge_board_feed_items([], states) == []


def test_board_feed_folds_merged_duplicate_into_kept_card():
    conductor = board.normalise_board_doc({"items": [
        {"id": "teams-root1", "title": "Reply to Robin on 626 cutover"},
    ]})["items"]
    states = [{"id": "workspace-learner", "last_run": "2026-11-03T11:00:00",
               "last_output": {"details": {"items": [{
                   "id": "learner-626-cutover", "title": "626 cutover question",
                   "situation": "Robin needs a date by Friday",
                   "links": [{"label": "PROJ-1", "url": "https://example.atlassian.net/browse/PROJ-1"}],
               }]}}}]
    merged = {"learner-626-cutover": {"into": "teams-root1"}}

    cards = board.merge_board_feed_items(conductor, states, merged)

    assert [card["id"] for card in cards] == ["teams-root1"]
    assert cards[0]["situation"] == "Robin needs a date by Friday"
    assert cards[0]["links"][0]["label"] == "PROJ-1"


def test_folded_duplicate_never_rewrites_the_conductor_synthesis():
    conductor = board.normalise_board_doc({"items": [{
        "id": "team-wins-2026-11-04", "title": "Squad shipped data-accuracy and search fixes",
        "situation": "Quinn, James and Ari all landed work",
        "links": [{"label": "PROJ-10691", "url": "https://example.atlassian.net/browse/PROJ-10691"}],
    }]})["items"]
    states = [{"id": "team-wins-watch", "last_run": "2026-11-04T18:30:00",
               "last_output": {"details": {"items": [{
                   "id": "celebrate-proj-10631", "title": "Ari landed the trigram indexes",
                   "situation": "Ari resolved PROJ-10631", "opening_move": "Thank Ari",
                   "links": [{"label": "PROJ-10631", "url": "https://example.atlassian.net/browse/PROJ-10631"}],
               }]}}}]
    merged = {"celebrate-proj-10631": {"into": "team-wins-2026-11-04"}}

    card = board.merge_board_feed_items(conductor, states, merged)[0]

    assert card["title"] == "Squad shipped data-accuracy and search fixes"
    assert card["situation"] == "Quinn, James and Ari all landed work"
    assert card["opening_move"] == "Thank Ari"  # blank on the synthesis, so filled
    assert [link["label"] for link in card["links"]] == ["PROJ-10691", "PROJ-10631"]


def test_record_merges_keeps_the_card_with_user_history(tmp_path):
    history = cmod.ConversationHistoryStore(tmp_path / "h.json")
    history.append("teams-root1", "user", "What did Robin ask?")
    cr = cmod.ChatRouter(session_map=cmod.SessionMap(tmp_path / "s.json"),
                         vault="/v", persistent_history=history,
                         merged_path=tmp_path / "merged.json")

    data = cr.record_merges({"teams-root1": "learner-626", "a": "b", "b": "a", "x": "x"})

    assert data["learner-626"]["into"] == "teams-root1"
    assert "teams-root1" not in data
    assert data["a"]["into"] == "b"
    assert "b" not in data and "x" not in data  # loops and self-merges ignored
    assert cmod.resolve_alias("learner-626", cr.merged()) == "teams-root1"


def test_roosta_engineer_failure_becomes_an_actionable_board_item():
    item = board.roosta_engineer_item([{
        "id": "roosta-engineer",
        "status": "error",
        "last_run": "2026-09-08T07:00:00+00:00",
        "last_error": "Harness did not return the required task result",
        "last_output": {"summary": "Stopped before delivery", "details": {}},
    }])

    assert item["id"] == "roosta-engineer-failed-202609080700"
    assert item["action_owner"] == "assistant"
    assert "no app change shipped" in item["why"]
    assert item["links"][0]["url"].endswith("?task=roosta-engineer")


def test_roosta_engineer_delivery_becomes_a_review_board_item():
    item = board.roosta_engineer_item([{
        "id": "roosta-engineer",
        "status": "success",
        "last_run": "2026-09-08T07:00:00+00:00",
        "last_output": {
            "summary": "Shipped attention history",
            "details": {"built": [{
                "what": "attention history",
                "why": "Sam repeatedly reopened closed work",
                "commit": "abc1234",
            }]},
        },
    }])

    assert item["id"] == "dashboard-improvement-abc1234"
    assert item["title"] == "Assistant improved: attention history"
    assert item["action_owner"] == "user"
    assert item["new"] is True


def test_roosta_engineer_no_change_does_not_create_noise():
    assert board.roosta_engineer_item([{
        "id": "roosta-engineer",
        "status": "success",
        "last_run": "2026-09-08T07:00:00+00:00",
        "last_output": {"summary": "No change", "details": {"built": []}},
    }]) is None


def test_scheduled_prompt_forbids_external_writes():
    assert "Never create or modify external content or state" in scheduler.PROMPT_TEMPLATE
    assert "chat messages, tickets, wiki pages, email, GitHub, deployments or jobs" in scheduler.PROMPT_TEMPLATE
    assert "Assistant board items" in scheduler.PROMPT_TEMPLATE
    assert "'documents':" in scheduler.PROMPT_TEMPLATE
    assert "'path': 'drafts/example.md'" in scheduler.PROMPT_TEMPLATE


def test_snooze_deadlines_use_local_mornings_and_utc_storage():
    bst = timezone(timedelta(hours=1))
    now = datetime(2026, 7, 16, 15, 30, tzinfo=bst)  # Thursday
    assert board.snooze_deadline("one_hour", now) == "2026-07-16T15:30:00+00:00"
    assert board.snooze_deadline("tomorrow", now) == "2026-07-17T08:00:00+00:00"
    assert board.snooze_deadline("next_monday", now) == "2026-07-20T08:00:00+00:00"


def test_snooze_deadline_rejects_arbitrary_input():
    with pytest.raises(ValueError):
        board.snooze_deadline("2035-01-01")


def test_split_snoozed_items_parks_future_and_resurfaces_expired():
    now = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
    items = [{"id": "future", "title": "F"}, {"id": "expired", "title": "E"},
             {"id": "broken", "title": "B"}, {"id": "wrong-type", "title": "W"},
             {"id": "plain", "title": "P"}]
    snoozed = {
        "future": {"until": "2026-07-17T09:00:00+00:00"},
        "expired": {"until": "2026-07-16T11:59:00+00:00"},
        "broken": {"until": "not-a-date"},
        "wrong-type": {"until": 123},
    }
    active, later = board.split_snoozed_items(items, snoozed, now)
    assert [item["id"] for item in active] == ["expired", "broken", "wrong-type", "plain"]
    assert [item["id"] for item in later] == ["future"]
    assert later[0]["snoozed_until"] == "2026-07-17T09:00:00+00:00"


def test_snooze_endpoint_accepts_only_current_item_and_known_preset(monkeypatch):
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def __init__(self):
            self.saved = None

        def reminders(self):
            return []

        def handled(self):
            return {}

        def snoozed(self):
            return {}

        def snooze(self, item_id, until):
            self.saved = (item_id, until)

    router = FakeRouter()
    monkeypatch.setattr(appmod, "chat_router", router)
    monkeypatch.setattr(appmod.runner, "get_state", lambda _task_id: {
        "last_output": {"details": {"items": [{"id": "item-1"}]}}
    })
    monkeypatch.setattr(appmod.runner, "get_states", lambda: [])
    ok = asyncio.run(appmod.api_board_snooze(
        {"item_id": "item-1", "preset": "one_hour"}))
    assert ok.status_code == 200
    assert router.saved[0] == "item-1"
    rejected = asyncio.run(appmod.api_board_snooze(
        {"item_id": "item-1", "preset": "whenever"}))
    assert rejected.status_code == 400
    missing = asyncio.run(appmod.api_board_snooze(
        {"item_id": "item-2", "preset": "one_hour"}))
    assert missing.status_code == 404


def test_snooze_endpoint_accepts_visible_reminder(monkeypatch):
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def __init__(self):
            self.saved = None

        def reminders(self):
            return [{
                "id": "remind-1",
                "title": "Move stand-up",
                "body": "Pick a later time.",
                "due": None,
            }]

        def snoozed(self):
            return {}

        def handled(self):
            return {}

        def snooze(self, item_id, until):
            self.saved = (item_id, until)

    router = FakeRouter()
    monkeypatch.setattr(appmod, "chat_router", router)
    monkeypatch.setattr(appmod.runner, "get_state", lambda _task_id: {
        "last_output": {"details": {"items": []}}
    })
    monkeypatch.setattr(appmod.runner, "get_states", lambda: [])

    response = asyncio.run(appmod.api_board_snooze(
        {"item_id": "remind-1", "preset": "one_hour"}))

    assert response.status_code == 200
    assert router.saved[0] == "remind-1"


def test_chatrouter_mark_and_read_handled(tmp_path):
    p = tmp_path / "handled.json"
    raised = tmp_path / "raised.json"
    cr = cmod.ChatRouter(session_map=cmod.SessionMap(tmp_path / "s.json"),
                         vault="/v", handled_path=p, raised_path=raised)
    cr.record_raised(["item-1"])
    assert "item-1" in cr.raised()
    cr.mark_handled("item-1", "Booked the review")
    h = cr.handled()
    assert h["item-1"]["result"] == "Booked the review" and "at" in h["item-1"]
    assert "item-1" not in cr.raised()
    # persisted + reloadable by a fresh router
    cr2 = cmod.ChatRouter(session_map=cmod.SessionMap(tmp_path / "s.json"),
                          vault="/v", handled_path=p)
    assert cr2.handled()["item-1"]["result"] == "Booked the review"


def test_chatrouter_record_raised_preserves_first_seen(tmp_path):
    raised = tmp_path / "raised.json"
    cr = cmod.ChatRouter(session_map=cmod.SessionMap(tmp_path / "s.json"),
                         vault="/v", raised_path=raised)
    first = cr.record_raised(["item-1"])["item-1"]["at"]
    second = cr.record_raised(["item-1", "item-2"])
    assert second["item-1"]["at"] == first
    assert "item-2" in second


def test_attach_raised_at_stamps_items():
    items = [{"id": "a", "title": "A"}, {"id": "b", "title": "B", "raised_at": "keep"}]
    board.attach_raised_at(items, {"a": {"at": "2026-07-01T10:00:00+00:00"}})
    assert items[0]["raised_at"] == "2026-07-01T10:00:00+00:00"
    assert items[1]["raised_at"] == "keep"


def test_reminder_to_item_carries_created_as_raised_at():
    item = board.reminder_to_item({
        "id": "remind-1", "title": "T", "body": "B",
        "created": "2026-07-01T09:00:00+00:00",
    })
    assert item["raised_at"] == "2026-07-01T09:00:00+00:00"


def test_chatrouter_handled_tolerates_corrupt(tmp_path):
    p = tmp_path / "handled.json"
    p.write_text("garbage{")
    cr = cmod.ChatRouter(session_map=cmod.SessionMap(tmp_path / "s.json"),
                         vault="/v", handled_path=p)
    assert cr.handled() == {}


def test_chatrouter_handled_normalises_accidental_items_wrapper(tmp_path):
    p = tmp_path / "handled.json"
    p.write_text(json.dumps({
        "items": [
            {"id": "old-item", "state": "handled"},
            {"id": "with-result", "result": "Sent the reply", "at": "2026-08-14T12:00:00Z"},
            "junk",
        ],
    }))
    cr = cmod.ChatRouter(
        session_map=cmod.SessionMap(tmp_path / "s.json"),
        vault="/v",
        handled_path=p,
    )

    assert cr.handled() == {
        "old-item": {"result": "Handled", "at": ""},
        "with-result": {"result": "Sent the reply", "at": "2026-08-14T12:00:00Z"},
    }


def test_chatrouter_mark_handled_noop_without_path():
    cr = cmod.ChatRouter(session_map=None, vault="/v")
    cr.mark_handled("x", "y")  # must not raise
    assert cr.handled() == {}


def test_chatrouter_snooze_roundtrip_unsnooze_and_handled_cleanup(tmp_path):
    handled = tmp_path / "handled.json"
    snoozed = tmp_path / "snoozed.json"
    cr = cmod.ChatRouter(
        session_map=cmod.SessionMap(tmp_path / "sessions.json"),
        vault="/v",
        handled_path=handled,
        snoozed_path=snoozed,
    )
    cr.snooze("item-1", "2026-07-17T09:00:00+00:00")
    assert cmod.ChatRouter(
        cmod.SessionMap(tmp_path / "sessions-2.json"), "/v",
        handled, snoozed,
    ).snoozed()["item-1"]["until"] == "2026-07-17T09:00:00+00:00"
    cr.unsnooze("item-1")
    assert cr.snoozed() == {}
    cr.snooze("item-1", "2026-07-18T09:00:00+00:00")
    cr.mark_handled("item-1", "Done")
    assert cr.snoozed() == {}


def test_assistant_frontend_exposes_attention_scheduler():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert 'id="snooze"' in html
    assert 'data-preset="tomorrow"' in html
    assert "Bring back" in html
    assert "ev.kind==='defer'" in html
    assert "Revisit ${esc(laterLabel(p.until))}" in html


def test_assistant_frontend_renders_action_badges():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "actionBadge(it.action_type)" in html
    assert "label:'Chat'" in html
    assert "label:'Ticket'" in html
    assert "label:'Stand-up'" in html


def test_assistant_history_and_streams_render_sanitised_markdown():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "const allowedMarkdownTags=new Set" in html
    assert "?md(visibleReply(message.text))" in html
    assert "b.innerHTML=md(visibleReply(ai._raw))" in html
    assert "element.removeAttribute(attribute.name)" in html
    assert "['http:','https:'].includes(url.protocol)" in html
    assert "vaultMarkdownPath(element.textContent)" in html
    assert "link.href=documentHref(path)" in html


def test_assistant_links_only_safe_inline_vault_markdown_paths():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    helper = re.search(r"function vaultMarkdownPath\(text\)\{.*?\n\}", html, re.S)
    assert helper, "vault Markdown path helper not found"
    paths = [
        "drafts/2026-09-10-jamie-1-1-topics.md",
        "../outside.md",
        "/tmp/outside.md",
        "dashboard/EVOLUTION.md",
        "Dashboard/EVOLUTION.md",
        "https://example.com/file.md",
        "drafts/not-markdown.txt",
    ]
    js = (
        f"{helper.group(0)}"
        f"process.stdout.write(JSON.stringify({json.dumps(paths)}"
        ".map(vaultMarkdownPath)));"
    )
    output = subprocess.run(
        [node, "-e", js], capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(output) == [
        "drafts/2026-09-10-jamie-1-1-topics.md", "", "", "", "", "", ""
    ]


def test_composer_paste_keeps_links_hidden_in_rich_text():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    helper = re.search(r"function pastedLinkText\(html,plain\)\{.*?\n\}", html, re.S)
    assert helper, "paste link helper not found"
    assert "pastedLinkText(data.getData('text/html'),data.getData('text/plain'))" in html
    url = "https://teams.microsoft.com/l/chat/19:abc@thread.v2?a=1&b=2"
    cases = [
        [f'<p>Here is <a href="{url.replace("&", "&amp;")}">Tiger team core</a></p>',
         "Here is Tiger team core"],
        [f'<a href="{url}">{url}</a>', url],
        ['<a href="javascript:alert(1)">x</a>', "x"],
        [f"<a href='{url}'><span>Open</span></a>", ""],
        ["<b>no links</b>", "no links"],
    ]
    js = (
        f"{helper.group(0)}"
        f"process.stdout.write(JSON.stringify({json.dumps(cases)}"
        ".map(([h,p])=>pastedLinkText(h,p))));"
    )
    output = subprocess.run(
        [node, "-e", js], capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(output) == [
        f"Here is [Tiger team core]({url})", None, None, url, None
    ]


def _reply_progress_js(html):
    render = re.search(r"function renderReplyProgress\(status,label\)\{.*?\n\}", html, re.S).group()
    return render + """
function statusNode(){
  return {
    get textContent(){return this.text||'';},
    set textContent(text){this.text=text; this.firstElementChild=null;},
    insertAdjacentHTML(_,markup){this.firstElementChild={markup};}
  };
}
"""


def test_thinking_dots_animate_only_when_motion_is_allowed():
    html = (Path(cmod.__file__).parent / "static" / "assistant.html").read_text()
    assert '.thinking-dots::after{content:"..."}' in html
    assert re.search(r"@media \(prefers-reduced-motion: no-preference\)\{\s*"
                     r"\.thinking-dots::after\{animation:thinking-dots [^}]*step-end infinite", html)
    frames = re.search(r"@keyframes thinking-dots\{(.*?)\n  \}", html, re.S).group(1)
    assert re.findall(r'content:"(.*?)"', frames) == [".", "..", "..."]


def test_chat_progress_js_rejects_stale_events_and_clears_on_terminal():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(cmod.__file__).parent / "static" / "assistant.html").read_text()
    handle = re.search(r"function handle\(id,ev,ai\)\{.*?\n\}", html, re.S).group()
    js = _reply_progress_js(html) + handle + """
const assert=require('node:assert/strict'), chats={};
const convo=id=>chats[id], scrollLog=()=>{}, md=s=>s, esc=s=>s, visibleReply=s=>s;
function start(id){
  let status=statusNode(); status.remove=()=>{status=null;};
  const bubble={innerHTML:'',insertAdjacentHTML(_,s){this.innerHTML+=s;},
    hasChildNodes(){return !!this.innerHTML;}};
  const ai={_raw:'',querySelector:s=>s==='.bubble'?bubble:status};
  chats[id]={stream:ai,historyCount:0};
  return ai;
}
const send=(ai,id,run,kind,data={})=>handle(id,{item_id:id,run_id:run,kind,...data},ai);
const a=start('a'), b=start('b');
send(a,'a','one','progress',{label:'Tool started · Read'});
send(b,'b','other','progress',{label:'Reply running'});
handle('a',{item_id:'b',run_id:'one',kind:'progress',label:'wrong chat'},a);
send(a,'a','old','progress',{label:'wrong run'});
assert.equal(a.querySelector('.reply-progress').textContent,'Tool started · Read');
send(a,'a','one','text',{text:'Final reply'});
assert.equal(a.querySelector('.reply-progress'),null);
send(a,'a','one','reply_end');
send(a,'a','one','progress',{label:'late'});
send(a,'a','one','_close');
assert.equal(a.querySelector('.bubble').innerHTML,'Final reply');
assert.equal(a.querySelector('.reply-progress'),null);
const status=b.querySelector('.reply-progress');
assert.equal(status.textContent,'Thinking');
assert.match(status.firstElementChild.markup,/class="thinking-dots" aria-hidden="true"/);
send(b,'b','other','progress',{label:'Tool running · Read'});
assert.equal(status.textContent,'Tool running · Read');
assert.equal(status.firstElementChild,null);
const next=start('b');
send(b,'b','other','error',{payload:{reason:'stale error'}});
assert.equal(b.querySelector('.bubble').innerHTML,'');
send(next,'b','new','progress',{label:'Reply running'});
send(next,'b','new','error',{payload:{reason:'Reply stopped.'}});
send(next,'b','new','progress',{label:'late'});
assert.equal(next.querySelector('.reply-progress'),null);
assert.match(next.querySelector('.bubble').innerHTML,/Reply stopped/);
"""
    subprocess.run([node, "-e", js], check=True)


def test_idle_poll_does_not_yank_chat_scroll():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    fn = re.search(r"function syncConversation\(id\)\{.*?\n\}", html, re.S)
    assert fn, "syncConversation not found"
    js = _reply_progress_js(html) + fn.group(0) + """
const chatContexts={}, activeId=null;
let scrolls=0, pending=null;
const scrollLog=()=>scrolls++, renderHistory=()=>{}, clearQueuedNotes=()=>{};
const assert=require('node:assert/strict');
const chatProgress={};
const document={createElement:()=>({dataset:{}, lastElementChild:statusNode(), remove(){pending=null;}})};
const log={querySelector:()=>pending, appendChild:row=>{pending=row;}};
const convos={a:{log, seeded:true, busy:false, historyCount:1}};
const chatHistories={a:[{}]}, activeChats=new Set(), pendingApprovals={};
const out=[];
syncConversation('a'); out.push(scrolls);           // idle poll
chatHistories.a.push({}); syncConversation('a'); out.push(scrolls);  // new message
activeChats.add('a'); syncConversation('a'); out.push(scrolls);      // thinking appears
assert.equal(pending.lastElementChild.textContent,'Thinking');
const dots=pending.lastElementChild.firstElementChild;
assert.ok(dots);
syncConversation('a');
assert.equal(pending.lastElementChild.firstElementChild,dots);
chatProgress.a={label:'Writing reply'};
syncConversation('a'); out.push(scrolls);
assert.equal(pending.lastElementChild.textContent,'Writing reply');
assert.equal(pending.lastElementChild.firstElementChild,null);
const first=pending;
chatProgress.a={run_id:'two',label:'Reply running'};
syncConversation('a');
assert.notEqual(pending,first);
assert.equal(pending.dataset.run,'two');
assert.equal(pending.lastElementChild.textContent,'Thinking');
assert.ok(pending.lastElementChild.firstElementChild);
activeChats.delete('a'); syncConversation('a'); out.push(scrolls);   // thinking clears
process.stdout.write(JSON.stringify(out));
"""
    output = subprocess.run(
        [node, "-e", js], capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(output) == [0, 1, 2, 2, 4]


def _order_attention_items(items, mode, pins=()):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    helpers = re.search(
        r"function importanceScore\(item\)\{.*?(?=function togglePin)",
        html,
        re.S,
    )
    assert helpers, "attention ordering helpers not found"
    js = (
        f"let orderMode={json.dumps(mode)};"
        f"let pinnedIds=new Set({json.dumps(list(pins))});"
        f"{helpers.group(0)}"
        f"process.stdout.write(JSON.stringify(orderedItems({json.dumps(items)}).map(x=>x.id)));"
    )
    output = subprocess.run(
        [node, "-e", js], capture_output=True, text=True, check=True
    ).stdout
    return json.loads(output)


def test_assistant_orders_items_by_importance_date_type_with_pins_first():
    items = [
        {
            "id": "urgent",
            "title": "Production incident blocked today",
            "why": "Approval is waiting",
            "action_owner": "user",
            "action_type": "decision",
            "new": True,
            "raised_at": "2026-08-06T10:00:00Z",
        },
        {
            "id": "pinned",
            "title": "Routine follow-up",
            "action_owner": "assistant",
            "action_type": "task",
            "new": False,
            "raised_at": "2026-08-05T10:00:00Z",
        },
        {
            "id": "newest",
            "title": "Review notes",
            "action_owner": "assistant",
            "action_type": "review",
            "new": False,
            "raised_at": "2026-08-07T10:00:00Z",
        },
    ]
    assert _order_attention_items(items, "importance", ["pinned"]) == [
        "pinned", "urgent", "newest",
    ]
    assert _order_attention_items(items, "date") == ["newest", "urgent", "pinned"]
    assert _order_attention_items(items, "type") == ["urgent", "newest", "pinned"]


def test_assistant_persists_pin_and_order_preferences():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "assistant-order-v1" in html
    assert "assistant-pins-v1" in html
    assert 'data-pin-id="${escAttr(it.id)}"' in html
    assert '<option value="importance"' in html
    assert '<option value="date"' in html
    assert '<option value="type"' in html
    assert "Importance ${importanceScore(it)}/5" in html


def test_assistant_uses_tabler_inbox_and_conversation_workspace():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert 'class="attention-queue" aria-label="Attention inbox"' in html
    assert 'class="main"' in html
    assert 'class="conversation-header card-header"' in html
    assert 'class="badge action-badge action-${key}"' in html
    assert 'class="card recommendation ' in html
    assert 'class="rail-meta">${actionBadge(it.action_type)}' in html
    assert "String(index+1).padStart(2,'0')" in html
    assert "grid-template-columns:64px minmax(0,1fr)" in html
    assert "it.id===activeId?'active':''" in html
    assert 'data-pin-id="${escAttr(it.id)}"' in html


def test_assistant_frontend_links_to_rendered_vault_documents():
    static = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"
    assistant = (static / "assistant.html").read_text()
    document = (static / "document.html").read_text()

    assert 'class="cta vault-document"' in assistant
    assert "documentHref(d.path,itemId)" in assistant
    assert "ctas(it.links,it.documents,it.id)" in assistant
    assert "syncItemUrl" in assistant
    assert "fetch('/api/vault-document?path='" in document
    assert "safeReturnUrl" in document
    assert "resolveReturnUrl" in document
    assert "backLabel" in document
    assert "safeMarkdown(wikiLinks(data.content," in document
    assert '/static/vault-markdown.js' in document
    assert "allowedTags" in (static / "vault-markdown.js").read_text()


def test_assistant_frontend_separates_context_from_recommended_action():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "Why now" in html
    assert "Situation" in html
    assert "Recommended action" in html
    assert "Assistant can do this" in html
    assert "Your action" in html
    assert "it.action_label||'Take next step'" in html
    assert "recommendation-btn" in html
    assert 'id="send-message">Send</button>' in html


def test_assistant_keeps_inline_action_panels_in_the_message_bubble():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()

    assert "(ai.querySelector('.bubble')||ai).appendChild(div)" in html
    assert "b.insertAdjacentHTML('beforeend'," in html
    assert "ai.appendChild(div)" not in html


def test_user_owned_recommendation_is_display_only():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "it.action_owner==='assistant'?`<div class=\"recommendation-actions\">" in html
    assert "if(recommendationButton) recommendationButton.onclick=()=>send(id,'')" in html


def test_dashboard_pages_share_navigation_and_favicon():
    static = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"
    for name in ("assistant.html", "index.html", "pulse.html", "document.html",
                 "workspace.html", "office.html", "changelog.html", "settings.html"):
        html = (static / name).read_text()
        assert 'data-bs-theme="dark"' in html
        # Light mode: theme.js runs undeferred after shell.css so the theme is set before first paint.
        assert '<script src="/static/theme.js"></script>' in html
        assert html.index('/static/shell.css') < html.index('/static/theme.js')
        # The header is an empty shell; nav-count.js renders the one shared navigation into it.
        assert '<header class="workspace-header navbar" aria-label="Workspace"></header>' in html
        assert '<script src="/static/nav-count.js" defer></script>' in html
        assert 'class="nav-link" href=' not in html
        assert 'rel="icon" href="/static/favicon.png"' in html
        assert "Workspace Dashboard" not in html
        assert re.search(r"<title>[^<]+ · Roosta</title>", html)
        assert html.index('/static/vendor/tabler/tabler.min.css') < html.index('/static/shell.css')
    nav = (static / "nav-count.js").read_text()
    for path, label in (("/assistant", "Assistant"), ("/workspace", "Workspace"), ("/runner", "Workers"),
                        ("/pulse", "Pulse"), ("/office", "The Office")):
        assert f"['{path}', '{label}']" in nav
    # Settings is a cog at the top right, not a nav link.
    assert "['/settings'" not in nav
    assert "cog.href = '/settings'" in nav and "cog.setAttribute('aria-label', 'Settings')" in nav
    assert "fetch('/api/pages')" in nav
    assert "aria-label', 'Roosta home'" in nav
    assert '<img src="/static/favicon.png" alt=""><span>Roosta</span>' in nav
    assert "aria-current', 'page'" in nav
    assert (static / "ui-icons.svg").is_file()
    shell = (static / "shell.css").read_text()
    assert '[data-bs-theme="light"] {' in shell
    favicon = (static / "favicon.png").read_bytes()
    assert favicon == (static.parents[2] / "assets" / "roosta-pixel.png").read_bytes()


def test_dashboard_assets_are_pinned_and_available_locally():
    static = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"
    css = (static / "vendor/tabler/tabler.min.css").read_text()
    assert "Tabler v1.7.3" in css
    assert "@import" not in css
    assert "Permission is hereby granted" in (static / "vendor/tabler/LICENSE").read_text()
    assert (static / "fonts/InterVariable.woff2").read_bytes().startswith(b"wOF2")
    assert (static / "fonts/Inter-LICENSE.txt").is_file()
    shell = (static / "shell.css").read_text()
    assert 'url("/static/fonts/InterVariable.woff2")' in shell
    assert "--tblr-body-font-family: var(--font-ui)" in shell
    assert "--shell-header-height: 52px" in shell
    assert "padding-top: var(--shell-header-height)" in shell
    assert "--shell-sidebar-width" not in shell


STATIC = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"
PAGES = ("assistant.html", "index.html", "pulse.html", "document.html", "workspace.html")


def test_buttons_use_tabler_without_a_parallel_control_system():
    for name in PAGES:
        page = (STATIC / name).read_text()
        assert 'class="btn' in page
        assert 'class="control ' not in page
        assert not re.search(r"\.btn(?:-primary|-danger|-sm)?\s*\{", page)
        for tag, classes in re.findall(r'<(\w+)\b[^>]*class="([^\"]*)"', page):
            if "btn" in classes.split():
                assert tag in ("a", "button"), (name, tag)
    assistant = (STATIC / "assistant.html").read_text()
    assert 'class="btn btn-danger aps"' in assistant
    assert 'class="btn btn-primary recommendation-btn"' in assistant
    assert 'class="btn btn-primary" id="send-message"' in assistant


def test_labels_use_tabler_badges_and_statuses_remain_non_interactive():
    runner = (STATIC / "index.html").read_text()
    pulse = (STATIC / "pulse.html").read_text()
    assistant = (STATIC / "assistant.html").read_text()
    for page, hook in ((runner, "act-kind"), (pulse, "running-badge"),
                       (pulse, "status-pill"), (assistant, "action-badge")):
        assert f'class="badge {hook} ' in page
        style = re.search(r"\." + hook + r"\s*\{([^}]*)\}", page)[1]
        assert "--tblr-badge-color:" in style
        assert not re.search(r"(?:^|;)\s*(?:border|background|box-shadow):", style)
    status = runner[runner.index(".task-status {"):].split("}", 1)[0]
    assert "background" not in status and "box-shadow" not in status
    assert ".task-status::before {" in runner


def test_forms_use_tabler_classes():
    for name in PAGES:
        page = (STATIC / name).read_text()
        for tag in re.findall(r"<(?:input|textarea|select)\b[^>]*>", page):
            if re.search(r'type="(?:hidden|checkbox|radio)"', tag):
                continue
            assert "form-select" in tag or "form-control" in tag, (name, tag)


def test_blocked_task_has_distinct_status_and_message_styles():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "index.html").read_text()
    assert ".task-status-blocked" in html
    assert ".task-message.blocked" in html
    assert "t.status === 'blocked' ? 'blocked' : 'error'" in html


def test_skill_runner_selects_connection_per_task():
    html = (STATIC / "index.html").read_text()
    assert 'name="connection"' in html
    assert 'name="harness"' not in html
    assert "fetch('/api/runtime-options')" in html
    assert 'name="unrestricted"' in html
    assert "${t.unrestricted === true ? 'checked' : ''}" in html
    assert "if (f.unrestricted.checked !== f.unrestricted.defaultChecked) body.unrestricted = f.unrestricted.checked" in html
    assert "body.connection = f.connection.value" in html
    assert "Keep existing setup" not in html
    assert "Use previous setup" not in html
    assert "Use the connected default" not in html
    assert "Default follows Settings and adds nothing to tasks.yaml" in html


def test_skill_runner_tasks_are_sortable_alphabetical_by_default():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "index.html").read_text()
    assert "skill-runner-sort-v1" in html
    assert "sortTasks(tasks)" in html
    assert 'value="alphabetical">Name</option>' in html
    assert "readPreference(SORT_KEY, 'alphabetical')" in html
    assert 'aria-label="Sort workers"' in html


def test_skill_runner_list_is_dense_and_expandable():
    """Every scheduled task has to be readable at a glance, detail on demand."""
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "index.html").read_text()
    assert ".list-head,\n        .task-row {" in html
    assert "min-height: 44px;" in html
    assert 'class="card-header list-head"' in html
    assert 'class="task-detail" data-task-id="${esc(t.id)}"' in html
    assert "${open ? detailPanel(t) : ''}" in html
    assert 'aria-label="Filter workers by name, nickname or skill"' in html
    assert 'aria-label="Filter workers by status"' in html
    assert "skill-runner-show-v1" in html
    assert 'value="attention">Needs attention</option>' in html
    assert "function toggleTask(id)" in html
    assert 'id="run-summary"' in html
    # a queued task must read as queued, not as its last result
    assert "if (t.queued && t.status !== 'running') return {key: 'queued'" in html


def test_worker_drawer_leads_with_the_last_run_and_folds_settings():
    """Issue #20: the expanded worker reads as a result first, with settings grouped and folded."""
    html = (STATIC / "index.html").read_text()
    assert "task-meta" not in html  # the row already shows schedule, last run, runs and skill
    assert [m for m in re.findall(r"<legend>(\w+)</legend>", html)] == ["Schedule", "AI", "Name"]
    assert "taskList.addEventListener('toggle'" in html
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    escape = re.search(r"function esc\(s\) \{.*?\n        \}", html, re.S).group(0)
    helpers = re.search(r"function asText\(v\) \{.*?\n        function timeAgo\(iso\) \{.*?\n        \}", html, re.S).group(0)
    drawer = re.search(r"function lastRunCard\(t\) \{.*?\n        function detailPanel\(t\) \{.*?\n        \}", html, re.S).group(0)
    subprocess.run([node, "-e", escape + helpers + drawer + r'''
const assert = require('node:assert/strict');
const openSettings = new Set();
const oneToOneHref = id => '/assistant?item=worker:' + id;
const settingsForm = () => '<form class="task-settings"></form>';
const ran = {id: 'brief', description: 'Daily <brief>', last_run: new Date(Date.now() - 7200e3).toISOString(),
    last_duration: 41.6, last_output: {summary: 'Two items', details: {items: [1]}}};
let html = detailPanel(ran);
assert.ok(html.indexOf('Two items') < html.indexOf('task-settings'), 'result before settings');
assert.match(html, /2h ago · took 42s/);
assert.match(html, /<details class="output-details">/);
assert.match(html, /Daily &lt;brief&gt;/);
assert.match(html, /data-settings-for="brief" >/);
openSettings.add('brief');
assert.match(detailPanel(ran), /data-settings-for="brief" open>/);
html = detailPanel({id: 'new', description: ''});
assert.match(html, /Not run yet/);
assert.doesNotMatch(html, /output-details/);
html = detailPanel({id: 'quiet', last_run: ran.last_run, status: 'blocked', last_error: 'Sign in'});
assert.match(html, /left no summary/);
assert.match(html, /task-message blocked/);
'''], check=True, capture_output=True, text=True)


def test_worker_skill_preview_loads_in_page():
    html = (STATIC / "index.html").read_text()
    assert html.count('data-skill="${esc(t.id)}"') == 1  # the row names the skill; the drawer doesn't repeat it
    assert '<dialog id="skill-preview" aria-labelledby="skill-preview-title">' in html
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    function = re.search(r"function viewSkill\(id\) \{.*?async function previewSkill\(url, name\) \{.*?\n        \}", html, re.S).group(0)
    subprocess.run([node, "-e", function + r'''
const assert = require('node:assert/strict');
const elements = {
    'skill-preview': {showModal() { this.open = true; }},
    'skill-preview-title': {},
    'skill-preview-body': {replaceChildren(child) { this.child = child; }},
};
const document = {getElementById: id => elements[id], createElement: () => ({})};
const latestTasks = [{id: 'daily brief', skill: 'daily-brief'}];
const safeMarkdown = text => 'sanitised:' + text;
let response;
const fetch = async url => {
    assert.equal(url, '/api/tasks/daily%20brief/skill');
    return response;
};
(async () => {
    response = {ok: true, json: async () => ({content: '---\nname: brief\n---\n# Instructions'})};
    await viewSkill('daily brief');
    assert.equal(elements['skill-preview'].open, true);
    assert.equal(elements['skill-preview-title'].textContent, 'daily-brief / SKILL.md');
    assert.equal(elements['skill-preview-body'].child.innerHTML,
        'sanitised:```yaml\nname: brief\n```\n# Instructions');
    response = {ok: false, json: async () => ({error: 'SKILL.md not found'})};
    await viewSkill('daily brief');
    assert.equal(elements['skill-preview-body'].child.textContent, 'SKILL.md not found');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''], check=True, capture_output=True, text=True)


def test_unscheduled_skills_render_with_preview_and_schedule_link():
    html = (STATIC / "index.html").read_text()
    assert '<section class="card runner-panel unscheduled-panel" id="unscheduled"' in html
    assert "setInterval(loadUnscheduled, 30000)" in html
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    helpers = re.search(r"function scheduleSkillHref\(skill\) \{.*?\n        function renderUnscheduled\(skills\) \{.*?\n        \}", html, re.S).group(0)
    escape = re.search(r"function esc\(s\) \{.*?\n        \}", html, re.S).group(0)
    subprocess.run([node, "-e", escape + helpers + r'''
const assert = require('node:assert/strict');
const elements = {unscheduled: {hidden: true}, 'unscheduled-summary': {}, 'unscheduled-list': {}};
const document = {getElementById: id => elements[id]};
renderUnscheduled([{skill: 'skill-auditor', description: 'Audits <skills>'}, {skill: 'write-a-skill', description: ''}]);
assert.equal(elements.unscheduled.hidden, false);
assert.equal(elements['unscheduled-summary'].textContent, '2 skills');
const list = elements['unscheduled-list'].innerHTML;
assert.match(list, /data-workspace-skill="skill-auditor"/);
assert.match(list, /Audits &lt;skills&gt;/);
assert.doesNotMatch(list, /<skills>/);
assert.match(list, /href="\/assistant\?item=hire&amp;ask=Put%20the%20skill-auditor%20skill%20on%20a%20schedule%20as%20a%20worker\."/);
assert.equal((list.match(/unscheduled-desc/g) || []).length, 1);
renderUnscheduled([]);
assert.equal(elements.unscheduled.hidden, true);
assert.equal(elements['unscheduled-list'].innerHTML, '');
'''], check=True, capture_output=True, text=True)


def test_skill_runner_activity_pins_running_work():
    """Running skills come from the activity log *and* live runner state."""
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "index.html").read_text()
    assert 'id="activity-now"' in html
    assert "function runningWork()" in html
    assert "if (entry.status !== 'running') continue;" in html
    assert "if (covered.has(task.id)) continue;" in html
    assert "task.status === 'running'" in html
    assert "Nothing running" in html
    assert "setInterval(renderRunningNow, 1000)" in html
    assert ".act-state.interrupted" in html
    # in-flight work is pinned above, so the list below is finished runs only
    assert ".filter(r => r.status !== 'running')" in html
    assert 'class="act-heading">Finished<' in html


def test_dashboard_uses_one_status_vocabulary():
    """A run reads the same word on the task row, the feed and Pulse."""
    static = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"
    runner = (static / "index.html").read_text()
    pulse = (static / "pulse.html").read_text()
    scheduler_py = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "scheduler.py").read_text()
    pulse_py = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "pulse.py").read_text()

    # a finished run is `success`, never `done`
    feed = ActivityLog()
    feed.finish(eid := feed.start("skill", "assistant", "manual"))
    assert feed.get(eid)["status"] == "success"
    assert '"error" if status == "error" else "success"' in scheduler_py
    assert '"today_success": sum(1 for entry in today if entry.get("status") == "success")' in pulse_py
    assert ".act-state.success" in runner
    assert ".act-state.done" not in runner

    # `kind` describes the spawn, so it must not borrow a verdict word
    assert '"skill", task.skill, source' in scheduler_py
    assert ".act-skill {" in runner and ".act-pass" not in runner

    assert "pass:" not in runner and "'done'" not in runner
    assert ".running-badge.skill" in pulse and ".running-badge.pass" not in pulse
    assert "'AI runs today', data.activity.today_runs" in pulse

    # no abbreviated status labels on a row
    assert "const STATUS_LABELS = {'auth-failed': 'auth failed'}" in runner

    # an unrecognised value must not vanish, so each falls back to neutral grey
    assert "color: #8d949e;" in runner[runner.index(".task-status {"):][:600]
    assert "--tag-colour: #8d949e;" in runner[runner.index(".act-kind {"):][:600]
    start = pulse.index(".running-badge {")
    assert "--tag-colour: #8d949e;" in pulse[start:start + 500]


STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"


@pytest.mark.parametrize("page", sorted(p.name for p in STATIC_DIR.glob("*.html")))
def test_page_inline_scripts_parse(page):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    scripts = re.findall(r"<script>(.*?)</script>", (STATIC_DIR / page).read_text(), re.S)
    assert scripts, f"{page} has no inline script"
    for script in scripts:
        result = subprocess.run([node, "--check"], input=script, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


# --- frontend schedule() display (the user's recurring "shows only interval" complaint) ---


def _schedule(task):
    """Run the schedule() helper lifted verbatim from index.html through node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "index.html").read_text()
    m = re.search(r"function schedule\(t\)\s*\{.*?\n        \}", html, re.S)
    assert m, "schedule() helper not found in index.html"
    js = m.group(0) + f"\nprocess.stdout.write(schedule({json.dumps(task)}));"
    return subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout


def test_schedule_renders_days_of_week_not_daily():
    # the rolling-comms case that motivated the whole days_of_week feature
    assert _schedule({"run_at": "09:00", "days_of_week": ["monday"]}) == "09:00 (mon)"


def test_schedule_renders_weekdays_daily_and_intervals():
    assert _schedule({"run_at": "07:00", "weekdays_only": True}) == "07:00 (weekdays)"
    assert _schedule({"run_at": "09:00"}) == "09:00 daily"
    assert _schedule({"interval": 20}) == "every 20s"
    assert _schedule({"interval": 1200}) == "every 20m"
    assert _schedule({"interval": 14400}) == "every 4h"


# --- board health (the board must not show a false all-clear when a sensor fails) ---

_NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def _sensor(sid, status="success", ago_seconds=0, interval=3600):
    return {
        "id": sid,
        "sensor": True,
        "status": status,
        "interval": interval,
        "last_run": (_NOW - timedelta(seconds=ago_seconds)).isoformat(),
    }


def test_board_health_ok_when_sensors_fresh_and_successful():
    states = [_sensor("assistant", ago_seconds=60),
              _sensor("teams-actions-watch", ago_seconds=120)]
    h = board.board_health(states, now=_NOW)
    assert h == {"ok": True, "degraded": [], "automation_failures": [],
                 "claude_signin_expired": False, "github_signin_expired": False}


def test_board_health_flags_errored_sensor():
    states = [_sensor("assistant"),
              _sensor("self-chat-commands", status="error")]
    h = board.board_health(states, now=_NOW)
    assert h["ok"] is False
    assert {"id": "self-chat-commands", "nickname": "", "reason": "last run failed"} in h["degraded"]


def test_board_health_flags_stale_sensor():
    # last run older than 3x its 3600s interval => stale
    states = [_sensor("support-watch", ago_seconds=3 * 3600 + 1, interval=3600)]
    h = board.board_health(states, now=_NOW)
    assert h["ok"] is False
    assert h["degraded"] == [{"id": "support-watch", "nickname": "", "reason": "stale"}]


def test_board_health_surfaces_failed_automations_without_changing_sensor_verdict():
    gardener = {
        **_sensor("workspace-gardener", status="error"),
        "sensor": False,
        "nickname": "Kevin",
        "last_error": "Task produced no output",
    }
    states = [
        gardener,
        {**_sensor("roosta-engineer", status="error"), "sensor": False},
        {"id": "assistant", "status": "success", "interval": 3600, "last_run": "junk"},
    ]
    assert board.board_health(states, now=_NOW) == {
        "ok": True,
        "degraded": [],
        "automation_failures": [
            {"id": "workspace-gardener", "nickname": "Kevin", "reason": "Task produced no output"},
        ],
        "claude_signin_expired": False,
        "github_signin_expired": False,
    }


def test_board_health_names_an_expired_claude_signin_once():
    failed = [
        {**_sensor(sid, status="error"), "last_error": board.CLAUDE_SIGNIN_MESSAGE}
        for sid in ("workspace-gardener", "teams-archive", "assistant")
    ]
    h = board.board_health(failed, now=_NOW)
    assert h["claude_signin_expired"] is True
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "h.claude_signin_expired" in html


def test_assistant_frontend_renders_health_warning():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "healthWarning" in html
    assert "picture may be incomplete" in html
    assert "automation_failures" in html
    assert 'class="health-warn" href="/runner"' in html


def test_restart_pending_when_a_module_changed_after_start(tmp_path):
    module = tmp_path / "app.py"
    module.write_text("")
    os.utime(module, (1000, 1000))
    assert board.restart_pending(started=2000, root=tmp_path) is False
    os.utime(module, (3000, 3000))
    assert board.restart_pending(started=2000, root=tmp_path) is True
    # Only Python modules count: static pages reload without a restart.
    os.utime(module, (1000, 1000))
    (tmp_path / "assistant.html").write_text("")
    assert board.restart_pending(started=2000, root=tmp_path) is False


def test_health_warning_names_a_pending_restart():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    helper = re.search(r"function healthWarning\(h\)\{.*?\n\}", html, re.S)
    assert helper, "healthWarning not found"
    cases = [
        {"restart_pending": True},
        {"restart_pending": False},
        {"restart_pending": True, "degraded": [{"id": "assistant", "reason": "last run failed"}]},
        {"degraded": [{"id": "assistant", "reason": "stale"}],
         "automation_failures": [{"id": "teams-watch", "nickname": "Dwight", "reason": "boom"}]},
    ]
    js = (
        "const escAttr=s=>String(s);"
        f"{helper.group(0)}"
        f"process.stdout.write(JSON.stringify({json.dumps(cases)}.map(healthWarning)));"
    )
    out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert "Restart Roosta to load the latest update" in out[0] and "health-warn" not in out[0]
    assert out[1] == ""
    assert "1 worker is sick" in out[2] and out[2].endswith("Restart Roosta to load the latest update</span>")
    assert "2 workers are sick" in out[3] and "Dwight (teams-watch): boom" in out[3]
    assert "Board picture may be incomplete" in out[3]


def test_assistant_composer_buttons_do_not_stretch_with_textarea():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert ".form{display:flex;align-items:flex-end" in html
    assert 'class="btn btn-primary" id="send-message"' in html
    assert 'class="btn" id="close"' in html
    assert '${itemControls}${contextMenu}</div>' in html


def test_attachment_icon_is_visible_without_a_fresh_sprite():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    attachment = re.search(r'<button\b[^>]*id="attach-menu-button"[\s\S]*?</button>', html).group(0)
    assert '<path ' in attachment and '<use ' not in attachment
    assert 'aria-label="Add files"' in attachment and 'title="Add images or files"' in attachment
    assert 'id="upload-files"' in html
    assert re.search(r'<a\b[^>]*id="attach-files"[^>]*href="/workspace"', html)


def test_attachment_labels_prefer_document_titles_and_readable_fallbacks():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    functions = "\n".join(re.search(r"function " + name + r"\([^\n]*\)\{.*?\n\}", html, re.S).group(0)
                          for name in ["docItem", "contextLabel"])
    js = '''
const assert=require('node:assert/strict');
const DOC_PREFIX='doc:';
const docTitles={'projects/atlas/README.md':'Atlas launch plan','notes/guide.md':'How we launch',
                 'projects/no-heading/README.md':'Readme'};
''' + functions + '''
assert.equal(contextLabel('projects/atlas/README.md'),'Atlas launch plan');
assert.equal(contextLabel('notes/guide.md'),'How we launch');
assert.equal(contextLabel('notes/release-checklist.md'),'Release Checklist');
assert.equal(contextLabel('projects/no-heading/README.md'),'No Heading');
assert.equal(contextLabel('projects/still-loading/README.md'),'Still Loading');
'''
    subprocess.run([node, "-e", js], capture_output=True, text=True, check=True)


def test_assistant_composer_autosizes_textarea():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "function autosizeComposer" in html
    assert "function bindComposerInput" in html
    assert "field-sizing:content" in html
    assert "resize:none" in html
    assert "max-height:180px" in html
    assert 'rows="1"' not in html


def test_assistant_confirms_closed_items_with_tabler_components():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert 'class="toast show" role="status" aria-live="polite"' in html
    assert 'class="toast-header"' in html and 'class="toast-body"' in html
    assert 'class="btn-close" aria-label="Dismiss confirmation"' in html
    assert 'class="alert alert-success mt-3 mb-0" role="status"' in html
    assert 'class="btn btn-sm resolution-undo"' in html
    assert "reopenItem(id)" in html
    assert "if(ok) showClosedNotice(closedLabel(id))" in html
    assert "const label=closedLabel(id,(ev.payload||{}).result);" in html
    assert "showClosedNotice(label)" in html
    assert "${esc(title||'One less thing on your list.')}" in html
    assert not re.search(r"\.(?:toast|toast-header|toast-body)\s*\{", html)
    assert "firework" not in html and "resolution-spark" not in html


def test_assistant_renders_saved_capture_inside_reply_bubble():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "const bubble=ai.querySelector('.bubble')" in html
    assert "bubble.insertAdjacentHTML('beforeend',lines)" in html
    assert 'class="capture-line"' in html
    assert ".capture-line{" in html


def test_assistant_frontend_hides_control_markers_in_streams_and_history():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "const visibleReply=" in html
    assert "PAUSE|DEFER|REMIND|DONE|ERROR" in html
    assert "?md(visibleReply(message.text))" in html
    assert "b.innerHTML=md(visibleReply(ai._raw))" in html


def test_assistant_frontend_isolates_conversations_by_item_id():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "function topicKey(id)" not in html
    assert "convos[it.thread_id||it.id]" not in html
    assert "convos[it.id]" in html
    assert "convos[id]={log, busy:false, seeded:false, historyCount:0, queuedCount:0}" in html


def test_assistant_has_persistent_general_chat_alongside_items(monkeypatch, fake_chat_connection):
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert 'data-tab="chats"' in html
    assert "Ask anything…" in html
    assert "const persistent=isChatId(id);" in html
    assert "const itemControls=persistent||aiSetup?'':" in html
    assert "d.chat_histories" in html
    assert "renderHistory(c.log,id)" in html
    assert "d.active_chat_ids" in html
    assert "if(activeChats.size) load()" in html
    assert "res.status===202" in html
    assert "Queued…" in html
    assert "c.historyCount+=1" in html
    assert "The reply will continue in the background." in html
    assert "data-new-chat" not in html
    assert "Restore previous chat" not in html
    assert 'id="clear-chat"' not in html

    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def __init__(self):
            self.turn = None

        def start_turn(self, item_id, item, message):
            self.turn = (item_id, item, message)
            events = asyncio.Queue()
            events.put_nowait({"kind": "reply_end"})
            events.put_nowait({"kind": "_close"})
            return cmod.TurnHandle(events=events)

    router = FakeRouter()
    monkeypatch.setattr(appmod, "chat_router", router)

    async def call():
        response = await appmod.api_board_chat({
            "item_id": 'chat:0123456789ab',
            "message": "What should I focus on?",
        })
        chunks = [chunk async for chunk in response.body_iterator]
        return response, chunks

    response, chunks = asyncio.run(call())
    assert response.status_code == 200
    assert chunks
    assert router.turn[0] == 'chat:0123456789ab'
    assert router.turn[1]["persistent"] is True
    assert router.turn[2] == "What should I focus on?"


def test_assistant_opens_standing_threads_and_prefills_the_asked_question():
    """A launchpad link must open a thread that is not in the rail."""
    static = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"
    html = (static / "assistant.html").read_text()
    # openItem resolves through itemById, so a doc id is not rejected by the
    # rail lookup the way an unknown board id is.
    assert "function itemById(id)" in html
    assert "const it=itemById(id); if(!it) return;" in html
    assert "isChatId(requestedItem)" in html
    assert "shown.map(chatRailItem)" in html
    assert "data-archive-chat" in html
    # The question is prefilled, never auto-sent.
    assert "input.value=requestedAsk;" in html
    assert "send(id,requestedAsk)" not in html
    assert "url.searchParams.delete('ask');" in html
    # The document viewer opens a doc: thread the same way.
    document = (static / "document.html").read_text()
    assert "'/assistant?item='+encodeURIComponent('doc:'+data.path)" in document
    assert "const DOC_PREFIX='doc:';" in html


def test_board_chat_returns_202_when_turn_is_queued(monkeypatch, fake_chat_connection):
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def start_turn(self, item_id, item, message):
            return cmod.TurnHandle(queued=True, position=2)

    monkeypatch.setattr(appmod, "chat_router", FakeRouter())

    async def call():
        return await appmod.api_board_chat({
            "item_id": 'chat:0123456789ab',
            "message": "Follow up",
        })

    response = asyncio.run(call())
    assert response.status_code == 202
    body = json.loads(response.body)
    assert body == {"queued": True, "position": 2}


def test_board_chat_continues_after_conductor_drops_item(monkeypatch, fake_chat_connection):
    """A live conversation must survive the conductor dropping its item."""
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def __init__(self):
            self.turn = None

        def reminders(self):
            return []

        def known_item(self, item_id):
            return {"id": item_id, "title": "Holdout outcome"}

        def start_turn(self, item_id, item, message):
            self.turn = (item_id, item, message)
            events = asyncio.Queue()
            events.put_nowait({"kind": "reply_end"})
            events.put_nowait({"kind": "_close"})
            return cmod.TurnHandle(events=events)

    router = FakeRouter()
    monkeypatch.setattr(appmod, "chat_router", router)
    monkeypatch.setattr(appmod.runner, "get_state", lambda _task_id: {
        "last_output": {"details": {"items": []}}})
    monkeypatch.setattr(appmod.runner, "get_states", lambda: [])

    async def call():
        response = await appmod.api_board_chat(
            {"item_id": "proj-9807", "message": "Give us a summary of it."})
        chunks = [chunk async for chunk in response.body_iterator]
        return response, chunks

    response, chunks = asyncio.run(call())
    assert response.status_code == 200
    assert chunks
    assert router.turn[0] == "proj-9807"
    assert router.turn[1]["title"] == "Holdout outcome"


def test_board_chat_starts_for_file_backed_reminder(monkeypatch, fake_chat_connection):
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def __init__(self):
            self.turn = None

        def reminders(self):
            return [{
                "id": "remind-123",
                "title": "Move Platform stand-ups",
                "body": "Mention this at tomorrow's stand-up.",
                "due": None,
            }]

        def known_item(self, _item_id):
            return None

        def start_turn(self, item_id, item, message):
            self.turn = (item_id, item, message)
            events = asyncio.Queue()
            events.put_nowait({"kind": "reply_end"})
            events.put_nowait({"kind": "_close"})
            return cmod.TurnHandle(events=events)

    router = FakeRouter()
    monkeypatch.setattr(appmod, "chat_router", router)
    monkeypatch.setattr(appmod.runner, "get_state", lambda _task_id: {
        "last_output": {"details": {"items": []}}})
    monkeypatch.setattr(appmod.runner, "get_states", lambda: [])

    async def call():
        response = await appmod.api_board_chat(
            {"item_id": "remind-123", "message": "Mention it tomorrow."})
        chunks = [chunk async for chunk in response.body_iterator]
        return response, chunks

    response, chunks = asyncio.run(call())
    assert response.status_code == 200
    assert chunks
    assert router.turn[0] == "remind-123"
    assert router.turn[1]["title"] == "Move Platform stand-ups"


class _StandingChatRouter:
    """Chat router that records the turn and has no prior conversation trace."""

    def __init__(self):
        self.turn = None

    def reminders(self):
        return []

    def known_item(self, _item_id):
        return None

    def start_turn(self, item_id, item, message):
        self.turn = (item_id, item, message)
        events = asyncio.Queue()
        events.put_nowait({"kind": "reply_end"})
        events.put_nowait({"kind": "_close"})
        return cmod.TurnHandle(events=events)


def test_document_chat_item_resolves_a_vault_document_as_persistent(tmp_path):
    readme = tmp_path / "projects" / "team-okrs" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("---\ntitle: Team OKRs\n---\n\n# Team OKRs\n", encoding="utf-8")

    item = chat_items.document_chat_item("doc:projects/team-okrs/README.md", tmp_path)
    assert item["id"] == "doc:projects/team-okrs/README.md"
    assert item["title"] == "Team OKRs"
    assert item["project_ref"] == "projects/team-okrs"
    assert item["documents"] == [{"label": "Open document", "path": "projects/team-okrs/README.md"}]
    assert item["persistent"] is True


def test_document_chat_item_rejects_escape_missing_and_foreign_ids(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("# A\n", encoding="utf-8")
    assert chat_items.document_chat_item("doc:notes/a.md", tmp_path)["project_ref"] is None
    assert chat_items.document_chat_item("doc:../outside.md", tmp_path) is None
    assert chat_items.document_chat_item("doc:notes/missing.md", tmp_path) is None
    assert chat_items.document_chat_item("doc:.roosta/AGENTS.md", tmp_path) is None
    assert chat_items.document_chat_item("notes/a.md", tmp_path) is None


def test_board_chat_starts_a_document_thread_off_the_rail(monkeypatch, tmp_path, fake_chat_connection):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "plan.md").write_text("# Plan\n", encoding="utf-8")
    router = _StandingChatRouter()
    monkeypatch.setattr(appmod, "chat_router", router)
    monkeypatch.setattr(appmod.paths, "WORKSPACE", tmp_path)

    async def call():
        response = await appmod.api_board_chat(
            {"item_id": "doc:notes/plan.md", "message": "Summarise this."})
        return response, [chunk async for chunk in response.body_iterator]

    response, _ = asyncio.run(call())
    assert response.status_code == 200
    assert router.turn[1]["title"] == "Plan"
    assert router.turn[1]["persistent"] is True

    missing = asyncio.run(appmod.api_board_chat(
        {"item_id": "doc:notes/nope.md", "message": "hello"}))
    assert missing.status_code == 404


def _worker_vault(tmp_path):
    skill = tmp_path / ".claude" / "skills" / "team-wins-watch" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\nname: team-wins-watch\ndescription: Spot wins.\n---\n", encoding="utf-8")
    task = task_config.TaskConfig(id="team-wins-watch", skill="team-wins-watch", interval=0,
                             dir=str(tmp_path), run_at="09:00", weekdays_only=True)
    return {task.id: task}


def test_worker_chat_item_speaks_as_the_worker_and_points_at_its_skill(tmp_path):
    tasks = _worker_vault(tmp_path)
    state = {"run_count": 12, "status": "error", "last_run": "2026-11-08T09:00:00+00:00",
             "last_output": {"summary": "Two wins found."}, "last_error": "Teams timed out"}
    runs = [
        {"kind": "skill", "task_id": "team-wins-watch", "status": "success", "summary": "ok",
         "started": "a", "duration": 3, "session_id": "secret"},
        {"kind": "skill", "task_id": "other", "status": "error"},
        {"kind": "chat", "task_id": "team-wins-watch", "status": "success"},
    ]
    item = chat_items.worker_chat_item("worker:team-wins-watch", tasks, state, runs, tmp_path)
    assert item["title"] == "1:1 with team-wins-watch"
    assert item["persistent"] is True
    assert item["documents"] == [{"label": "Open SKILL.md",
                                  "path": ".claude/skills/team-wins-watch/SKILL.md"}]
    assert "weekdays at 09:00" in item["situation"]
    assert "Two wins found." in item["situation"] and "Teams timed out" in item["situation"]
    assert "first person" in item["voice"] and "SKILL.md" in item["voice"]
    assert item["recent_runs"] == [{"status": "success", "started": "a", "duration": 3, "summary": "ok"}]


def test_worker_chat_item_rejects_unknown_and_foreign_ids(tmp_path):
    tasks = _worker_vault(tmp_path)
    assert chat_items.worker_chat_item("worker:invented", tasks, root=tmp_path) is None
    assert chat_items.worker_chat_item("team-wins-watch", tasks, root=tmp_path) is None
    assert chat_items.is_chat_id("worker:team-wins-watch")


def test_board_chat_starts_a_worker_one_to_one(monkeypatch, tmp_path, fake_chat_connection):
    router = _StandingChatRouter()
    monkeypatch.setattr(appmod, "chat_router", router)
    monkeypatch.setattr(appmod.paths, "WORKSPACE", tmp_path)
    monkeypatch.setattr(appmod, "load_tasks_map", lambda: _worker_vault(tmp_path))
    monkeypatch.setattr(appmod.runner, "get_state", lambda _task_id: None)

    async def call():
        response = await appmod.api_board_chat(
            {"item_id": "worker:team-wins-watch", "message": "How are you finding your role?"})
        return response, [chunk async for chunk in response.body_iterator]

    response, _ = asyncio.run(call())
    assert response.status_code == 200
    assert router.turn[1]["title"] == "1:1 with team-wins-watch"

    missing = asyncio.run(appmod.api_board_chat({"item_id": "worker:nobody", "message": "hi"}))
    assert missing.status_code == 404


def test_hire_chat_item_sets_up_a_new_worker_through_write_a_skill():
    item = chat_items.hire_chat_item("hire:0123456789ab")
    assert item["id"] == "hire:0123456789ab"
    assert item["title"] == "New worker"
    assert item["persistent"] is True
    voice = item["voice"]
    assert "write-a-skill" in voice and "scheduled-worker.md" in voice
    assert ".roosta/tasks.yaml" in voice and "only after" in voice
    assert "never put a schedule in the skill" in voice
    for bad in ("hire:xyz", "hire:0123456789AB", "hire:0123456789abc", "chat:0123456789ab", ""):
        assert chat_items.hire_chat_item(bad) is None
    assert chat_items.is_chat_id("hire:0123456789ab")
    assert not chat_items.is_chat_id("hire:nope")


def test_board_chat_starts_a_new_worker_thread(monkeypatch, fake_chat_connection):
    router = _StandingChatRouter()
    monkeypatch.setattr(appmod, "chat_router", router)

    async def call():
        response = await appmod.api_board_chat(
            {"item_id": "hire:00112233aabb", "message": "Watch my PRs every hour."})
        return response, [chunk async for chunk in response.body_iterator]

    response, _ = asyncio.run(call())
    assert response.status_code == 200
    assert router.turn[1]["title"] == "New worker"
    assert "write-a-skill" in router.turn[1]["voice"]

    bad = asyncio.run(appmod.api_board_chat({"item_id": "hire:../../x", "message": "hi"}))
    assert bad.status_code == 404


def test_workers_page_offers_a_one_to_one_and_new_worker():
    html = (Path(appmod.__file__).parent / "static" / "index.html").read_text()
    assert '<h1 class="page-title">Workers</h1>' in html
    assert "skill on a schedule" in html
    assert 'href="/assistant?item=hire"' in html
    # The same standing thread the Office dossier opens.
    assert "encodeURIComponent('worker:' + id)" in html
    assistant = (Path(appmod.__file__).parent / "static" / "assistant.html").read_text()
    assert "const NEW_HIRE='hire';" in assistant
    assert "if(requestedItem===NEW_HIRE) requestedItem=mintHireId();" in assistant


def test_standing_thread_ids_accepts_only_reserved_namespaces():
    raw = ("doc:notes/a.md,proj-9807,doc:notes/a.md,,chat:0123456789ab,__general__,chat:x,worker:ada,"
           "hire:0123456789ab,hire:x")
    assert chat_items.standing_thread_ids(raw) == ["doc:notes/a.md", "chat:0123456789ab", "worker:ada",
                                               "hire:0123456789ab"]
    assert chat_items.standing_thread_ids("") == []
    assert len(chat_items.standing_thread_ids(",".join(f"doc:notes/p{i}.md" for i in range(40)))) == 20


def test_board_chat_404_for_unknown_item(monkeypatch, fake_chat_connection):
    """An id with no live board entry and no conversation trace still 404s."""
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def reminders(self):
            return []

        def known_item(self, item_id):
            return None

        def start_turn(self, item_id, item, message):  # pragma: no cover
            raise AssertionError("must not start a turn for an unknown item")

    monkeypatch.setattr(appmod, "chat_router", FakeRouter())
    monkeypatch.setattr(appmod.runner, "get_state", lambda _task_id: {
        "last_output": {"details": {"items": []}}})
    monkeypatch.setattr(appmod.runner, "get_states", lambda: [])

    response = asyncio.run(appmod.api_board_chat(
        {"item_id": "made-up", "message": "hello"}))
    assert response.status_code == 404


def test_known_item_reconstructs_from_topic_and_rejects_unseen(tmp_path):
    topics = cmod.TopicStore(tmp_path / "topics.json")
    cr = cmod.ChatRouter(
        session_map=cmod.SessionMap(tmp_path / "s.json"),
        vault="/v", handled_path=tmp_path / "handled.json", topic_store=topics)
    topics.begin("item-1", {"title": "Holdout outcome",
                            "project_ref": "projects/platform-roadmap"}, "ses_1")
    rebuilt = cr.known_item("item-1")
    assert rebuilt == {"id": "item-1", "title": "Holdout outcome",
                       "project_ref": "projects/platform-roadmap"}
    assert cr.known_item("never-seen") is None


def test_mark_handled_preserves_conversation_for_continuation(tmp_path):
    """Resolving an item must not wipe its session, so a follow-up keeps context."""
    topics = cmod.TopicStore(tmp_path / "topics.json")
    sessions = cmod.SessionMap(tmp_path / "s.json")
    cr = cmod.ChatRouter(
        session_map=sessions, vault="/v",
        handled_path=tmp_path / "handled.json", topic_store=topics)
    sessions.set("item-1", "ses_1")
    topics.begin("item-1", {"title": "Holdout outcome"}, "ses_1")
    cr.mark_handled("item-1", "Backfilled the historic holdouts")
    assert sessions.get("item-1") == "ses_1"
    assert topics.get("item-1")["title"] == "Holdout outcome"
    assert cr.known_item("item-1")["id"] == "item-1"


def test_board_returns_visible_history_for_open_chats_and_current_items(monkeypatch, tmp_path, fake_chat_connection):
    topics = tmp_path / "topics.json"
    boundary = {"end": 1, "at": "2026-11-19T12:00:00Z"}
    topics.write_text(json.dumps({"item-1": {"boundaries": [boundary], "summary": "private"},
                                 "other": {"boundaries": [boundary]}}))
    monkeypatch.setattr(appmod, "TOPICS_FILE", topics)
    histories = {
        'chat:0123456789ab': [{"role": "user", "text": "General question"}],
        "item-1": [{"role": "assistant", "text": "Item answer"}],
    }

    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def handled(self):
            return {}

        def snoozed(self):
            return {}

        def reminders(self):
            return []

        def conversation_histories(self):
            return histories

        active_progress = {"item-1": {"run_id": "run-2", "label": "Tool started · Read"}}

        def active_items(self):
            return ["item-1"]

        def pending_approvals(self):
            return {"item-1": [{"run_id": "run-1", "kind": "action", "summary": "Book room"}]}

        def record_raised(self, item_ids):
            return {}

    monkeypatch.setattr(appmod, "chat_router", FakeRouter())
    monkeypatch.setattr(appmod.runner, "get_state", lambda _task_id: {
        "last_output": {"details": {"items": [{"id": "item-1"}]}}
    })
    monkeypatch.setattr(appmod.runner, "get_states", lambda: [{
        "id": "support-watch",
        "last_output": {"details": {"items": [
            {"id": "support-1", "title": "Support ask", "new": True},
        ]}},
    }])

    response = asyncio.run(appmod.api_board(threads="chat:0123456789ab"))
    body = json.loads(response.body)

    assert body["chat_histories"] == histories
    assert body["chat_contexts"] == {"item-1": {"boundaries": [boundary], "refreshed_at": None}}
    assert body["active_chat_ids"] == ["item-1"]
    assert body["chat_progress"] == FakeRouter.active_progress
    assert body["pending_approvals"]["item-1"][0]["run_id"] == "run-1"
    assert [item["id"] for item in body["document"]["items"]] == ["item-1", "support-1"]


def test_chat_list_orders_by_activity_and_archive_hides_until_new_activity():
    histories = {
        "item-1": [{"role": "user", "text": "Board item", "at": "2026-11-08T09:00"}],
        "chat:aaaaaaaaaaaa": [{"role": "user", "text": "Older  question\nhere", "at": "2026-11-07T09:00"}],
        "chat:bbbbbbbbbbbb": [{"role": "user", "text": "Newer", "at": "2026-11-08T10:00"},
                              {"role": "assistant", "text": "Answer", "at": "2026-11-08T10:01"}],
        "doc:notes/a.md": [{"role": "user", "text": "About the doc", "at": "2026-11-08T08:00"}],
        "chat:cccccccccccc": [{"role": "user", "text": "Archived", "at": "2026-11-06T09:00"}],
    }
    archived = {"chat:cccccccccccc": "2026-11-06T10:00", "doc:notes/a.md": "2026-11-01T00:00"}
    rows = chat_items.chat_list(histories, archived)
    assert [r["id"] for r in rows] == ["chat:bbbbbbbbbbbb", "doc:notes/a.md", "chat:aaaaaaaaaaaa"]
    assert rows[0]["turns"] == 2
    assert rows[2]["preview"] == "Older question here"


def test_archive_endpoint_accepts_only_chat_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "ARCHIVED_CHATS_FILE", tmp_path / "archived.json")
    history = tmp_path / "history.json"
    monkeypatch.setattr(appmod, "CHAT_HISTORY_FILE", history)
    appmod.ConversationHistoryStore(history).append("chat:aaaaaaaaaaaa", "user", "hello")
    ok = asyncio.run(appmod.api_chats_archive({"item_id": "chat:aaaaaaaaaaaa"}))
    assert ok.status_code == 200
    assert "chat:aaaaaaaaaaaa" in appmod.archived_chats()
    for bad in ("item-1", "__general__", "chat:nothex", ""):
        assert asyncio.run(appmod.api_chats_archive({"item_id": bad})).status_code == 400


def test_new_chat_has_no_confirm_dialog_and_starts_from_the_ask_box():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "confirm(" not in html
    assert 'id="ask-box"' in html
    assert "askNewChat(text)" in html
    assert "/api/chats/archive" in html


def test_desktop_notification_deep_links_are_supported():
    static = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"
    assistant = (static / "assistant.html").read_text()
    runner = (static / "index.html").read_text()
    assert "new URLSearchParams(location.search).get('item')" in assistant
    assert "openItem(requestedItem)" in assistant
    assert "new URLSearchParams(location.search).get('task')" in runner
    assert "scrollIntoView" in runner


def _default_assistant_item(requested, active, attention_ids):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    helper = re.search(r"function defaultItemId\(.*?\n\}", html, re.S)
    assert helper, "defaultItemId() helper not found"
    js = (
        "const NEW_CHAT='new';"
        f"{helper.group(0)}"
        "process.stdout.write(JSON.stringify(defaultItemId("
        f"{json.dumps(requested)},{json.dumps(active)},{json.dumps(attention_ids)})));"
    )
    output = subprocess.run(
        [node, "-e", js], capture_output=True, text=True, check=True
    ).stdout
    return json.loads(output)


def test_assistant_opens_ready_on_the_top_item_or_general_chat():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()

    assert "tryOpenRequested();\n  openDefaultItem();" in html
    assert _default_assistant_item(None, None, ["top", "next"]) == "top"
    assert _default_assistant_item(None, None, []) == "new"
    assert _default_assistant_item("deep-link", None, ["top"]) is None
    assert _default_assistant_item(None, "current", ["top"]) is None


# --- Recently closed review + revive, and rail search ---


def test_closed_snapshot_keeps_context_fields_and_drops_junk():
    snap = cmod._closed_snapshot({
        "id": "i", "title": "T", "why": "W", "situation": "S", "opening_move": "O",
        "action_type": "review", "action_owner": "user", "action_label": "Review it",
        "links": [{"label": "L", "url": "https://x"}],
        "documents": [{"label": "D", "path": "drafts/x.md"}],
        "project_ref": "projects/magic-mirror", "new": True,
    })
    assert snap["title"] == "T" and snap["action_type"] == "review"
    assert snap["links"] == [{"label": "L", "url": "https://x"}]
    assert snap["project_ref"] == "projects/magic-mirror"
    assert "id" not in snap and "new" not in snap
    assert cmod._closed_snapshot(None) is None
    assert cmod._closed_snapshot({}) is None


def test_mark_handled_stores_snapshot_and_unhandle_returns_it(tmp_path):
    p = tmp_path / "handled.json"
    cr = cmod.ChatRouter(session_map=cmod.SessionMap(tmp_path / "s.json"),
                         vault="/v", handled_path=p)
    cr.mark_handled("item-1", "Closed by Sam", {"title": "Holdout outcome", "why": "deadline"})
    record = cr.handled()["item-1"]
    assert record["result"] == "Closed by Sam"
    assert record["item"] == {"title": "Holdout outcome", "why": "deadline"}

    restored = cr.unhandle("item-1")
    assert restored == {"title": "Holdout outcome", "why": "deadline"}
    assert "item-1" not in cr.handled()
    assert cr.unhandle("item-1") is None


def test_recently_closed_lists_newest_first_with_titles():
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def known_item(self, item_id):
            return {"id": item_id, "title": "From topic"}

    handled = {
        "a": {"result": "Done A", "at": "2026-08-01T10:00:00Z",
              "item": {"title": "Alpha", "action_type": "review"}},
        "b": {"result": "Done B", "at": "2026-08-02T10:00:00Z"},
    }
    rows = board.recently_closed(handled, FakeRouter())
    assert [r["id"] for r in rows] == ["b", "a"]
    assert rows[0]["title"] == "From topic"       # fallback via known_item
    assert rows[1]["title"] == "Alpha" and rows[1]["action_type"] == "review"


def test_board_reopen_restores_snapshot_to_rail(monkeypatch):
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def __init__(self):
            self.unhandled = None

        def handled(self):
            return {"item-1": {"result": "Closed", "at": "", "item": {"title": "Holdout"}}}

        def unhandle(self, item_id):
            self.unhandled = item_id
            return {"title": "Holdout", "action_type": "review"}

    router = FakeRouter()
    monkeypatch.setattr(appmod, "chat_router", router)
    board._pushed_notifications.clear()
    try:
        response = asyncio.run(appmod.api_board_reopen({"item_id": "item-1"}))
        assert response.status_code == 200
        assert json.loads(response.body) == {"reopened": True, "restored": True}
        assert router.unhandled == "item-1"
        pushed = board._pushed_notifications
        assert pushed and pushed[0]["id"] == "item-1"
        assert pushed[0]["title"] == "Holdout"
        assert pushed[0]["action_type"] == "review"
        assert pushed[0]["new"] is True
    finally:
        board._pushed_notifications.clear()


def test_board_reopen_404_for_item_not_closed(monkeypatch):
    class FakeRouter:
        def record_merges(self, merges):
            return {}

        def handled(self):
            return {}

    monkeypatch.setattr(appmod, "chat_router", FakeRouter())
    response = asyncio.run(appmod.api_board_reopen({"item_id": "nope"}))
    assert response.status_code == 404


def test_assistant_frontend_has_rail_search():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert 'id="search"' in html
    assert "function matchesQuery" in html
    assert "query=searchInput.value.trim().toLowerCase()" in html


def test_assistant_frontend_reviews_and_reopens_closed_items():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "closed=d.document.closed||[]" in html
    assert "Recently closed (" in html
    assert "data-toggle-closed" in html
    assert "data-reopen-id" in html
    assert "function reopenItem" in html


def test_assistant_records_coarse_usage_without_item_content():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()

    assert "fetch('/api/usage'" in html
    for event in (
        "assistant_opened", "item_opened", "chat_sent", "item_closed",
        "item_snoozed", "item_reopened", "item_unsnoozed", "item_pinned",
        "order_changed", "chat_started", "chat_archived", "chat_tab_opened",
    ):
        assert f"trackUsage('{event}'" in html



def test_pending_approvals_are_reoffered_by_item(tmp_path):
    router = cmod.ChatRouter(cmod.SessionMap(tmp_path / "sessions.json"), "/vault")
    router._paused["run-room"] = {
        "item_id": "chat:0123456789ab",
        "action": {"kind": "action", "verb": "Book room", "summary": "Add the Jedi room"},
    }
    assert router.pending_approvals() == {"chat:0123456789ab": [
        {"kind": "action", "verb": "Book room", "summary": "Add the Jedi room", "run_id": "run-room"},
    ]}


def test_assistant_restores_approval_cards_missed_by_the_stream():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "d.pending_approvals" in html
    assert "div.dataset.run=runId" in html
    fn = re.search(r"function syncConversation\(id\)\{.*?\n\}", html, re.S)
    js = _reply_progress_js(html) + fn.group(0) + """
const chatContexts={}, activeId=null;
const shown=new Set(), rendered=[];
const scrollLog=()=>{}, renderHistory=()=>{}, clearQueuedNotes=()=>{};
const CSS={escape:s=>s}, document={createElement:()=>({})};
const renderApproval=(id,ai,run)=>{ rendered.push(run); shown.add(run); };
const log={appendChild(){}, insertAdjacentHTML(){},
  querySelector:sel=>{ const m=sel.match(/data-run="([^"]+)"/); return m&&shown.has(m[1])?{}:null; }};
const convos={a:{log, seeded:true, busy:false, historyCount:0}};
const chatHistories={}, activeChats=new Set();
const pendingApprovals={a:[{run_id:'run-1',kind:'action',summary:'Book room'}]};
syncConversation('a'); syncConversation('a');
process.stdout.write(JSON.stringify(rendered));
"""
    out = subprocess.run([node, "-e", js], text=True, capture_output=True, check=True)
    assert json.loads(out.stdout) == ["run-1"]


def _hold_stream(events):
    hold = cmod.ToolRoundHold()
    return "".join(hold.feed(ev) for ev in events) + hold.finish()


def test_tool_round_hold_drops_progress_before_a_tool_call():
    # Tool boundaries also catch progress text that matches no phrase rule.
    sep, tool = {"kind": "separator", "text": "\n\n"}, {"kind": "tool", "text": ""}
    reply = _hold_stream([
        {"kind": "text", "text": "Still tracing where holdout results "},
        {"kind": "text", "text": "get their segments in the UI code."},
        tool, sep,
        {"kind": "text", "text": "Need sender names for the key messages."},
        tool, sep,
        {"kind": "text", "text": "It sits with XD, not the UI."},
    ])
    assert reply == "It sits with XD, not the UI."


def test_tool_round_hold_keeps_long_answers_streaming_before_a_tool_call():
    answer = "The holdout segment list is defined upstream in 626. " * 4
    hold = cmod.ToolRoundHold()
    assert hold.feed({"kind": "text", "text": answer}) == answer
    assert hold.feed({"kind": "tool", "text": ""}) == ""
    assert hold.feed({"kind": "separator", "text": "\n\n"}) == ""
    assert hold.feed({"kind": "text", "text": "Done."}) == ""
    assert hold.finish() == "\n\nDone."


def test_doc_pane_rereads_the_document_after_a_reply_without_losing_scroll():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    fn = re.search(r"function refreshDocPane\(\)\{.*?\n\}", html, re.S)
    assert fn, "refreshDocPane() not found"
    assert "if(activeId===id) refreshDocPane();" in html
    js = """
let docPaneToken=1;
const body={innerHTML:'<p>old</p>'};
const path={textContent:'drafts/a.md'};
const el={hidden:false,scrollTop:420,querySelector:s=>s==='.md'?body:path};
const document={getElementById:()=>el};
const md=t=>'<p>'+t+'</p>';
let asked='';
const fetch=u=>{ asked=u; return Promise.resolve({ok:true,json:()=>({content:'new'})}); };
""" + fn.group(0) + """
refreshDocPane();
setTimeout(()=>process.stdout.write(JSON.stringify([asked,body.innerHTML,el.scrollTop])),10);
"""
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["/api/vault-document?path=drafts%2Fa.md", "<p>new</p>", 420]


def test_document_page_rereads_on_return_and_keeps_scroll():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "document.html").read_text()
    assert "addEventListener('visibilitychange'" in html
    assert "if(version===shownVersion) return;" in html
    assert "window.scrollTo(0,top);" in html


def test_board_health_names_an_expired_github_signin_from_real_run_summaries():
    lost = [
        "No new wins (GitHub unavailable: token invalid).",
        "GitHub auth is invalid (keyring token), so merged PRs were not checked.",
        "GitHub unavailable (gh auth failed for github.example.com); Teams was a thin search.",
        "Vault gardener: not run. The clone failed because GitHub auth is broken.",
        "GitHub was unavailable because the gh token for github.example.com is invalid.",
    ]
    for text in lost:
        state = {**_sensor("team-wins-watch", status="error"), "last_error": text}
        assert board.board_health([state], now=_NOW)["github_signin_expired"] is True, text
    for text in ("GitHub was unreachable (network error), so merged PRs were not checked.",
                 "Teams not connected - run `msteams login`.",
                 "Jira auth was rejected."):
        state = {**_sensor("team-wins-watch", status="error"), "last_error": text}
        assert board.board_health([state], now=_NOW)["github_signin_expired"] is False, text
    # A later successful run clears it.
    ok = {**_sensor("team-wins-watch"), "last_error": lost[0]}
    assert board.board_health([ok], now=_NOW)["github_signin_expired"] is False
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "h.github_signin_expired" in html


def test_chat_retries_starting_and_names_what_is_missing(monkeypatch):
    starts = []

    async def failing_start():
        starts.append(1)

    monkeypatch.setattr(appmod, "chat_router", None)
    monkeypatch.setattr(appmod, "_start_chat_router", failing_start)
    monkeypatch.setattr(appmod.ai_connections, "load", lambda: {"default": "", "connections": []})
    response = asyncio.run(appmod.api_board_chat({"item_id": "chat:0123456789ab", "message": "hi"}))
    assert response.status_code == 503 and starts == [1]
    assert "Choose an AI connection in Settings" in json.loads(response.body)["error"]


def test_chats_run_at_the_workspace_root_not_the_state_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "chat_router", None)
    monkeypatch.setattr(appmod.paths, "WORKSPACE", tmp_path)
    asyncio.run(appmod._start_chat_router())
    assert appmod.chat_router._vault == str(tmp_path)


def test_setup_card_survives_setup_writing_the_name(monkeypatch):
    monkeypatch.setattr(appmod.ai_backend, "connection_available", lambda: True)
    monkeypatch.setattr(appmod.ai_connections, "get", lambda: {"provider":"anthropic"})
    class Router:
        history = []

        def conversation_history(self, item_id):
            return self.history if item_id == board.SETUP_ITEM_ID else []

    router = Router()
    monkeypatch.setattr(appmod, "chat_router", router)
    named = appmod.profile.Profile(name="Sam Example")
    monkeypatch.setattr(appmod.profile, "load", lambda path=None: named)
    assert board.setup_item(router) is None                      # set up long ago, never via the card
    router.history = [{"role": "user", "text": "hi"}]
    assert board.setup_item(router)["id"] == board.SETUP_ITEM_ID  # mid-setup: keep the card
    monkeypatch.setattr(appmod.profile, "load", lambda path=None: appmod.profile.Profile())
    router.history = []
    assert board.setup_item(router) is not None                  # brand new workspace


def test_new_users_get_example_prompts_that_prefill_but_never_send():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    assert "const EXAMPLES=[" in html and "function examplesHtml(" in html
    assert "/assistant?item=new&amp;ask=${encodeURIComponent(idea.text)}" in html
    assert "examplesHtml()" in html and "examplesHtml('Ideas to start with')" in html
    # Picking an idea fills the composer; nothing in useIdea sends.
    use_idea = re.search(r"function useIdea\(.*?\n\}", html, re.S).group(0)
    assert "input.value=text" in use_idea and "send(" not in use_idea


def test_chats_tab_always_starts_with_new_chat():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    render = re.search(r"function renderChats\(.*?\n\}", html, re.S).group(0)
    assert "newChatRow()" in render and "No chats yet" not in render
    tab = re.search(r"function setRailTab\(.*?\n\}", html, re.S).group(0)
    assert "tab==='chats'&&!isChatId(activeId)" in tab and "openItem(NEW_CHAT)" in tab


def test_chat_ideas_are_validated_and_capped(tmp_path):
    path = tmp_path / "chat-ideas.json"
    assert appmod.load_chat_ideas(path) == {"ideas": [], "generated": None}   # missing file
    path.write_text("{not json")
    assert appmod.load_chat_ideas(path)["ideas"] == []
    ideas = [{"kind": "focus", "label": "This week", "text": "  What matters\n this week?  "},
             "Plain string idea",
             {"kind": "bogus", "text": "Unknown kind keeps the text"},
             {"text": "what matters this week?"},          # duplicate, any case
             {"text": "x" * 241}, {"text": ""}, 42, None]
    ideas += [{"text": f"Idea {n}"} for n in range(20)]
    path.write_text(json.dumps({"generated": "2026-11-14T07:30:00+00:00", "ideas": ideas}))
    loaded = appmod.load_chat_ideas(path)
    assert loaded["generated"] == "2026-11-14T07:30:00+00:00"
    assert len(loaded["ideas"]) == appmod.CHAT_IDEAS_MAX
    assert loaded["ideas"][:3] == [
        {"text": "What matters this week?", "label": "This week", "kind": "focus"},
        {"text": "Plain string idea", "label": "", "kind": ""},
        {"text": "Unknown kind keeps the text", "label": "", "kind": ""},
    ]


def test_chat_ideas_endpoint_reads_the_workspace_file(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    path = tmp_path / "chat-ideas.json"
    path.write_text(json.dumps({"generated": "2026-11-14T07:30:00+00:00", "ideas": [{"kind": "build", "text": "Build a page"}]}))
    monkeypatch.setattr(appmod, "CHAT_IDEAS_FILE", path)
    response = TestClient(appmod.app).get("/api/chat-ideas")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["ideas"] == [{"text": "Build a page", "label": "", "kind": "build"}]


def test_settings_page_offers_colour_schemes():
    from fastapi.testclient import TestClient
    response = TestClient(appmod.app).get("/settings")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert 'id="color-scheme"' in response.text
    for scheme in ('purple', 'slate', 'midnight', 'forest', 'charcoal', 'light'):
        assert f'<option value="{scheme}">' in response.text
    theme = (STATIC / "theme.js").read_text()
    assert "'roosta-theme'" in theme and "data-bs-theme" in theme


def test_colour_schemes_restore_sync_and_keep_legacy_modes():
    if not shutil.which('node'):
        pytest.skip('Node is required for UI checks')
    source = (STATIC / 'theme.js').read_text()
    subprocess.run(['node', '-e', 'const source = ' + json.dumps(source) + ';\n' + """
const assert = require('node:assert/strict');
const vm = require('node:vm');
function load(value, blocked = false) {
  const state = {value, attrs:{}, events:[], listeners:{}};
  const context = {
    localStorage:{
      getItem() { if (blocked) throw Error('disabled'); return state.value; },
      setItem(key, value) { if (blocked) throw Error('disabled'); state.value = value; },
    },
    document:{documentElement:{setAttribute(key, value) { state.attrs[key] = value; }}},
    CustomEvent:class { constructor(type, options) { this.detail = options.detail; } },
    window:{
      addEventListener(type, callback) { state.listeners[type] = callback; },
      dispatchEvent(event) { state.events.push(event.detail); },
    },
  };
  vm.runInNewContext(source, context);
  return {...state, state, theme:context.window.roostaTheme};
}
for (const [saved, scheme, mode] of [
  [null,'purple','dark'], ['purple','purple','dark'], ['slate','slate','dark'],
  ['midnight','midnight','dark'], ['forest','forest','dark'], ['charcoal','charcoal','dark'],
  ['dark','slate','dark'], ['light','light','light'], ['unknown','purple','dark'],
]) {
  const app = load(saved);
  assert.equal(app.theme.scheme(), scheme);
  assert.equal(app.theme.get(), mode);
  assert.equal(app.attrs['data-roosta-scheme'], scheme);
  assert.equal(app.attrs['data-bs-theme'], mode);
  assert.equal(app.events.at(-1), mode);
}
const app = load(null);
app.theme.set('slate');
assert.equal(app.state.value, 'slate');
assert.equal(load(app.state.value).theme.scheme(), 'slate');
app.state.value = 'light';
app.listeners.storage({key:'other-preference'});
assert.equal(app.attrs['data-bs-theme'], 'dark');
app.listeners.storage({key:'roosta-theme'});
assert.equal(app.attrs['data-roosta-scheme'], 'light');
assert.equal(app.events.at(-1), 'light');
app.theme.set('unknown');
assert.equal(app.state.value, 'light');
app.theme.set('dark');
assert.equal(app.attrs['data-roosta-scheme'], 'slate');
const blocked = load(null, true);
blocked.theme.set('light');
assert.equal(blocked.attrs['data-bs-theme'], 'light');
assert.equal(blocked.theme.scheme(), 'light');
"""], check=True)


def test_actor_does_not_close_just_because_it_edited_the_workspace():
    skill = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "skills" / "actor" / "SKILL.md").read_text()
    assert "You changed the workspace:** `<<<DONE" not in skill
    assert "## Closing an item" in skill
    assert "End with `<<<DONE>>>` and `acted: true`." not in skill


def test_actor_acts_on_workspace_requests_and_points_at_the_approval_button():
    skill = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "skills" / "actor" / "SKILL.md").read_text()
    assert "A workspace change the user asks for is already approved." in skill
    assert "Never ask the same thing twice." in skill
    assert "Only the button approves." in skill
    assert "Don't phrase the pause as a question" in skill


def test_board_does_not_announce_a_close_on_standing_threads():
    html = (Path(__file__).resolve().parent.parent / "src" / "roosta" / "static" / "assistant.html").read_text()
    handler = html[html.index("else if(ev.kind==='done'){"):]
    handler = handler[:handler.index("else if(ev.kind==='error')")]
    assert "!isChatId(id)" in handler
    assert "person:" in handler


def test_carry_forward_fills_id_only_keep_stubs():
    previous = {"items": [{"id": "a", "title": "Old title", "why": "Because",
                           "links": [{"label": "T", "url": "https://x.test"}]},
                          {"id": "b", "title": "B", "why": "Old why"}]}
    details = {"items": [{"id": "a", "new": False},
                         {"id": "b", "title": "B", "why": "New why"},
                         {"id": "c", "new": True}]}
    board.carry_forward_board_items(details, previous)
    a, b, c = details["items"]
    assert a["title"] == "Old title" and a["why"] == "Because" and a["links"]
    assert b["why"] == "New why"
    assert "title" not in c


def test_carry_forward_tolerates_garbage():
    board.carry_forward_board_items(None, {"items": []})
    board.carry_forward_board_items({"items": [1, {"id": "a"}]}, {"items": "bad"})



def test_remove_task_drops_only_that_block(tmp_path):
    path = tmp_path / "tasks.yaml"
    path.write_text(
        "# schedule\ntasks:\n  - id: a\n    skill: a\n    interval: 60\n"
        "  # b runs hourly\n  - id: b\n    skill: b\n  - id: c\n    skill: c\n"
    )
    task_config.remove_task(path, "a")
    assert path.read_text() == "# schedule\ntasks:\n  # b runs hourly\n  - id: b\n    skill: b\n  - id: c\n    skill: c\n"
    task_config.remove_task(path, "c")
    assert [t["id"] for t in appmod.yaml.safe_load(path.read_text())["tasks"]] == ["b"]
    with pytest.raises(ValueError):
        task_config.remove_task(path, "missing")


def test_remove_worker_preserves_quoted_id_then_loads_empty_schedule(tmp_path, monkeypatch):
    path = tmp_path / "tasks.yaml"
    monkeypatch.setattr(task_config.paths, "TASKS_FILE", path)
    other = '  # second worker\n  - skill: actor\n    id: "second"\n'
    footer = "settings: {keep: true}\n"
    path.write_text("tasks:\n  - id: first\n    skill: actor\n" + other + footer)
    task_config.remove_task(path, "first")
    assert path.read_text() == "tasks:\n" + other + footer
    task_config.remove_task(path, "second")
    assert appmod.yaml.safe_load(path.read_text()) == {"tasks": [], "settings": {"keep": True}}
    assert task_config.load_tasks() == []


def test_chat_retrieval_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "chat_router", None)
    monkeypatch.setattr(appmod.runner, "get_state", lambda _id: {})
    monkeypatch.setattr(appmod.runner, "get_states", lambda: [])
    store = tmp_path / "history.json"
    archive = tmp_path / "archived.json"
    monkeypatch.setattr(appmod, "CHAT_HISTORY_FILE", store)
    monkeypatch.setattr(appmod, "ARCHIVED_CHATS_FILE", archive)

    def turn(text, at):
        return [{"role": "user", "text": text, "at": at}]

    doc = 'doc:notes/Q&A, "next".md'
    hire = "hire:aaaaaaaaaaaa"
    general = "chat:aaaaaaaaaaaa"
    worker = "worker:writer"
    active = "worker:busy"
    unsent = "chat:bbbbbbbbbbbb"
    histories = {f"chat:{i:012x}": turn(f"Question {i}", "2026-02-01") for i in range(170)}
    histories.update({doc: turn("Discuss", "2026-01"), hire: turn("Schedule reports", "2026-01"),
                      general: turn("A question", "2026-01"), worker: turn("How are you?", "2026-01"),
                      active: turn("Later reply", "2026-04")})
    store.write_text(json.dumps(histories))
    original = store.read_bytes()
    legacy = {f"chat:{i:012x}": "2026-02-02" for i in range(60)}
    legacy.update({hire: "2026-03-03", general: "2026-03-02", worker: "2026-03-01",
                   active: "2026-03-01", "item-1": "2026-03-01"})
    archive.write_text(json.dumps(legacy))

    def recent():
        return json.loads(asyncio.run(appmod.api_chats_archived()).body)

    close = appmod.api_chats_archive
    assert json.loads(asyncio.run(close({"item_id": unsent})).body) == {"archived": False}
    assert unsent not in appmod.archived_chats()
    asyncio.run(close({"item_id": doc, "title": "Quarterly <review>"}))
    rows = recent()
    assert len(rows) == 50
    assert [(r["id"], r["title"]) for r in rows[:4]] == [
        (doc, "Quarterly <review>"), (hire, "New worker: Schedule reports"),
        (general, "A question"), (worker, "1:1 with writer")]
    assert active not in {r["id"] for r in rows}
    assert doc not in {r["id"] for r in chat_items.chat_list(histories, {})}
    restore = appmod.api_chats_restore
    assert asyncio.run(restore({"item_id": "item-1"})).status_code == 400
    assert asyncio.run(restore({"item_id": unsent})).status_code == 404
    assert asyncio.run(restore({"item_id": doc})).status_code == 200
    assert doc not in {r["id"] for r in recent()}
    # Fresh readers, as after a restart. Messages and their timestamps are byte-for-byte intact.
    assert chat_items.chat_list(histories, appmod.archived_chats())[0]["id"] == doc
    board_response = asyncio.run(appmod.api_board(thread=[doc]))
    assert json.loads(board_response.body)["chat_histories"][doc] == histories[doc]
    assert store.read_bytes() == original
    asyncio.run(close({"item_id": doc}))
    assert recent()[0]["title"] == doc.removeprefix("doc:")
    archive.write_text("{broken")
    with pytest.raises(ValueError):
        asyncio.run(close({"item_id": doc}))
    assert archive.read_text() == "{broken"


def test_chat_retrieval_controls():
    html = (STATIC_DIR / "assistant.html").read_text()
    settings = (STATIC_DIR / "settings.html").read_text()
    js = (html[html.index("async function archiveChat"):html.index("function itemById")]
          + html[html.index("function showClosedNotice"):html.index("let items=[]")]
          + settings[settings.index("async function loadClosedChats"):settings.index("\nloadClosedChats();")])
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    subprocess.run([node, "-e", js + r"""
const assert=require('node:assert/strict');
class Element {
  constructor(){ this.children=[]; this.parts={}; }
  querySelector(s){ return this.parts[s]??=new Element(); }
  appendChild(e){ this.children.push(e); if(e.id) elements[e.id]=e; return e; }
  append(...es){ es.forEach(e=>this.appendChild(e)); }
  replaceChildren(...children){ this.children=children; }
  setAttribute(k,v){ this[k]=v; }
  getAttribute(k){ return this[k]; }
  remove(){ this.removed=true; }
}
const elements={},document={getElementById:id=>elements[id],createElement:()=>new Element(),body:new Element()};
const id='doc:notes/u & "v",w.md', other='worker:alice', title='<hello>', NEW_CHAT='new';
const docEditor={leave:()=>true};
let activeId=other,chats=[{id},{id:other}],ok=true,archived=true,destination='';
const location={assign:url=>destination=url}, trackUsage=()=>{}, renderRail=()=>{}, load=async()=>{};
const chatItem=()=>({title}),openItem=id=>activeId=id,esc=s=>s.replaceAll('<','&lt;');
let closed=[{id,title}];
const calls=[],fetch=async(url,options)=>{
  calls.push([url,options&&JSON.parse(options.body)]);
  return {ok,json:async()=>url.endsWith('/archived')?closed:{archived}};
};
const timers=[], setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;},clearTimeout=()=>{};
const notice=()=>elements['closed-notices'].children.at(-1);
(async()=>{
  await archiveChat(id);
  assert.equal(activeId,other);
  assert.deepEqual(chats,[{id:other}]);
  assert.ok(notice().innerHTML.includes('&lt;hello>'));
  assert.equal(timers.at(-1).ms,10000);
  timers.at(-1).fn(); assert.ok(notice().removed);
  await archiveChat(id);
  await notice().querySelector('.toast-body').children[0].onclick();
  assert.deepEqual(calls.at(-1),['/api/chats/restore',{item_id:id}]);
  assert.equal(activeId,id);
  await archiveChat(id); ok=false;
  await notice().querySelector('.toast-body').children[0].onclick();
  assert.equal(activeId,NEW_CHAT);
  assert.ok(notice().innerHTML.includes('Could not restore'));
  chats=[{id}]; await archiveChat(id); assert.deepEqual(chats,[{id}]);
  assert.ok(notice().innerHTML.includes('Could not close'));
  ok=true; archived=false; const last=notice(); await archiveChat(id); assert.equal(notice(),last);
  const list=elements['closed-chats']=new Element(),status=elements['closed-chats-status']=new Element();
  const footer=elements['closed-chats-footer']=new Element();
  const toggle=elements['closed-chats-toggle']=new Element();
  await loadClosedChats();
  assert.equal(footer.hidden,true);
  const [name,button]=list.children[0].children;
  assert.equal(name.textContent,title); assert.equal(button['aria-label'],'Restore '+title);
  ok=false; await button.onclick(); assert.equal(destination,''); assert.equal(button.disabled,false);
  assert.match(status.textContent,/Could not restore/);
  ok=true; await button.onclick(); assert.equal(new URL(destination,'http://localhost').searchParams.get('item'),id);
  closed=Array.from({length:55},(_,i)=>({id:'chat-'+i,title:'Chat '+i}));
  const visibleTitles=()=>list.children.map(row=>row.children[0].textContent);
  const first=n=>closed.slice(0,n).map(chat=>chat.title);
  await loadClosedChats();
  assert.equal(footer.hidden,false); assert.deepEqual(visibleTitles(),first(10));
  toggle.onclick(); assert.deepEqual(visibleTitles(),first(50)); assert.equal(toggle['aria-expanded'],'true');
  assert.equal(toggle.textContent,'Show less');
  await list.children.at(-1).children[1].onclick();
  assert.deepEqual(calls.at(-1),['/api/chats/restore',{item_id:'chat-49'}]);
  toggle.onclick(); assert.deepEqual(visibleTitles(),first(10)); assert.equal(toggle.textContent,'Show more');
  toggle.onclick(); await loadClosedChats();
  assert.deepEqual(visibleTitles(),first(10)); assert.equal(toggle['aria-expanded'],'false');
  closed=closed.slice(0,10); await loadClosedChats(); assert.equal(footer.hidden,true);
  closed=[]; await loadClosedChats(); assert.equal(status.textContent,'No recently closed chats.');
  ok=false; await loadClosedChats(); assert.match(status.textContent,/Could not load/);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""], check=True)
