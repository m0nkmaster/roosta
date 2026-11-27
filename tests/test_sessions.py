import json
import sys
from pathlib import Path


from roosta import app as appmod
from roosta.cursor_sessions import read_cursor_transcript, valid_session_id


def test_valid_session_id_accepts_cursor_chat_uuid():
    assert valid_session_id("019bf2f4-9c27-49a5-8c09-707860e58585")
    assert not valid_session_id("../etc/passwd")
    assert not valid_session_id("")


def test_read_cursor_transcript_parses_user_and_assistant_turns(tmp_path, monkeypatch):
    session_id = "019bf2f4-9c27-49a5-8c09-707860e58585"
    root = tmp_path / "agent-transcripts" / session_id
    root.mkdir(parents=True)
    lines = [
        {"role": "user", "message": {"content": [
            {"type": "text", "text": "<user_query>Run the gardener</user_query>"},
        ]}},
        {"role": "assistant", "message": {"content": [
            {"type": "text", "text": "Done."},
        ]}},
    ]
    (root / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "roosta.cursor_sessions.cursor_transcript_dir",
        lambda workspace=None: tmp_path / "agent-transcripts",
    )

    turns = read_cursor_transcript(session_id)
    assert turns == [
        {"role": "user", "text": "Run the gardener"},
        {"role": "assistant", "text": "Done."},
    ]


def test_activity_transcript_endpoint_returns_turns(tmp_path, monkeypatch):
    async def scenario():
        from httpx import ASGITransport, AsyncClient

        session_id = "019bf2f4-9c27-49a5-8c09-707860e58585"
        eid = appmod.activity.start("pass", "skill", "manual")
        appmod.activity.set_session(eid, session_id)

        monkeypatch.setattr(
            appmod,
            "read_cursor_transcript",
            lambda sid: [{"role": "assistant", "text": "hello"}] if sid == session_id else [],
        )

        transport = ASGITransport(app=appmod.app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.get(f"/api/activity/{eid}/transcript")
            assert response.status_code == 200
            body = response.json()
            assert body["session_id"] == session_id
            assert body["turns"] == [{"role": "assistant", "text": "hello"}]
            assert f"agent --resume {session_id}" in body["resume_command"]

    import asyncio
    asyncio.run(scenario())


def test_read_claude_transcript_keeps_prompt_and_replies_only(tmp_path):
    from roosta.claude_code import read_claude_transcript

    session_id = "70734d05-4cb8-41bc-9e2a-712d13d75a9a"
    project = tmp_path / "-Users-sam-workspace"
    project.mkdir()
    lines = [
        {"type": "user", "message": {"role": "user", "content": "Run the assistant skill"}},
        {"type": "user", "isMeta": True, "message": {"content": [{"type": "text", "text": "meta"}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
        {"type": "attachment"},
    ]
    (project / f"{session_id}.jsonl").write_text("\n".join(json.dumps(line) for line in lines))

    assert read_claude_transcript(session_id, tmp_path) == [
        {"role": "user", "text": "Run the assistant skill"},
        {"role": "assistant", "text": "Done."},
    ]
    assert read_claude_transcript("../etc/passwd", tmp_path) == []


def test_claude_activity_transcript_returns_outcome_and_claude_resume(monkeypatch):
    async def scenario():
        from httpx import ASGITransport, AsyncClient

        session_id = "70734d05-4cb8-41bc-9e2a-712d13d75a9a"
        eid = appmod.activity.start("skill", "assistant", "scheduled", backend="claude")
        appmod.activity.set_session(eid, session_id)
        appmod.activity.finish(eid, "success")
        final = '<task-output>{"summary": "4 items raised", "status": "success"}</task-output>'
        monkeypatch.setattr(
            appmod, "read_claude_transcript",
            lambda sid: [{"role": "assistant", "text": final}] if sid == session_id else [],
        )

        transport = ASGITransport(app=appmod.app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            body = (await client.get(f"/api/activity/{eid}/transcript")).json()
        assert body["outcome"] == "4 items raised"
        assert f"claude --resume {session_id}" in body["resume_command"]
        assert "CURSOR_CONFIG_DIR" not in body["resume_command"]

    import asyncio
    asyncio.run(scenario())


def test_activity_static_routes_precede_param_route():
    """`/api/activity/stream` must register before `{activity_id}` or SSE 404s."""
    activity_paths = [
        getattr(route, "path", "")
        for route in appmod.app.router.routes
        if getattr(route, "path", "").startswith("/api/activity")
    ]
    assert activity_paths.index("/api/activity/stream") < activity_paths.index(
        "/api/activity/{activity_id}"
    )


def test_activity_rows_from_tests_stay_out_of_the_live_feed(isolated_activity_log):
    live = appmod.DASHBOARD_ROOT / "cache" / "activity.jsonl"
    before = live.stat().st_size if live.exists() else 0

    eid = appmod.activity.start("skill", "isolation-check", "manual")
    appmod.activity.finish(eid)

    assert "isolation-check" in isolated_activity_log.read_text()
    after = live.stat().st_size if live.exists() else 0
    assert after == before or "isolation-check" not in live.read_text()[before:]


def test_learner_lists_assistant_chats_by_their_own_latest_message(tmp_path):
    import subprocess

    helper = Path(appmod.__file__).parent / "skills" / "workspace-learner" / "sessions.py"
    history = tmp_path / "chat-history.json"
    history.write_text(json.dumps({
        "chat:old": [
            {"role": "user", "text": "old question", "at": "2026-11-15T00:00:00+00:00"},
            {"role": "assistant", "text": "old answer", "at": "2026-11-15T00:01:00+00:00"},
        ],
        "chat:new": [
            {"role": "user", "text": "new question", "at": "2026-11-17T23:02:00+00:00"},
            {"role": "assistant", "text": "new answer", "at": "2026-11-17T23:04:00Z"},
        ],
    }), encoding="utf-8")
    since = 1794956337000  # 2026-11-17 22:58:57 UTC; the file mtime is now, after both chats
    out = subprocess.run(
        [sys.executable, str(helper), "list", str(since), "--source", "assistant", "--json"],
        env={"ASSISTANT_HISTORY": str(history), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    ).stdout
    rows = json.loads(out)
    assert [row["id"] for row in rows] == ["chat:new"]
    assert rows[0]["timestamp_utc"] == "2026-11-17 23:04"


def _queued(prompt, **fields):
    return {"type": "attachment", "attachment": {
        "type": "queued_command", "humanTurn": True, "prompt": prompt, **fields,
    }}


def _write_cc(path, records):
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")


def _cc_cli(store, *args):
    import subprocess

    helper = Path(appmod.__file__).parent / "skills" / "workspace-learner" / "sessions.py"
    return subprocess.run(
        [sys.executable, str(helper), *args], env={"CLAUDE_PROJECTS_DIR": str(store)},
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()


def test_learner_cc_queued_corrections_keep_order_and_identity(tmp_path):
    repeat = {"type": "user", "message": {"content": "Try again"}}
    _write_cc(tmp_path / "chat.jsonl", [
        {"type": "user", "message": {"content": "Start"}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Checking"}, {"type": "tool_use", "name": "Read"},
        ]}},
        _queued([{"type": "text", "text": "Try again"}], source_uuid="first"),
        {"type": "assistant", "message": {"content": "Will do"}},
        {**repeat, "uuid": "first"},
        {**repeat, "uuid": "second"},
        _queued("Try again", source_uuid="second"),
        _queued("Try again"),
        repeat,
    ])
    expected = ["USER: Start", "ASSISTANT: Checking", "USER: Try again", "ASSISTANT: Will do",
                "USER: Try again", "USER: Try again", "USER: Try again"]
    assert _cc_cli(tmp_path, "transcript", "cc:chat") == expected
    assert _cc_cli(tmp_path, "transcript", "cc:chat", "--tools") == [
        *expected, "--- TOOL CALLS (tool | status | input) ---", "Read | called | {}",
    ]


def test_learner_cc_ignores_nonhuman_and_malformed_attachments(tmp_path):
    _write_cc(tmp_path / "noise.jsonl", [
        {**_queued("side"), "isSidechain": True}, {**_queued("meta"), "isMeta": True},
        _queued("meta", isMeta=True), _queued("other", type="file"),
        _queued("system", humanTurn=False), _queued("system", origin={"kind": "system"}),
        _queued("notice", commandMode="task-notification"), _queued("  "),
        {"type": "attachment", "attachment": []}, _queued({"unexpected": "value"}),
        _queued([None, {"type": "text", "text": 1}, {"type": "tool_use", "name": "hidden"}]),
        {"type": "assistant", "message": {"content": "Still scanning"}, "timestamp": "2026-11-17"},
    ])
    assert _cc_cli(tmp_path, "transcript", "cc:noise", "--tools") == ["ASSISTANT: Still scanning"]
    assert _cc_cli(tmp_path, "list", "0", "--source", "cc", "--json") == ["[]"]


def test_learner_cc_lists_queued_human_by_embedded_timestamp_and_filters_runners(tmp_path):
    reply = {"type": "assistant", "message": {"content": "Okay"}}
    queued = {**_queued("Change direction"), "timestamp": "2026-11-17T23:04:00Z"}
    _write_cc(tmp_path / "chat.jsonl", [reply, queued])
    for i, marker in enumerate((
        "running as an unattended background task.",
        "running as an unattended scheduled background task.",
        "triggered Run now on the skill runner.",
    )):
        for kind, record in (("queued", _queued(marker)), ("user", {"type": "user", "message": {"content": marker}})):
            _write_cc(tmp_path / f"{kind}-{i}.jsonl", [queued, record, reply])

    rows = json.loads("\n".join(_cc_cli(tmp_path, "list", "1794956337000", "--source", "cc", "--json")))
    assert [(r["id"], r["title"], r["timestamp_utc"]) for r in rows] == [
        ("chat", "Change direction", "2026-11-17 23:04"),
    ]


def test_learner_cc_skips_transcripts_not_written_since_the_window(tmp_path):
    import os

    reply = {"type": "assistant", "message": {"content": "Okay"}}
    queued = {**_queued("Change direction"), "timestamp": "2026-11-17T23:04:00Z"}
    stale = tmp_path / "stale.jsonl"
    _write_cc(stale, [reply, queued])
    _write_cc(tmp_path / "fresh.jsonl", [reply, queued])
    os.utime(stale, (1, 1))

    rows = json.loads("\n".join(_cc_cli(tmp_path, "list", "1794956337000", "--source", "cc", "--json")))
    assert [r["id"] for r in rows] == ["fresh"]
