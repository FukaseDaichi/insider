"""質問を判定する：表記ゆれの正規化、完全一致の即決、Jev への問い合わせ。"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal, Protocol

# NFKC 後は全角の ？！．， が半角になるため、両方を列挙しておく
_TRAILING_MARKS = "？?！!。．.、，,"
# 長いものから順に照合する
_QUESTION_ENDINGS = ("でしょうか", "ですか", "だよね", "ですね", "かな", "だね")


def _katakana_to_hiragana(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def normalize(text: str) -> str:
    """即決の比較用に表記ゆれをそろえる。長音や記号は意味を持つので残す。"""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _katakana_to_hiragana(text)
    return "".join(c for c in text if not c.isspace())


def extract_guess(question: str) -> set[str]:
    """質問から「お題そのものを言った」とみなせる候補を取り出す。"""
    base = normalize(question).rstrip(_TRAILING_MARKS)
    candidates = {base}
    for ending in _QUESTION_ENDINGS:
        if base.endswith(ending):
            candidates.add(base[: -len(ending)])
            break
    candidates.discard("")
    return candidates


def is_exact_guess(topic: str, question: str) -> bool:
    target = normalize(topic)
    return bool(target) and target in extract_guess(question)


@dataclass(frozen=True)
class Verdict:
    yes_prob: float
    is_correct: bool
    source: Literal["exact", "jev"]


class JudgeError(Exception):
    """判定に失敗した（API エラー・タイムアウト等）。"""


class Judge(Protocol):
    async def judge(self, topic: str, hint: str, question: str) -> Verdict: ...
