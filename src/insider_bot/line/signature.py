"""LINE の webhook の署名。本文の bytes に対する HMAC-SHA256 をチャネルシークレットで計算し、Base64 にしたもの。"""

from __future__ import annotations

import base64
import hashlib
import hmac


def sign(channel_secret: str, body: bytes) -> str:
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify(channel_secret: str, body: bytes, signature: str | None) -> bool:
    """X-Line-Signature が本文の署名と一致するか。一致した長さを時間の差から推測されないよう、定数時間で比べる。"""
    if not signature:
        return False
    # ASCII でない値（壊れたヘッダー）は一致しないだけで、例外にしない
    return hmac.compare_digest(sign(channel_secret, body).encode("ascii"), signature.encode("utf-8", "replace"))
