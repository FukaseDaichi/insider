"""LINE の返信 API（POST /v2/bot/message/reply）のクライアント。公式の SDK は使わず httpx2 で送る。

送るのは返信だけ。replyToken は 1 回限りで短命なので、失敗しても再試行しない（呼び出し側がログに残す）。
"""

from __future__ import annotations

from typing import Any

import httpx2

DEFAULT_API_BASE_URL = "https://api.line.me"
REPLY_PATH = "/v2/bot/message/reply"
REPLY_TIMEOUT_SECONDS = 10.0
# 1 回の返信で送れるメッセージの数の上限
MAX_REPLY_MESSAGES = 5


class LineReplyClient:
    def __init__(
        self,
        channel_token: str,
        api_base_url: str = DEFAULT_API_BASE_URL,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx2.AsyncClient(
            base_url=api_base_url,
            headers={"Authorization": f"Bearer {channel_token}"},
            timeout=REPLY_TIMEOUT_SECONDS,
            transport=transport,
        )

    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> None:
        """返信する。HTTP のエラーと通信の失敗は httpx2 の例外のまま上げる。"""
        if not 1 <= len(messages) <= MAX_REPLY_MESSAGES:
            # LINE が 400 で断る返信を送らない
            raise ValueError(f"返信のメッセージは 1〜{MAX_REPLY_MESSAGES} 通です（{len(messages)} 通）")
        response = await self._client.post(REPLY_PATH, json={"replyToken": reply_token, "messages": messages})
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()
