import contextlib
import json
import logging
import random

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from insider_bot.village import messages
from insider_bot.village.commands import CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.service import VillageService
from insider_bot.village.words import parse_dictionary
from insider_bot.web.replyjson import replies_json
from insider_bot.web.village_api import VillageApp, add_village_routes
from tests.fakes import FixedRandom

OWNER = "owner-token-0123456789"
MEMBER = "member-token-012345678"
DICTIONARY = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])
GUIDE = replies_json(messages.guide_reply())


@pytest.fixture
def page(tmp_path):
    path = tmp_path / "village.html"
    path.write_text("<!doctype html><title>配役</title>", encoding="utf-8")
    return path


@contextlib.asynccontextmanager
async def serve(page, *draws):
    """配役の乱数だけを固定し、採番は本物の乱数に任せる。"""
    rng = FixedRandom(*draws) if draws else random.Random(3)
    service = VillageService(
        VillageRegistry(random.Random(1)),
        SpecialVillageRegistry(random.Random(2)),
        DICTIONARY,
        Illustrations("", FixedRandom(0)),
        rng,
    )
    app = web.Application()
    add_village_routes(app, VillageApp(service, CommandHandler(service, "/village/special")), page)
    async with TestClient(TestServer(app)) as client:
        yield client


async def call(client, name, token=OWNER, **fields):
    response = await client.post(f"/api/village/{name}", json={"token": token, **fields})
    assert response.status == 200, await response.text()
    return await response.json()


async def create_special(client, messages_):
    response = await client.post("/api/village/special", json={"messages": messages_})
    assert response.status == 200, await response.text()
    return (await response.json())["number"]


# --- 村を作る ---


async def test_create_returns_the_reply_and_the_new_village(page):
    async with serve(page) as client:
        body = await call(client, "create", kind="normal")
        number = body["village"]["number"]
        assert 1000 <= number <= 9999
        assert body["found"] is True
        assert body["replies"] == replies_json(messages.created_reply(number))
        assert body["village"] == {
            "number": number,
            "mode": "normal",
            "has_topic": False,
            "size": 0,
            "member_count": 0,
            "reverse": False,
        }


async def test_create_god_and_random_villages(page):
    async with serve(page, 0) as client:
        assert (await call(client, "create", kind="god"))["village"]["mode"] == "god"
        body = await call(client, "create", kind="random")
        assert (body["village"]["mode"], body["village"]["has_topic"]) == ("random", True)
        assert body["replies"] == replies_json(messages.random_created_reply(body["village"]["number"]))


async def test_mine_resumes_the_newest_village_without_changing_it(page):
    async with serve(page) as client:
        assert await call(client, "mine") == {"found": True, "replies": [], "village": None}
        number = (await call(client, "create", kind="normal"))["village"]["number"]
        body = await call(client, "mine")
        assert (body["replies"], body["village"]["number"], body["village"]["has_topic"]) == ([], number, False)


# --- お題と人数 ---


async def test_topic_then_size_then_the_status(page):
    async with serve(page, 0) as client:
        number = (await call(client, "create", kind="normal"))["village"]["number"]
        body = await call(client, "topic", topic="すいか")
        assert body["village"]["has_topic"] is True
        body = await call(client, "size", size=3)
        assert body["village"]["size"] == 3
        assert body["replies"][0]["image"] == "/static/roles/GM.png"
        assert body["replies"][0]["title"] == f"{number}村"
        # オーナーが自分の村番号で入ると配布状況
        status = await call(client, "join", number=number)
        assert status["replies"][0]["text"] == f"{number}村：0/3人にお題を配りました。お題は『すいか』です。"


async def test_a_topic_cannot_be_set_twice_and_the_guide_is_returned(page):
    async with serve(page) as client:
        await call(client, "create", kind="normal")
        await call(client, "topic", topic="すいか")
        body = await call(client, "topic", topic="めろん")
        assert (body["found"], body["replies"]) == (False, GUIDE)


async def test_topic_of_exactly_5000_utf16_units_is_accepted(page):
    async with serve(page) as client:
        await call(client, "create", kind="normal")
        body = await call(client, "topic", topic="😀" * 2500)
        assert body["village"]["has_topic"] is True


async def test_size_of_one_or_less_is_answered_with_the_core_message(page):
    async with serve(page) as client:
        await call(client, "create", kind="normal")
        for size in (1, 0, -3):
            body = await call(client, "size", size=size)
            assert body["replies"] == replies_json(messages.size_error_reply()), size
        assert body["village"]["size"] == 0


async def test_random_village_size_returns_the_owners_role(page):
    async with serve(page, 0, 0, 1) as client:
        await call(client, "create", kind="random")
        body = await call(client, "size", size=3)
        assert body["replies"][0]["text"].endswith("人』に設定しました。\n皆さんに村番号を伝えてください。")
        assert body["replies"][1]["image"] == "/static/roles/INSIDER.png"


# --- 逆村と Werewords ---


async def test_reverse_and_werewords(page):
    async with serve(page, 0) as client:
        number = (await call(client, "create", kind="normal"))["village"]["number"]
        await call(client, "topic", topic="すいか")
        await call(client, "size", size=3)
        body = await call(client, "reverse")
        assert body["replies"] == [
            {"type": "text", "text": f"{number}村 を『逆村』に設定しました。\nお題を知らない村人が1人となります。"}
        ]
        assert body["village"]["reverse"] is True
        assert "special_number" not in body
        body = await call(client, "werewords")
        assert "ワーワーズ" in body["replies"][0]["text"]
        # 作った特殊村の番号を、返事の本文とは別に返す。元の村の要約は変わらない
        special = body["special_number"]
        assert 10000 <= special <= 99998
        assert f"『{special}』" in body["replies"][0]["text"]
        assert body["village"]["number"] == number
        # その番号の特殊村に入れる
        assert (await call(client, "join", token=MEMBER, number=special))["found"] is True


async def test_a_failed_werewords_has_no_special_number(page):
    async with serve(page) as client:
        await call(client, "create", kind="normal")
        body = await call(client, "werewords")
        assert (body["found"], body["replies"]) == (False, GUIDE)
        assert "special_number" not in body


# --- 村に入る ---


async def test_participants_join_with_their_own_token(page):
    async with serve(page, 0) as client:
        number = (await call(client, "create", kind="normal"))["village"]["number"]
        await call(client, "topic", topic="すいか")
        await call(client, "size", size=2)
        body = await call(client, "join", token=MEMBER, number=number)
        assert body["replies"][0]["text"] == "あなたの役職はインサイダーです。お題は『すいか』です。"
        assert body["replies"][0]["image"] == "/static/roles/INSIDER.png"
        # 参加者には自分の村がない
        assert body["village"] is None
        # 再表示しても同じ役職
        assert await call(client, "join", token=MEMBER, number=number) == body


async def test_special_village_numbers_join_the_special_village(page):
    async with serve(page) as client:
        number = await create_special(client, ["占い師", None, ""])
        body = await call(client, "join", token=MEMBER, number=number)
        assert body["found"] is True
        assert body["replies"][0]["type"] == "buttons"


async def test_unknown_village_numbers_get_the_guide(page):
    async with serve(page) as client:
        for number in (0, 50, 1234, 99999):
            body = await call(client, "join", number=number)
            assert (body["found"], body["replies"]) == (False, GUIDE), number


# --- 返事のボタン ---


async def test_message_buttons_are_read_like_a_line_message(page):
    async with serve(page) as client:
        body = await call(client, "text", text="お題")
        assert body["replies"] == replies_json(messages.created_reply(body["village"]["number"]))
        # お題の候補の「確定」は、その文字列を送ったことになる
        body = await call(client, "text", text="a")
        assert body["village"]["has_topic"] is True


async def test_postback_buttons(page):
    async with serve(page, 0) as client:
        body = await call(client, "postback", data="0")
        assert body["replies"] == replies_json(messages.candidate_reply("a"))
        body = await call(client, "postback", data="すいか")
        assert (body["found"], body["replies"]) == (False, GUIDE)


# --- 特殊村 ---


async def test_special_village_creation(page):
    async with serve(page) as client:
        assert 10000 <= await create_special(client, ["a"] * 100) <= 99998
        # UTF-16 でちょうど 5,000
        await create_special(client, ["😀" * 2500])


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"messages": []},
        {"messages": ["a"] * 101},
        {"messages": "a"},
        {"messages": [1]},
        {"messages": ["😀" * 2500 + "a"]},
        {"messages": ["\ud800"]},
    ],
)
async def test_special_village_rejects_undeliverable_messages(page, payload):
    async with serve(page) as client:
        response = await client.post("/api/village/special", json=payload)
        assert response.status == 400


# --- 入力の誤り ---


@pytest.mark.parametrize(
    ("name", "fields"),
    [
        ("create", {"kind": "secret"}),
        ("create", {}),
        ("topic", {"topic": ""}),
        ("topic", {"topic": 3}),
        ("topic", {"topic": "😀" * 2500 + "a"}),
        ("topic", {"topic": "\ud800"}),
        ("size", {"size": "3"}),
        ("size", {"size": True}),
        ("size", {"size": 101}),
        ("join", {"number": "1234"}),
        ("join", {"number": -1}),
        ("join", {"number": 2**31}),
        ("text", {"text": ""}),
        ("postback", {"data": 3}),
        ("postback", {"data": "1" * 301}),
    ],
)
async def test_malformed_fields_are_rejected(page, name, fields):
    async with serve(page) as client:
        response = await client.post(f"/api/village/{name}", json={"token": OWNER, **fields})
        assert response.status == 400
        assert await response.json() == {"error": "入力が正しくありません"}


@pytest.mark.parametrize("token", [None, "", "short", "has space 0123456789", "あ" * 22, "x" * 65])
async def test_missing_or_malformed_tokens_are_rejected(page, token):
    async with serve(page) as client:
        response = await client.post("/api/village/mine", json={"token": token})
        assert response.status == 400


async def test_non_json_bodies_are_rejected(page):
    async with serve(page) as client:
        for data in (b"", b"not json", b"[1, 2]", b"\xff\xfe"):
            response = await client.post("/api/village/mine", data=data, headers={"Content-Type": "application/json"})
            assert response.status == 400, data


async def test_bogus_charset_is_rejected(page):
    async with serve(page) as client:
        response = await client.post(
            "/api/village/mine",
            data=b'{"token": "owner-token-0123456789"}',
            headers={"Content-Type": "application/json; charset=bogus"},
        )
        assert response.status == 400


@pytest.mark.parametrize("content_type", ["text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded", None])
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/village/create", {"token": OWNER, "kind": "normal"}),
        ("/api/village/special", {"messages": ["a"]}),
    ],
)
async def test_only_application_json_bodies_are_accepted(page, path, payload, content_type):
    """別のサイトのフォームやプリフライトなしの単純な POST が通らないよう、本文が JSON と宣言されている場合だけ読む。"""
    async with serve(page) as client:
        headers = {} if content_type is None else {"Content-Type": content_type}
        response = await client.post(path, data=json.dumps(payload).encode(), headers=headers)
        assert response.status == 400
        assert await response.json() == {"error": "入力が正しくありません"}
        # 弾いた POST では村ができていない
        assert (await call(client, "mine"))["village"] is None


async def test_deeply_nested_json_is_rejected(page):
    async with serve(page) as client:
        deeply_nested = ('{"token": "owner-token-0123456789", "x": ' + "[" * 100000 + "]" * 100000 + "}").encode()
        response = await client.post(
            "/api/village/mine",
            data=deeply_nested,
            headers={"Content-Type": "application/json"},
        )
        assert response.status == 400


async def test_the_token_and_the_topic_are_not_logged(page, caplog):
    with caplog.at_level(logging.DEBUG):
        async with serve(page, 0) as client:
            await call(client, "create", kind="normal")
            await call(client, "topic", topic="ひみつのおだい")
            await call(client, "size", size=2)
    assert OWNER not in caplog.text
    assert "ひみつのおだい" not in caplog.text


# --- 画面 ---


async def test_the_page_is_served_on_every_village_path(page):
    async with serve(page) as client:
        for path in (
            "/village",
            "/village/",
            "/village/new",
            "/village/new/",
            "/village/special",
            "/village/special/",
            "/v/1234",
            "/v/12345/",
        ):
            response = await client.get(path)
            assert response.status == 200, path
            assert "配役" in await response.text()
