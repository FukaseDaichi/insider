"""同梱した役職画像を各役職の 5 枚から等確率で選ぶ。"""

from __future__ import annotations

import random

from insider_bot.village.model import Rng

ROLE_FILES = {"INSIDER": "INSIDER.png", "VILLAGERS": "VILLAGERS.png", "GM": "GM.png", "GOD": "GOD.png"}
ROLE_VARIANTS = {
    role: (default, *(f"{role}_1_{number:02d}.png" for number in range(2, 6)))
    for role, default in ROLE_FILES.items()
}
ROLE_IMAGE_VERSION = "20261004"
INVITATION_FILE = "966mpnqz.png"
STATIC_ROLES_PATH = "/static/roles/"


class Illustrations:
    def __init__(self, base_url: str, rng: Rng | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._rng: Rng = rng if rng is not None else random.Random()

    def _role_url(self, filename: str) -> str:
        # LINE 側に同じ URL の旧画像が残っていても、新しい画像を取得できるようにする。
        return f"{self._base_url}{STATIC_ROLES_PATH}{filename}?v={ROLE_IMAGE_VERSION}"

    def default_url(self, role_key: str) -> str:
        return self._role_url(ROLE_FILES[role_key])

    @property
    def invitation_image_url(self) -> str:
        return f"{self._base_url}{STATIC_ROLES_PATH}{INVITATION_FILE}"

    def url_for(self, role_key: str) -> str:
        candidates = ROLE_VARIANTS[role_key]
        return self._role_url(candidates[self._rng.randrange(len(candidates))])
