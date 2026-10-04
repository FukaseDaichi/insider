import asyncio
import contextlib
import json
import logging
import random

import httpx2
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from insider_bot.line.render import render
from insider_bot.line.signature import sign
from insider_bot.line.sticker import sticker_reply
from insider_bot.line.webhook import CALLBACK_PATH, LineWebhook, add_line_routes
from insider_bot.village import messages
from insider_bot.village.commands import CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.service import VillageService
from insider_bot.village.words import parse_dictionary
from tests.fakes import FirstRandom, FixedRandom

SECRET = "channel-secret"
BASE = "https://game.example.com"
OWNER = "U0123456789abcdef0123456789abcdef"
MEMBER = "Ufedcba9876543210fedcba9876543210"
SECRET_TOPIC = "ひみつのおだい"
DICTIONARY = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])
# 役職画像は毎回 5 枚から選ぶので、1 枚目に固定する（スタンプ応答の期待値と同じ画像になる）
ILLUST = Illustrations(BASE, FirstRandom())
UNIDENTIFIED = [{"type": "text", "text": "ユーザーを識別できないため操作できません。\nbotとの1対1のトークから操作してください。"}]


class CountingRegistry(VillageRegistry):
    """作られた村を数える。識別できない利用者の操作で村が増えないことを確かめる。"""

    def __init__(self) -> None:
        super().__init__(random.Random(1))
        self.added = 0

    def add(self, village):
        self.added += 1
        return super().add(village)


class RecordingSender:
    """返信を記録する。gate を渡すと set されるまで送信中のまま止まり、error を渡すと送信に失敗する。"""

    def __init__(self, gate: asyncio.Event | None = None, error: Exception | None = None) -> None:
        self.sent: list[tuple[str, list[dict]]] = []
        self.gate = gate
        self.error = error

    async def reply(self, reply_token, line_messages):
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        self.sent.append((reply_token, line_messages))


class GatedSender:
    """返信先の replyToken ごとに、set されるまで送信中のまま止める。"""

    def __init__(self, gates: dict[str, asyncio.Event]) -> None:
        self.sent: list[str] = []
        self.gates = gates

    async def reply(self, reply_token, line_messages):
        await self.gates[reply_token].wait()
        self.sent.append(reply_token)


class FailingCommands(CommandHandler):
    """特定のテキストだけ、中核が例外を上げる。例外の文に入力が入る場合を再現する。"""

    def handle(self, user_id, text):
        if text == SECRET_TOPIC:
            raise ValueError(f"boom {text}")
        return super().handle(user_id, text)


@contextlib.asynccontextmanager
async def serve(sender, *draws, commands=CommandHandler):
    """配役の乱数だけを固定し（draws）、採番は本物の乱数に任せる。"""
    villages = CountingRegistry()
    rng = FixedRandom(*draws) if draws else random.Random(3)
    service = VillageService(villages, SpecialVillageRegistry(random.Random(2)), DICTIONARY, ILLUST, rng)
    webhook = LineWebhook(SECRET, commands(service, f"{BASE}/village/special"), ILLUST, sender, BASE)
    app = web.Application()
    add_line_routes(app, webhook)
    async with TestClient(TestServer(app)) as client:
        yield client, webhook, villages


def source(user):
    return {"type": "user", "userId": user} if user is not None else {"type": "group", "groupId": "Cgroup"}


def text_event(text, user=OWNER, token="token-1"):
    message = {"type": "text", "id": "1", "text": text}
    return {"type": "message", "replyToken": token, "source": source(user), "message": message}


def postback_event(data, user=OWNER, token="token-1"):
    return {"type": "postback", "replyToken": token, "source": source(user), "postback": {"data": data}}


def sticker_event(user=OWNER, token="token-1"):
    message = {"type": "sticker", "id": "1", "packageId": "1", "stickerId": "1"}
    return {"type": "message", "replyToken": token, "source": source(user), "message": message}


async def post(client, *events, body=None, headers=None):
    """署名つきで webhook を送る。body と headers を渡すと、そのまま送る。"""
    if body is None:
        body = json.dumps({"destination": "Ubot", "events": list(events)}, ensure_ascii=False).encode()
    if headers is None:
        headers = {"X-Line-Signature": sign(SECRET, body)}
    return await client.post(CALLBACK_PATH, data=body, headers={"Content-Type": "application/json", **headers})


async def deliver(client, webhook, *events):
    """webhook を送って 200 を確かめ、送りかけの返信を待つ。"""
    response = await post(client, *events)
    assert response.status == 200
    await webhook.drain()


def owned(villages, user=OWNER):
    return villages.find_latest_owned(f"line:{user}", lambda v: True)


# --- テキスト ---


async def test_a_text_message_is_answered_through_the_core():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        await deliver(client, webhook, text_event("お題"))
        # LINE の利用者は line:<ユーザー ID> で識別する
        number = owned(villages).number
    assert sender.sent == [("token-1", render(messages.created_reply(number)))]


async def test_no_village_gets_the_confirm_template_that_suggests_creating_one():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(client, webhook, text_event("500"))
    assert sender.sent == [("token-1", render(messages.default_reply()))]


@pytest.mark.parametrize("text", ["お題", "ランダム", "3", "すいか", "@逆村"])
async def test_text_without_a_user_id_is_refused_without_changing_anything(text):
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        await deliver(client, webhook, text_event(text, user=None))
    assert sender.sent == [("token-1", UNIDENTIFIED)]
    assert villages.added == 0


# --- ポストバック ---


async def test_a_topic_candidate_postback_is_answered_even_without_a_user_id():
    sender = RecordingSender()
    async with serve(sender, 0) as (client, webhook, _):
        await deliver(client, webhook, postback_event("2", user=None))
    assert sender.sent == [("token-1", render(messages.candidate_reply("a")))]


async def test_a_status_postback_without_a_user_id_is_refused():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(client, webhook, postback_event("1234", user=None))
    assert sender.sent == [("token-1", UNIDENTIFIED)]


async def test_a_status_postback_answers_the_seat_and_the_count():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        await deliver(client, webhook, text_event("お題"), text_event("すいか"), text_event("2"))
        number = owned(villages).number
        await deliver(client, webhook, text_event(str(number), user=MEMBER))
        await deliver(client, webhook, postback_event(str(number), user=MEMBER, token="status"))
        village = villages.get(number)
    assert sender.sent[-1] == ("status", render(messages.status_reply(village, f"line:{MEMBER}")))


async def test_unreadable_postback_data_gets_the_default_reply():
    sender = RecordingSender()
    no_data = {"type": "postback", "replyToken": "token-4", "source": source(OWNER), "postback": {}}
    async with serve(sender) as (client, webhook, _):
        # 前後の空白は除かない（Java の Integer.parseInt と同じ）
        await deliver(
            client,
            webhook,
            postback_event("abc"),
            postback_event(" 3", token="token-2"),
            postback_event("", token="token-3"),
            no_data,
        )
    default = render(messages.default_reply())
    assert sender.sent == [("token-1", default), ("token-2", default), ("token-3", default), ("token-4", default)]


# --- スタンプ ---


async def test_a_sticker_gets_the_maker_information_even_without_a_user_id():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(client, webhook, sticker_event(user=None))
    assert sender.sent == [("token-1", render(sticker_reply(ILLUST, BASE)))]


# --- 署名と本文 ---


@pytest.mark.parametrize(
    "headers_for",
    [
        lambda body: {},
        lambda body: {"X-Line-Signature": ""},
        lambda body: {"X-Line-Signature": "wrong"},
        lambda body: {"X-Line-Signature": sign("other-secret", body)},
    ],
    ids=["missing", "empty", "garbage", "other-secret"],
)
async def test_webhooks_without_the_right_signature_are_refused(headers_for):
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        body = json.dumps({"events": [text_event("お題")]}).encode()
        response = await post(client, body=body, headers=headers_for(body))
        assert response.status == 400
        await webhook.drain()
    assert (sender.sent, villages.added) == ([], 0)


async def test_a_body_changed_after_signing_is_refused():
    async with serve(RecordingSender()) as (client, _, villages):
        body = json.dumps({"events": [text_event("お題")]}).encode()
        response = await post(client, body=body + b" ", headers={"X-Line-Signature": sign(SECRET, body)})
        assert response.status == 400
    assert villages.added == 0


@pytest.mark.parametrize("body", [b"not json", b"\xff", b"[]", b"{}", b'{"events": {}}'])
async def test_signed_but_unreadable_bodies_are_refused(body):
    async with serve(RecordingSender()) as (client, _, _):
        assert (await post(client, body=body)).status == 400


async def test_the_console_verification_without_events_is_accepted():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(client, webhook)
    assert sender.sent == []


@pytest.mark.parametrize(
    "event",
    [
        {"type": "follow", "replyToken": "token-1", "source": source(OWNER)},
        {"type": "unfollow", "source": source(OWNER)},
        {"type": "message", "replyToken": "token-1", "source": source(OWNER), "message": {"type": "image", "id": "1"}},
        {"type": "message", "replyToken": "token-1", "source": source(OWNER), "message": {"type": "text", "id": "1"}},
        {"type": "message", "source": source(OWNER), "message": {"type": "text", "id": "1", "text": "お題"}},
        "not an event",
    ],
    ids=["follow", "unfollow", "image", "text-without-text", "without-reply-token", "not-an-object"],
)
async def test_events_that_need_no_reply_are_accepted_quietly(event):
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        await deliver(client, webhook, event)
    # 返信先のないテキストでも村を作らない（作っても番号を伝えられない）
    assert (sender.sent, villages.added) == ([], 0)


# --- 返信 ---


async def test_each_event_in_one_webhook_is_answered_with_its_own_token_in_order():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(
            client,
            webhook,
            text_event("500", token="t1"),
            sticker_event(token="t2"),
            postback_event("abc", token="t3"),
        )
    assert [token for token, _ in sender.sent] == ["t1", "t2", "t3"]


async def test_the_webhook_answers_before_the_reply_is_sent():
    gate = asyncio.Event()
    sender = RecordingSender(gate=gate)
    async with serve(sender) as (client, webhook, _):
        async with asyncio.timeout(2):
            response = await post(client, text_event("500"))
        assert response.status == 200
        assert sender.sent == []
        gate.set()
        await webhook.drain()
    assert len(sender.sent) == 1


@pytest.mark.parametrize(
    "error",
    [
        httpx2.ReadTimeout("timed out"),
        httpx2.HTTPStatusError(
            "401 Unauthorized",
            request=httpx2.Request("POST", "https://api.line.me/v2/bot/message/reply"),
            response=httpx2.Response(401),
        ),
    ],
    ids=["timeout", "unauthorized"],
)
async def test_a_failed_reply_is_only_logged(caplog, error):
    with caplog.at_level(logging.DEBUG):
        async with serve(RecordingSender(error=error)) as (client, webhook, _):
            response = await post(client, text_event("お題"), text_event(SECRET_TOPIC, token="token-2"))
            assert response.status == 200
            await webhook.drain()
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all("返信を送れませんでした" in warning for warning in warnings)
    assert OWNER not in caplog.text
    assert "ひみつのおだい" not in caplog.text


async def test_event_contents_are_never_logged(caplog):
    with caplog.at_level(logging.DEBUG):
        async with serve(RecordingSender()) as (client, webhook, _):
            await deliver(
                client,
                webhook,
                text_event("お題"),
                text_event("ひみつのおだい", token="t2"),
                postback_event("2", token="t3"),
            )
    assert OWNER not in caplog.text
    assert "ひみつのおだい" not in caplog.text
    # 種別は残す
    assert "message/text" in caplog.text


async def test_replies_in_flight_are_sent_before_the_app_stops():
    gate = asyncio.Event()
    sender = RecordingSender(gate=gate)
    async with serve(sender) as (client, _, _):
        assert (await post(client, text_event("500"))).status == 200
        asyncio.get_running_loop().call_later(0.05, gate.set)
    # serve を抜けるとアプリが止まる。止まる前に、送りかけの返信を待つ
    assert len(sender.sent) == 1


async def test_drain_also_waits_for_a_reply_dispatched_while_it_is_draining():
    first, second = asyncio.Event(), asyncio.Event()
    sender = GatedSender({"t1": first, "t2": second})
    async with serve(sender) as (client, webhook, _):
        try:
            assert (await post(client, text_event("500", token="t1"))).status == 200
            draining = asyncio.create_task(webhook.drain())
            # draining の最初の中断（t1 の返信待ち）まで進める。create_task で積んだ順に実行される
            await asyncio.sleep(0)
            # 止める途中でも、実行中のハンドラーは新しい返信を始め得る
            assert (await post(client, text_event("500", token="t2"))).status == 200
            first.set()
            # t1 が済んでも、あとから始まった t2 を待つ（待たない実装なら、ここですぐ終わる）
            done, _ = await asyncio.wait({draining}, timeout=0.05)
            assert not done
            second.set()
            await asyncio.wait_for(draining, timeout=2)
            assert sender.sent == ["t1", "t2"]
        finally:
            # 失敗しても、アプリを止めるときの待ちが残らないようにする
            first.set()
            second.set()


async def test_an_event_that_fails_does_not_stop_the_other_events(caplog):
    sender = RecordingSender()
    with caplog.at_level(logging.DEBUG):
        async with serve(sender, commands=FailingCommands) as (client, webhook, _):
            response = await post(
                client,
                text_event("500", token="t1"),
                text_event(SECRET_TOPIC, token="t2"),
                text_event("500", token="t3"),
            )
            assert response.status == 200
            await webhook.drain()
    # 失敗した 2 つ目は返信しない。前後は順に答える
    assert [token for token, _ in sender.sent] == ["t1", "t3"]
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "message/text" in errors[0].getMessage()
    assert "処理に失敗しました" in errors[0].getMessage()
    assert "ValueError" in errors[0].getMessage()
    assert errors[0].exc_info is None
    # 例外の文（入力が入る）とユーザー ID はログに出さない
    assert SECRET_TOPIC not in caplog.text
    assert OWNER not in caplog.text
