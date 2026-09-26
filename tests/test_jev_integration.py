import os

import pytest
from typesafe_sdk import AsyncTypeSafeClient

from insider_bot.judge import JevJudge

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY が未設定"),
]


@pytest.mark.parametrize(
    ("question", "want_yes", "want_correct"),
    [
        ("果物ですか？", True, False),
        ("動物ですか？", False, False),
        ("林檎ですか？", True, True),
        ("りんごではない？", False, False),
    ],
)
async def test_jev_judges_japanese_questions(question, want_yes, want_correct):
    async with AsyncTypeSafeClient() as client:
        verdict = await JevJudge(client, 0.8, 10).judge("りんご", "", question)
    assert (verdict.yes_prob >= 0.5) == want_yes
    assert verdict.is_correct == want_correct
