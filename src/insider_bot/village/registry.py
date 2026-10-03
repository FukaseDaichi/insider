"""村のプロセス内レジストリ。上限を超えると古い村から FIFO で消える。再起動で失われる。

番号は空いているものからランダムに採番する。連番ではないので隣の番号を推測して他人の村へ入ることは
できないが、総当たりを防ぐ強度はなく、認証の代わりにはならない。
"""

from __future__ import annotations

import random
from collections.abc import Callable

from insider_bot.village.model import Rng, SpecialVillage, Village

MIN_VILLAGE_NUMBER = 1000
MAX_VILLAGE_NUMBER = 9999
MIN_SPECIAL_NUMBER = 10000
MAX_SPECIAL_NUMBER = 99998

MAX_VILLAGE_COUNT = 50
MAX_SPECIAL_COUNT = 30

_DRAW_ATTEMPTS = 100


def _draw_number(rng: Rng, taken: Callable[[int], bool], low: int, high: int, draw_high: int) -> int:
    """low〜draw_high から抽選し、外れ続けたら low から high まで順に空きを探す。"""
    for _ in range(_DRAW_ATTEMPTS):
        candidate = rng.randrange(draw_high - low + 1) + low
        if not taken(candidate):
            return candidate
    for candidate in range(low, high + 1):
        if not taken(candidate):
            return candidate
    raise RuntimeError("空いている村番号がありません")


class VillageRegistry:
    def __init__(self, rng: Rng | None = None, max_count: int = MAX_VILLAGE_COUNT) -> None:
        self._rng: Rng = rng if rng is not None else random.Random()
        self._max_count = max_count
        self._villages: list[Village] = []

    def add(self, village: Village) -> int:
        """空き番号を採番して登録し、番号を返す。上限を超えたら最古の村を消す。"""
        # Java と同じく抽選は MAX の 1 つ手前まで。MAX は総当たりでのみ採番される
        village.number = _draw_number(
            self._rng, lambda n: self.get(n) is not None, MIN_VILLAGE_NUMBER, MAX_VILLAGE_NUMBER, MAX_VILLAGE_NUMBER - 1
        )
        self._villages.append(village)
        if len(self._villages) > self._max_count:
            del self._villages[0]
        return village.number

    def get(self, number: int) -> Village | None:
        for village in self._villages:
            if village.number == number:
                return village
        return None

    def find_latest_owned(self, owner_id: str, predicate: Callable[[Village], bool]) -> Village | None:
        """所有者が一致し条件を満たす、最も新しい村。"""
        for village in reversed(self._villages):
            if village.owner_id == owner_id and predicate(village):
                return village
        return None


class SpecialVillageRegistry:
    def __init__(self, rng: Rng | None = None, max_count: int = MAX_SPECIAL_COUNT) -> None:
        self._rng: Rng = rng if rng is not None else random.Random()
        self._max_count = max_count
        self._villages: list[SpecialVillage] = []

    def add(self, village: SpecialVillage) -> int:
        village.number = _draw_number(
            self._rng, lambda n: self.get(n) is not None, MIN_SPECIAL_NUMBER, MAX_SPECIAL_NUMBER, MAX_SPECIAL_NUMBER
        )
        self._villages.append(village)
        if len(self._villages) > self._max_count:
            del self._villages[0]
        return village.number

    def get(self, number: int) -> SpecialVillage | None:
        for village in self._villages:
            if village.number == number:
                return village
        return None
