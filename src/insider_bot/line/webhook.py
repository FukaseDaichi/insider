"""LINE の webhook（POST /line/callback）。署名を確かめ、イベントごとに村の中核を 1 回呼んで返信する。

- 本文を bytes のまま読んで署名を確かめてから JSON として読む。署名が合わない・読めない本文は 400。
- 返信は待たない。LINE は webhook に 2 秒以内の応答を求め、返信 API の所要時間はこちらで制御できないので、
  送信はタスクに任せて 200 を先に返す。送信の失敗は WARNING に残すだけで再試行しない
  （replyToken は 1 回限りで短命。利用者はもう一度送れば同じ応答を受け取れる）。
- イベントの本文はログに出さない。LINE のユーザー ID とお題（ゲームの答え）が入っているので、
  記録するのはイベントの種別と処理の結果まで。

イベントの扱いは LineBot（Java）の LineEventHandler と同じ。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

import httpx2
from aiohttp import web

from insider_bot.line.render import render
from insider_bot.line.signature import verify
from insider_bot.line.sticker import sticker_reply
from insider_bot.village import messages, texts
from insider_bot.village.commands import CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.reply import Reply, Text

log = logging.getLogger(__name__)

CALLBACK_PATH = "/line/callback"
SIGNATURE_HEADER = "X-Line-Signature"


class ReplySender(Protocol):
    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> None: ...


def _or_default(replies: list[Reply] | None) -> list[Reply]:
    """対象の村がない（None）は、村の作成を促す既定の応答にする。"""
    return messages.default_reply() if replies is None else replies


def _user_id(event: dict[str, Any]) -> str | None:
    """LINE のユーザー ID を村の識別子（line:<ID>）にする。グループで規約に同意していない人は ID がない。"""
    source = event.get("source")
    user_id = source.get("userId") if isinstance(source, dict) else None
    return f"line:{user_id}" if isinstance(user_id, str) and user_id else None


def _kind(event: dict[str, Any]) -> str:
    """ログに出すイベントの種別。LINE が決める語だけで、利用者の入力は含まない。"""
    message = event.get("message")
    if event.get("type") == "message" and isinstance(message, dict):
        return f"message/{message.get('type')}"
    return str(event.get("type"))


def _events_of(body: bytes) -> list[Any] | None:
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return None
    events = payload.get("events") if isinstance(payload, dict) else None
    return events if isinstance(events, list) else None


def _describe(error: Exception) -> str:
    """失敗の原因。例外の文には URL などが入り得るので、種類と HTTP の状態コードだけにする。"""
    if isinstance(error, httpx2.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    return type(error).__name__


class LineWebhook:
    def __init__(
        self,
        channel_secret: str,
        commands: CommandHandler,
        illust: Illustrations,
        sender: ReplySender,
        homepage_url: str,
    ) -> None:
        self._channel_secret = channel_secret
        self._commands = commands
        self._illust = illust
        self._sender = sender
        self._homepage_url = homepage_url
        # 送信中の返信。参照を持たないとタスクが途中で回収され得る
        self._pending: set[asyncio.Task[None]] = set()

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.read()
        if not verify(self._channel_secret, body, request.headers.get(SIGNATURE_HEADER)):
            log.warning("LINE: 署名の合わない webhook を拒否しました")
            return web.Response(status=400, text="invalid signature")
        events = _events_of(body)
        if events is None:
            log.warning("LINE: 読めない webhook の本文を拒否しました")
            return web.Response(status=400, text="invalid body")
        for event in events:
            self._dispatch(event)
        return web.Response(text="OK")

    def _dispatch(self, event: Any) -> None:
        if not isinstance(event, dict):
            log.debug("LINE: イベントでない要素を読み飛ばしました")
            return
        kind = _kind(event)
        token = event.get("replyToken")
        # 返信先のないイベントでは中核を呼ばない（村を作っても番号を伝えられない）
        replies = self.replies_for(event) if isinstance(token, str) and token else None
        if replies is None:
            log.debug("LINE: %s イベントには返信しません", kind)
            return
        log.debug("LINE: %s イベントに返信します", kind)
        task = asyncio.create_task(self._send(kind, token, render(replies)))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def replies_for(self, event: dict[str, Any]) -> list[Reply] | None:
        """イベントへの返事。返信しないイベントは None。村の中核の同期の操作を高々 1 回だけ呼ぶ。"""
        user_id = _user_id(event)
        if event.get("type") == "message":
            message = event.get("message")
            if not isinstance(message, dict):
                return None
            if message.get("type") == "text" and isinstance(message.get("text"), str):
                if user_id is None:
                    # 識別できない利用者の村を作らないよう、状態を変えずに 1 対 1 のトークを促す
                    return [Text(texts.ERR_UNIDENTIFIED_USER)]
                return _or_default(self._commands.handle(user_id, message["text"]))
            if message.get("type") == "sticker":
                return sticker_reply(self._illust, self._homepage_url)
            return None
        if event.get("type") == "postback":
            postback = event.get("postback")
            data = postback.get("data") if isinstance(postback, dict) else None
            # Java は data を Integer.parseInt に渡し、読めなければ既定の応答にしていた。data がない場合も同じ
            return _or_default(self._commands.postback(user_id, data) if isinstance(data, str) else None)
        return None

    async def _send(self, kind: str, reply_token: str, line_messages: list[dict[str, Any]]) -> None:
        try:
            await self._sender.reply(reply_token, line_messages)
        except Exception as error:
            log.warning("LINE: %s イベントへの返信を送れませんでした（%s）", kind, _describe(error))

    async def drain(self) -> None:
        """送信中の返信を待つ。停止の前に呼び、送りかけの返信を落とさない。"""
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)


def add_line_routes(app: web.Application, webhook: LineWebhook) -> None:
    """LINE の webhook のパスを足す。停止するときは、送りかけの返信を待ってから閉じる。"""
    app.router.add_post(CALLBACK_PATH, webhook.handle)

    async def drain(_app: web.Application) -> None:
        await webhook.drain()

    app.on_shutdown.append(drain)
