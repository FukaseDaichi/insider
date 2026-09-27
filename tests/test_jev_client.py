"""Jev クライアントの接続設定：接続や応答が固まっても再試行で吸収し、全体は時間内に打ち切る。"""

import asyncio
import json
import time

import httpx2
import pytest

from insider_bot import judge
from insider_bot.judge import CONNECT_TIMEOUT_SECONDS, JevJudge, JudgeError, create_jev_client

OK_BODY = {
    "model": "jev-test",
    "answers": {
        "is_yes": {"type": "noul", "noul": 0.9},
        "is_correct": {"type": "noul", "noul": 0.1},
    },
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


class FlakyTransport(httpx2.AsyncBaseTransport):
    """最初の fail_times 回は接続タイムアウトを起こし、その後は正常に応答する。"""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.attempts = 0

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise httpx2.ConnectTimeout("connect timed out", request=request)
        return httpx2.Response(200, json=OK_BODY, request=request)


class LocalJev:
    """本物の TCP で応答するローカルの偽 Jev。replies の順に応答し、尽きたら 200 を返す。

    reply が "stall" なら応答せずに待ち続ける。(status, headers) ならその応答を返す。
    """

    def __init__(self, replies: list | None = None) -> None:
        self.replies = list(replies or [])
        self.requests = 0
        self.connections = 0
        self._server: asyncio.Server | None = None

    async def __aenter__(self) -> "LocalJev":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.close()

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            while head := await reader.readuntil(b"\r\n\r\n"):
                length = next(
                    (int(line.split(b":")[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length")),
                    0,
                )
                await reader.readexactly(length)
                self.requests += 1
                reply = self.replies.pop(0) if self.replies else (200, {})
                if reply == "stall":
                    await asyncio.sleep(3600)
                status, headers = reply
                body = json.dumps(OK_BODY if status == 200 else {}).encode()
                lines = [f"HTTP/1.1 {status} X", f"Content-Length: {len(body)}", "Content-Type: application/json"]
                lines += [f"{k}: {v}" for k, v in headers.items()]
                writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


@pytest.fixture
async def local_jev(monkeypatch):
    async def start(replies: list | None = None) -> LocalJev:
        server = await LocalJev(replies).__aenter__()
        servers.append(server)
        monkeypatch.setenv("TYPESAFE_BASE_URL", server.url)
        return server

    servers: list[LocalJev] = []
    yield start
    for server in servers:
        await server.__aexit__()


def test_connect_timeout_is_shorter_than_total_budget():
    assert CONNECT_TIMEOUT_SECONDS < 10 / 3


def test_read_timeout_leaves_room_to_retry_within_budget():
    # 通常の応答は 1 秒未満。固まった応答を見切っても、10 秒の中でもう 1 回試せる長さにする
    assert 1 < judge.READ_TIMEOUT_SECONDS < 10 / 2


async def test_retries_after_response_stalls(local_jev, monkeypatch):
    monkeypatch.setattr(judge, "READ_TIMEOUT_SECONDS", 0.3, raising=False)
    server = await local_jev(["stall"])
    async with create_jev_client("test-key", timeout=3) as client:
        verdict = await JevJudge(client, 0.8, 3).judge("りんご", "", "果物ですか？")
    assert verdict.yes_prob == pytest.approx(0.9)
    assert server.requests == 2


async def test_reuses_connection_after_idle_gap(local_jev):
    # 質問の間隔は 15〜60 秒あるので、httpx 既定の 5 秒で接続を捨てずに使い回す
    server = await local_jev()
    async with create_jev_client("test-key", timeout=10) as client:
        jev = JevJudge(client, 0.8, 10)
        await jev.judge("りんご", "", "果物ですか？")
        await asyncio.sleep(5.5)
        await jev.judge("りんご", "", "赤いですか？")
    assert server.requests == 2
    assert server.connections == 1


async def test_failure_message_shows_elapsed_and_retry_hints(local_jev):
    server = await local_jev([(520, {"Retry-After": "30", "CF-Ray": "abc123-NRT"})])
    async with create_jev_client("test-key", timeout=10) as client:
        with pytest.raises(JudgeError) as caught:
            await JevJudge(client, 0.8, 10).judge("りんご", "", "果物ですか？")
    message = str(caught.value)
    assert "retry-after=30" in message
    assert "cf-ray=abc123-NRT" in message
    assert "経過" in message
    assert server.requests == 1


async def test_retries_after_connect_timeout():
    transport = FlakyTransport(fail_times=2)
    async with create_jev_client("test-key", timeout=10, transport=transport) as client:
        verdict = await JevJudge(client, 0.8, 10).judge("りんご", "", "果物ですか？")
    assert verdict.yes_prob == pytest.approx(0.9)
    assert transport.attempts == 3


async def test_keeps_retrying_connect_timeouts_while_budget_remains():
    transport = FlakyTransport(fail_times=4)
    async with create_jev_client("test-key", timeout=10, transport=transport) as client:
        verdict = await JevJudge(client, 0.8, 10).judge("りんご", "", "果物ですか？")
    assert verdict.yes_prob == pytest.approx(0.9)
    assert transport.attempts == 5


async def test_gives_up_within_budget_when_connect_keeps_failing():
    transport = FlakyTransport(fail_times=1000)
    started = time.monotonic()
    async with create_jev_client("test-key", timeout=2, transport=transport) as client:
        with pytest.raises(JudgeError, match="TypeSafeAPI"):
            await JevJudge(client, 0.8, 2).judge("りんご", "", "果物ですか？")
    assert time.monotonic() - started < 3
    assert transport.attempts >= 2
