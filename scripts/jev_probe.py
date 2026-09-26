"""Jev の日本語判定精度を確認する使い捨てスクリプト。

実行: uv run --env-file .env python scripts/jev_probe.py
"""

import asyncio

from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulCriteria

VARIANTS = {
    "en": {
        "is_yes": Noul(
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
        ),
        "is_correct": Noul(
            instructions="Is `question` a direct guess that the secret answer is exactly `topic` itself?",
            criteria=NoulCriteria(
                true=(
                    "The player names `topic` (or a synonym or another spelling of it, "
                    "such as kanji instead of kana) as their single guess"
                ),
                false=(
                    "The question asks about a property or category, is negated "
                    "('isn't it X?'), compares something with `topic`, offers several "
                    "options, or names something that merely contains or relates to `topic`"
                ),
            ),
        ),
    },
    "ja": {
        "is_yes": Noul(
            instructions=(
                "当てっこゲームで、秘密のお題は `topic`（`hint` が空でなければその補足説明）です。"
                "プレイヤーがお題について `question` と質問しました。この質問への正しい答えは「はい」ですか？"
            ),
            criteria=NoulCriteria(
                true="`question` が尋ねている内容は `topic` に当てはまる",
                false="`question` が尋ねている内容は `topic` に当てはまらない",
            ),
        ),
        "is_correct": Noul(
            instructions="`question` は、秘密のお題が `topic` そのものだと直接言い当てようとしていますか？",
            criteria=NoulCriteria(
                true="プレイヤーが `topic`（または同義語や漢字・かな違いの表記）を 1 つの答えとして挙げている",
                false=(
                    "性質やカテゴリを尋ねている、否定形（〜ではない？）、`topic` との比較、"
                    "複数の選択肢、`topic` を含む・関係する別のものを挙げている"
                ),
            ),
        ),
    },
}

# (topic, hint, question, 期待する is_yes, 期待する is_correct)
CASES = [
    ("りんご", "", "果物ですか？", True, False),
    ("りんご", "", "赤いですか？", True, False),
    ("りんご", "", "動物ですか？", False, False),
    ("りんご", "", "食べられますか？", True, False),
    ("りんご", "", "林檎ですか？", True, True),
    ("りんご", "", "アップル？", True, True),
    ("りんご", "", "りんごではない？", False, False),
    ("りんご", "", "りんごより大きい？", False, False),
    ("りんご", "", "青りんごですか", False, False),
    ("りんご", "", "りんごかみかん？", True, False),
    ("東京タワー", "", "建物ですか？", True, False),
    ("東京タワー", "", "日本にありますか？", True, False),
    ("東京タワー", "", "スカイツリー？", False, False),
    ("猫", "ペットとして飼われる動物", "犬ですか？", False, False),
    ("猫", "ペットとして飼われる動物", "ネコ？", True, True),
]


def mark(prob: float, expected: bool, threshold: float) -> str:
    return "OK " if (prob >= threshold) == expected else "NG "


async def main() -> None:
    async with AsyncTypeSafeClient() as client:
        for name, questions in VARIANTS.items():
            yes_ok = correct_ok = 0
            print(f"\n=== variant: {name} ===")
            print("is_yes      is_correct  topic / question")
            for topic, hint, question, want_yes, want_correct in CASES:
                result = await client.system_one(
                    state={"topic": topic, "hint": hint, "question": question},
                    questions=questions,
                )
                y = result.nouls["is_yes"].noul
                c = result.nouls["is_correct"].noul
                yes_ok += (y >= 0.5) == want_yes
                correct_ok += (c >= 0.8) == want_correct
                print(
                    f"{mark(y, want_yes, 0.5)}{y:5.2f}   {mark(c, want_correct, 0.8)}{c:5.2f}   "
                    f"{topic} / {question}"
                )
            print(f"is_yes 正答 {yes_ok}/{len(CASES)}  is_correct 正答 {correct_ok}/{len(CASES)}")


if __name__ == "__main__":
    asyncio.run(main())
