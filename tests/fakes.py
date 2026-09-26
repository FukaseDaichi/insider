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
