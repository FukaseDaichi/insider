import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from insider_bot.config import LineConfig, WebConfig
from insider_bot.line.signature import sign
from insider_bot.web.__main__ import make_app
from insider_bot.web.village_api import VILLAGE

BASE = "https://game.example.com"


def web_config(line=None):
    return WebConfig(
        typesafe_api_key="ts-key",
        correct_threshold=0.8,
        jev_timeout_seconds=10.0,
        host="127.0.0.1",
        port=8080,
        public_base_url=BASE,
        line=line,
    )


def fake_line_client(created, gate=None):
    """LINE へは送らず、返信を記録するクライアント。作られたものを created に積む。gate を渡すと、set されるまで送信中のまま止まる。"""

    class FakeLineClient:
        def __init__(self, channel_token, api_base_url):
            self.args = (channel_token, api_base_url)
            self.sent = []
            self.closed = False
            # 送信と閉じるの順番
            self.events = []
            created.append(self)

        async def reply(self, reply_token, line_messages):
            if gate is not None:
                await gate.wait()
            self.sent.append((reply_token, line_messages))
            self.events.append("sent")

        async def aclose(self):
            self.closed = True
            self.events.append("closed")

    return FakeLineClient


def text_event(text, token):
    return {
        "type": "message",
        "replyToken": token,
        "source": {"type": "user", "userId": "U1"},
        "message": {"type": "text", "id": "1", "text": text},
    }


async def test_the_line_callback_exists_only_when_line_is_configured():
    async with TestClient(TestServer(await make_app(web_config()))) as client:
        assert (await client.post("/line/callback", data=b"{}")).status == 404


async def test_a_village_made_on_line_can_be_joined_from_the_web(monkeypatch):
    created = []
    monkeypatch.setattr("insider_bot.web.__main__.LineReplyClient", fake_line_client(created))
    app = await make_app(web_config(LineConfig("secret", "token")))
    async with TestClient(TestServer(app)) as client:
        for text, token in (("お題", "t1"), ("すいか", "t2"), ("2", "t3")):
            body = json.dumps({"events": [text_event(text, token)]}, ensure_ascii=False).encode()
            response = await client.post("/line/callback", data=body, headers={"X-Line-Signature": sign("secret", body)})
            assert response.status == 200
        # LINE と Web は同じプロセスの同じ中核を使う
        number = app[VILLAGE].service.latest_owned("line:U1").number
        response = await client.post("/api/village/join", json={"token": "web-token-0123456789", "number": number})
        role = (await response.json())["replies"][0]["text"]
        assert role in ("あなたの役職はインサイダーです。お題は『すいか』です。", "あなたの役職は村人です。")
    (line_client,) = created
    assert line_client.args == ("token", "https://api.line.me")
    assert [token for token, _ in line_client.sent] == ["t1", "t2", "t3"]
    assert line_client.closed


async def test_the_line_client_is_closed_only_after_the_replies_in_flight_are_sent(monkeypatch):
    created = []
    gate = asyncio.Event()
    monkeypatch.setattr("insider_bot.web.__main__.LineReplyClient", fake_line_client(created, gate))
    app = await make_app(web_config(LineConfig("secret", "token")))
    # on_shutdown の待ちのあとに返信が始まる場合を、片付けの処理だけを直接呼んで再現する
    (close_line,) = (fn for fn in app.on_cleanup if fn.__name__ == "close_line")
    async with TestClient(TestServer(app)) as client:
        try:
            body = json.dumps({"events": [text_event("お題", "t1")]}, ensure_ascii=False).encode()
            headers = {"X-Line-Signature": sign("secret", body)}
            response = await client.post("/line/callback", data=body, headers=headers)
            assert response.status == 200
            closing = asyncio.create_task(close_line(app))
            # close_line が最初の中断まで進む。返信が済むまで閉じない
            await asyncio.sleep(0)
            assert not created[0].closed
            gate.set()
            await closing
            assert created[0].events == ["sent", "closed"]
        finally:
            gate.set()
