"""配役ツールの HTTP API（/api/village/…）と画面のパス。

中核の構造化操作を 1 対 1 で呼び、返事モデルを JSON で返す。画面の進み方の判断はブラウザ側にあり、
ここは入力の検査と中核の呼び出しだけを持つ。本文を読み終えてから中核の同期の操作を 1 回呼ぶので、
中核の 1 操作の途中で await を挟まない。

利用者は本文の token で識別する（web:<トークン>）。トークンを知る人がその参加者として振る舞えるので、
トークンとお題はログに出さない。
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from insider_bot.village import messages
from insider_bot.village.commands import MAX_SIZE_INPUT, CommandHandler
from insider_bot.village.parsing import java_length
from insider_bot.village.registry import MIN_SPECIAL_NUMBER
from insider_bot.village.reply import Reply
from insider_bot.village.service import OwnedVillage, VillageService
from insider_bot.web.replyjson import replies_json

# 推測されにくい長さの英数字と - _。ブラウザは 16 バイトの乱数を base64url にした 22 文字を使う
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}")
# LINE のテキストメッセージの上限にそろえる。数え方も LINE と同じ UTF-16 の符号単位
MAX_TEXT_LENGTH = 5000
# LINE のポストバックの data の上限
MAX_POSTBACK_LENGTH = 300
# 特殊村は通常村の参加人数の上限にそろえる（LineBot の特殊村フォームと同じ）
MAX_SPECIAL_MESSAGES = 100
MAX_SPECIAL_MESSAGE_LENGTH = 5000
# 村番号として受け付ける整数の範囲（Java の int）。範囲内で村がなければ「対象の村がない」
_MAX_NUMBER = 2**31 - 1
_KINDS = ("normal", "god", "random")
_BAD_REQUEST = {"error": "入力が正しくありません"}

# 画面はどのパスでも同じ HTML で、何を表示するかは画面側がパスで決める
PAGE_PATHS = (
    "/village",
    "/village/",
    "/village/new",
    "/village/new/",
    "/village/special",
    "/village/special/",
    "/v/{number}",
    "/v/{number}/",
)

# 日本語を \uXXXX に膨らませない（外向き通信を抑えるため）
_dumps = functools.partial(json.dumps, ensure_ascii=False)


@dataclass(frozen=True)
class VillageApp:
    """Web と LINE の入口が共有する村の中核。同じプロセスに 1 つだけ作る。"""

    service: VillageService
    commands: CommandHandler


VILLAGE = web.AppKey("village", VillageApp)


@dataclass(frozen=True)
class CreatedSpecial:
    """特殊村を作った操作の結果。応答に作った特殊村の番号を添える。"""

    replies: list[Reply]
    special_number: int


class BadRequest(Exception):
    """本文の形が違う。400 で返す。"""


async def _read_body(request: web.Request) -> dict[str, Any]:
    # JSON と宣言された本文だけを読む。別のサイトのフォームが送れる text/plain などは通さず、
    # JSON を送るにはプリフライトが要るので、CORS を許していないこのサーバーには別のオリジンから届かない
    if request.content_type != "application/json":
        raise BadRequest
    try:
        body = await request.json()
    except (ValueError, LookupError, RecursionError):
        # JSON でない・UTF-8 でない・charset が不明・入れ子が深すぎる
        raise BadRequest from None
    except ConnectionResetError:
        # 本文を読み切る前に接続が切れた。本番では Caddy が 2MiB を超えた本文をここで打ち切る
        # （クライアントには Caddy が 413 を返す）。aiohttp の client_max_size は本文を読み終えてから
        # 数えるので先に効かない。捕まえないと 500 と Traceback が ERROR で残る
        raise BadRequest from None
    if not isinstance(body, dict):
        raise BadRequest
    # 孤立したサロゲートは UTF-8 にできず、お題に入ると以後の返事が送れなくなる
    try:
        json.dumps(body, ensure_ascii=False).encode("utf-8")
    except (UnicodeEncodeError, RecursionError):
        raise BadRequest from None
    return body


def _user_of(body: dict[str, Any]) -> str:
    token = body.get("token")
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise BadRequest
    return f"web:{token}"


def _text_field(body: dict[str, Any], name: str, max_length: int) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value or java_length(value) > max_length:
        raise BadRequest
    return value


def _int_field(body: dict[str, Any], name: str) -> int:
    value = body.get(name)
    # JSON の true / false は Python では int の仲間なので、明示的に除く
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequest
    return value


def _owned_json(owned: OwnedVillage | None) -> dict[str, Any] | None:
    if owned is None:
        return None
    return {
        "number": owned.number,
        "mode": owned.mode,
        "has_topic": owned.has_topic,
        "size": owned.size,
        "member_count": owned.member_count,
        "reverse": owned.reverse,
    }


def _bad_request() -> web.Response:
    return web.json_response(_BAD_REQUEST, status=400, dumps=_dumps)


# --- 操作。本文の検査を先に済ませてから中核を 1 回だけ呼ぶ ---


def _create(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    kind = body.get("kind")
    if kind not in _KINDS:
        raise BadRequest
    if kind == "random":
        return village.service.create_random_village(user_id)
    return village.service.create_village(user_id, god_mode=kind == "god")


def _mine(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    """何も変えず、最新の村の要約だけを返す。画面の再読み込みで続きから表示するため。"""
    return []


def _topic(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    return village.service.set_topic(user_id, _text_field(body, "topic", MAX_TEXT_LENGTH))


def _size(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    size = _int_field(body, "size")
    # 101 以上は LINE では村番号として扱う入力なので、人数としては受け付けない。1 以下は中核が案内する
    if size > MAX_SIZE_INPUT:
        raise BadRequest
    return village.service.set_size(user_id, size)


def _reverse(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    return village.service.set_reverse(user_id)


def _werewords(village: VillageApp, user_id: str, body: dict[str, Any]) -> CreatedSpecial | None:
    created = village.service.create_werewords(user_id)
    return None if created is None else CreatedSpecial(*created)


def _join(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    number = _int_field(body, "number")
    if not 0 <= number <= _MAX_NUMBER:
        raise BadRequest
    # 入る画面の入力なので、100 以下を人数として扱う LINE のテキストの解釈は通さない
    if number >= MIN_SPECIAL_NUMBER:
        return village.service.join_special_village(user_id, number)
    return village.service.join_village(user_id, number)


def _text(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    """返事のメッセージのボタン。LINE でその文字列を送ったのと同じ解釈をする。"""
    return village.commands.handle(user_id, _text_field(body, "text", MAX_TEXT_LENGTH))


def _postback(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    """返事のポストバックのボタン。LINE のポストバックと同じ解釈をする。"""
    data = body.get("data")
    if not isinstance(data, str) or java_length(data) > MAX_POSTBACK_LENGTH:
        raise BadRequest
    return village.commands.postback(user_id, data)


Operation = Callable[[VillageApp, str, dict[str, Any]], "list[Reply] | CreatedSpecial | None"]

_OPERATIONS: dict[str, Operation] = {
    "create": _create,
    "mine": _mine,
    "topic": _topic,
    "size": _size,
    "reverse": _reverse,
    "werewords": _werewords,
    "join": _join,
    "text": _text,
    "postback": _postback,
}


def _api(operation: Operation) -> Callable[[web.Request], Any]:
    """本文を読み、利用者を識別し、中核の操作を 1 回呼んで返事を返すハンドラを作る。"""

    async def handler(request: web.Request) -> web.Response:
        village = request.app[VILLAGE]
        try:
            body = await _read_body(request)
            user_id = _user_of(body)
            result = operation(village, user_id, body)
        except BadRequest:
            return _bad_request()
        special_number = None
        replies = result
        if isinstance(result, CreatedSpecial):
            replies, special_number = result.replies, result.special_number
        # 対象の村がない（None）は Web の既定応答（案内文）にする。画面が次に何を聞くかを決められるよう、
        # 利用者が作った最新の村の要約を毎回添える
        payload = {
            "found": replies is not None,
            "replies": replies_json(replies if replies is not None else messages.guide_reply()),
            "village": _owned_json(village.service.latest_owned(user_id)),
        }
        if special_number is not None:
            payload["special_number"] = special_number
        return web.json_response(payload, dumps=_dumps)

    return handler


def _special_messages(body: dict[str, Any]) -> list[str | None]:
    items = body.get("messages")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_SPECIAL_MESSAGES:
        raise BadRequest
    for item in items:
        # null と空文字は中核で「メッセージは特にありません。」になる
        if item is not None and (not isinstance(item, str) or java_length(item) > MAX_SPECIAL_MESSAGE_LENGTH):
            raise BadRequest
    return items


async def create_special(request: web.Request) -> web.Response:
    """特殊村を作る。配るメッセージの列だけを受け取り、利用者の識別は要らない。"""
    village = request.app[VILLAGE]
    try:
        items = _special_messages(await _read_body(request))
    except BadRequest:
        return _bad_request()
    return web.json_response({"number": village.service.create_special_village(items)}, dumps=_dumps)


def add_village_routes(app: web.Application, village: VillageApp, page: Path) -> None:
    """配役ツールの API と画面のパスを足す。"""
    app[VILLAGE] = village
    for name, operation in _OPERATIONS.items():
        app.router.add_post(f"/api/village/{name}", _api(operation))
    app.router.add_post("/api/village/special", create_special)

    async def serve_page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(page)

    for path in PAGE_PATHS:
        app.router.add_get(path, serve_page)
