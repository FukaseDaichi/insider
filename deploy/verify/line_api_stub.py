#!/usr/bin/env python3
"""LINE の返信 API（POST /v2/bot/message/reply）のスタブ。外へは何も送らない。

Web 版を LINE_API_BASE_URL=http://127.0.0.1:18080 で起動すると、LINE への返信がここへ届く。
本文を整形して標準出力へ出し、200 {} を返す。切替前の検証で、返信の中身を読むのに使う。

使い方: uv run python deploy/verify/line_api_stub.py [port]   （既定 18080）
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

REPLY_PATH = "/v2/bot/message/reply"


class ReplyRecorder(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        # トークンそのものは出さず、付いているかだけを見る
        bearer = self.headers.get("Authorization", "").startswith("Bearer ")
        print(f"--- {self.command} {self.path}（Authorization: {'Bearer あり' if bearer else 'なし'}）")
        if self.path != REPLY_PATH:
            print(f"!!! 返信 API ではないパスへの POST です: {self.path}")
            sys.stdout.flush()
            self.send_response(404)
            self.end_headers()
            return
        try:
            print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
        except ValueError:
            print(body.decode("utf-8", errors="replace"))
        sys.stdout.flush()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: object) -> None:
        pass


def main(argv: list[str]) -> None:
    port = int(argv[0]) if argv else 18080
    print(f"listening on 127.0.0.1:{port}", flush=True)
    HTTPServer(("127.0.0.1", port), ReplyRecorder).serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
