#!/usr/bin/env python3
"""署名付きの LINE webhook を組み立てて POST し、応答コードと所要時間を出す。

使い方（環境変数 LINE_CHANNEL_SECRET が必要。送り先の Web 版と同じ値）:
  uv run python deploy/verify/post_callback.py <url> text <userId> <本文>      テキストメッセージ
  uv run python deploy/verify/post_callback.py <url> postback <userId> <data>  ポストバック
  uv run python deploy/verify/post_callback.py <url> sticker <userId>          スタンプ
末尾に --bad-signature を付けると署名を壊して送る（拒否されることの確認用）。

所要時間は接続の開始から応答の完了までで、LINE の 2 秒の制限に対する余裕を見るために出す。
返信の中身は、Web 版の LINE_API_BASE_URL を line_api_stub.py へ向けて、スタブ側で読む。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from insider_bot.line.signature import sign

REPLY_TOKEN = "verify-reply-token"


def build_body(kind: str, user_id: str, arg: str | None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "replyToken": REPLY_TOKEN,
        "timestamp": int(time.time() * 1000),
        "source": {"type": "user", "userId": user_id},
        "mode": "active",
    }
    if kind == "text":
        event["type"] = "message"
        event["message"] = {"type": "text", "id": "1", "text": arg}
    elif kind == "postback":
        event["type"] = "postback"
        event["postback"] = {"data": arg}
    elif kind == "sticker":
        event["type"] = "message"
        event["message"] = {"type": "sticker", "id": "1", "packageId": "1", "stickerId": "1"}
    else:
        raise ValueError(f"知らないイベントの種類です: {kind}")
    return {"destination": "Uverify", "events": [event]}


def post(url: str, secret: str, body: bytes, bad_signature: bool = False) -> tuple[int, float]:
    signature = sign(secret + ("x" if bad_signature else ""), body)
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Line-Signature": signature},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    return status, (time.perf_counter() - started) * 1000


def main(argv: list[str]) -> int:
    bad_signature = "--bad-signature" in argv
    args = [arg for arg in argv if arg != "--bad-signature"]
    if len(args) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    secret = os.environ.get("LINE_CHANNEL_SECRET", "")
    if not secret:
        print("LINE_CHANNEL_SECRET を設定してください（送り先の Web 版と同じ値）", file=sys.stderr)
        return 2
    url, kind, user_id = args[0], args[1], args[2]
    arg = args[3] if len(args) > 3 else None
    body = json.dumps(build_body(kind, user_id, arg), ensure_ascii=False).encode("utf-8")
    status, elapsed_ms = post(url, secret, body, bad_signature)
    print(f"status={status} elapsed_ms={elapsed_ms:.0f}")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
