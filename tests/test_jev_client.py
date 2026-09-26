"""Jev クライアントの接続設定：接続が固まっても再試行で吸収し、全体は時間内に打ち切る。"""

import time

import httpx2
import pytest

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


def test_connect_timeout_is_shorter_than_total_budget():
    assert CONNECT_TIMEOUT_SECONDS < 10 / 3


async def test_retries_after_connect_timeout():
    transport = FlakyTransport(fail_times=2)
    async with create_jev_client("test-key", timeout=10, transport=transport) as client:
        verdict = await JevJudge(client, 0.8, 10).judge("りんご", "", "果物ですか？")
    assert verdict.yes_prob == pytest.approx(0.9)
    assert transport.attempts == 3


async def test_gives_up_within_budget_when_connect_keeps_failing():
    transport = FlakyTransport(fail_times=1000)
    started = time.monotonic()
    async with create_jev_client("test-key", timeout=2, transport=transport) as client:
        with pytest.raises(JudgeError, match="TypeSafeAPI"):
            await JevJudge(client, 0.8, 2).judge("りんご", "", "果物ですか？")
    assert time.monotonic() - started < 3
    assert transport.attempts >= 2
