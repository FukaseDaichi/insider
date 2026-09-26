# お題当てゲーム GM ボット Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 出題者が登録したお題について、参加者の質問に TypeSafe AI の Jev で「はい／いいえ（割合つき）／正解です」を返す Discord ボットを作る。

**Architecture:** Discord 非依存のゲーム中核（`game.py` / `judge.py` / `format.py` / `service.py`）と、薄い Discord アダプター（`bot.py`）に分ける。質問の入口は `GameService.handle_question` の 1 か所で、戻り値は公開／非公開の本文を持つ `Outcome`。同一チャンネルの操作は `asyncio.Lock` で直列化し、`game_id` で古い質問を排除する。

**Tech Stack:** Python 3.13 / uv / discord.py 2.x / typesafe-sdk（`AsyncTypeSafeClient`, `Noul`）/ pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-09-26-odai-gm-bot-design.md`

## Global Constraints

- Python 3.13。**すべてのコマンドは uv 経由**（`uv add` / `uv run` / `uv run pytest`）。pip・venv・システム Python は使わない。
- 依存は `discord.py`、`typesafe-sdk`（本体）、`pytest`、`pytest-asyncio`（開発用）のみ。設定の読み込みは `uv run --env-file .env`（dotenv ライブラリは入れない）。
- お題 1〜50 文字、補足 0〜300 文字。表示する質問文は 200 文字超で先頭 200 文字＋「…」。
- 割合バーは 12 マス。`CORRECT_THRESHOLD` 既定 0.8、`JEV_TIMEOUT_SECONDS` 既定 10。
- 返信文言は仕様書 §3 の文言をそのまま使う（`🎮 ゲーム開始！…`、`🎉 正解です！お題は「…」でした`、`🏳️ ギブアップ！お題は『…』でした（質問数: N）`、`⚠️ 判定できませんでした。もう一度どうぞ`、`進行中のゲームはありません`、`このチャンネルではゲームが進行中です`）。
- `.env` は Git に含めない。
- コミットメッセージの末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` を付ける。

### 仕様書からの小さな確定事項（Task 1 で仕様書にも反映する）

- `Game` に `setter_name` を持たせる（`/odai status` で出題者名を表示するため）。
- 「はい／いいえ」のラベルは、**四捨五入後の割合が 50% 以上なら「はい」**で決める（`yes_prob=0.496` が「❌ いいえ　はい 50%」と矛盾表示になるのを防ぐ）。

## Review Focus

1. **質問文に `@everyone` やメンションが含まれる** → ボットの返信（質問の引用）で全員に通知が飛んではいけない。Task 8 で `allowed_mentions=AllowedMentions.none()` をクライアント全体に設定し、手動確認手順に含める。
2. **Jev の確率が 0.495 付近** → ラベルと割合表示が矛盾しない（「はい 50%」なら「✅ はい」）。Task 4 のテストで固定。
3. **お題が空白だけ／前後に全角空白付きで登録される** → 空白だけなら登録を断り、前後の空白は除いて保存する。Task 6 のテストで固定。
4. **質問が「？？」や記号だけ** → 即決の候補が空になっても落ちず、Jev に回る。Task 2 のテストで固定。
5. **1 時間を超えるゲーム** → 経過時間が「1時間2分3秒」の形で正しく出る。Task 4 のテストで固定。

---

## File Structure

| パス | 責務 |
|---|---|
| `pyproject.toml` | uv プロジェクト定義、依存、pytest 設定、エントリポイント |
| `.env.example` / `.gitignore` | 設定雛形 / Git 除外 |
| `scripts/jev_probe.py` | Task 1 の日本語検証スクリプト（実 API を叩いて表を出す） |
| `src/insider_bot/__init__.py` | パッケージ（空） |
| `src/insider_bot/judge.py` | `normalize` / `extract_guess` / `is_exact_guess` / `Verdict` / `JudgeError` / `Judge` / `JevJudge` |
| `src/insider_bot/game.py` | `Game` / `GameManager` / `GameAlreadyRunning` |
| `src/insider_bot/format.py` | 返信文を組み立てる純粋関数 |
| `src/insider_bot/service.py` | `Outcome` / `GameService`（排他制御と進行） |
| `src/insider_bot/config.py` | `Config` / `ConfigError` / `load_config` |
| `src/insider_bot/bot.py` | discord.py アダプター（`OdaiBot`、`/odai` コマンド群） |
| `src/insider_bot/__main__.py` | 組み立てと起動 |
| `tests/__init__.py` / `tests/fakes.py` | テスト用の偽物（`FakeJudge`, `FakeClock`） |
| `tests/test_*.py` | 各ユニットのテスト |
| `README.md` | セットアップと遊び方 |

---

### Task 1: プロジェクト雛形と Jev 日本語検証（判断ゲートあり）

**Files:**
- Create: `pyproject.toml`（uv init で生成後に編集）, `.python-version`, `.gitignore`, `.env.example`, `src/insider_bot/__init__.py`, `tests/__init__.py`, `scripts/jev_probe.py`
- Modify: `docs/superpowers/specs/2026-09-26-odai-gm-bot-design.md`（上記「小さな確定事項」を反映）

**Interfaces:**
- Consumes: なし
- Produces: uv プロジェクト（`uv run pytest` が動く状態）、Jev への指示文の採用案（英語案 or 日本語案）

- [ ] **Step 1: uv プロジェクトを作る**

```bash
cd /Users/fukasedaichi/git/insider
uv init --package --name insider-bot --python 3.13 --vcs none --no-readme .
uv add "discord.py>=2.6" typesafe-sdk
uv add --dev pytest pytest-asyncio
```

Expected: `pyproject.toml`、`.python-version`（`3.13`）、`src/insider_bot/__init__.py`、`uv.lock` ができる。

- [ ] **Step 2: pyproject.toml を整える**

`src/insider_bot/__init__.py` の中身（uv が生成した `main` 関数）を空にする:

```python
```

`pyproject.toml` の `[project.scripts]` を次に置き換え、末尾に pytest 設定を追記する:

```toml
[project.scripts]
insider-bot = "insider_bot.__main__:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
testpaths = ["tests"]
markers = ["integration: 実際の TypeSafe API を呼ぶテスト（TYPESAFE_API_KEY が必要）"]
addopts = "-m 'not integration'"
```

- [ ] **Step 3: .gitignore / .env.example / tests パッケージを作る**

`.gitignore`:

```gitignore
.env
.venv/
__pycache__/
.pytest_cache/
*.egg-info/
```

`.env.example`:

```dotenv
# Discord Developer Portal で発行したボットトークン
DISCORD_TOKEN=
# https://console.typesafe.ai で発行した API キー
TYPESAFE_API_KEY=
# 任意: 指定するとスラッシュコマンドをこのサーバーにだけ即時登録（開発向け）
DISCORD_GUILD_ID=
# 任意: 正解とみなす is_correct のしきい値（0〜1）
CORRECT_THRESHOLD=0.8
# 任意: Jev 呼び出しのタイムアウト秒数
JEV_TIMEOUT_SECONDS=10
```

`tests/__init__.py`: 空ファイル。

- [ ] **Step 4: 雛形の動作確認**

Run: `uv run pytest`
Expected: `no tests ran`（exit code 5）。エラーなく pytest が起動すること。

- [ ] **Step 5: 日本語検証スクリプトを書く**

`scripts/jev_probe.py`:

```python
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
```

- [ ] **Step 6: 検証を実行する（ユーザーの API キーが必要）**

`.env.example` を `.env` にコピーし、ユーザーに `TYPESAFE_API_KEY` を記入してもらう（エージェントはキーを入力・表示しない）。

Run: `uv run --env-file .env python scripts/jev_probe.py`
Expected: 2 つの案それぞれについて 15 行の表と正答数が出る。

- [ ] **Step 7: 判断ゲート — 結果をユーザーに報告して採用案を決める**

- 良い方の案で `is_yes` 12/15 以上かつ `is_correct` 13/15 以上 → その案を採用して続行。**日本語案（ja）を採用した場合は Task 5 の `IS_YES` / `IS_CORRECT` 定数を probe の `VARIANTS["ja"]` の内容に置き換える。**
- どちらの案も下回る → 実装を止め、結果の表をユーザーに見せて相談する（しきい値調整、指示文の改善、別方式の検討）。

- [ ] **Step 8: 仕様書に確定事項を反映する**

`docs/superpowers/specs/2026-09-26-odai-gm-bot-design.md` を次のとおり編集する:
- §3.2 の `` - `yes_prob >= 0.5` なら「✅ はい」、それ未満なら「❌ いいえ」。`` を
  `` - 四捨五入後の「はい」の割合が 50% 以上なら「✅ はい」、それ未満なら「❌ いいえ」（割合表示とラベルを一致させる）。`` に置き換える。
- §5.1 game.py の `Game` のフィールド列に `setter_name` を追加し、`GameManager.start` の引数を `start(channel_id, topic, hint, setter_id, setter_name) -> Game` にする。
- §8 の手順 1 の末尾に「（採用した指示文: en / ja）」と、Step 7 の結果を追記する。

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore .env.example src tests scripts docs
git commit -m "chore: uvプロジェクト雛形とJev日本語検証スクリプトを追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 表記ゆれの正規化と完全一致の即決判定

**Files:**
- Create: `src/insider_bot/judge.py`
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: なし
- Produces（`insider_bot.judge`）:
  - `normalize(text: str) -> str`
  - `extract_guess(question: str) -> set[str]`
  - `is_exact_guess(topic: str, question: str) -> bool`
  - `@dataclass(frozen=True) class Verdict: yes_prob: float; is_correct: bool; source: Literal["exact", "jev"]`
  - `class JudgeError(Exception)`
  - `class Judge(Protocol): async def judge(self, topic: str, hint: str, question: str) -> Verdict`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_matching.py`:

```python
import pytest

from insider_bot.judge import extract_guess, is_exact_guess, normalize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("リンゴ", "りんご"),
        ("ﾘﾝｺﾞ", "りんご"),
        ("ＡＰＰＬＥ", "apple"),
        ("り ん\tご\n", "りんご"),
        ("　りんご　", "りんご"),
        ("ビール", "びーる"),
        ("C++", "c++"),
    ],
)
def test_normalize(text, expected):
    assert normalize(text) == expected


def test_normalize_keeps_long_vowel_mark_so_beer_and_building_differ():
    assert normalize("ビール") != normalize("ビル")


@pytest.mark.parametrize(
    "question",
    ["リンゴ？", "ﾘﾝｺﾞ", "りんご", "りんごですか", "りんごですか？", "りんごでしょうか？！", "りんごかな？", "りんご!!"],
)
def test_exact_guess_matches(question):
    assert is_exact_guess("りんご", question)


@pytest.mark.parametrize(
    "question",
    ["りんごか？", "りんごではない？", "りんごより大きい？", "青りんごですか", "林檎", "りんごかみかん？"],
)
def test_exact_guess_does_not_match(question):
    assert not is_exact_guess("りんご", question)


def test_single_char_ending_is_not_stripped():
    assert not is_exact_guess("すい", "すいか？")


def test_topic_ending_with_question_like_suffix_still_matches():
    assert is_exact_guess("さかな", "さかな？")


def test_beer_does_not_match_building():
    assert not is_exact_guess("ビール", "ビル？")


def test_extract_guess_candidates():
    assert extract_guess("りんごですか？") == {"りんごですか", "りんご"}


@pytest.mark.parametrize("question", ["？？", "", "　", "!?"])
def test_punctuation_only_question_has_no_candidates(question):
    assert extract_guess(question) == set()
    assert not is_exact_guess("りんご", question)


def test_blank_topic_never_matches():
    assert not is_exact_guess("　", "")
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_matching.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'insider_bot.judge'`）

- [ ] **Step 3: 実装する**

`src/insider_bot/judge.py`:

```python
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
```

- [ ] **Step 4: 通ることを確認する**

Run: `uv run pytest tests/test_matching.py -v`
Expected: 全件 PASS

- [ ] **Step 5: Commit**

```bash
git add src/insider_bot/judge.py tests/test_matching.py
git commit -m "feat: 表記ゆれの正規化と完全一致の即決判定を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: ゲーム状態の管理

**Files:**
- Create: `src/insider_bot/game.py`, `tests/fakes.py`
- Test: `tests/test_game.py`

**Interfaces:**
- Consumes: なし
- Produces（`insider_bot.game`）:
  - `Clock = Callable[[], float]`
  - `@dataclass class Game: game_id: int; channel_id: int; topic: str; hint: str; setter_id: int; setter_name: str; started_at: float; question_count: int = 0`
  - `class GameAlreadyRunning(Exception)`
  - `class GameManager(clock: Clock = time.monotonic)`: `start(channel_id: int, topic: str, hint: str, setter_id: int, setter_name: str) -> Game`、`get(channel_id: int) -> Game | None`、`end(channel_id: int) -> Game | None`
- Produces（`tests.fakes`）: `FakeClock(now: float = 1000.0)` — 呼ぶと `now` を返す。`advance(seconds: float)` で進める。

- [ ] **Step 1: テスト用の時計を作る**

`tests/fakes.py`:

```python
"""テスト用の偽物。"""


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_game.py`:

```python
import pytest

from insider_bot.game import GameAlreadyRunning, GameManager
from tests.fakes import FakeClock


def test_start_creates_game_with_fields():
    manager = GameManager(clock=FakeClock(500.0))
    game = manager.start(1, "りんご", "赤い果物", 10, "出題者")
    assert (game.channel_id, game.topic, game.hint, game.setter_id, game.setter_name) == (
        1, "りんご", "赤い果物", 10, "出題者",
    )
    assert game.started_at == 500.0
    assert game.question_count == 0
    assert manager.get(1) is game


def test_one_game_per_channel():
    manager = GameManager()
    manager.start(1, "りんご", "", 10, "a")
    with pytest.raises(GameAlreadyRunning):
        manager.start(1, "みかん", "", 11, "b")


def test_channels_are_independent():
    manager = GameManager()
    a = manager.start(1, "りんご", "", 10, "a")
    b = manager.start(2, "みかん", "", 11, "b")
    assert manager.get(1) is a and manager.get(2) is b


def test_end_removes_and_returns_game():
    manager = GameManager()
    game = manager.start(1, "りんご", "", 10, "a")
    assert manager.end(1) is game
    assert manager.get(1) is None
    assert manager.end(1) is None


def test_game_ids_are_unique_even_in_same_channel():
    manager = GameManager()
    first = manager.start(1, "りんご", "", 10, "a")
    manager.end(1)
    second = manager.start(1, "りんご", "", 10, "a")
    assert first.game_id != second.game_id
```

- [ ] **Step 3: 失敗を確認する**

Run: `uv run pytest tests/test_game.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'insider_bot.game'`）

- [ ] **Step 4: 実装する**

`src/insider_bot/game.py`:

```python
"""ゲームの状態（1 チャンネル 1 ゲーム）。Discord や Jev には依存しない。"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from typing import Callable

Clock = Callable[[], float]


@dataclass
class Game:
    game_id: int
    channel_id: int
    topic: str
    hint: str
    setter_id: int
    setter_name: str
    started_at: float
    question_count: int = 0


class GameAlreadyRunning(Exception):
    """そのチャンネルでは既にゲームが進行中。"""


class GameManager:
    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._games: dict[int, Game] = {}
        self._ids = itertools.count(1)

    def start(self, channel_id: int, topic: str, hint: str, setter_id: int, setter_name: str) -> Game:
        if channel_id in self._games:
            raise GameAlreadyRunning(channel_id)
        game = Game(
            game_id=next(self._ids),
            channel_id=channel_id,
            topic=topic,
            hint=hint,
            setter_id=setter_id,
            setter_name=setter_name,
            started_at=self._clock(),
        )
        self._games[channel_id] = game
        return game

    def get(self, channel_id: int) -> Game | None:
        return self._games.get(channel_id)

    def end(self, channel_id: int) -> Game | None:
        return self._games.pop(channel_id, None)
```

- [ ] **Step 5: 通ることを確認する**

Run: `uv run pytest tests/test_game.py -v`
Expected: 全件 PASS

- [ ] **Step 6: Commit**

```bash
git add src/insider_bot/game.py tests/fakes.py tests/test_game.py
git commit -m "feat: チャンネルごとのゲーム状態管理を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 返信文の組み立て

**Files:**
- Create: `src/insider_bot/format.py`
- Test: `tests/test_format.py`

**Interfaces:**
- Consumes: `Verdict`（Task 2）、`Game`（Task 3）
- Produces（`insider_bot.format`）:
  - `yes_percent(yes_prob: float) -> int`
  - `format_duration(seconds: float) -> str`
  - `format_answer(question: str, verdict: Verdict) -> str`
  - `format_correct(game: Game, answerer_name: str, elapsed: float) -> str`
  - `format_giveup(game: Game) -> str`
  - `format_status(game: Game, elapsed: float) -> str`
  - `format_started(setter_name: str) -> str`
  - `format_registered(topic: str) -> str`
  - `format_already_running() -> str` / `format_no_game() -> str` / `format_error() -> str` / `format_invalid_topic() -> str`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_format.py`:

```python
import pytest

from insider_bot.format import (
    format_already_running,
    format_answer,
    format_correct,
    format_duration,
    format_error,
    format_giveup,
    format_invalid_topic,
    format_no_game,
    format_registered,
    format_started,
    format_status,
    yes_percent,
)
from insider_bot.game import Game
from insider_bot.judge import Verdict


def make_game(**overrides) -> Game:
    fields = dict(
        game_id=1, channel_id=1, topic="りんご", hint="", setter_id=10,
        setter_name="出題者", started_at=0.0, question_count=14,
    )
    fields.update(overrides)
    return Game(**fields)


@pytest.mark.parametrize(
    ("prob", "pct"),
    [(0.0, 0), (1.0, 100), (0.82, 82), (0.825, 83), (0.004, 0), (0.995, 100), (-0.1, 0), (1.2, 100)],
)
def test_yes_percent_rounds_half_up_and_clamps(prob, pct):
    assert yes_percent(prob) == pct


def test_format_answer_yes():
    text = format_answer("果物ですか？", Verdict(0.82, False, "jev"))
    assert text == "❓ 果物ですか？\n✅ はい　　はい 82% ██████████░░ いいえ 18%"


def test_format_answer_no():
    text = format_answer("動物ですか？", Verdict(0.1, False, "jev"))
    assert text == "❓ 動物ですか？\n❌ いいえ　　はい 10% █░░░░░░░░░░░ いいえ 90%"


def test_label_follows_rounded_percent_at_boundary():
    # 0.496 は 50% と表示されるので、ラベルも「はい」にそろえる
    assert "✅ はい　　はい 50%" in format_answer("q", Verdict(0.496, False, "jev"))
    assert "❌ いいえ　　はい 49%" in format_answer("q", Verdict(0.494, False, "jev"))


def test_long_question_is_truncated_for_display():
    text = format_answer("あ" * 250, Verdict(0.5, False, "jev"))
    first_line = text.split("\n")[0]
    assert first_line == "❓ " + "あ" * 200 + "…"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0秒"), (45.9, "45秒"), (392, "6分32秒"), (3723, "1時間2分3秒"), (3600, "1時間0分0秒")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_format_correct():
    text = format_correct(make_game(), "回答者", 392)
    assert text == "🎉 正解です！お題は「りんご」でした\n正解者: 回答者　質問数: 14　経過時間: 6分32秒"


def test_format_giveup():
    assert format_giveup(make_game(question_count=3)) == "🏳️ ギブアップ！お題は『りんご』でした（質問数: 3）"


def test_format_status_does_not_reveal_topic():
    text = format_status(make_game(question_count=5), 65)
    assert text == "進行中のゲーム　出題者: 出題者　質問数: 5　経過時間: 1分5秒"
    assert "りんご" not in text


def test_fixed_messages():
    assert format_started("出題者") == "🎮 ゲーム開始！出題者さんがお題を出しました。質問をどうぞ"
    assert format_registered("りんご") == "お題『りんご』を登録しました"
    assert format_already_running() == "このチャンネルではゲームが進行中です"
    assert format_no_game() == "進行中のゲームはありません"
    assert format_error() == "⚠️ 判定できませんでした。もう一度どうぞ"
    assert format_invalid_topic() == "お題を入力してください"
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_format.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'insider_bot.format'`）

- [ ] **Step 3: 実装する**

`src/insider_bot/format.py`:

```python
"""返信文を組み立てる純粋関数。"""

from __future__ import annotations

import math

from insider_bot.game import Game
from insider_bot.judge import Verdict

BAR_CELLS = 12
QUESTION_DISPLAY_LIMIT = 200


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def yes_percent(yes_prob: float) -> int:
    return _round_half_up(min(max(yes_prob, 0.0), 1.0) * 100)


def format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}時間{minutes}分{secs}秒"
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"


def _shorten(question: str) -> str:
    if len(question) <= QUESTION_DISPLAY_LIMIT:
        return question
    return question[:QUESTION_DISPLAY_LIMIT] + "…"


def format_answer(question: str, verdict: Verdict) -> str:
    yes = yes_percent(verdict.yes_prob)
    label = "✅ はい" if yes >= 50 else "❌ いいえ"
    filled = _round_half_up(yes / 100 * BAR_CELLS)
    bar = "█" * filled + "░" * (BAR_CELLS - filled)
    return f"❓ {_shorten(question)}\n{label}　　はい {yes}% {bar} いいえ {100 - yes}%"


def format_correct(game: Game, answerer_name: str, elapsed: float) -> str:
    return (
        f"🎉 正解です！お題は「{game.topic}」でした\n"
        f"正解者: {answerer_name}　質問数: {game.question_count}　経過時間: {format_duration(elapsed)}"
    )


def format_giveup(game: Game) -> str:
    return f"🏳️ ギブアップ！お題は『{game.topic}』でした（質問数: {game.question_count}）"


def format_status(game: Game, elapsed: float) -> str:
    return (
        f"進行中のゲーム　出題者: {game.setter_name}　"
        f"質問数: {game.question_count}　経過時間: {format_duration(elapsed)}"
    )


def format_started(setter_name: str) -> str:
    return f"🎮 ゲーム開始！{setter_name}さんがお題を出しました。質問をどうぞ"


def format_registered(topic: str) -> str:
    return f"お題『{topic}』を登録しました"


def format_already_running() -> str:
    return "このチャンネルではゲームが進行中です"


def format_no_game() -> str:
    return "進行中のゲームはありません"


def format_error() -> str:
    return "⚠️ 判定できませんでした。もう一度どうぞ"


def format_invalid_topic() -> str:
    return "お題を入力してください"
```

- [ ] **Step 4: 通ることを確認する**

Run: `uv run pytest tests/test_format.py -v`
Expected: 全件 PASS

- [ ] **Step 5: Commit**

```bash
git add src/insider_bot/format.py tests/test_format.py
git commit -m "feat: 回答・正解・ギブアップ等の返信文を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Jev による判定（JevJudge）

**Files:**
- Modify: `src/insider_bot/judge.py`（末尾に追加、先頭の import を拡張）
- Test: `tests/test_jev_judge.py`, `tests/test_jev_integration.py`

**Interfaces:**
- Consumes: `is_exact_guess`, `Verdict`, `JudgeError`（Task 2）
- Produces（`insider_bot.judge`）:
  - `IS_YES: Noul`, `IS_CORRECT: Noul`（Task 1 で採用した案の指示文）
  - `class JevJudge(client, correct_threshold: float, timeout: float)` — `client` は `AsyncTypeSafeClient` 互換（`async system_one(state=..., questions=...)` を持ち、戻り値の `.nouls[name].noul` が float）。`async judge(topic, hint, question) -> Verdict`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_jev_judge.py`:

```python
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
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_jev_judge.py -v`
Expected: FAIL（`ImportError: cannot import name 'JevJudge'`）

- [ ] **Step 3: 実装する**

`src/insider_bot/judge.py` の import を次に置き換える:

```python
from __future__ import annotations

import asyncio
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from typesafe_sdk import Noul, NoulCriteria, TypeSafeError
```

`src/insider_bot/judge.py` の末尾に追加する（Task 1 で日本語案を採用した場合は `IS_YES` / `IS_CORRECT` を `scripts/jev_probe.py` の `VARIANTS["ja"]` の内容にする）:

```python
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

IS_CORRECT = Noul(
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
```

- [ ] **Step 4: 通ることを確認する**

Run: `uv run pytest tests/test_jev_judge.py tests/test_matching.py -v`
Expected: 全件 PASS

- [ ] **Step 5: 実 API の結合テストを書く**

`tests/test_jev_integration.py`:

```python
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
```

- [ ] **Step 6: 結合テストを実行する**

Run: `uv run --env-file .env pytest -m integration -v`
Expected: 4 件 PASS（キー未設定なら SKIPPED）。FAIL した場合は結果をユーザーに報告する（Task 1 の検証と同じ指示文なので、通常は通る）。

Run: `uv run pytest`
Expected: 結合テストは除外され、他は全件 PASS

- [ ] **Step 7: Commit**

```bash
git add src/insider_bot/judge.py tests/test_jev_judge.py tests/test_jev_integration.py
git commit -m "feat: Jevによる判定（JevJudge）を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: ゲーム進行（GameService）

**Files:**
- Create: `src/insider_bot/service.py`
- Modify: `tests/fakes.py`（`FakeJudge` を追加）
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `GameManager`, `GameAlreadyRunning`, `Clock`（Task 3）、`Judge`, `JudgeError`, `Verdict`（Task 2）、`format_*`（Task 4）
- Produces（`insider_bot.service`）:
  - `@dataclass(frozen=True) class Outcome: private: str | None = None; public: str | None = None`
  - `class GameService(manager: GameManager, judge: Judge, clock: Clock = time.monotonic)`
    - `async start(channel_id: int, setter_id: int, setter_name: str, topic: str, hint: str) -> Outcome`
    - `async status(channel_id: int) -> Outcome`
    - `async giveup(channel_id: int) -> Outcome`
    - `async handle_question(channel_id: int, author_id: int, author_name: str, text: str) -> Outcome`
- Produces（`tests.fakes`）: `FakeJudge(default: Verdict = Verdict(0.82, False, "jev"), answers: dict[str, Verdict] | None = None, error: Exception | None = None, gate: asyncio.Event | None = None)` — `calls: list[tuple[str, str, str]]`

- [ ] **Step 1: FakeJudge を追加する**

`tests/fakes.py` を次の内容にする:

```python
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
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_service.py`:

```python
import asyncio

from insider_bot.game import GameManager
from insider_bot.judge import JudgeError, Verdict
from insider_bot.service import GameService, Outcome
from tests.fakes import FakeClock, FakeJudge

CH = 1
SETTER = 10
PLAYER = 20
CORRECT = Verdict(1.0, True, "exact")


def make(judge=None):
    clock = FakeClock()
    judge = judge or FakeJudge()
    manager = GameManager(clock=clock)
    return GameService(manager, judge, clock=clock), manager, judge, clock


async def started(judge=None, topic="りんご", hint=""):
    service, manager, judge, clock = make(judge)
    await service.start(CH, SETTER, "出題者", topic, hint)
    return service, manager, judge, clock


async def wait_until(predicate):
    while not predicate():
        await asyncio.sleep(0)


# --- start / status / giveup ---


async def test_start_returns_private_confirmation_and_public_announcement():
    service, manager, _, _ = make()
    outcome = await service.start(CH, SETTER, "出題者", "りんご", "赤い果物")
    assert outcome == Outcome(
        private="お題『りんご』を登録しました",
        public="🎮 ゲーム開始！出題者さんがお題を出しました。質問をどうぞ",
    )
    assert manager.get(CH).hint == "赤い果物"


async def test_start_strips_whitespace_around_topic_and_hint():
    service, manager, _, _ = make()
    await service.start(CH, SETTER, "出題者", "　りんご ", " 赤い ")
    game = manager.get(CH)
    assert (game.topic, game.hint) == ("りんご", "赤い")


async def test_start_rejects_blank_topic():
    service, manager, _, _ = make()
    outcome = await service.start(CH, SETTER, "出題者", "　 ", "")
    assert outcome == Outcome(private="お題を入力してください")
    assert manager.get(CH) is None


async def test_start_while_running_is_private_error():
    service, manager, _, _ = await started()
    outcome = await service.start(CH, 99, "別の人", "みかん", "")
    assert outcome == Outcome(private="このチャンネルではゲームが進行中です")
    assert manager.get(CH).topic == "りんご"


async def test_status_without_game():
    service, _, _, _ = make()
    assert await service.status(CH) == Outcome(private="進行中のゲームはありません")


async def test_status_with_game_is_private():
    service, _, _, clock = await started()
    await service.handle_question(CH, PLAYER, "p", "果物？")
    clock.advance(65)
    assert await service.status(CH) == Outcome(
        private="進行中のゲーム　出題者: 出題者　質問数: 1　経過時間: 1分5秒"
    )


async def test_giveup_reveals_topic_publicly_and_ends():
    service, manager, _, _ = await started()
    await service.handle_question(CH, PLAYER, "p", "果物？")
    assert await service.giveup(CH) == Outcome(public="🏳️ ギブアップ！お題は『りんご』でした（質問数: 1）")
    assert manager.get(CH) is None


async def test_giveup_without_game_is_private():
    service, _, _, _ = make()
    assert await service.giveup(CH) == Outcome(private="進行中のゲームはありません")


# --- handle_question ---


async def test_question_without_game_is_ignored():
    service, _, judge, _ = make()
    assert await service.handle_question(CH, PLAYER, "p", "果物？") == Outcome()
    assert judge.calls == []


async def test_question_gets_public_answer_and_counts():
    service, manager, judge, _ = await started(hint="赤い果物")
    outcome = await service.handle_question(CH, PLAYER, "p", "果物ですか？")
    assert outcome == Outcome(public="❓ 果物ですか？\n✅ はい　　はい 82% ██████████░░ いいえ 18%")
    assert judge.calls == [("りんご", "赤い果物", "果物ですか？")]
    assert manager.get(CH).question_count == 1


async def test_setter_and_blank_messages_are_ignored():
    service, manager, judge, _ = await started()
    assert await service.handle_question(CH, SETTER, "出題者", "果物？") == Outcome()
    assert await service.handle_question(CH, PLAYER, "p", " \n　") == Outcome()
    assert judge.calls == []
    assert manager.get(CH).question_count == 0


async def test_correct_answer_ends_game_and_counts_winning_question():
    judge = FakeJudge(answers={"りんご？": CORRECT})
    service, manager, _, clock = await started(judge)
    clock.advance(392)
    outcome = await service.handle_question(CH, PLAYER, "回答者", "りんご？")
    assert outcome == Outcome(
        public="🎉 正解です！お題は「りんご」でした\n正解者: 回答者　質問数: 1　経過時間: 6分32秒"
    )
    assert manager.get(CH) is None


async def test_judge_error_replies_and_does_not_count():
    service, manager, _, _ = await started(FakeJudge(error=JudgeError("down")))
    outcome = await service.handle_question(CH, PLAYER, "p", "果物？")
    assert outcome == Outcome(public="⚠️ 判定できませんでした。もう一度どうぞ")
    assert manager.get(CH).question_count == 0


# --- 排他制御 ---


async def test_two_simultaneous_correct_guesses_announce_once():
    gate = asyncio.Event()
    service, _, judge, _ = await started(FakeJudge(default=CORRECT, gate=gate))
    first = asyncio.create_task(service.handle_question(CH, PLAYER, "a", "りんご？"))
    await wait_until(lambda: judge.calls)
    second = asyncio.create_task(service.handle_question(CH, 21, "b", "りんご！"))
    await asyncio.sleep(0)
    gate.set()
    outcomes = [await first, await second]
    assert sum("正解です" in (o.public or "") for o in outcomes) == 1
    assert outcomes[1] == Outcome()
    assert len(judge.calls) == 1


async def test_giveup_waits_for_in_flight_question():
    gate = asyncio.Event()
    service, _, judge, _ = await started(FakeJudge(default=Verdict(0.3, False, "jev"), gate=gate))
    question = asyncio.create_task(service.handle_question(CH, PLAYER, "p", "動物？"))
    await wait_until(lambda: judge.calls)
    giveup = asyncio.create_task(service.giveup(CH))
    await asyncio.sleep(0)
    assert not giveup.done()
    gate.set()
    assert (await question).public.startswith("❓ 動物？")
    assert await giveup == Outcome(public="🏳️ ギブアップ！お題は『りんご』でした（質問数: 1）")


async def test_giveup_after_in_flight_correct_answer_finds_no_game():
    gate = asyncio.Event()
    service, _, judge, _ = await started(FakeJudge(default=CORRECT, gate=gate))
    question = asyncio.create_task(service.handle_question(CH, PLAYER, "p", "りんご？"))
    await wait_until(lambda: judge.calls)
    giveup = asyncio.create_task(service.giveup(CH))
    await asyncio.sleep(0)
    gate.set()
    assert "正解です" in (await question).public
    assert await giveup == Outcome(private="進行中のゲームはありません")


async def test_stale_question_is_not_judged_in_next_game():
    gate = asyncio.Event()
    service, manager, judge, _ = await started(FakeJudge(gate=gate))
    in_flight = asyncio.create_task(service.handle_question(CH, PLAYER, "p", "果物？"))
    await wait_until(lambda: judge.calls)
    giveup = asyncio.create_task(service.giveup(CH))
    await asyncio.sleep(0)
    restart = asyncio.create_task(service.start(CH, 30, "次の出題者", "みかん", ""))
    await asyncio.sleep(0)
    # 旧ゲームがまだ残っている間に届いた質問（旧ゲームの game_id を記録してロック待ちになる）
    stale = asyncio.create_task(service.handle_question(CH, PLAYER, "p", "丸いですか？"))
    await asyncio.sleep(0)
    gate.set()
    await in_flight
    await giveup
    await restart
    assert await stale == Outcome()
    assert len(judge.calls) == 1
    game = manager.get(CH)
    assert (game.topic, game.question_count) == ("みかん", 0)
```

- [ ] **Step 3: 失敗を確認する**

Run: `uv run pytest tests/test_service.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'insider_bot.service'`）

- [ ] **Step 4: 実装する**

`src/insider_bot/service.py`:

```python
"""ゲーム進行の中核。Discord に依存しないので、テキストでも音声でも同じ入口を使う。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from insider_bot import format as fmt
from insider_bot.game import Clock, GameAlreadyRunning, GameManager
from insider_bot.judge import Judge, JudgeError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Outcome:
    """private は操作した本人だけに見せる本文、public はチャンネルに投稿する本文。"""

    private: str | None = None
    public: str | None = None


IGNORED = Outcome()


class GameService:
    def __init__(self, manager: GameManager, judge: Judge, clock: Clock = time.monotonic) -> None:
        self._manager = manager
        self._judge = judge
        self._clock = clock
        # チャンネルごとのロック。参加チャンネル数ぶんしか増えないので削除しない
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, channel_id: int) -> asyncio.Lock:
        return self._locks.setdefault(channel_id, asyncio.Lock())

    async def start(self, channel_id: int, setter_id: int, setter_name: str, topic: str, hint: str) -> Outcome:
        topic, hint = topic.strip(), hint.strip()
        if not topic:
            return Outcome(private=fmt.format_invalid_topic())
        async with self._lock(channel_id):
            try:
                self._manager.start(channel_id, topic, hint, setter_id, setter_name)
            except GameAlreadyRunning:
                return Outcome(private=fmt.format_already_running())
        return Outcome(private=fmt.format_registered(topic), public=fmt.format_started(setter_name))

    async def status(self, channel_id: int) -> Outcome:
        async with self._lock(channel_id):
            game = self._manager.get(channel_id)
            if game is None:
                return Outcome(private=fmt.format_no_game())
            return Outcome(private=fmt.format_status(game, self._clock() - game.started_at))

    async def giveup(self, channel_id: int) -> Outcome:
        async with self._lock(channel_id):
            game = self._manager.end(channel_id)
            if game is None:
                return Outcome(private=fmt.format_no_game())
            return Outcome(public=fmt.format_giveup(game))

    async def handle_question(self, channel_id: int, author_id: int, author_name: str, text: str) -> Outcome:
        """channel_id はゲームを登録したテキストチャンネルの ID。"""
        received = self._manager.get(channel_id)
        if received is None:
            return IGNORED
        async with self._lock(channel_id):
            game = self._manager.get(channel_id)
            if game is None or game.game_id != received.game_id:
                return IGNORED
            if author_id == game.setter_id or not text.strip():
                return IGNORED
            try:
                verdict = await self._judge.judge(game.topic, game.hint, text)
            except JudgeError:
                log.exception("判定に失敗しました（channel=%s）", channel_id)
                return Outcome(public=fmt.format_error())
            game.question_count += 1
            if verdict.is_correct:
                self._manager.end(channel_id)
                return Outcome(public=fmt.format_correct(game, author_name, self._clock() - game.started_at))
            return Outcome(public=fmt.format_answer(text, verdict))
```

- [ ] **Step 5: 通ることを確認する**

Run: `uv run pytest -v`
Expected: 全件 PASS（結合テストは除外）

- [ ] **Step 6: Commit**

```bash
git add src/insider_bot/service.py tests/fakes.py tests/test_service.py
git commit -m "feat: チャンネル単位で直列化したゲーム進行（GameService）を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 設定の読み込み

**Files:**
- Create: `src/insider_bot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: なし
- Produces（`insider_bot.config`）:
  - `@dataclass(frozen=True) class Config: discord_token: str; typesafe_api_key: str; guild_id: int | None; correct_threshold: float; jev_timeout_seconds: float`
  - `class ConfigError(Exception)`
  - `load_config(env: Mapping[str, str] | None = None) -> Config`（`None` なら `os.environ`）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_config.py`:

```python
import pytest

from insider_bot.config import Config, ConfigError, load_config

REQUIRED = {"DISCORD_TOKEN": "discord-token", "TYPESAFE_API_KEY": "ts-key"}


def test_defaults():
    assert load_config(REQUIRED) == Config(
        discord_token="discord-token",
        typesafe_api_key="ts-key",
        guild_id=None,
        correct_threshold=0.8,
        jev_timeout_seconds=10.0,
    )


def test_optional_values():
    config = load_config(
        REQUIRED | {"DISCORD_GUILD_ID": "123", "CORRECT_THRESHOLD": "0.9", "JEV_TIMEOUT_SECONDS": "5"}
    )
    assert (config.guild_id, config.correct_threshold, config.jev_timeout_seconds) == (123, 0.9, 5.0)


def test_blank_optional_values_use_defaults():
    config = load_config(REQUIRED | {"DISCORD_GUILD_ID": "", "CORRECT_THRESHOLD": " "})
    assert (config.guild_id, config.correct_threshold) == (None, 0.8)


def test_missing_required_lists_all_names():
    with pytest.raises(ConfigError) as error:
        load_config({"DISCORD_TOKEN": " "})
    assert "DISCORD_TOKEN" in str(error.value)
    assert "TYPESAFE_API_KEY" in str(error.value)


@pytest.mark.parametrize(
    "extra",
    [
        {"DISCORD_GUILD_ID": "abc"},
        {"CORRECT_THRESHOLD": "high"},
        {"CORRECT_THRESHOLD": "1.5"},
        {"JEV_TIMEOUT_SECONDS": "0"},
    ],
)
def test_invalid_values(extra):
    with pytest.raises(ConfigError):
        load_config(REQUIRED | extra)
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'insider_bot.config'`）

- [ ] **Step 3: 実装する**

`src/insider_bot/config.py`:

```python
"""環境変数から設定を読み込む。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(Exception):
    """設定が不足・不正。"""


@dataclass(frozen=True)
class Config:
    discord_token: str
    typesafe_api_key: str
    guild_id: int | None
    correct_threshold: float
    jev_timeout_seconds: float


def _get(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _get(env, name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} は数値で指定してください（現在: {raw!r}）") from None


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env

    missing = [name for name in ("DISCORD_TOKEN", "TYPESAFE_API_KEY") if not _get(env, name)]
    if missing:
        raise ConfigError(f"必須の環境変数が未設定です: {', '.join(missing)}（.env を確認してください）")

    guild_raw = _get(env, "DISCORD_GUILD_ID")
    try:
        guild_id = int(guild_raw) if guild_raw else None
    except ValueError:
        raise ConfigError(f"DISCORD_GUILD_ID は数字で指定してください（現在: {guild_raw!r}）") from None

    threshold = _float(env, "CORRECT_THRESHOLD", 0.8)
    if not 0.0 <= threshold <= 1.0:
        raise ConfigError(f"CORRECT_THRESHOLD は 0〜1 で指定してください（現在: {threshold}）")

    timeout = _float(env, "JEV_TIMEOUT_SECONDS", 10.0)
    if timeout <= 0:
        raise ConfigError(f"JEV_TIMEOUT_SECONDS は 0 より大きい値にしてください（現在: {timeout}）")

    return Config(
        discord_token=_get(env, "DISCORD_TOKEN"),
        typesafe_api_key=_get(env, "TYPESAFE_API_KEY"),
        guild_id=guild_id,
        correct_threshold=threshold,
        jev_timeout_seconds=timeout,
    )
```

- [ ] **Step 4: 通ることを確認する**

Run: `uv run pytest tests/test_config.py -v`
Expected: 全件 PASS

- [ ] **Step 5: Commit**

```bash
git add src/insider_bot/config.py tests/test_config.py
git commit -m "feat: 環境変数からの設定読み込みを追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Discord アダプター・起動・README・実サーバー確認

**Files:**
- Create: `src/insider_bot/bot.py`, `src/insider_bot/__main__.py`, `README.md`

**Interfaces:**
- Consumes: `GameService`, `Outcome`（Task 6）、`GameManager`（Task 3）、`JevJudge`（Task 5）、`load_config`, `ConfigError`（Task 7）
- Produces: `OdaiBot(service: GameService, guild_id: int | None)`（`discord.Client` 派生）、`insider_bot.__main__.main()`

- [ ] **Step 1: Discord アダプターを書く**

`src/insider_bot/bot.py`:

```python
"""discord.py アダプター。判断はすべて GameService に任せ、ここは送受信だけを行う。"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.utils import escape_markdown

from insider_bot.service import GameService, Outcome

log = logging.getLogger(__name__)


def _name(user: discord.abc.User) -> str:
    return escape_markdown(user.display_name)


async def _respond(interaction: discord.Interaction, outcome: Outcome) -> None:
    """defer 済みのスラッシュコマンドに結果を返す。公開通知はチャンネルへ別途投稿する。"""
    if outcome.public and interaction.channel is not None:
        await interaction.channel.send(outcome.public)
    await interaction.followup.send(outcome.private or "完了しました", ephemeral=True)


def build_odai_group(service: GameService) -> app_commands.Group:
    group = app_commands.Group(name="odai", description="お題当てゲーム", guild_only=True)

    @group.command(name="set", description="お題を登録してゲームを開始します（お題は自分にしか見えません）")
    @app_commands.rename(topic="お題", hint="補足")
    @app_commands.describe(topic="当ててもらうお題（50文字まで）", hint="お題の補足説明（任意・300文字まで）")
    async def set_topic(
        interaction: discord.Interaction,
        topic: app_commands.Range[str, 1, 50],
        hint: Optional[app_commands.Range[str, 1, 300]] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        outcome = await service.start(
            interaction.channel_id, interaction.user.id, _name(interaction.user), topic, hint or ""
        )
        await _respond(interaction, outcome)

    @group.command(name="status", description="進行中のゲームの状況を表示します")
    async def status(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _respond(interaction, await service.status(interaction.channel_id))

    @group.command(name="giveup", description="お題を公開してゲームを終了します")
    async def giveup(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _respond(interaction, await service.giveup(interaction.channel_id))

    return group


class OdaiBot(discord.Client):
    def __init__(self, service: GameService, guild_id: int | None) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        # 質問文を引用して返すので、@everyone 等で誰にも通知が飛ばないようにする
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.service = service
        self.guild_id = guild_id
        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(build_odai_group(service))

    async def setup_hook(self) -> None:
        if self.guild_id is not None:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("スラッシュコマンドをサーバー %s に同期しました（%d 件）", self.guild_id, len(synced))
        else:
            synced = await self.tree.sync()
            log.info("スラッシュコマンドをグローバル同期しました（%d 件、反映まで時間がかかる場合があります）", len(synced))

    async def on_ready(self) -> None:
        log.info("ログインしました: %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        outcome = await self.service.handle_question(
            message.channel.id, message.author.id, _name(message.author), message.content
        )
        if outcome.public is None:
            return
        try:
            await message.channel.send(
                outcome.public, reference=message.to_reference(fail_if_not_exists=False)
            )
        except discord.HTTPException:
            # 判定・質問数・終了処理はやり直さない
            log.exception("返信の送信に失敗しました（channel=%s）", message.channel.id)
```

- [ ] **Step 2: 起動処理を書く**

`src/insider_bot/__main__.py`:

```python
"""起動: uv run --env-file .env python -m insider_bot"""

from __future__ import annotations

import asyncio
import sys

import discord
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

from insider_bot.bot import OdaiBot
from insider_bot.config import Config, ConfigError, load_config
from insider_bot.game import GameManager
from insider_bot.judge import JevJudge
from insider_bot.service import GameService


async def run(config: Config) -> None:
    client = AsyncTypeSafeClient(
        api_key=config.typesafe_api_key,
        retry=RetryPolicy(max_retries=1, timeout=config.jev_timeout_seconds),
    )
    try:
        judge = JevJudge(client, config.correct_threshold, config.jev_timeout_seconds)
        service = GameService(GameManager(), judge)
        bot = OdaiBot(service, config.guild_id)
        async with bot:
            await bot.start(config.discord_token)
    finally:
        await client.aclose()


def main() -> None:
    discord.utils.setup_logging()
    try:
        config = load_config()
    except ConfigError as error:
        print(f"設定エラー: {error}", file=sys.stderr)
        sys.exit(1)
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: import と設定エラーの動作を確認する**

Run: `uv run python -c "import insider_bot.bot, insider_bot.__main__; print('ok')"`
Expected: `ok`

Run: `env -u DISCORD_TOKEN -u TYPESAFE_API_KEY uv run python -m insider_bot; echo "exit=$?"`
Expected: `設定エラー: 必須の環境変数が未設定です: DISCORD_TOKEN, TYPESAFE_API_KEY（.env を確認してください）` と `exit=1`

Run: `uv run pytest`
Expected: 全件 PASS

- [ ] **Step 4: README を書く**

`README.md`:

````markdown
# お題当てゲーム GM ボット

Discord で「お題当てゲーム」の GM を務めるボットです。出題者が登録したお題について、
参加者の質問に TypeSafe AI の Jev が「はい／いいえ」とその割合で答え、言い当てたら「正解です」でゲーム終了します。

## 遊び方

1. 出題者がゲームをするチャンネルで `/odai set お題:りんご 補足:赤い果物`（補足は任意）
   - お題は出題者本人にしか表示されません
2. 参加者はそのチャンネルに質問を書き込む（スマホの音声入力も OK）
   ```
   ❓ 果物ですか？
   ✅ はい　　はい 82% ██████████░░ いいえ 18%
   ```
3. お題を言い当てると `🎉 正解です！` でゲーム終了
- `/odai status` … 進行状況（質問数・経過時間）
- `/odai giveup` … お題を公開して終了

ゲーム中のチャンネルでは、出題者以外の発言がすべて質問として扱われます。雑談は別チャンネルでどうぞ。
ボットを再起動すると進行中のゲームは消えます。

## セットアップ

### 1. Discord ボットを作る

1. https://discord.com/developers/applications で「New Application」
2. 「Bot」タブでトークンを発行（Reset Token）し控える
3. 同じ「Bot」タブの **Privileged Gateway Intents → MESSAGE CONTENT INTENT** をオンにする
4. 「OAuth2 → URL Generator」で Scopes に `bot` と `applications.commands`、
   Bot Permissions に「View Channels」「Send Messages」「Read Message History」を選び、生成された URL でサーバーに招待する

### 2. TypeSafe の API キーを発行する

https://console.typesafe.ai でキーを発行する。

### 3. 設定して起動する

[uv](https://docs.astral.sh/uv/) が必要です。

```bash
cp .env.example .env   # DISCORD_TOKEN と TYPESAFE_API_KEY を記入
uv sync
uv run --env-file .env python -m insider_bot
```

開発中は `.env` に `DISCORD_GUILD_ID`（サーバーを右クリック →「サーバー ID をコピー」、開発者モードが必要）を
入れると、スラッシュコマンドがすぐに反映されます。未指定だと全サーバー向け登録になり、反映に時間がかかることがあります。

| 環境変数 | 必須 | 既定 | 説明 |
|---|---|---|---|
| `DISCORD_TOKEN` | ✓ | — | Discord ボットトークン |
| `TYPESAFE_API_KEY` | ✓ | — | TypeSafe API キー |
| `DISCORD_GUILD_ID` | | — | コマンドを即時反映するサーバー ID |
| `CORRECT_THRESHOLD` | | 0.8 | 正解とみなすしきい値（0〜1） |
| `JEV_TIMEOUT_SECONDS` | | 10 | Jev 呼び出しのタイムアウト秒数 |

## 開発

```bash
uv run pytest                                   # 単体テスト
uv run --env-file .env pytest -m integration    # 実際の Jev を呼ぶテスト
uv run --env-file .env python scripts/jev_probe.py  # Jev の日本語判定の確認表
```
````

- [ ] **Step 5: 実サーバーで手動確認する（ユーザーのトークンが必要）**

ユーザーに README の「セットアップ」1〜2 を実施してもらい、`.env` に `DISCORD_TOKEN`・`TYPESAFE_API_KEY`・`DISCORD_GUILD_ID` を記入してもらう（エージェントはトークンを入力・表示しない）。

Run: `uv run --env-file .env python -m insider_bot`
Expected: ログに `スラッシュコマンドをサーバー … に同期しました（1 件）` と `ログインしました: …`

ユーザーと一緒に、テスト用チャンネルで次を確認する:

| # | 操作 | 期待する結果 |
|---|---|---|
| 1 | A さんが `/odai set お題:りんご 補足:赤い果物` | A さんにだけ「お題『りんご』を登録しました」、チャンネルに「🎮 ゲーム開始！…」 |
| 2 | B さんが「果物ですか？」 | 質問へのリプライで `✅ はい　　はい NN% … いいえ NN%` |
| 3 | A さん（出題者）が発言 | 反応しない |
| 4 | B さんが「@everyone 動物ですか？」 | 回答は返るが、誰にもメンション通知が飛ばない |
| 5 | `/odai status` | 本人にだけ質問数・経過時間・出題者 |
| 6 | 同じチャンネルで `/odai set` をもう一度 | 本人にだけ「このチャンネルではゲームが進行中です」 |
| 7 | B さんが「林檎ですか？」 | 「🎉 正解です！お題は「りんご」でした」、質問数・経過時間つき |
| 8 | 正解後に発言 | 反応しない |
| 9 | 新しくお題を登録し `/odai giveup` | チャンネルに「🏳️ ギブアップ！お題は『…』でした（質問数: N）」 |
| 10 | ゲームなしで `/odai giveup` | 本人にだけ「進行中のゲームはありません」 |

問題があれば superpowers:systematic-debugging で原因を調べてから直す。

- [ ] **Step 6: Commit**

```bash
git add src/insider_bot/bot.py src/insider_bot/__main__.py README.md
git commit -m "feat: Discordアダプターと起動処理、READMEを追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
