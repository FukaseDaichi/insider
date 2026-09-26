import asyncio
from types import SimpleNamespace

import pytest
from typesafe_sdk import TypeSafeError

from insider_bot.judge import JevJudge, JudgeError, Verdict


class FakeClient:
    def __init__(self, is_yes=0.82, is_correct=0.1, error=None, delay=0.0):
        self.is_yes, self.is_correct, self.error, self.delay = is_yes, is_correct, error, delay
        self.calls = []

    async def system_one(self, *, state, questions):
        self.calls.append((state, questions))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return SimpleNamespace(
            nouls={
                "is_yes": SimpleNamespace(noul=self.is_yes),
                "is_correct": SimpleNamespace(noul=self.is_correct),
            }
        )


async def test_exact_guess_skips_jev():
    client = FakeClient()
    verdict = await JevJudge(client, 0.8, 10).judge("りんご", "", "リンゴですか？")
    assert verdict == Verdict(1.0, True, "exact")
    assert client.calls == []


async def test_sends_state_and_both_questions():
    client = FakeClient()
    await JevJudge(client, 0.8, 10).judge("りんご", "赤い果物", "果物ですか？")
    state, questions = client.calls[0]
    assert state == {"topic": "りんご", "hint": "赤い果物", "question": "果物ですか？"}
    assert set(questions) == {"is_yes", "is_correct"}


async def test_not_correct_below_threshold():
    verdict = await JevJudge(FakeClient(is_yes=0.82, is_correct=0.79), 0.8, 10).judge("りんご", "", "果物？")
    assert verdict == Verdict(0.82, False, "jev")


async def test_correct_at_threshold():
    verdict = await JevJudge(FakeClient(is_yes=0.9, is_correct=0.8), 0.8, 10).judge("りんご", "", "林檎？")
    assert verdict == Verdict(0.9, True, "jev")


async def test_sdk_error_becomes_judge_error():
    client = FakeClient(error=TypeSafeError("boom"))
    with pytest.raises(JudgeError):
        await JevJudge(client, 0.8, 10).judge("りんご", "", "果物？")


async def test_timeout_becomes_judge_error():
    client = FakeClient(delay=1.0)
    with pytest.raises(JudgeError):
        await JevJudge(client, 0.8, 0.01).judge("りんご", "", "果物？")


async def test_missing_answer_becomes_judge_error():
    class BrokenClient(FakeClient):
        async def system_one(self, *, state, questions):
            return SimpleNamespace(nouls={})

    with pytest.raises(JudgeError):
        await JevJudge(BrokenClient(), 0.8, 10).judge("りんご", "", "果物？")
