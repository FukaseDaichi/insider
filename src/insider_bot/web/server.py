"""aiohttp のアプリ。HTTP の配信と WebSocket の受信ループだけを持ち、判断は RoomHub に任せる。"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import weakref
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

from aiohttp import WSCloseCode, WSMsgType, web

from insider_bot.web.hub import RoomHub
from insider_bot.web.rooms import InvalidName, Player, Room, RoomFull, RoomLimitReached, RoomNotFound
from insider_bot.web.village_api import VillageApp, add_village_routes

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
SEND_QUEUE_LIMIT = 100
CLEANUP_INTERVAL_SECONDS = 600.0
JOIN_TIMEOUT_SECONDS = 10.0
HEARTBEAT_SECONDS = 30.0
MAX_MESSAGE_BYTES = 4096
VENDOR_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
# 特殊村は 100 通×5,000 文字まで受け取る（日本語の UTF-8 で約 1.5MB）。本番の Caddy の本文上限（deploy/Caddyfile の request_body の 2MiB）と同じ値
MAX_REQUEST_BYTES = 2 * 1024 * 1024

CLOSE_BAD_REQUEST = 4400
CLOSE_NOT_FOUND = 4404
CLOSE_FULL = 4409
# ブラウザは接続に失敗したときの HTTP ステータスを読めないので、接続を受けてから独自のコードで閉じる
_JOIN_ERRORS: dict[type[Exception], tuple[int, bytes]] = {
    RoomNotFound: (CLOSE_NOT_FOUND, b"room not found"),
    RoomFull: (CLOSE_FULL, b"room full"),
    InvalidName: (CLOSE_BAD_REQUEST, b"invalid name"),
}

# 日本語を \uXXXX に膨らませない（無料枠の外向き通信を抑えるため）
_dumps = functools.partial(json.dumps, ensure_ascii=False)

HUB = web.AppKey("hub", RoomHub)
STATIC = web.AppKey("static_dir", Path)
SOCKETS = web.AppKey("sockets", weakref.WeakSet)


class WsConnection:
    """接続ごとの送信待ちの列。enqueue は積むだけで待たず、送信は専用のタスクが積んだ順に行う。"""

    def __init__(self, ws: Any, queue_limit: int = SEND_QUEUE_LIMIT) -> None:
        self._ws = ws
        self._limit = queue_limit
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._closer: asyncio.Task[Any] | None = None
        self.closed = False
        self._sender = asyncio.create_task(self._send_loop())

    def enqueue(self, message: dict[str, Any]) -> None:
        if self.closed:
            return
        if self._queue.qsize() >= self._limit:
            # 受け取りが極端に遅い。閉じれば画面は再接続して snapshot で追いつく
            log.warning("送信待ちが %d 件たまったため接続を閉じます", self._limit)
            self.closed = True
            self._sender.cancel()
            self._closer = asyncio.create_task(self._ws.close(code=WSCloseCode.TRY_AGAIN_LATER))
            return
        self._queue.put_nowait(message)

    async def aclose(self) -> None:
        """受信ループが終わったときに呼ぶ。送信タスクを止める。"""
        self.closed = True
        self._sender.cancel()
        pending = [self._sender] + ([self._closer] if self._closer is not None else [])
        await asyncio.gather(*pending, return_exceptions=True)

    async def _send_loop(self) -> None:
        try:
            while True:
                await self._ws.send_json(await self._queue.get(), dumps=_dumps)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # 送信の失敗はこの接続だけの問題にする。ほかの接続への配信は続く
            log.info("送信に失敗したため接続を閉じます: %s", error)
            self.closed = True
            await self._ws.close()


def _parse(data: str) -> dict[str, Any] | None:
    try:
        message = json.loads(data)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


async def _read_join(ws: web.WebSocketResponse) -> dict[str, Any] | None:
    try:
        first = await ws.receive(timeout=JOIN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return None
    if first.type != WSMsgType.TEXT:
        return None
    message = _parse(first.data)
    if message is None or message.get("type") != "join":
        return None
    token = message.get("token")
    if not isinstance(message.get("name"), str) or not (token is None or isinstance(token, str)):
        return None
    return message


async def _dispatch(hub: RoomHub, room: Room, player: Player, message: dict[str, Any] | None) -> None:
    if message is None:
        return
    kind = message.get("type")
    if kind == "ask":
        text = message.get("text")
        if isinstance(text, str):
            hub.ask(room, player, text, message.get("game_id"))
    elif kind == "start":
        topic, hint = message.get("topic"), message.get("hint", "")
        if isinstance(topic, str) and isinstance(hint, str):
            await hub.start(room, player, topic, hint)
    elif kind == "giveup":
        await hub.giveup(room, player)


async def websocket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=HEARTBEAT_SECONDS, max_msg_size=MAX_MESSAGE_BYTES)
    await ws.prepare(request)
    request.app[SOCKETS].add(ws)
    join = await _read_join(ws)
    if join is None:
        await ws.close(code=CLOSE_BAD_REQUEST, message=b"join required")
        return ws

    hub = request.app[HUB]
    conn = WsConnection(ws)
    try:
        room, player = hub.join(conn, request.match_info["code"], join["name"], join.get("token"))
    except (RoomNotFound, RoomFull, InvalidName) as error:
        await conn.aclose()
        code, reason = _JOIN_ERRORS[type(error)]
        await ws.close(code=code, message=reason)
        return ws

    try:
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                await _dispatch(hub, room, player, _parse(message.data))
    finally:
        hub.leave(room, conn)
        await conn.aclose()
    return ws


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(request.app[STATIC] / "index.html")


async def create_room(request: web.Request) -> web.Response:
    try:
        room = request.app[HUB].create_room()
    except RoomLimitReached:
        return web.json_response({"error": "今はルームを作れません。しばらくしてからどうぞ"}, status=503)
    return web.json_response({"code": room.code}, status=201)


async def healthz(request: web.Request) -> web.Response:
    """HTTP を受け付けていることだけを示す。外形監視は本文の ok で判定する。"""
    return web.Response(text="ok")


async def _cache_headers(request: web.Request, response: web.StreamResponse) -> None:
    path = request.path
    if path.startswith("/static/vendor/"):
        # 版番号付きのファイル名なので、中身が変わることはない
        response.headers["Cache-Control"] = f"public, max-age={VENDOR_MAX_AGE_SECONDS}"
    elif path == "/" or (path.startswith(("/static/", "/r/", "/village", "/v/")) and not path.endswith("/ws")):
        # 更新を git pull で配るので毎回確かめる（変わっていなければ 304）
        response.headers["Cache-Control"] = "no-cache"


async def _cleanup_loop(hub: RoomHub, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        hub.cleanup()


async def close_all(sockets: Iterable[Any]) -> None:
    """停止時にすべての WebSocket を同時に閉じる。

    1 本ずつ待つと、応答しない端末の数だけ close のタイムアウト（10 秒）が積み上がり、
    systemd の TimeoutStopSec（90 秒）を超えて SIGKILL される。
    """
    await asyncio.gather(
        *(ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown") for ws in list(sockets)),
        return_exceptions=True,
    )


def create_app(
    hub: RoomHub,
    static_dir: Path = STATIC_DIR,
    cleanup_interval: float = CLEANUP_INTERVAL_SECONDS,
    village: VillageApp | None = None,
) -> web.Application:
    app = web.Application(client_max_size=MAX_REQUEST_BYTES)
    app[HUB] = hub
    app[STATIC] = static_dir
    app[SOCKETS] = weakref.WeakSet()
    app.router.add_get("/", index)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_get("/r/{code}", index)
    # 手で打った URL の末尾の / も受け付ける（画面側も /r/<番号>/ を受け付ける）
    app.router.add_get("/r/{code}/", index)
    app.router.add_get("/r/{code}/ws", websocket)
    app.router.add_static("/static/", static_dir)
    app.router.add_get("/healthz", healthz)
    if village is not None:
        add_village_routes(app, village, static_dir / "village.html")
    app.on_response_prepare.append(_cache_headers)

    async def run_cleanup(app: web.Application) -> AsyncIterator[None]:
        task = asyncio.create_task(_cleanup_loop(hub, cleanup_interval))
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def close_sockets(app: web.Application) -> None:
        await close_all(app[SOCKETS])

    app.cleanup_ctx.append(run_cleanup)
    app.on_shutdown.append(close_sockets)
    return app
