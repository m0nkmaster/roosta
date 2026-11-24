import asyncio, json, re, shutil, subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from roosta import chat_items
from roosta import app as appmod
from roosta import attachments
from roosta import chat as cmod

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
STATIC = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"


@pytest.mark.parametrize("raw, expected", [
    ("../../etc/passwd", "passwd"),
    ("C:\\x\\a b.png", "a b.png"),
    (".env", "env"),
    ("", "file"),
    (None, "file"),
    (42, "file"),
    ("...", "file"),
])
def test_safe_name(raw, expected):
    assert attachments.safe_name(raw) == expected


def test_safe_name_caps_length_and_strips_unsafe_characters():
    long = attachments.safe_name("a" * 300 + ".png")
    assert len(long) <= 100 and long.endswith(".png")
    clean = attachments.safe_name("a\x00<b>.txt")
    assert clean.endswith(".txt") and not re.search(r"[\x00-\x1f<>]", clean)


def test_round_trip_and_image_sniffing(tmp_path):
    png = attachments.save(tmp_path, "chat:0123456789ab", "shot.png", PNG)
    text = attachments.save(tmp_path, "chat:0123456789ab", "fake.png", b"just text")
    assert png["image"] is True and text["image"] is False
    assert png["name"] == "shot.png" and png["size"] == len(PNG)
    files = attachments.describe(tmp_path, "chat:0123456789ab", [png["id"], text["id"], png["id"]])
    assert [f["name"] for f in files] == ["shot.png", "fake.png"]
    assert [f["image"] for f in files] == [True, False]
    assert Path(files[0]["path"]).read_bytes() == PNG
    assert Path(files[0]["path"]).is_relative_to(tmp_path.resolve())


@pytest.mark.parametrize("data, head", [
    (b"\xff\xd8\xff\xe0", "image/jpeg"), (b"GIF89a....", "image/gif"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"), (b"<svg></svg>", ""), (b"", ""),
])
def test_image_type_uses_magic_bytes_only(data, head):
    assert attachments.image_type(data) == head


def test_describe_enforces_message_limit_and_list_shape(tmp_path):
    ids = [attachments.save(tmp_path, "c", f"f{i}.txt", b"x")["id"] for i in range(9)]
    assert len(attachments.describe(tmp_path, "c", ids[:8])) == 8
    with pytest.raises(ValueError):
        attachments.describe(tmp_path, "c", ids)
    with pytest.raises(ValueError):
        attachments.describe(tmp_path, "c", "abc")
    with pytest.raises(ValueError):
        attachments.describe(tmp_path, "c", [{"a": 1}])


def test_save_limits(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="empty"):
        attachments.save(tmp_path, "c", "a.txt", b"")
    with pytest.raises(ValueError):
        attachments.save(tmp_path, "", "a.txt", b"x")
    with pytest.raises(ValueError):
        attachments.save(tmp_path, "x" * 521, "a.txt", b"x")
    monkeypatch.setattr(attachments, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(ValueError, match="20 MB"):
        attachments.save(tmp_path, "c", "a.txt", b"12345")
    monkeypatch.setattr(attachments, "MAX_CHAT_UPLOAD_BYTES", 6)
    attachments.save(tmp_path, "c", "a.txt", b"1234")
    with pytest.raises(ValueError, match="200 MB"):
        attachments.save(tmp_path, "c", "b.txt", b"123")
    attachments.save(tmp_path, "other", "b.txt", b"123")


def test_resolve_rejects_unsafe_ids_and_foreign_or_symlinked_files(tmp_path):
    saved = attachments.save(tmp_path, "c", "a.txt", b"x")
    for bad in ["../x", "zzzzzzzzzzzz", None, 12, saved["id"] + "0", "ABCDEF012345"]:
        with pytest.raises(ValueError):
            attachments.resolve(tmp_path, "c", bad)
    with pytest.raises(FileNotFoundError):
        attachments.resolve(tmp_path, "other", saved["id"])
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (attachments.upload_dir(tmp_path, "c") / "abcdef012345-link.txt").symlink_to(outside)
    with pytest.raises(ValueError):
        attachments.resolve(tmp_path, "c", "abcdef012345")


def test_path_like_item_ids_get_distinct_directories_inside_root(tmp_path):
    first = attachments.upload_dir(tmp_path, "doc:a/b.md")
    second = attachments.upload_dir(tmp_path, "doc:a_b.md")
    assert first != second
    for directory in (first, second):
        assert directory.parent == tmp_path and "/" not in directory.name


def test_remove_deletes_only_that_conversation(tmp_path):
    attachments.save(tmp_path, "a", "a.txt", b"x")
    keep = attachments.save(tmp_path, "b", "b.txt", b"x")
    attachments.remove(tmp_path, "a")
    attachments.remove(tmp_path, "never-existed")
    assert not attachments.upload_dir(tmp_path, "a").exists()
    assert attachments.resolve(tmp_path, "b", keep["id"]).exists()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "UPLOADS_DIR", tmp_path / "uploads")
    return TestClient(appmod.app)


def upload(client, name="shot.png", data=PNG, item_id="chat:0123456789ab", headers=None):
    return client.post("/api/board/chat/upload", params={"item_id": item_id, "name": name}, content=data,
                       headers={"content-type": "application/octet-stream", **(headers or {})})


def test_upload_endpoint_stores_a_file(client):
    response = upload(client)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "shot.png" and body["image"] is True and body["size"] == len(PNG)
    assert re.fullmatch(r"[0-9a-f]{12}", body["id"])


def test_upload_endpoint_rejects_oversize_and_bad_requests(client, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_UPLOAD_BYTES", 8)
    big = upload(client, data=b"x" * 9)
    assert big.status_code == 413 and "20 MB" in big.json()["error"]
    assert upload(client, item_id="").status_code == 400
    assert upload(client, item_id="x" * 521).status_code == 400
    assert upload(client, data=b"").status_code == 400


def test_upload_endpoint_refuses_other_sites(client):
    assert upload(client, headers={"origin": "https://evil.example"}).status_code == 403
    assert upload(client, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert upload(client, headers={"origin": "http://testserver"}).status_code == 200


def test_download_serves_images_inline_and_everything_else_as_attachment(client):
    item = "chat:0123456789ab"
    image = upload(client).json()
    page = upload(client, "evil.html", b"<script>alert(1)</script>").json()
    svg = upload(client, "logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>").json()
    fake = upload(client, "pic.png", b"<html>not a png</html>").json()

    served = client.get(f"/api/board/chat/upload/{image['id']}", params={"item_id": item})
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["cache-control"] == "private, max-age=3600"
    for stored in (page, svg, fake):
        response = client.get(f"/api/board/chat/upload/{stored['id']}", params={"item_id": item})
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith("attachment")
        assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/board/chat/upload/{image['id']}", params={"item_id": "chat:other"}).status_code == 404
    assert client.get("/api/board/chat/upload/abcdef012345", params={"item_id": item}).status_code == 404
    assert client.get("/api/board/chat/upload/not-an-id", params={"item_id": item}).status_code == 400


class RecordingRouter:
    def __init__(self):
        self.turns = []

    def record_merges(self, merges):
        return {}

    def start_turn(self, item_id, item, message):
        self.turns.append((item_id, item, message))
        events = asyncio.Queue()
        events.put_nowait({"kind": "_close"})
        return cmod.TurnHandle(events=events)


@pytest.fixture
def chat_env(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(appmod.paths, "WORKSPACE", vault)
    monkeypatch.setattr(appmod, "UPLOADS_DIR", vault / "uploads")
    router = RecordingRouter()
    monkeypatch.setattr(appmod, "chat_router", router)
    monkeypatch.setattr(appmod, "setup_item", lambda *_: None)  # AI is connected
    return router


def send_chat(body):
    async def call():
        response = await appmod.api_board_chat(body)
        if getattr(response, "body_iterator", None):
            [chunk async for chunk in response.body_iterator]
        return response
    return asyncio.run(call())


def test_chat_passes_uploaded_files_to_the_turn(chat_env):
    item_id = "chat:0123456789ab"
    saved = attachments.save(appmod.UPLOADS_DIR, item_id, "shot.png", PNG)
    before = dict(chat_items.GENERAL_CHAT_ITEM)
    response = send_chat({"item_id": item_id, "message": "", "uploads": [saved["id"]]})
    assert response.status_code == 200
    (turn_id, item, message), = chat_env.turns
    assert turn_id == item_id and message == ""
    (upload_info,) = item["uploaded_files"]
    assert upload_info["name"] == "shot.png" and upload_info["image"] is True
    assert (appmod.paths.WORKSPACE / upload_info["path"]).read_bytes() == PNG
    assert not Path(upload_info["path"]).is_absolute()
    assert chat_items.GENERAL_CHAT_ITEM == before and "uploaded_files" not in chat_items.GENERAL_CHAT_ITEM


def test_chat_rejects_bad_uploads_without_starting_a_turn(chat_env):
    item_id = "chat:0123456789ab"
    saved = attachments.save(appmod.UPLOADS_DIR, item_id, "a.txt", b"x")
    for uploads in (["abcdef012345"], [saved["id"]] * 9, [str(i).zfill(12) for i in range(9)], "nope", [None]):
        response = send_chat({"item_id": item_id, "message": "hi", "uploads": uploads})
        assert response.status_code == 400, uploads
    other = send_chat({"item_id": "chat:ba9876543210", "message": "hi", "uploads": [saved["id"]]})
    assert other.status_code == 400
    assert chat_env.turns == []


def test_chat_without_uploads_is_unchanged(chat_env):
    send_chat({"item_id": "chat:0123456789ab", "message": "hi"})
    assert "uploaded_files" not in chat_env.turns[0][1]
    send_chat({"item_id": "chat:0123456789ab", "message": "hi", "uploads": []})
    assert "uploaded_files" not in chat_env.turns[1][1]


def test_firing_a_worker_removes_its_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "UPLOADS_DIR", tmp_path / "uploads")
    forgotten = []
    monkeypatch.setattr(appmod, "chat_router", SimpleNamespace(forget=forgotten.append))
    monkeypatch.setattr(appmod.runner, "remove", lambda task_id: True)
    item_id = f"{chat_items.WORKER_CHAT_PREFIX}scout"
    attachments.save(appmod.UPLOADS_DIR, item_id, "a.txt", b"x")
    kept = attachments.save(appmod.UPLOADS_DIR, "chat:0123456789ab", "a.txt", b"x")
    assert asyncio.run(appmod.api_task_delete("scout")).status_code == 200
    assert forgotten == [item_id]
    assert not attachments.upload_dir(appmod.UPLOADS_DIR, item_id).exists()
    assert attachments.resolve(appmod.UPLOADS_DIR, "chat:0123456789ab", kept["id"]).exists()


def test_history_store_keeps_attachment_only_turns_and_never_paths(tmp_path):
    store = cmod.ConversationHistoryStore(tmp_path / "history.json")
    files = [{"id": "0123456789ab", "name": "shot.png", "size": 12, "image": True, "path": "/secret/shot.png"}]
    store.append("c", "user", "", files)
    store.append("c", "assistant", "", files)
    store.append("c", "user", "")
    (entry,) = store.read("c")
    assert entry["role"] == "user" and entry["text"] == ""
    assert entry["attachments"] == [{"id": "0123456789ab", "name": "shot.png", "size": 12, "image": True}]
    assert "/secret" not in (tmp_path / "history.json").read_text()


def test_history_store_drops_malformed_attachments(tmp_path):
    path = tmp_path / "history.json"
    good = {"id": "0123456789ab", "name": "n" * 300, "size": -5, "image": "yes"}
    path.write_text(json.dumps({"c": [
        {"role": "user", "text": "", "attachments": [good, {"id": "../x", "name": "a"}, "junk", {"id": "0123456789ab"}]},
        {"role": "user", "text": "", "attachments": "bad"},
        {"role": "user", "text": "kept", "attachments": [{"id": "zz", "name": "a"}]},
        {"role": "assistant", "text": "reply", "attachments": [good]},
    ]}))
    entries = cmod.ConversationHistoryStore(path).read("c")
    assert [e["text"] for e in entries] == ["", "kept", "reply"]
    assert entries[0]["attachments"] == [{"id": "0123456789ab", "name": "n" * 100, "size": 0, "image": False}]
    assert "attachments" not in entries[1] and "attachments" not in entries[2]


def test_chat_list_preview_falls_back_to_the_file_name():
    at = "2026-11-16T10:00:00+00:00"
    attached = {"role": "user", "text": "", "at": at,
                "attachments": [{"id": "0123456789ab", "name": "shot.png", "size": 1, "image": True}]}
    rows = chat_items.chat_list({"chat:0123456789ab": [attached],
                             "chat:ba9876543210": [{**attached, "text": "Look at this"}]}, {})
    previews = {row["id"]: row["preview"] for row in rows}
    assert previews == {"chat:0123456789ab": "shot.png", "chat:ba9876543210": "Look at this"}


def test_run_turn_records_attachments_and_prompts_with_the_path(monkeypatch, tmp_path, fake_chat_connection):
    captured = {}


    class FakeProcess:
        returncode = 0

        def __init__(self):
            async def lines():
                event = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Nice screenshot."}]},
                         "timestamp_ms": 1}
                yield (json.dumps(event) + "\n").encode()
            self.stdout = lines()

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        return FakeProcess()

    monkeypatch.setattr(cmod.asyncio, "create_subprocess_exec", fake_exec)
    history = cmod.ConversationHistoryStore(tmp_path / "chat-history.json")
    router = cmod.ChatRouter(cmod.SessionMap(tmp_path / "sessions.json"), "/vault",
                             persistent_history=history)
    item = {"id": "item-1", "uploaded_files": [
        {"id": "0123456789ab", "name": "shot.png", "size": 12, "image": True,
         "path": "uploads-test/0123456789ab-shot.png"}]}

    async def run():
        return [event async for event in router.run_turn("item-1", item, "")]

    asyncio.run(run())
    rows = history.read("item-1")
    assert rows[0]["role"] == "user" and rows[0]["text"] == ""
    assert rows[0]["attachments"] == [{"id": "0123456789ab", "name": "shot.png", "size": 12, "image": True}]
    assert rows[1] == {**rows[1], "role": "assistant", "text": "Nice screenshot."}
    assert "uploads-test/0123456789ab-shot.png" in " ".join(str(arg) for arg in captured["args"])


def test_attachment_markup_is_escaped_and_typed():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = (STATIC / "assistant.html").read_text()
    functions = "\n".join(re.search(r"function " + name + r"\([^\n]*\)\{.*?\n\}", html, re.S).group(0)
                          for name in ["fileSize", "uploadUrl", "attachmentsHtml"])
    helpers = "\n".join(re.search(r"const " + name + r"=[^\n]*", html).group(0) for name in ["esc", "escAttr", "UPLOAD_ID"])
    js = helpers + '''
const assert=require('node:assert/strict');
''' + functions + '''
assert.equal(fileSize(812),'812 B'); assert.equal(fileSize(14*1024),'14 KB'); assert.equal(fileSize(2.3*1048576),'2.3 MB');
assert.equal(attachmentsHtml('chat:x',[]),''); assert.equal(attachmentsHtml('chat:x',undefined),'');
const out=attachmentsHtml('doc:a/b.md',[
  {id:'0123456789ab',name:'shot.png',size:10,image:true},
  {id:'ba9876543210',name:'x"><script>alert(1)</script>.pdf',size:2048,image:false},
  {id:'../../etc/passwd',name:'bad.txt',size:1,image:false}]);
assert.match(out,/<a class="chat-attachment-image" href="\\/api\\/board\\/chat\\/upload\\/0123456789ab\\?item_id=doc%3Aa%2Fb\\.md" target="_blank" rel="noopener"><img src="[^"]+" alt="shot\\.png" loading="lazy"><\\/a>/);
assert.match(out,/class="chat-attachment-file tag" href="[^"]+" download="x&quot;&gt;&lt;script&gt;alert\\(1\\)&lt;\\/script&gt;\\.pdf">/);
assert.match(out,/2 KB/);
assert.ok(!out.includes('<script>')&&!out.includes('passwd')&&!out.includes('bad.txt'));
'''
    subprocess.run([node, "-e", js], capture_output=True, text=True, check=True)
