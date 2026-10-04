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


def fake_line_client(created):
    """LINE へは送らず、返信を記録するクライアント。作られたものを created に積む。"""

    class FakeLineClient:
        def __init__(self, channel_token, api_base_url):
            self.args = (channel_token, api_base_url)
            self.sent = []
            self.closed = False
            created.append(self)

        async def reply(self, reply_token, line_messages):
            self.sent.append((reply_token, line_messages))

        async def aclose(self):
            self.closed = True

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
