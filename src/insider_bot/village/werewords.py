"""Werewords の配布メッセージ列。占師 1・インサイダー 1・残りは村人で、1 つの役職が「欠け」として抜ける。

神モード: 人数ぶんのメッセージ。先頭は GM 向けで、どの役職が欠けたかを伝える。
神モードでない: 人数 + 1 通。オーナー自身も入室し、オーナーが受け取った役職が欠けた役職になる。
並び替えは特殊村の作成時にもう一度行われるので、ここでの shuffle は「欠け」を選ぶためのもの。
"""

from __future__ import annotations

from insider_bot.village import texts
from insider_bot.village.model import Rng

# 占師・インサイダー・村人で 3 人必要
MIN_WEREWORDS_SIZE = 3

_SEER, _INSIDER, _VILLAGER, _GAME_MASTER = 1, 2, 3, 4


def role_name(role_number: int) -> str:
    return texts.WEREWORDS_ROLES[role_number]


def _message(role_number: int, topic: str, missing: str) -> str:
    return texts.WEREWORDS_MESSAGES[role_number].format(topic, missing)


def werewords_messages(god_mode: bool, size: int, topic: str, rng: Rng) -> list[str]:
    roles = [_SEER, _INSIDER] + [_VILLAGER] * (size - 2)
    rng.shuffle(roles)
    missing = role_name(roles[0])
    if god_mode:
        return [_message(_GAME_MASTER, topic, missing)] + [_message(role, topic, missing) for role in roles[1:]]
    return [_message(_VILLAGER, topic, missing)] + [_message(role, topic, missing) for role in roles]
