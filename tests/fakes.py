"""テスト用の偽物。"""

from __future__ import annotations

import asyncio

from insider_bot.judge import Verdict


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeJudge:
    """質問文ごとに決めた Verdict を返す。gate を渡すと set されるまで判定中のまま止まる。"""

    def __init__(
        self,
        default: Verdict = Verdict(0.82, False, "jev"),
        answers: dict[str, Verdict] | None = None,
        error: Exception | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.default = default
        self.answers = answers or {}
        self.error = error
        self.gate = gate
        self.calls: list[tuple[str, str, str]] = []

    async def judge(self, topic: str, hint: str, question: str) -> Verdict:
        self.calls.append((topic, hint, question))
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return self.answers.get(question, self.default)


class FixedRandom:
    """randrange が与えた値を順に返す乱数。shuffle は並びを変えない。

    Java の FixedRandom（nextInt が固定値を返す）に対応する。配役の席を固定するために使う。
    """

    def __init__(self, *values: int) -> None:
        self._values = list(values)

    def randrange(self, n: int) -> int:
        if not self._values:
            raise AssertionError("FixedRandom の値を使い切りました")
        value = self._values.pop(0)
        if not 0 <= value < n:
            raise AssertionError(f"FixedRandom の値 {value} が範囲 [0, {n}) の外です")
        return value

    def shuffle(self, seq: list) -> None:
        return None
