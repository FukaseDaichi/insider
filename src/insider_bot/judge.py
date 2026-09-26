"""質問を判定する：表記ゆれの正規化、完全一致の即決、Jev への問い合わせ。"""

from __future__ import annotations

import asyncio
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from typesafe_sdk import Noul, NoulCriteria, TypeSafeError

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


IS_YES = Noul(
    instructions=(
        "In a guessing game, the secret answer is `topic` "
        "(`hint` describes it further when not empty). "
        "A player asked `question` about the secret answer. "
        "Is the correct answer to the player's question 'yes'?"
    ),
    criteria=NoulCriteria(
        true="What `question` asks is true of `topic`",
        false="What `question` asks is false of `topic`",
    ),
)

# 正解判定は日本語の指示文の方が、しきい値 0.8 に対する余裕が大きかった（scripts/jev_probe.py の検証結果）
IS_CORRECT = Noul(
    instructions="`question` は、秘密のお題が `topic` そのものだと直接言い当てようとしていますか？",
    criteria=NoulCriteria(
        true="プレイヤーが `topic`（または同義語や漢字・かな違いの表記）を 1 つの答えとして挙げている",
        false=(
            "性質やカテゴリを尋ねている、否定形（〜ではない？）、`topic` との比較、"
            "複数の選択肢、`topic` を含む・関係する別のものを挙げている"
        ),
    ),
)

_QUESTIONS = {"is_yes": IS_YES, "is_correct": IS_CORRECT}


class JevJudge:
    """完全一致なら即決、それ以外は Jev に 2 つの Noul を 1 リクエストで問い合わせる。"""

    def __init__(self, client: Any, correct_threshold: float, timeout: float) -> None:
        self._client = client
        self._correct_threshold = correct_threshold
        self._timeout = timeout

    async def judge(self, topic: str, hint: str, question: str) -> Verdict:
        if is_exact_guess(topic, question):
            return Verdict(yes_prob=1.0, is_correct=True, source="exact")
        try:
            result = await asyncio.wait_for(
                self._client.system_one(
                    state={"topic": topic, "hint": hint, "question": question},
                    questions=_QUESTIONS,
                ),
                timeout=self._timeout,
            )
            yes_prob = result.nouls["is_yes"].noul
            correct_prob = result.nouls["is_correct"].noul
        except (TypeSafeError, TimeoutError, KeyError) as error:
            raise JudgeError(str(error) or type(error).__name__) from error
        return Verdict(
            yes_prob=yes_prob,
            is_correct=correct_prob >= self._correct_threshold,
            source="jev",
        )
