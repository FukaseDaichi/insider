import asyncio
import contextlib
import re

import pytest
from aiohttp import WSCloseCode, WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from insider_bot.game import GameManager
from insider_bot.service import GameService
from insider_bot.web.hub import RoomHub
from insider_bot.web.rooms import CODE_ALPHABET, RoomRegistry
from insider_bot.web.server import WsConnection, create_app
from tests.fakes import FakeClock, FakeJudge


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>テスト</title>", encoding="utf-8")
    (tmp_path / "app.js").write_text("// app", encoding="utf-8")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "lib-1.0.0.js").write_text("// lib", encoding="utf-8")
    return tmp_path


@contextlib.asynccontextmanager
async def serve(static_dir, judge=None, **limits):
    clock = FakeClock()
    manager = GameManager(clock=clock)
    service = GameService(manager, judge or FakeJudge(), clock=clock)
    registry = RoomRegistry(clock=clock, on_remove=lambda room: manager.end(room.room_id), **limits)
    hub = RoomHub(registry, service, manager, clock=clock)
    async with TestClient(TestServer(create_app(hub, static_dir=static_dir))) as client:
        yield client


async def create_room(client) -> str:
    response = await client.post("/api/rooms")
    assert response.status == 201
    return (await response.json())["code"]


async def join(client, code, name, token=None):
    ws = await client.ws_connect(f"/r/{code}/ws")
    await ws.send_json({"type": "join", "name": name, "token": token})
    welcome = await ws.receive_json()
    snapshot = await ws.receive_json()
    assert (welcome["type"], snapshot["type"]) == ("welcome", "snapshot")
    return ws, welcome["token"], snapshot


async def receive_until(ws, predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while True:
            message = await ws.receive_json()
            if predicate(message):
                return message


def is_entry(text, pending=False):
    return lambda m: m["type"] == "entry" and text in m["entry"]["text"] and m["entry"]["pending"] is pending


async def start_game(setter, asker, topic="りんご", hint="赤い果物"):
    await setter.send_json({"type": "start", "topic": topic, "hint": hint})
    room = await receive_until(asker, lambda m: m["type"] == "room" and m["game"] is not None)
    return room["game"]["id"]


async def wait_until(predicate):
    while not predicate():
        await asyncio.sleep(0)


# --- HTTP ---


async def test_index_is_served_for_top_and_room_paths_without_caching(static_dir):
    async with serve(static_dir) as client:
        for path in ("/", "/r/K7Q2MX"):
            response = await client.get(path)
            assert response.status == 200
            assert "テスト" in await response.text()
            assert response.headers["Cache-Control"] == "no-cache"


async def test_vendor_files_are_cached_but_app_files_are_revalidated(static_dir):
    async with serve(static_dir) as client:
        vendor = await client.get("/static/vendor/lib-1.0.0.js")
        app = await client.get("/static/app.js")
        assert vendor.headers["Cache-Control"] == "public, max-age=604800"
        assert app.headers["Cache-Control"] == "no-cache"


async def test_create_room_returns_code(static_dir):
    async with serve(static_dir) as client:
        assert re.fullmatch(f"[{CODE_ALPHABET}]{{6}}", await create_room(client))


async def test_create_room_returns_503_when_every_room_is_in_use(static_dir):
    async with serve(static_dir, max_rooms=1) as client:
        code = await create_room(client)
        await join(client, code, "はなこ")
        response = await client.post("/api/rooms")
        assert response.status == 503
        assert (await response.json())["error"] == "今はルームを作れません。しばらくしてからどうぞ"


# --- WebSocket ---


async def test_question_reaches_every_player(static_dir):
    async with serve(static_dir) as client:
        code = await create_room(client)
        setter, _, _ = await join(client, code, "たろう")
        asker, _, _ = await join(client, code, "はなこ")
        game_id = await start_game(setter, asker)
        await asker.send_json({"type": "ask", "text": "果物ですか", "game_id": game_id})
        for ws in (setter, asker):
            message = await receive_until(ws, is_entry("果物ですか？"))
            assert "はい 82%" in message["entry"]["text"]


async def test_reconnect_with_token_restores_setter_and_history(static_dir):
    async with serve(static_dir) as client:
        code = await create_room(client)
        setter, token, _ = await join(client, code, "たろう")
        asker, _, _ = await join(client, code, "はなこ")
        await start_game(setter, asker)
        await setter.close()
        _, again_token, snapshot = await join(client, code, "たろう", token)
        assert again_token == token
        assert snapshot["room"]["you"] == {"is_setter": True, "topic": "りんご", "hint": "赤い果物"}
        assert any("ゲーム開始" in entry["text"] for entry in snapshot["log"])


async def test_reconnect_during_judging_gets_pending_entry_then_result(static_dir):
    gate = asyncio.Event()
    async with serve(static_dir, judge=FakeJudge(gate=gate)) as client:
        code = await create_room(client)
        setter, _, _ = await join(client, code, "たろう")
        asker, _, _ = await join(client, code, "はなこ")
        game_id = await start_game(setter, asker)
        await asker.send_json({"type": "ask", "text": "果物ですか", "game_id": game_id})
        await receive_until(asker, is_entry("果物ですか？", pending=True))
        late, _, snapshot = await join(client, code, "じろう")
        assert [entry["pending"] for entry in snapshot["log"] if "果物ですか" in entry["text"]] == [True]
        gate.set()
        await receive_until(late, is_entry("果物ですか？"))


async def test_unknown_room_is_closed_with_4404(static_dir):
    async with serve(static_dir) as client:
        ws = await client.ws_connect("/r/ZZZZZZ/ws")
        await ws.send_json({"type": "join", "name": "はなこ", "token": None})
        message = await ws.receive()
        assert (message.type, message.data) == (WSMsgType.CLOSE, 4404)


@pytest.mark.parametrize(
    "first",
    [
        '{"type": "ask", "text": "果物ですか"}',
        "join",
        '{"type": "join", "name": 5}',
        '{"type": "join", "name": ""}',
    ],
)
async def test_bad_first_message_is_closed_with_4400(static_dir, first):
    async with serve(static_dir) as client:
        code = await create_room(client)
        ws = await client.ws_connect(f"/r/{code}/ws")
        await ws.send_str(first)
        message = await ws.receive()
        assert (message.type, message.data) == (WSMsgType.CLOSE, 4400)


async def test_full_room_turns_away_new_players_but_not_returning_ones(static_dir):
    async with serve(static_dir, max_players=1) as client:
        code = await create_room(client)
        first, token, _ = await join(client, code, "たろう")
        await first.close()
        newcomer = await client.ws_connect(f"/r/{code}/ws")
        await newcomer.send_json({"type": "join", "name": "はなこ", "token": None})
        message = await newcomer.receive()
        assert (message.type, message.data) == (WSMsgType.CLOSE, 4409)
        _, again_token, _ = await join(client, code, "たろう", token)
        assert again_token == token


async def test_malformed_messages_are_ignored(static_dir):
    async with serve(static_dir) as client:
        code = await create_room(client)
        setter, _, _ = await join(client, code, "たろう")
        for junk in ("not json", "[1, 2]", '{"type": "ask", "text": 5}', '{"type": "start"}', '{"type": "dance"}'):
            await setter.send_str(junk)
        await setter.send_json({"type": "start", "topic": "りんご", "hint": ""})
        notice = await receive_until(setter, lambda m: m["type"] == "notice")
        assert notice["text"] == "お題『りんご』を登録しました"


# --- WsConnection（送信待ちの列） ---


class FakeWs:
    def __init__(self, fail: bool = False, gate: asyncio.Event | None = None) -> None:
        self.sent: list[dict] = []
        self.fail = fail
        self.gate = gate
        self.close_code: int | None = None

    async def send_json(self, message: dict) -> None:
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise ConnectionResetError("切断済み")
        self.sent.append(message)

    async def close(self, *, code: int = 1000, message: bytes = b"") -> bool:
        self.close_code = code
        return True


async def test_connection_sends_in_enqueued_order():
    ws = FakeWs()
    conn = WsConnection(ws)
    for n in range(3):
        conn.enqueue({"n": n})
    await wait_until(lambda: len(ws.sent) == 3)
    assert ws.sent == [{"n": 0}, {"n": 1}, {"n": 2}]
    await conn.aclose()


async def test_send_failure_closes_only_that_connection():
    bad_ws, good_ws = FakeWs(fail=True), FakeWs()
    bad, good = WsConnection(bad_ws), WsConnection(good_ws)
    for conn in (bad, good):
        conn.enqueue({"type": "notice", "text": "x"})
    await wait_until(lambda: bad_ws.close_code is not None and good_ws.sent)
    assert bad.closed
    assert not good.closed
    for conn in (bad, good):
        await conn.aclose()


async def test_backlog_over_limit_closes_connection():
    ws = FakeWs(gate=asyncio.Event())
    conn = WsConnection(ws, queue_limit=3)
    for n in range(5):
        conn.enqueue({"n": n})
    await wait_until(lambda: ws.close_code is not None)
    assert conn.closed
    assert ws.close_code == WSCloseCode.TRY_AGAIN_LATER
    await conn.aclose()
