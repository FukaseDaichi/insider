"""役職に添える画像。既定画像は自前の静的ファイル、任意で外部カタログから重み付きで抽選する。

カタログは Google Apps Script のウェブアプリが返す {"files": [{"name", "url"}]}。
name は <役職名>_<重み>_<任意> の 3 部構成で、重みは抽選枠の数。規約外の要素はその要素だけ読み飛ばす
（1 件の書き間違いで全役職が既定画像に戻るのは割に合わない）。取得に失敗したら前回分を使い続ける。

カタログ URL は必ずデプロイ URL（/macros/s/<ID>/exec）を指定する。ブラウザで開いたときの転送先
（script.googleusercontent.com）は一時的な鍵を含み、失効すると 400 を返し続ける。
"""

from __future__ import annotations

import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from insider_bot.village.model import Rng
from insider_bot.village.parsing import java_split, parse_java_int

log = logging.getLogger(__name__)

ROLE_FILES = {"INSIDER": "INSIDER.png", "VILLAGERS": "VILLAGERS.png", "GM": "GM.png", "GOD": "GOD.png"}
INVITATION_FILE = "966mpnqz.png"
STATIC_ROLES_PATH = "/static/roles/"

CATALOG_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class WeightedUrl:
    url: str
    # この要素までの重みの合計。抽選値がこの値未満ならこの URL
    cumulative_weight: int


def parse_catalog(files: list[Mapping[str, Any]]) -> dict[str, tuple[WeightedUrl, ...]]:
    parsed: dict[str, list[WeightedUrl]] = {}
    ignored = 0
    for file in files:
        name = file.get("name")
        url = file.get("url")
        # Java の String.split / Integer.parseInt と同じ規則で読む（末尾の空要素を落とす、全角数字も重みとして読む）
        parts = java_split(name, "_") if isinstance(name, str) else []
        weight = parse_java_int(parts[1]) if len(parts) == 3 else None
        if weight is None or not isinstance(url, str):
            ignored += 1
            continue
        candidates = parsed.setdefault(parts[0], [])
        total = candidates[-1].cumulative_weight if candidates else 0
        candidates.append(WeightedUrl(url, total + max(weight, 0)))
    if ignored:
        # ファイル名は画像の名前で、利用者の識別子やお題は含まれない
        log.warning("役職画像のカタログのうち %d 件を読み飛ばしました", ignored)
    return {role: tuple(candidates) for role, candidates in parsed.items()}


class Illustrations:
    def __init__(self, base_url: str, rng: Rng | None = None, catalog_url: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._rng: Rng = rng if rng is not None else random.Random()
        self._catalog_url = catalog_url
        self._catalog: dict[str, tuple[WeightedUrl, ...]] = {}

    def default_url(self, role_key: str) -> str:
        return f"{self._base_url}{STATIC_ROLES_PATH}{ROLE_FILES[role_key]}"

    @property
    def invitation_image_url(self) -> str:
        return f"{self._base_url}{STATIC_ROLES_PATH}{INVITATION_FILE}"

    def url_for(self, role_key: str) -> str:
        candidates = self._catalog.get(role_key)
        if not candidates:
            return self.default_url(role_key)
        total = candidates[-1].cumulative_weight
        if total <= 0:
            return self.default_url(role_key)
        draw = self._rng.randrange(total)
        for candidate in candidates:
            if draw < candidate.cumulative_weight:
                return candidate.url
        return self.default_url(role_key)

    def apply_catalog(self, files: list[Mapping[str, Any]]) -> None:
        self._catalog = parse_catalog(files)

    async def refresh(self, client: Any) -> None:
        """カタログを取り直す。URL が未設定なら何もしない。失敗は WARNING で前回分を維持する。"""
        if self._catalog_url is None:
            return
        try:
            response = await client.get(self._catalog_url, follow_redirects=True, timeout=CATALOG_TIMEOUT_SECONDS)
            response.raise_for_status()
            body = response.json()
            files = body.get("files") if isinstance(body, dict) else None
            if not isinstance(files, list):
                log.warning("役職画像のカタログの応答に files がありません")
                return
            self.apply_catalog(files)
        except Exception as error:
            log.warning("役職画像のカタログを取り直せませんでした: %s", error)
