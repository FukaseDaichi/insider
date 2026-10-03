# M1: 村の中核の移植 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LineBot（Java）の村の中核（通常村・神モード・逆村・ランダム村・特殊村・Werewords・お題辞書・役職画像）を、経路中立の返事モデルを返す Python パッケージ `insider_bot.village` として移植する。LINE・Web の入口にはまだつながない。

**Architecture:** 状態（`model.py`）、レジストリ（`registry.py`）、辞書（`words.py`）、画像（`illust.py`）、Werewords（`werewords.py`）、返事の組み立て（`messages.py`）、構造化操作（`service.py`）、テキスト解釈（`commands.py`）に分け、依存は下から上への一方向にする。中核の操作は同期関数で、途中に `await` を挟まない。乱数は注入し、テストで決定的にする。

**Tech Stack:** Python 3.13、uv、pytest、dataclasses。新しい実行時依存は足さない（画像カタログの取得は既存の `httpx2` を使う）。

**Spec:** [docs/superpowers/specs/2026-10-03-unify-line-web-discord-design.md](../specs/2026-10-03-unify-line-web-discord-design.md)

## Global Constraints

- Python は `>=3.13`、パッケージ管理は uv。`pip` や system python は使わない。テストは `uv run pytest` で動かす
- 新しい実行時依存を足さない。HTTP は既存の `httpx2`
- 中核の 1 操作の途中で `await` を挟まない（asyncio 単一スレッドで整合性を保つ規律）
- 文言は Java の `MessageConst` と各クラスの文字列を**一字一句**保つ（「全く同じ」が要件）。全角の「ＧＭ」、鉤括弧『』「」の使い分け、末尾の「。」の有無も含む
- 参加者の識別子は不透明な文字列（`line:<id>` / `web:<token>`）。中核は接頭辞を解釈しない
- 「対象の村がない」は例外ではなく `None` で返す
- ログに利用者の識別子とお題を出さない
- `docs/` は現在形で、コードの現状と一致させる（docs/AGENTS.md）
- コミットメッセージは日本語、既存リポジトリの書き方（`feat:` / `docs:` / `test:` の接頭辞）に合わせる

## Review Focus

仕様が黙っているが、使う人に当たりそうな入力。各行のテストを所有タスクに入れてある。

1. **お題や特殊村のメッセージに `,` や改行が含まれる** → 文言にそのまま入り、辞書の CSV 解釈とは無関係に扱われること（Task 7・Task 8）
2. **特殊村のメッセージに `None` と空文字が混ざる** → その参加者には「メッセージは特にありません。」が返り、入室状況は正しい番号になること（Task 3・Task 7）
3. **人数に `0`・負数・`100`・`101` を送る** → 1 以下は再入力の案内、100 は人数、101 は村番号（該当なし）として扱われること（Task 9）
4. **全角数字「３」、前後に半角空白のある「 3 」、全角スペースで囲んだ「　3　」を送る** → Java の `Integer.parseInt` は全角数字を受け付け、`String.trim()` は U+0020 以下の文字しか除かない（全角スペースは残る）。「３」と「 3 」は人数 3、「　3　」と「お題　」はお題として扱うこと。Python の `int()` と `str.strip()` はどちらも Java より受け付ける範囲が広いので使わない（Task 1・Task 9）
5. **int の範囲を超える数字「99999999999」や「1_0」を送る** → Java では数値として読めずお題になる。Python の `int()` は読めてしまうので、範囲と書式を Java に合わせること（Task 1・Task 9）
6. **辞書 CSV が壊れている（難易度が逆順・欠番・非整数）** → 辞書全体を破棄し、お題の抽選が `None` を返し、ERROR ログが出ること（Task 4）
7. **お題を決めないまま人数を設定し、参加者が入室する** → Java の文字列連結と同じく、お題の欄に『null』と出ること（Python の f 文字列だと『None』になる）（Task 7）

---

## ファイル構成

```
src/insider_bot/village/
  __init__.py       空
  reply.py          返事モデル（Text / Image / Buttons / Confirm とアクション）
  texts.py          文言の定数
  parsing.py        Java と同じ規則の文字列解釈（trim / Integer.parseInt / split）
  model.py          Village / SpecialVillage / Role / Seat と不変条件
  registry.py       VillageRegistry / SpecialVillageRegistry
  words.py          お題辞書の読み込みと抽選
  word.csv          8,436 語の辞書（LineBot から複製）
  illust.py         役職画像の既定 URL と外部カタログの重み付き抽選
  werewords.py      Werewords の役職メッセージ列
  messages.py       返事の組み立て（役職・配布状況・既定応答・お題候補 など）
  service.py        VillageService（構造化操作）
  commands.py       CommandHandler（テキストの解釈）
src/insider_bot/web/static/roles/
  INSIDER.png VILLAGERS.png GM.png GOD.png 966mpnqz.png   LineBot/Image から複製
tests/
  fakes.py          FixedRandom を追加
  test_village_reply.py
  test_village_parsing.py
  test_village_model.py
  test_village_registry.py
  test_village_words.py
  test_village_illust.py
  test_village_werewords.py
  test_village_messages.py
  test_village_service.py
  test_village_commands.py
docs/village.md     村の外部仕様（Java の game-spec.md の移植）
docs/spec.md        「村の中核」の節を追記
```

---

### Task 1: 返事モデル・文言・Java 互換の文字列解釈

**Files:**
- Create: `src/insider_bot/village/__init__.py`
- Create: `src/insider_bot/village/reply.py`
- Create: `src/insider_bot/village/texts.py`
- Create: `src/insider_bot/village/parsing.py`
- Test: `tests/test_village_reply.py`
- Test: `tests/test_village_parsing.py`

**Interfaces:**
- Produces: `reply.py` の `Text`, `Image`, `Buttons`, `Confirm`, `MessageAction`, `PostbackAction`, `UriAction`, 型エイリアス `Action`, `Reply`。すべて frozen dataclass で、等値比較ができる
- Produces: `texts.py` の定数（下記のコードそのまま）
- Produces: `parsing.py` の `java_trim(text) -> str`、`parse_java_int(text) -> int | None`、`java_split(text, separator) -> list[str]`。Java の `String.trim()` / `Integer.parseInt()` / `String.split()` と同じ結果を返す（Task 4・5・9 と、M2 の LINE のポストバック解釈が使う）

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_village_reply.py
from insider_bot.village.reply import Buttons, Confirm, Image, MessageAction, PostbackAction, Text, UriAction


def test_replies_compare_by_value():
    assert Text("a") == Text("a")
    assert Image("https://x/a.png") == Image("https://x/a.png")
    assert MessageAction("確認", "1234") == MessageAction("確認", "1234")
    assert PostbackAction("入室状況確認", "1234") != PostbackAction("入室状況確認", "1235")
    assert UriAction("ご意見", "https://x") == UriAction("ご意見", "https://x")


def test_buttons_defaults():
    buttons = Buttons("本文", (MessageAction("確認", "1"),))
    assert buttons.image is None
    assert buttons.title is None
    assert buttons.alt_text is None
    assert buttons.overflow == ()


def test_buttons_overflow_can_nest():
    inner = Buttons("本文", (PostbackAction("入室状況確認", "1"),), overflow=(Text("本文"),))
    outer = Buttons("本文", (PostbackAction("入室状況確認", "1"),), image="https://x/a.png", overflow=(inner,))
    assert outer.overflow[0].overflow[0] == Text("本文")


def test_confirm_has_two_actions():
    confirm = Confirm("村の作成をしますか？", (MessageAction("GM", "お題"), MessageAction("神", "神")), alt_text="案内")
    assert len(confirm.actions) == 2
    assert confirm.alt_text == "案内"
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_village_reply.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.village'`

- [ ] **Step 3: 返事モデルを書く**

```python
# src/insider_bot/village/__init__.py
（空ファイル）
```

```python
# src/insider_bot/village/reply.py
"""経路中立の返事モデル。中核はこれを返し、LINE や Web の入口がそれぞれの形に描く。

Buttons.overflow は「表示側が本文を文字数に収められないときに代わりに出す返事の列」。
LINE のボタンテンプレートは画像つきで 60 文字、画像なしで 160 文字までなので、
Java が Text＋入室状況の 2 通に落としていた分岐をここで表す。overflow の中にさらに
Buttons を置けるので、「画像を外して収める → それでも無理なら Text」の多段も書ける。
Web は制限がないので常に本体を描く。

収まるかどうかの文字数は Java の String.length() と同じく UTF-16 の符号単位で数える（絵文字は 2）。
Python の len() は符号位置で数えるので、LINE の入口がそのまま使うと Java と違う形で返事が届く。

alt_text は LINE のテンプレートに添える代替文。None なら本文を使う。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MessageAction:
    """押すと text を送信したことになるボタン。"""

    label: str
    text: str


@dataclass(frozen=True)
class PostbackAction:
    """押すと data が postback として届くボタン。"""

    label: str
    data: str


@dataclass(frozen=True)
class UriAction:
    label: str
    uri: str


Action = MessageAction | PostbackAction | UriAction


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Image:
    url: str


@dataclass(frozen=True)
class Buttons:
    text: str
    actions: tuple[Action, ...]
    image: str | None = None
    title: str | None = None
    alt_text: str | None = None
    overflow: tuple["Reply", ...] = ()


@dataclass(frozen=True)
class Confirm:
    text: str
    actions: tuple[Action, ...]
    alt_text: str | None = None


Reply = Text | Image | Buttons | Confirm
```

- [ ] **Step 4: 文言を書く**

```python
# src/insider_bot/village/texts.py
"""村の文言。LineBot（Java）の MessageConst と各クラスの文字列を一字一句保つ。"""

DEFAULT_MESSAGE = "お題を配りたい方は「お題」または「神」を、\nお題及び役職を確認したい場合は村番号（数字4桁）を入力してください。"
DEFAULT_CONFIRM_TEXT = "村の作成をしますか？"

OWNER_ODAI_MESSAGE = "お題を入力してください。"
OWNER_NUMSET_MESSAGE = "お題を配りたい人数を入力してください。\n　例：「5」の場合は、「インサイダー１人、村4人」です。"
GOD_NUMSET_MESSAGE = "お題を配りたい人数を入力してください。\n　例：「6」の場合は、「GM１人、インサイダー１人、村4人」です。"
RANDOM_NUMSET_MESSAGE = "人数を設定してください。役職もお題もランダムに配ります。"
ERR_NUMSET_MESSAGE = "村の人数は2人以上に設定してください。\nもう一度村の人数を設定してください。"
ERR_UNIDENTIFIED_USER = "ユーザーを識別できないため操作できません。\nbotとの1対1のトークから操作してください。"

VILLAGE_FULL = "村がいっぱいです。"
NO_SPECIAL_MESSAGE = "メッセージは特にありません。"

INSIDER_ROLE = "インサイダー"
VILLAGER_ROLE = "村人"
GAME_MASTER_ROLE = "ＧＭ"

# Werewords。添字は役職番号（1 占師、2 インサイダー、3 村人、4 GM）
WEREWORDS_MESSAGES = (
    "",
    "あなたの役職は占師です。お題は「{0}」です。",
    "あなたの役職はインサイダーです。お題は「{0}」です。",
    "あなたの役職は村人です",
    "あなたの役職はGMです。お題は「{0}」です。\n役職は「{1}」が欠けています。",
)
WEREWORDS_ROLES = ("", "占師", "インサイダー", "村人")

OFFICIAL_ACCOUNT_URL = "https://line.me/R/ti/p/%40966mpnqz"
OFFICIAL_ACCOUNT_ID_MESSAGE = "お友達ID\n@966mpnqz"
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_reply.py -q`
Expected: `4 passed`

- [ ] **Step 6: Java 互換の文字列解釈の失敗するテストを書く**

期待値はすべて Java 11 で `String.trim()` / `Integer.parseInt()` / `String.split()` を実行して確かめた結果。

```python
# tests/test_village_parsing.py
import pytest

from insider_bot.village.parsing import java_split, java_trim, parse_java_int


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3", 3),
        ("-5", -5),
        ("+5", 5),
        ("３", 3),  # 全角数字も Unicode の 10 進数字として読む
        ("１２", 12),
        ("٣", 3),
        ("2147483647", 2147483647),
        ("-2147483648", -2147483648),
    ],
)
def test_reads_what_integer_parse_int_reads(text, expected):
    assert parse_java_int(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "+", "-", " 3", "3 ", "1_0", "3.0", "2147483648", "-2147483649", "99999999999", "三", "0x10", "+-3", "--3"],
)
def test_rejects_what_integer_parse_int_rejects(text):
    assert parse_java_int(text) is None


def test_trim_removes_only_ascii_spaces_and_controls():
    assert java_trim(" \t\n3\r ") == "3"
    # 全角スペース（U+3000）は U+0020 より大きいので残る
    assert java_trim("　3　") == "　3　"


def test_split_drops_trailing_empty_parts():
    assert java_split("GM_1_a_", "_") == ["GM", "1", "a"]
    assert java_split("GM_1_", "_") == ["GM", "1"]
    assert java_split("_1_a", "_") == ["", "1", "a"]
    assert java_split("GM__a", "_") == ["GM", "", "a"]
    assert java_split("", "_") == [""]
    assert java_split("_", "_") == []
```

- [ ] **Step 7: 失敗を確認する**

Run: `uv run pytest tests/test_village_parsing.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.village.parsing'`

- [ ] **Step 8: Java 互換の文字列解釈を書く**

```python
# src/insider_bot/village/parsing.py
"""Java（LineBot）と同じ規則で文字列を読む。

入力の解釈が Java とずれると、同じ入力への応答が LINE 版と食い違う。Python の str.strip() と int() は
Java の String.trim() と Integer.parseInt() より受け付ける範囲が広い（全角スペースを除く、「1_0」や
int の範囲外を読む）ので、利用者の入力や外部データの解釈には使わない。
"""

from __future__ import annotations

import re

# String.trim() が除くのは U+0020 以下の文字だけ
_JAVA_TRIM_CHARS = "".join(chr(code) for code in range(0x21))
# Integer.parseInt は符号 1 つと Unicode の 10 進数字（全角数字を含む）だけを受け付ける
_JAVA_INT = re.compile(r"[+-]?\d+")
_INT_MIN = -(2**31)
_INT_MAX = 2**31 - 1


def java_trim(text: str) -> str:
    return text.strip(_JAVA_TRIM_CHARS)


def parse_java_int(text: str) -> int | None:
    """Integer.parseInt と同じ規則で読む。読めなければ None。前後の空白は読めない（先に java_trim する）。"""
    if not _JAVA_INT.fullmatch(text):
        return None
    value = int(text)
    if not _INT_MIN <= value <= _INT_MAX:
        return None
    return value


def java_split(text: str, separator: str) -> list[str]:
    """String.split と同じく末尾の空要素を落とす。区切りが現れなければ元の文字列 1 つ。"""
    if separator not in text:
        return [text]
    parts = text.split(separator)
    while parts and parts[-1] == "":
        parts.pop()
    return parts
```

- [ ] **Step 9: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_reply.py tests/test_village_parsing.py -q`
Expected: `28 passed`

- [ ] **Step 10: コミット**

```bash
git add src/insider_bot/village/__init__.py src/insider_bot/village/reply.py src/insider_bot/village/texts.py src/insider_bot/village/parsing.py tests/test_village_reply.py tests/test_village_parsing.py
git commit -m "feat: 村の中核の返事モデル・文言・Java 互換の文字列解釈を追加"
```

---

### Task 2: 通常村の状態（Village）

**Files:**
- Create: `src/insider_bot/village/model.py`
- Modify: `tests/fakes.py`（`FixedRandom` を追加）
- Test: `tests/test_village_model.py`

**Interfaces:**
- Produces: `model.py` の `Rng`（Protocol: `randrange(n: int) -> int`, `shuffle(seq: list) -> None`）、`Role`（Enum: `INSIDER`, `VILLAGER`, `GAME_MASTER`、`label` プロパティ、`illust_key` プロパティ）、`Seat(user_id: str, role: Role)`、`GOD_MODE_PENDING = 999`、`Village`
- `Village(owner_id: str)`。属性 `number: int`（0 = 未採番）、`topic: str | None`、`size: int`（0 = 未設定）、`insider_seat: int`、`gm_seat: int`、`reverse: bool`、`random_mode: bool`、`seats: list[Seat]`
- メソッド: `set_topic(topic) -> bool`、`mark_god_mode()`、`is_god_mode_awaiting_size() -> bool`、`has_game_master() -> bool`、`configure(size, rng) -> bool`、`join(user_id) -> Seat | None`、`role_of(user_id) -> Role | None`、`seat_number_of(user_id) -> int`（0 = 未参加）、`apply_reverse() -> bool`、`has_members() -> bool`、`member_count() -> int`
- Produces: `tests/fakes.py` の `FixedRandom(*values)`。`randrange(n)` は与えた値を順に返す、`shuffle` は何もしない

- [ ] **Step 1: FixedRandom を足す**

`tests/fakes.py` の末尾に追加:

```python
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
```

- [ ] **Step 2: 失敗するテストを書く**

```python
# tests/test_village_model.py
import random

import pytest

from insider_bot.village.model import GOD_MODE_PENDING, Role, Village
from tests.fakes import FixedRandom


def village_of(size: int, insider_at: int) -> Village:
    village = Village("owner")
    assert village.configure(size, FixedRandom(insider_at - 1))
    return village


def join_all(village: Village, *user_ids: str) -> None:
    for user_id in user_ids:
        assert village.join(user_id) is not None, f"参加できなかった: {user_id}"
    assert village.member_count() == len(user_ids) + (1 if village.random_mode else 0)


# --- 配役 ---


def test_normal_village_assigns_insider_by_join_order():
    village = village_of(3, insider_at=2)
    join_all(village, "first", "second", "third")
    assert village.role_of("first") is Role.VILLAGER
    assert village.role_of("second") is Role.INSIDER
    assert village.role_of("third") is Role.VILLAGER


def test_join_is_capacity_bound_and_idempotent():
    village = village_of(1, insider_at=1)
    assert village.join("first") is not None
    assert village.join("first") is not None
    assert village.join("second") is None
    assert village.role_of("first") is Role.INSIDER
    assert village.member_count() == 1


def test_god_mode_assigns_game_master_at_its_own_seat():
    village = Village("owner")
    village.mark_god_mode()
    assert village.is_god_mode_awaiting_size()
    # インサイダーは1番目、GM は3番目
    assert village.configure(3, FixedRandom(0, 2))
    assert not village.is_god_mode_awaiting_size()
    assert village.has_game_master()
    join_all(village, "first", "second", "third")
    assert village.role_of("first") is Role.INSIDER
    assert village.role_of("second") is Role.VILLAGER
    assert village.role_of("third") is Role.GAME_MASTER


def test_god_mode_never_puts_the_game_master_on_the_insider_seat():
    village = Village("owner")
    village.mark_god_mode()
    # GM の席がインサイダーと衝突したら引き直す
    village.configure(3, FixedRandom(1, 1, 1, 0))
    assert village.insider_seat == 2
    assert village.gm_seat == 1


def test_normal_village_has_no_game_master():
    village = village_of(3, insider_at=1)
    assert not village.has_game_master()
    assert village.gm_seat == 0


def test_random_mode_seats_the_owner_first():
    village = Village("owner")
    village.mark_god_mode()
    village.random_mode = True
    # インサイダーは1番目、GM は2番目
    assert village.configure(3, FixedRandom(0, 1))
    assert village.member_count() == 1
    assert village.role_of("owner") is Role.INSIDER
    assert village.join("second") is not None
    assert village.join("third") is not None
    assert village.member_count() == 3
    assert village.role_of("second") is Role.GAME_MASTER
    assert village.role_of("third") is Role.VILLAGER


def test_exactly_one_insider_whatever_the_draw():
    for seed in range(50):
        village = Village("owner")
        village.configure(6, random.Random(seed))
        users = [f"u{i}" for i in range(1, 7)]
        join_all(village, *users)
        insiders = [u for u in users if village.role_of(u) is Role.INSIDER]
        assert len(insiders) == 1, f"seed={seed}"


# --- 逆村 ---


def test_reverse_village_inverts_insider_and_villagers():
    village = village_of(3, insider_at=2)
    assert village.apply_reverse()
    join_all(village, "first", "second", "third")
    assert village.role_of("first") is Role.INSIDER
    assert village.role_of("second") is Role.VILLAGER
    assert village.role_of("third") is Role.INSIDER


def test_reverse_village_keeps_the_game_master():
    village = Village("owner")
    village.mark_god_mode()
    village.configure(3, FixedRandom(0, 2))
    assert village.apply_reverse()
    join_all(village, "first", "second", "third")
    assert village.role_of("first") is Role.VILLAGER
    assert village.role_of("second") is Role.INSIDER
    assert village.role_of("third") is Role.GAME_MASTER


def test_reverse_village_is_rejected_once_someone_joined():
    village = village_of(3, insider_at=2)
    assert village.join("first") is not None
    assert not village.apply_reverse()
    assert not village.reverse
    assert village.role_of("first") is Role.VILLAGER


# --- 一度きりの設定 ---


def test_configure_is_one_shot():
    village = village_of(3, insider_at=2)
    assert not village.configure(5, FixedRandom(0))
    assert village.size == 3
    assert village.insider_seat == 2


def test_set_topic_is_one_shot():
    village = Village("owner")
    assert village.set_topic("すいか")
    assert not village.set_topic("めろん")
    assert village.topic == "すいか"


# --- 参照 ---


def test_seat_number_and_role_of_unknown_user():
    village = village_of(2, insider_at=1)
    assert village.role_of("nobody") is None
    assert village.seat_number_of("nobody") == 0
    village.join("a")
    village.join("b")
    assert village.seat_number_of("a") == 1
    assert village.seat_number_of("b") == 2


def test_join_before_configure_is_full():
    # 人数未設定の村は定員 0。Java と同じく「村がいっぱいです。」側に落ちる
    village = Village("owner")
    assert village.join("a") is None


def test_role_labels_and_illust_keys():
    assert Role.INSIDER.label == "インサイダー"
    assert Role.VILLAGER.label == "村人"
    assert Role.GAME_MASTER.label == "ＧＭ"
    assert Role.INSIDER.illust_key == "INSIDER"
    assert Role.VILLAGER.illust_key == "VILLAGERS"
    assert Role.GAME_MASTER.illust_key == "GM"


def test_god_mode_pending_is_not_a_seat():
    assert GOD_MODE_PENDING == 999
```

- [ ] **Step 3: 失敗を確認する**

Run: `uv run pytest tests/test_village_model.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.village.model'`

- [ ] **Step 4: Village を書く**

```python
# src/insider_bot/village/model.py
"""村の状態と不変条件。ネットワークにも文言にも依存しない。

Java では synchronized で守っていた操作（人数確定と配役抽選、お題設定、逆村化、参加）は、
asyncio 単一スレッドでは「1 つの同期メソッドで完結し、途中で await しない」ことで同じ保証になる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from insider_bot.village import texts


class Rng(Protocol):
    def randrange(self, n: int, /) -> int: ...

    def shuffle(self, seq: list, /) -> None: ...


class Role(Enum):
    INSIDER = "INSIDER"
    VILLAGER = "VILLAGER"
    GAME_MASTER = "GAME_MASTER"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def illust_key(self) -> str:
        """役職画像のカタログで使う名前。"""
        return _ILLUST_KEYS[self]


_LABELS = {Role.INSIDER: texts.INSIDER_ROLE, Role.VILLAGER: texts.VILLAGER_ROLE, Role.GAME_MASTER: texts.GAME_MASTER_ROLE}
_ILLUST_KEYS = {Role.INSIDER: "INSIDER", Role.VILLAGER: "VILLAGERS", Role.GAME_MASTER: "GM"}

# 席番号としてあり得ない値を「GM を立てる村だが、人数が未確定で席が未抽選」の印に使う
GOD_MODE_PENDING = 999


@dataclass(frozen=True)
class Seat:
    user_id: str
    role: Role


@dataclass(eq=False)
class Village:
    owner_id: str
    number: int = 0
    topic: str | None = None
    size: int = 0
    insider_seat: int = 0
    gm_seat: int = 0
    reverse: bool = False
    random_mode: bool = False
    seats: list[Seat] = field(default_factory=list)

    def set_topic(self, topic: str) -> bool:
        """一度だけ設定できる。設定済みなら False。"""
        if self.topic is not None:
            return False
        self.topic = topic
        return True

    def mark_god_mode(self) -> None:
        self.gm_seat = GOD_MODE_PENDING

    def is_god_mode_awaiting_size(self) -> bool:
        return self.gm_seat == GOD_MODE_PENDING

    def has_game_master(self) -> bool:
        return self.gm_seat != 0

    def has_members(self) -> bool:
        return bool(self.seats)

    def member_count(self) -> int:
        return len(self.seats)

    def configure(self, size: int, rng: Rng) -> bool:
        """人数を確定し、インサイダーと（神モードなら）GM の席を抽選する。設定済みなら False。

        配役を決めてから size を書くので、「人数は決まったが配役は未確定」の状態は観測されない。
        ランダム村ではオーナーも参加者なので、同じ操作の中で先頭に着席させる。
        """
        if self.size != 0:
            return False
        self.insider_seat = rng.randrange(size) + 1
        if self.gm_seat == GOD_MODE_PENDING:
            candidate = rng.randrange(size) + 1
            while candidate == self.insider_seat:
                candidate = rng.randrange(size) + 1
            self.gm_seat = candidate
        self.size = size
        if self.random_mode:
            self.join(self.owner_id)
        return True

    def join(self, user_id: str) -> Seat | None:
        """参加させて配役する。参加済みなら同じ席を返す。満員（人数未設定を含む）なら None。"""
        for seat in self.seats:
            if seat.user_id == user_id:
                return seat
        if len(self.seats) >= self.size:
            return None
        seat = Seat(user_id, self._role_for(len(self.seats) + 1))
        self.seats.append(seat)
        return seat

    def role_of(self, user_id: str) -> Role | None:
        for seat in self.seats:
            if seat.user_id == user_id:
                return seat.role
        return None

    def seat_number_of(self, user_id: str) -> int:
        """参加順の番号（1 始まり）。未参加なら 0。"""
        for index, seat in enumerate(self.seats, start=1):
            if seat.user_id == user_id:
                return index
        return 0

    def apply_reverse(self) -> bool:
        """誰も参加していないときだけ逆村にする。参加者がいれば False。"""
        if self.seats:
            return False
        self.reverse = True
        return True

    def _role_for(self, seat_number: int) -> Role:
        """逆村はインサイダーと村人を入れ替える。GM の席は変わらない。"""
        if seat_number == self.insider_seat:
            return Role.VILLAGER if self.reverse else Role.INSIDER
        if seat_number == self.gm_seat:
            return Role.GAME_MASTER
        return Role.INSIDER if self.reverse else Role.VILLAGER
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_model.py -q`
Expected: `16 passed`

- [ ] **Step 6: コミット**

```bash
git add src/insider_bot/village/model.py tests/fakes.py tests/test_village_model.py
git commit -m "feat: 通常村の状態（席による配役・逆村・ランダム村）を追加"
```

---

### Task 3: 特殊村の状態とレジストリ

**Files:**
- Modify: `src/insider_bot/village/model.py`（`SpecialVillage` を追加）
- Create: `src/insider_bot/village/registry.py`
- Test: `tests/test_village_model.py`（特殊村の節を追加）
- Test: `tests/test_village_registry.py`

**Interfaces:**
- Consumes: Task 2 の `Village`, `Rng`
- Produces: `model.py` の `SpecialVillage(messages: Sequence[str | None])`。属性 `number: int`、`messages: tuple[str | None, ...]`、`members: list[str]`。メソッド `join(user_id) -> bool`、`has_member(user_id) -> bool`、`message_for(user_id) -> str | None`（未参加なら None、空や None のメッセージなら `texts.NO_SPECIAL_MESSAGE`）、`seat_number_of(user_id) -> int`、`capacity() -> int`、`member_count() -> int`
- Produces: `registry.py` の `MIN_VILLAGE_NUMBER = 1000`、`MAX_VILLAGE_NUMBER = 9999`、`MIN_SPECIAL_NUMBER = 10000`、`MAX_SPECIAL_NUMBER = 99998`、`VillageRegistry(rng: Rng | None = None, max_count: int = 50)` の `add(village) -> int`、`get(number) -> Village | None`、`find_latest_owned(owner_id, predicate) -> Village | None`、`SpecialVillageRegistry(rng=None, max_count=30)` の `add(village) -> int`、`get(number) -> SpecialVillage | None`

- [ ] **Step 1: 特殊村の失敗するテストを書く**

`tests/test_village_model.py` の末尾に追加:

```python
# --- 特殊村 ---

from insider_bot.village.model import SpecialVillage  # noqa: E402


def test_special_village_hands_out_messages_in_join_order():
    village = SpecialVillage(["1人目", "2人目", "3人目"])
    assert village.capacity() == 3
    assert village.join("a")
    assert village.join("b")
    assert village.message_for("a") == "1人目"
    assert village.message_for("b") == "2人目"
    assert village.seat_number_of("a") == 1
    assert village.seat_number_of("b") == 2
    assert village.member_count() == 2


def test_special_village_join_is_idempotent_and_capacity_bound():
    village = SpecialVillage(["only"])
    assert village.join("a")
    assert village.join("a")
    assert not village.join("b")
    assert village.member_count() == 1


def test_special_village_blank_messages_get_the_placeholder():
    village = SpecialVillage([None, "", "本文"])
    for user in ("a", "b", "c"):
        assert village.join(user)
    assert village.message_for("a") == "メッセージは特にありません。"
    assert village.message_for("b") == "メッセージは特にありません。"
    assert village.message_for("c") == "本文"


def test_special_village_message_for_unknown_user_is_none():
    village = SpecialVillage(["x"])
    assert village.message_for("nobody") is None
    assert village.seat_number_of("nobody") == 0


def test_special_village_copies_the_messages():
    source = ["a", "b"]
    village = SpecialVillage(source)
    source.append("c")
    assert village.capacity() == 2
```

- [ ] **Step 2: レジストリの失敗するテストを書く**

```python
# tests/test_village_registry.py
import random

from insider_bot.village.model import SpecialVillage, Village
from insider_bot.village.registry import (
    MAX_SPECIAL_NUMBER,
    MAX_VILLAGE_NUMBER,
    MIN_SPECIAL_NUMBER,
    MIN_VILLAGE_NUMBER,
    SpecialVillageRegistry,
    VillageRegistry,
)
from tests.fakes import FixedRandom


def test_assigns_unique_four_digit_numbers():
    registry = VillageRegistry(random.Random(1))
    numbers = {registry.add(Village("owner")) for _ in range(50)}
    assert len(numbers) == 50
    assert all(MIN_VILLAGE_NUMBER <= n <= MAX_VILLAGE_NUMBER for n in numbers)


def test_add_writes_the_number_into_the_village():
    registry = VillageRegistry(random.Random(1))
    village = Village("owner")
    number = registry.add(village)
    assert village.number == number
    assert registry.get(number) is village


def test_evicts_the_oldest_village_beyond_the_limit():
    registry = VillageRegistry(random.Random(1), max_count=50)
    oldest = registry.add(Village("owner"))
    second = registry.add(Village("owner"))
    for _ in range(49):
        registry.add(Village("owner"))
    assert registry.get(oldest) is None
    assert registry.get(second) is not None


def test_find_latest_owned_returns_the_newest_match():
    registry = VillageRegistry(random.Random(1))
    registry.add(Village("other"))
    older = registry.add(Village("owner"))
    newer = registry.add(Village("owner"))
    assert registry.find_latest_owned("owner", lambda v: True).number == newer
    assert registry.find_latest_owned("owner", lambda v: v.number != newer).number == older
    assert registry.find_latest_owned("owner", lambda v: False) is None


def test_find_latest_owned_ignores_other_owners():
    registry = VillageRegistry(random.Random(1))
    registry.add(Village("other"))
    assert registry.find_latest_owned("owner", lambda v: True) is None


def test_number_draw_skips_taken_numbers_and_sweeps_when_unlucky():
    # 抽選は MIN〜MAX-1。100 回外れたら MIN から順に空きを探す（MAX は総当たりでしか出ない）
    registry = VillageRegistry(FixedRandom(*([0] * 101)))
    first = registry.add(Village("owner"))
    assert first == MIN_VILLAGE_NUMBER
    second = registry.add(Village("owner"))
    assert second == MIN_VILLAGE_NUMBER + 1


def test_special_registry_assigns_five_digit_numbers_and_evicts():
    registry = SpecialVillageRegistry(random.Random(1), max_count=30)
    first = registry.add(SpecialVillage(["a"]))
    assert MIN_SPECIAL_NUMBER <= first <= MAX_SPECIAL_NUMBER
    for _ in range(30):
        registry.add(SpecialVillage(["a"]))
    assert registry.get(first) is None


def test_special_registry_get_unknown_is_none():
    registry = SpecialVillageRegistry(random.Random(1))
    assert registry.get(12345) is None
```

- [ ] **Step 3: 失敗を確認する**

Run: `uv run pytest tests/test_village_model.py tests/test_village_registry.py -q`
Expected: `ImportError: cannot import name 'SpecialVillage'` と `ModuleNotFoundError ... registry`

- [ ] **Step 4: SpecialVillage を書く**

`src/insider_bot/village/model.py` の末尾に追加し、冒頭の import に `from collections.abc import Sequence` を足す。dataclass ではなく普通のクラスにする（メッセージ列を複製して tuple に固定する独自の初期化が必要なため）:

```python
class SpecialVillage:
    """任意のメッセージ集合を参加順に 1 通ずつ配る村。

    不変条件は「i 番目の参加者に i 番目のメッセージが対応する」ことと「参加者数はメッセージ数を超えない」こと。
    配布順は作成時に確定し（並べ替えは作る側の責務）、以降は参加者が増えるだけ。
    """

    def __init__(self, messages: Sequence[str | None]) -> None:
        self.messages: tuple[str | None, ...] = tuple(messages)
        self.number: int = 0
        self.members: list[str] = []

    def capacity(self) -> int:
        return len(self.messages)

    def member_count(self) -> int:
        return len(self.members)

    def has_member(self, user_id: str) -> bool:
        return user_id in self.members

    def join(self, user_id: str) -> bool:
        """参加済みなら True のまま。満員なら False。"""
        if user_id in self.members:
            return True
        if len(self.members) >= len(self.messages):
            return False
        self.members.append(user_id)
        return True

    def seat_number_of(self, user_id: str) -> int:
        try:
            return self.members.index(user_id) + 1
        except ValueError:
            return 0

    def message_for(self, user_id: str) -> str | None:
        """未参加なら None。空や None のメッセージは「メッセージは特にありません。」。"""
        seat = self.seat_number_of(user_id)
        if seat == 0:
            return None
        message = self.messages[seat - 1]
        return message if message else texts.NO_SPECIAL_MESSAGE
```

- [ ] **Step 5: レジストリを書く**

```python
# src/insider_bot/village/registry.py
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
```

- [ ] **Step 6: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_model.py tests/test_village_registry.py -q`
Expected: `29 passed`

- [ ] **Step 7: コミット**

```bash
git add src/insider_bot/village/model.py src/insider_bot/village/registry.py tests/test_village_model.py tests/test_village_registry.py
git commit -m "feat: 特殊村の状態と、通常村・特殊村のレジストリを追加"
```

---

### Task 4: お題辞書

**Files:**
- Create: `src/insider_bot/village/word.csv`（`/Users/fukasedaichi/git/LineBot/insider-game-bot/src/main/resources/word.csv` の複製）
- Create: `src/insider_bot/village/words.py`
- Test: `tests/test_village_words.py`

**Interfaces:**
- Consumes: Task 1 の `parsing.java_split` / `java_trim` / `parse_java_int`、Task 2 の `Rng`
- Produces: `words.py` の `BEGINNER_RANK = 2`、`ADVANCED_RANK = 3`、`EXPERT_RANK = 4`、`UNSPECIFIED_RANK = 10`、`Dictionary`（frozen dataclass: `words: tuple[str, ...]`、`last_lines: tuple[int, ...]`（添字 = 難易度 1〜5、添字 0 は 0）、メソッド `last_line(difficulty) -> int`、`is_empty` プロパティ、`pick(rank, rng) -> str | None`）、`load_dictionary(path: Path | None = None) -> Dictionary`、`parse_dictionary(lines: Iterable[str]) -> Dictionary`、`EMPTY_DICTIONARY`

- [ ] **Step 1: 辞書を複製する**

```bash
cp /Users/fukasedaichi/git/LineBot/insider-game-bot/src/main/resources/word.csv src/insider_bot/village/word.csv
wc -l src/insider_bot/village/word.csv
```

Expected: `8436`

- [ ] **Step 2: 失敗するテストを書く**

```python
# tests/test_village_words.py
import logging
import random

from insider_bot.village.words import (
    ADVANCED_RANK,
    BEGINNER_RANK,
    EMPTY_DICTIONARY,
    EXPERT_RANK,
    UNSPECIFIED_RANK,
    Dictionary,
    load_dictionary,
    parse_dictionary,
)
from tests.fakes import FixedRandom

# 行番号定数で表現していた頃の難易度境界。CSV から導出した結果がこれと一致すること
SECOND_LINE = 954
THIRD_LINE = 5084
FOURTH_LINE = 7646
FIFTH_LINE = 8436


def csv_rows() -> list[list[str]]:
    from insider_bot.village import words

    path = words.DEFAULT_PATH
    return [line.rstrip("\n").split(",") for line in path.read_text(encoding="utf-8").splitlines()]


def csv_words(from_line: int, to_line: int) -> set[str]:
    return {row[0] for number, row in enumerate(csv_rows(), start=1) if from_line <= number <= to_line}


def every_draw_comes_from(dictionary: Dictionary, rank: int, from_line: int, to_line: int) -> None:
    allowed = csv_words(from_line, to_line)
    rng = random.Random(0)
    for _ in range(200):
        word = dictionary.pick(rank, rng)
        assert word is not None
        assert word in allowed, f"難易度 {rank} の範囲外のお題: {word}"


def test_the_bundled_csv_matches_the_former_boundaries():
    dictionary = load_dictionary()
    assert not dictionary.is_empty
    assert dictionary.last_line(2) == SECOND_LINE
    assert dictionary.last_line(3) == THIRD_LINE
    assert dictionary.last_line(4) == FOURTH_LINE
    assert dictionary.last_line(5) == FIFTH_LINE
    assert len(dictionary.words) == FIFTH_LINE


def test_the_csv_is_sorted_by_difficulty():
    previous = 0
    for number, row in enumerate(csv_rows(), start=1):
        assert len(row) == 2, f"2 列でない行: {number}"
        difficulty = int(row[1])
        assert 1 <= difficulty <= 5, f"難易度が 1〜5 でない行: {number}"
        assert difficulty >= previous, f"難易度が昇順でない行: {number}"
        previous = difficulty


def test_beginner_draws_from_difficulty_1_to_3():
    every_draw_comes_from(load_dictionary(), BEGINNER_RANK, 1, THIRD_LINE)


def test_advanced_draws_from_difficulty_3_to_4():
    every_draw_comes_from(load_dictionary(), ADVANCED_RANK, SECOND_LINE + 1, FOURTH_LINE)


def test_expert_draws_from_difficulty_5():
    every_draw_comes_from(load_dictionary(), EXPERT_RANK, FOURTH_LINE + 1, FIFTH_LINE)


def test_unspecified_draws_from_everything_but_expert():
    every_draw_comes_from(load_dictionary(), UNSPECIFIED_RANK, 1, FOURTH_LINE)
    every_draw_comes_from(load_dictionary(), 0, 1, FOURTH_LINE)


def test_pick_uses_the_draw_as_a_line_number():
    dictionary = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])
    # 初心者: 1〜last(3)=3 行目。randrange(3) → 0 なら 1 行目
    assert dictionary.pick(BEGINNER_RANK, FixedRandom(0)) == "a"
    assert dictionary.pick(BEGINNER_RANK, FixedRandom(2)) == "c"
    # 上級者: last(2)+1=3 〜 last(4)=4 行目
    assert dictionary.pick(ADVANCED_RANK, FixedRandom(0)) == "c"
    assert dictionary.pick(ADVANCED_RANK, FixedRandom(1)) == "d"
    # 変態: last(4)+1=5 〜 last(5)=5 行目
    assert dictionary.pick(EXPERT_RANK, FixedRandom(0)) == "e"
    # 指定なし: 1 〜 last(4)=4 行目
    assert dictionary.pick(UNSPECIFIED_RANK, FixedRandom(3)) == "d"


def test_empty_dictionary_picks_none():
    assert EMPTY_DICTIONARY.is_empty
    assert EMPTY_DICTIONARY.pick(BEGINNER_RANK, random.Random(0)) is None
    assert EMPTY_DICTIONARY.last_line(3) == 0


def test_broken_csv_is_discarded_entirely(caplog):
    broken = [
        ["a,1", "b,3", "c,2", "d,4", "e,5"],  # 昇順を破る
        ["a,1", "b,2", "c,4", "d,5"],  # 難易度 3 の語がない
        ["a,1", "b,x", "c,3", "d,4", "e,5"],  # 整数でない
        ["a", "b,2", "c,3", "d,4", "e,5"],  # 2 列目がない
        ["a,0", "b,2", "c,3", "d,4", "e,5"],  # 範囲外
        ["a,1", "b,2", "c,3", "d,4", "e,6"],  # 範囲外
        ["a,0_1", "b,2", "c,3", "d,4", "e,5"],  # Integer.parseInt は「_」を読めない
        ["a,　1　", "b,2", "c,3", "d,4", "e,5"],  # trim() は全角スペースを除かない
    ]
    for lines in broken:
        with caplog.at_level(logging.ERROR, logger="insider_bot.village.words"):
            caplog.clear()
            dictionary = parse_dictionary(lines)
        assert dictionary.is_empty, lines
        assert any(record.levelno == logging.ERROR for record in caplog.records), lines


def test_only_the_first_column_is_the_word_and_the_difficulty_is_trimmed():
    # Java の split(",") と同じく 1 列目だけを語として使い、3 列目以降は無視する。難易度は trim してから読む
    dictionary = parse_dictionary(["a,1,extra", "b, 2 ", "c,3", "d,４", "e,5"])
    assert dictionary.words[0] == "a"
    assert dictionary.last_line(2) == 2
    assert dictionary.last_line(4) == 4


def test_missing_file_gives_an_empty_dictionary(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="insider_bot.village.words"):
        dictionary = load_dictionary(tmp_path / "nope.csv")
    assert dictionary.is_empty
    assert caplog.records
```

- [ ] **Step 3: 失敗を確認する**

Run: `uv run pytest tests/test_village_words.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.village.words'`

- [ ] **Step 4: 辞書を書く**

```python
# src/insider_bot/village/words.py
"""お題辞書。CSV（1 列目がお題、2 列目が難易度 1〜5）を起動時に 1 度だけ読み、難易度の区間から引く。

難易度の区間は 2 列目から導出するので、行を増減しても境界を手で直す必要はない。ただし CSV は難易度の
昇順でなければならない。難易度が読めない行、昇順を破る行、語のない難易度があれば辞書全体を破棄する。
中途半端な辞書から引くと、違う難易度のお題を黙って配ることになるため。破棄したときの抽選は None を返す。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from insider_bot.village.model import Rng
from insider_bot.village.parsing import java_split, java_trim, parse_java_int

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).parent / "word.csv"

# 利用者に見せる難易度（UI の番号）。CSV の難易度とは体系が違う
BEGINNER_RANK = 2
ADVANCED_RANK = 3
EXPERT_RANK = 4
UNSPECIFIED_RANK = 10

_MIN_DIFFICULTY = 1
_MAX_DIFFICULTY = 5


@dataclass(frozen=True)
class Dictionary:
    words: tuple[str, ...]
    # 添字 = CSV の難易度。その難易度の最終行番号（1 始まり）。添字 0 は常に 0
    last_lines: tuple[int, ...]

    @property
    def is_empty(self) -> bool:
        return not self.words

    def last_line(self, difficulty: int) -> int:
        return self.last_lines[difficulty]

    def pick(self, rank: int, rng: Rng) -> str | None:
        """初心者は難易度 1〜3、上級者は 3〜4、変態は 5、指定なしは 1〜4 から引く。空なら None。"""
        if self.is_empty:
            return None
        if rank == BEGINNER_RANK:
            line = rng.randrange(self.last_line(3)) + 1
        elif rank == ADVANCED_RANK:
            line = rng.randrange(self.last_line(4) - self.last_line(2)) + self.last_line(2) + 1
        elif rank == EXPERT_RANK:
            line = rng.randrange(self.last_line(5) - self.last_line(4)) + self.last_line(4) + 1
        else:
            line = rng.randrange(self.last_line(4)) + 1
        return self.words[min(line, len(self.words)) - 1]


EMPTY_DICTIONARY = Dictionary((), (0,) * (_MAX_DIFFICULTY + 1))


def parse_dictionary(lines: Iterable[str]) -> Dictionary:
    words: list[str] = []
    last_lines = [0] * (_MAX_DIFFICULTY + 1)
    previous = 0
    for line in lines:
        columns = java_split(line.rstrip("\r\n"), ",")
        difficulty = _difficulty_of(columns)
        if difficulty < _MIN_DIFFICULTY or difficulty > _MAX_DIFFICULTY or difficulty < previous:
            log.error("お題辞書の %d 行目の難易度が使えないため、辞書を破棄します", len(words) + 1)
            return EMPTY_DICTIONARY
        words.append(columns[0])
        last_lines[difficulty] = len(words)
        previous = difficulty
    for difficulty in range(_MIN_DIFFICULTY, _MAX_DIFFICULTY + 1):
        if last_lines[difficulty] <= last_lines[difficulty - 1]:
            log.error("お題辞書に難易度 %d の語がないため、辞書を破棄します", difficulty)
            return EMPTY_DICTIONARY
    return Dictionary(tuple(words), tuple(last_lines))


def load_dictionary(path: Path | None = None) -> Dictionary:
    path = DEFAULT_PATH if path is None else path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        log.error("お題辞書 %s を読めません: %s", path.name, error)
        return EMPTY_DICTIONARY
    return parse_dictionary(text.splitlines())


def _difficulty_of(columns: list[str]) -> int:
    """2 列目の難易度。Java と同じく trim してから Integer.parseInt の規則で読む。読めなければ -1。"""
    if len(columns) < 2:
        return -1
    difficulty = parse_java_int(java_trim(columns[1]))
    return -1 if difficulty is None else difficulty
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_words.py -q`
Expected: `11 passed`

- [ ] **Step 6: コミット**

```bash
git add src/insider_bot/village/word.csv src/insider_bot/village/words.py tests/test_village_words.py
git commit -m "feat: お題辞書（8,436 語）の読み込みと難易度別の抽選を追加"
```

---

### Task 5: 役職画像

**Files:**
- Create: `src/insider_bot/web/static/roles/{INSIDER,VILLAGERS,GM,GOD,966mpnqz}.png`（`/Users/fukasedaichi/git/LineBot/Image/` の複製）
- Create: `src/insider_bot/village/illust.py`
- Test: `tests/test_village_illust.py`

**Interfaces:**
- Consumes: Task 1 の `parsing.java_split` / `parse_java_int`、Task 2 の `Rng`
- Produces: `illust.py` の `Illustrations(base_url: str, rng: Rng | None = None)`。メソッド `url_for(role_key: str) -> str`（`"INSIDER"` / `"VILLAGERS"` / `"GM"` / `"GOD"`。カタログに候補があれば重み付き抽選、なければ既定画像）、`default_url(role_key) -> str`（`{base_url}/static/roles/{role_key}.png`）、`invitation_image_url` プロパティ（`{base_url}/static/roles/966mpnqz.png`）、`apply_catalog(files: list[dict]) -> None`（カタログ応答の `files` を解析して差し替える）、`async refresh(client) -> None`（`catalog_url` を GET して `apply_catalog`。失敗は WARNING で前回分を維持）。コンストラクタの任意引数 `catalog_url: str | None = None`
- Produces: `parse_catalog(files: list[dict]) -> dict[str, tuple[WeightedUrl, ...]]`、`WeightedUrl(url: str, cumulative_weight: int)`

- [ ] **Step 1: 画像を複製する**

```bash
mkdir -p src/insider_bot/web/static/roles
cp /Users/fukasedaichi/git/LineBot/Image/{INSIDER,VILLAGERS,GM,GOD,966mpnqz}.png src/insider_bot/web/static/roles/
ls src/insider_bot/web/static/roles/
```

Expected: 5 ファイル

- [ ] **Step 2: 失敗するテストを書く**

```python
# tests/test_village_illust.py
import logging

import pytest

from insider_bot.village.illust import Illustrations, WeightedUrl, parse_catalog
from tests.fakes import FixedRandom

BASE = "https://game.example.com"


def entry(name, url):
    return {"name": name, "url": url}


def test_default_urls_are_served_from_our_own_static_dir():
    illust = Illustrations(BASE)
    assert illust.default_url("INSIDER") == f"{BASE}/static/roles/INSIDER.png"
    assert illust.default_url("VILLAGERS") == f"{BASE}/static/roles/VILLAGERS.png"
    assert illust.default_url("GM") == f"{BASE}/static/roles/GM.png"
    assert illust.default_url("GOD") == f"{BASE}/static/roles/GOD.png"
    assert illust.invitation_image_url == f"{BASE}/static/roles/966mpnqz.png"


def test_trailing_slash_in_base_url_is_tolerated():
    assert Illustrations(BASE + "/").default_url("GM") == f"{BASE}/static/roles/GM.png"


def test_falls_back_to_defaults_while_no_catalog_is_loaded():
    illust = Illustrations(BASE, FixedRandom(0))
    for key in ("INSIDER", "VILLAGERS", "GM", "GOD"):
        assert illust.url_for(key) == illust.default_url(key)


def test_entries_without_a_three_part_name_are_ignored():
    parsed = parse_catalog(
        [
            entry("INSIDER_2_a.png", "https://x/insider.png"),
            entry("VILLAGERS.png", "https://x/no-weight.png"),
            entry("GM_1_b_c.png", "https://x/too-many-parts.png"),
        ]
    )
    assert set(parsed) == {"INSIDER"}


def test_names_and_weights_are_read_like_java():
    # Java の String.split は末尾の空要素を落とし、Integer.parseInt は空白と int の範囲外を読まず、全角数字を読む
    parsed = parse_catalog(
        [
            entry("GM_1_a.png_", "https://x/trailing.png"),  # 末尾の空要素を落として 3 部
            entry("GM_1_", "https://x/two-parts.png"),  # 2 部
            entry("GM_1_a_b_", "https://x/four-parts.png"),  # 4 部
            entry("GM_ 1 _a.png", "https://x/spaced.png"),  # 重みに空白
            entry("GM_2147483648_a.png", "https://x/overflow.png"),  # int の範囲外
            entry("GM_２_b.png", "https://x/fullwidth.png"),  # 全角数字の重み
        ]
    )
    assert parsed == {"GM": (WeightedUrl("https://x/trailing.png", 1), WeightedUrl("https://x/fullwidth.png", 3))}


def test_an_unusable_entry_is_skipped_without_dropping_the_rest(caplog):
    with caplog.at_level(logging.WARNING, logger="insider_bot.village.illust"):
        parsed = parse_catalog(
            [
                entry("INSIDER_おおい_broken.png", "https://x/broken.png"),
                entry("GM_1_no-url.png", None),
                entry(None, "https://x/no-name.png"),
                {"url": "https://x/no-name-key.png"},
                entry("VILLAGERS_1_ok.png", "https://x/villagers.png"),
            ]
        )
    assert set(parsed) == {"VILLAGERS"}
    assert "4" in caplog.text  # 読み飛ばした件数


def test_weights_decide_how_many_draw_slots_a_file_gets():
    illust = Illustrations(BASE)
    illust.apply_catalog([entry("INSIDER_1_rare.png", "https://x/rare.png"), entry("INSIDER_3_common.png", "https://x/common.png")])
    draws = []
    for value in (0, 1, 3):
        illust._rng = FixedRandom(value)
        draws.append(illust.url_for("INSIDER"))
    assert draws == ["https://x/rare.png", "https://x/common.png", "https://x/common.png"]


def test_the_draw_bound_is_the_total_weight():
    class Recording(FixedRandom):
        bound = None

        def randrange(self, n):
            self.bound = n
            return 0

    rng = Recording()
    illust = Illustrations(BASE, rng)
    illust.apply_catalog([entry("INSIDER_1_rare.png", "https://x/rare.png"), entry("INSIDER_3_common.png", "https://x/common.png")])
    illust.url_for("INSIDER")
    assert rng.bound == 4


def test_files_without_a_positive_weight_are_never_drawn():
    illust = Illustrations(BASE, FixedRandom(0))
    illust.apply_catalog(
        [
            entry("INSIDER_0_zero.png", "https://x/zero.png"),
            entry("INSIDER_-2_negative.png", "https://x/negative.png"),
            entry("INSIDER_1_only.png", "https://x/only.png"),
        ]
    )
    assert illust.url_for("INSIDER") == "https://x/only.png"


def test_a_role_without_any_positive_weight_falls_back_to_the_default():
    illust = Illustrations(BASE, FixedRandom(0))
    illust.apply_catalog([entry("INSIDER_0_a.png", "https://x/a.png"), entry("INSIDER_0_b.png", "https://x/b.png")])
    assert illust.url_for("INSIDER") == illust.default_url("INSIDER")
    # 他の役職は候補がないので既定
    assert illust.url_for("GM") == illust.default_url("GM")


def test_unknown_role_key_is_rejected():
    with pytest.raises(KeyError):
        Illustrations(BASE).default_url("NOPE")


class FakeResponse:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


async def test_refresh_replaces_the_catalog():
    illust = Illustrations(BASE, FixedRandom(0), catalog_url="https://script.google.com/macros/s/x/exec")
    client = FakeClient(FakeResponse({"files": [entry("GM_1_a.png", "https://x/gm.png")]}))
    await illust.refresh(client)
    assert client.calls[0][0] == "https://script.google.com/macros/s/x/exec"
    assert client.calls[0][1]["follow_redirects"] is True
    assert illust.url_for("GM") == "https://x/gm.png"


async def test_refresh_keeps_the_previous_catalog_on_failure(caplog):
    illust = Illustrations(BASE, FixedRandom(0), catalog_url="https://script.google.com/macros/s/x/exec")
    await illust.refresh(FakeClient(FakeResponse({"files": [entry("GM_1_a.png", "https://x/gm.png")]})))
    with caplog.at_level(logging.WARNING, logger="insider_bot.village.illust"):
        await illust.refresh(FakeClient(error=RuntimeError("boom")))
        await illust.refresh(FakeClient(FakeResponse({"nope": 1})))
    assert illust.url_for("GM") == "https://x/gm.png"
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2


async def test_refresh_without_a_catalog_url_does_nothing():
    illust = Illustrations(BASE, FixedRandom(0))
    client = FakeClient()
    await illust.refresh(client)
    assert client.calls == []
```

- [ ] **Step 3: 失敗を確認する**

Run: `uv run pytest tests/test_village_illust.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.village.illust'`

- [ ] **Step 4: 画像モジュールを書く**

```python
# src/insider_bot/village/illust.py
"""役職に添える画像。既定画像は自前の静的ファイル、任意で外部カタログから重み付きで抽選する。

カタログは Google Apps Script のウェブアプリが返す {"files": [{"name", "url"}]}。
name は <役職名>_<重み>_<任意> の 3 部構成で、重みは抽選枠の数。規約外の要素はその要素だけ読み飛ばす
（1 件の書き間違いで全役職が既定画像に戻るのは割に合わない）。取得に失敗したら前回分を使い続ける。

カタログ URL は必ずデプロイ URL（/macros/s/<ID>/exec）を指定する。ブラウザで開いたときの転送先
（script.googleusercontent.com）は一時的な鍵を含み、失効すると 400 を返し続ける。
"""

from __future__ import annotations

import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from insider_bot.village.model import Rng
from insider_bot.village.parsing import java_split, parse_java_int

log = logging.getLogger(__name__)

ROLE_FILES = {"INSIDER": "INSIDER.png", "VILLAGERS": "VILLAGERS.png", "GM": "GM.png", "GOD": "GOD.png"}
INVITATION_FILE = "966mpnqz.png"
STATIC_ROLES_PATH = "/static/roles/"

CATALOG_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class WeightedUrl:
    url: str
    # この要素までの重みの合計。抽選値がこの値未満ならこの URL
    cumulative_weight: int


def parse_catalog(files: list[Mapping[str, Any]]) -> dict[str, tuple[WeightedUrl, ...]]:
    parsed: dict[str, list[WeightedUrl]] = {}
    ignored = 0
    for file in files:
        name = file.get("name")
        url = file.get("url")
        # Java の String.split / Integer.parseInt と同じ規則で読む（末尾の空要素を落とす、全角数字も重みとして読む）
        parts = java_split(name, "_") if isinstance(name, str) else []
        weight = parse_java_int(parts[1]) if len(parts) == 3 else None
        if weight is None or not isinstance(url, str):
            ignored += 1
            continue
        candidates = parsed.setdefault(parts[0], [])
        total = candidates[-1].cumulative_weight if candidates else 0
        candidates.append(WeightedUrl(url, total + max(weight, 0)))
    if ignored:
        # ファイル名は画像の名前で、利用者の識別子やお題は含まれない
        log.warning("役職画像のカタログのうち %d 件を読み飛ばしました", ignored)
    return {role: tuple(candidates) for role, candidates in parsed.items()}


class Illustrations:
    def __init__(self, base_url: str, rng: Rng | None = None, catalog_url: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._rng: Rng = rng if rng is not None else random.Random()
        self._catalog_url = catalog_url
        self._catalog: dict[str, tuple[WeightedUrl, ...]] = {}

    def default_url(self, role_key: str) -> str:
        return f"{self._base_url}{STATIC_ROLES_PATH}{ROLE_FILES[role_key]}"

    @property
    def invitation_image_url(self) -> str:
        return f"{self._base_url}{STATIC_ROLES_PATH}{INVITATION_FILE}"

    def url_for(self, role_key: str) -> str:
        candidates = self._catalog.get(role_key)
        if not candidates:
            return self.default_url(role_key)
        total = candidates[-1].cumulative_weight
        if total <= 0:
            return self.default_url(role_key)
        draw = self._rng.randrange(total)
        for candidate in candidates:
            if draw < candidate.cumulative_weight:
                return candidate.url
        return self.default_url(role_key)

    def apply_catalog(self, files: list[Mapping[str, Any]]) -> None:
        self._catalog = parse_catalog(files)

    async def refresh(self, client: Any) -> None:
        """カタログを取り直す。URL が未設定なら何もしない。失敗は WARNING で前回分を維持する。"""
        if self._catalog_url is None:
            return
        try:
            response = await client.get(self._catalog_url, follow_redirects=True, timeout=CATALOG_TIMEOUT_SECONDS)
            response.raise_for_status()
            body = response.json()
            files = body.get("files") if isinstance(body, dict) else None
            if not isinstance(files, list):
                log.warning("役職画像のカタログの応答に files がありません")
                return
            self.apply_catalog(files)
        except Exception as error:
            log.warning("役職画像のカタログを取り直せませんでした: %s", error)
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_illust.py -q`
Expected: `14 passed`

- [ ] **Step 6: コミット**

```bash
git add src/insider_bot/web/static/roles src/insider_bot/village/illust.py tests/test_village_illust.py
git commit -m "feat: 役職画像を同梱し、外部カタログからの重み付き抽選を追加"
```

---

### Task 6: Werewords の役職列

**Files:**
- Create: `src/insider_bot/village/werewords.py`
- Test: `tests/test_village_werewords.py`

**Interfaces:**
- Consumes: Task 1 の `texts.WEREWORDS_MESSAGES`, `texts.WEREWORDS_ROLES`、Task 2 の `Rng`
- Produces: `werewords.py` の `MIN_WEREWORDS_SIZE = 3`、`werewords_messages(god_mode: bool, size: int, topic: str, rng: Rng) -> list[str]`、`role_name(role_number: int) -> str`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_village_werewords.py
import random

from insider_bot.village.werewords import MIN_WEREWORDS_SIZE, role_name, werewords_messages
from tests.fakes import FixedRandom


def test_god_mode_distributes_one_message_per_participant():
    messages = werewords_messages(True, 5, "すいか", random.Random(0))
    assert len(messages) == 5
    assert messages[0].startswith("あなたの役職はGMです。")
    assert "が欠けています。" in messages[0]


def test_without_god_mode_an_extra_villager_message_is_added():
    messages = werewords_messages(False, 5, "すいか", random.Random(0))
    assert len(messages) == 6
    assert messages[0] == "あなたの役職は村人です"


def test_every_message_is_assigned():
    for message in werewords_messages(True, 4, "すいか", random.Random(0)):
        assert message


def test_the_missing_role_is_the_first_after_shuffle():
    # shuffle しない乱数なら並びは [占師, インサイダー, 村人, 村人, 村人]。先頭の占師が欠け
    messages = werewords_messages(True, 5, "すいか", FixedRandom())
    assert messages[0] == "あなたの役職はGMです。お題は「すいか」です。\n役職は「占師」が欠けています。"
    assert messages[1] == "あなたの役職はインサイダーです。お題は「すいか」です。"
    assert messages[2:] == ["あなたの役職は村人です"] * 3


def test_without_god_mode_all_roles_are_distributed_including_the_missing_one():
    messages = werewords_messages(False, 3, "すいか", FixedRandom())
    assert messages == [
        "あなたの役職は村人です",
        "あなたの役職は占師です。お題は「すいか」です。",
        "あなたの役職はインサイダーです。お題は「すいか」です。",
        "あなたの役職は村人です",
    ]


def test_the_missing_role_is_named_rather_than_described():
    assert role_name(3) == "村人"
    saw_missing_villager = False
    for seed in range(100):
        gm = werewords_messages(True, 5, "すいか", random.Random(seed))[0]
        assert gm.count("あなたの役職は") == 1, gm
        if "役職は「村人」が欠けています。" in gm:
            saw_missing_villager = True
    assert saw_missing_villager


def test_minimum_size_is_three():
    assert MIN_WEREWORDS_SIZE == 3
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_village_werewords.py -q`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 実装する**

```python
# src/insider_bot/village/werewords.py
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
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_werewords.py -q`
Expected: `7 passed`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/village/werewords.py tests/test_village_werewords.py
git commit -m "feat: Werewords の役職メッセージ列を追加"
```

---

### Task 7: 返事の組み立て（messages.py）

**Files:**
- Create: `src/insider_bot/village/messages.py`
- Test: `tests/test_village_messages.py`

**Interfaces:**
- Consumes: Task 1 の返事モデルと `texts`、Task 2・3 の `Village`, `SpecialVillage`, `Role`、Task 5 の `Illustrations`
- Produces: `messages.py` の純粋関数（すべて `list[Reply]` を返す）
  - `role_reply(village: Village, user_id: str, illust: Illustrations) -> list[Reply]`（役職ごとの Buttons と overflow。未参加なら `[Text(DEFAULT_MESSAGE)]`）
  - `status_reply(village: Village | SpecialVillage, user_id: str) -> list[Reply]`（「あなたは N 番目の参加者です。\n　入室状況：n/m人」）
  - `owner_reply(village: Village) -> list[Reply]`（配布状況。Buttons（再確認）、overflow は Text）
  - `special_role_reply(village: SpecialVillage, user_id: str) -> list[Reply] | None`（未参加なら None）
  - `default_reply() -> list[Reply]`（村の作成を促す Confirm）
  - `created_reply(number: int) -> list[Reply]`、`random_created_reply(number) -> list[Reply]`
  - `size_set_reply(village: Village, god_mode: bool, illust) -> list[Reply]`、`random_size_set_reply(village, size, illust) -> list[Reply]`
  - `topic_set_reply(village: Village) -> list[Reply]`、`reverse_set_reply(village) -> list[Reply]`、`werewords_created_reply(topic, number, god_mode) -> list[Reply]`
  - `candidate_reply(topic: str | None) -> list[Reply]`、`invitation_reply(illust) -> list[Reply]`、`special_form_reply(url: str) -> list[Reply]`、`size_error_reply() -> list[Reply]`、`full_reply() -> list[Reply]`、`random_numset_reply() -> list[Reply]`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_village_messages.py
from insider_bot.village import messages, texts
from insider_bot.village.illust import Illustrations
from insider_bot.village.model import SpecialVillage, Village
from insider_bot.village.reply import Buttons, Confirm, Image, MessageAction, PostbackAction, Text
from tests.fakes import FixedRandom

BASE = "https://game.example.com"
ILLUST = Illustrations(BASE, FixedRandom(0))


def village_with(size: int, insider_at: int, topic: str = "すいか", number: int = 1234, god_at: int | None = None) -> Village:
    village = Village("owner")
    village.number = number
    village.set_topic(topic)
    if god_at is not None:
        village.mark_god_mode()
        assert village.configure(size, FixedRandom(insider_at - 1, god_at - 1))
    else:
        assert village.configure(size, FixedRandom(insider_at - 1))
    return village


# --- 役職 ---


def test_insider_reply_has_image_button_and_text_overflow():
    village = village_with(2, insider_at=1)
    village.join("user")
    reply = messages.role_reply(village, "user", ILLUST)
    text = "あなたの役職はインサイダーです。お題は『すいか』です。"
    assert reply == [
        Buttons(
            text,
            (PostbackAction("入室状況確認", "1234"),),
            image=f"{BASE}/static/roles/INSIDER.png",
            overflow=(Text(text), Text("あなたは1番目の参加者です。\n　入室状況：1/2人")),
        )
    ]


def test_villager_reply_has_image_button_without_overflow():
    village = village_with(2, insider_at=2)
    village.join("user")
    reply = messages.role_reply(village, "user", ILLUST)
    assert reply == [
        Buttons("あなたの役職は村人です。", (PostbackAction("入室状況確認", "1234"),), image=f"{BASE}/static/roles/VILLAGERS.png")
    ]


def test_game_master_reply_has_three_tiers():
    village = village_with(3, insider_at=1, god_at=2)
    village.join("a")
    village.join("gm")
    text = "役職はＧＭです。\n2/3人にお題を配りました。お題は『すいか』です。"
    status = Text("あなたは2番目の参加者です。\n　入室状況：2/3人")
    assert messages.role_reply(village, "gm", ILLUST) == [
        Buttons(
            text,
            (PostbackAction("入室状況確認", "1234"),),
            image=f"{BASE}/static/roles/GM.png",
            overflow=(Buttons(text, (PostbackAction("入室状況確認", "1234"),), overflow=(Text(text), status)),),
        )
    ]


def test_role_reply_for_a_stranger_is_the_default_text():
    village = village_with(2, insider_at=1)
    assert messages.role_reply(village, "nobody", ILLUST) == [Text(texts.DEFAULT_MESSAGE)]


def test_unset_topic_is_shown_as_null_like_java():
    # お題を決めずに人数を設定した村。Java の文字列連結と同じく『null』と出る（Python の f 文字列なら『None』）
    village = Village("owner")
    village.number = 1234
    assert village.configure(2, FixedRandom(0))
    village.join("user")
    assert messages.role_reply(village, "user", ILLUST)[0].text == "あなたの役職はインサイダーです。お題は『null』です。"
    assert messages.owner_reply(village)[0].text == "1234村：1/2人にお題を配りました。お題は『null』です。"
    god = Village("owner")
    god.number = 1234
    god.mark_god_mode()
    assert god.configure(2, FixedRandom(0, 1))
    god.join("a")
    god.join("gm")
    assert messages.role_reply(god, "gm", ILLUST)[0].text == "役職はＧＭです。\n2/2人にお題を配りました。お題は『null』です。"


def test_topic_with_comma_and_newline_is_kept_verbatim():
    village = village_with(1, insider_at=1, topic="りんご,みかん\nぶどう")
    village.join("user")
    assert messages.role_reply(village, "user", ILLUST)[0].text == "あなたの役職はインサイダーです。お題は『りんご,みかん\nぶどう』です。"


# --- 配布状況 ---


def test_status_reply_counts_from_one_and_zero_for_strangers():
    village = village_with(3, insider_at=1)
    village.join("a")
    village.join("b")
    assert messages.status_reply(village, "b") == [Text("あなたは2番目の参加者です。\n　入室状況：2/3人")]
    assert messages.status_reply(village, "nobody") == [Text("あなたは0番目の参加者です。\n　入室状況：2/3人")]


def test_owner_reply_is_a_button_with_text_overflow():
    village = village_with(2, insider_at=1)
    village.join("a")
    text = "1234村：1/2人にお題を配りました。お題は『すいか』です。"
    assert messages.owner_reply(village) == [Buttons(text, (MessageAction("再確認", "1234"),), overflow=(Text(text),))]


# --- 特殊村 ---


def test_special_role_reply_is_a_button_with_text_and_status_overflow():
    village = SpecialVillage(["あなたの役職は村人です", "x"])
    village.number = 12345
    village.join("user")
    assert messages.special_role_reply(village, "user") == [
        Buttons(
            "あなたの役職は村人です",
            (PostbackAction("入室状況確認", "12345"),),
            overflow=(Text("あなたの役職は村人です"), Text("あなたは1番目の参加者です。\n　入室状況：1/2人")),
        )
    ]


def test_special_role_reply_for_blank_message_and_stranger():
    village = SpecialVillage([None])
    village.number = 12345
    assert messages.special_role_reply(village, "nobody") is None
    village.join("user")
    assert messages.special_role_reply(village, "user")[0].text == "メッセージは特にありません。"


def test_special_status_reply():
    village = SpecialVillage(["a", "b", "c"])
    village.join("x")
    assert messages.status_reply(village, "x") == [Text("あなたは1番目の参加者です。\n　入室状況：1/3人")]


# --- 案内 ---


def test_default_reply_is_a_confirm_with_two_choices():
    assert messages.default_reply() == [
        Confirm("村の作成をしますか？", (MessageAction("GM", "お題"), MessageAction("神", "神")), alt_text=texts.DEFAULT_MESSAGE)
    ]


def test_created_reply():
    text = "1234村 を新しく作成しました。お題を入力してください。"
    assert messages.created_reply(1234) == [
        Buttons(text + "\nお題の自動取得もできます。", (PostbackAction("お題の自動取得", "0"),), alt_text=text)
    ]


def test_random_created_reply():
    assert messages.random_created_reply(1234) == [Text("1234村 を新しく作成しました。人数を設定してください。役職もお題もランダムに配ります。")]


def test_size_set_reply_uses_god_or_gm_image():
    village = village_with(3, insider_at=1)
    text = "人数を『3人』に設定しました。\n皆さんに村番号を伝えてください。"
    assert messages.size_set_reply(village, god_mode=False, illust=ILLUST) == [
        Buttons(
            text,
            (MessageAction("確認", "1234"),),
            image=f"{BASE}/static/roles/GM.png",
            title="1234村",
            alt_text=text + "配布状況の確認は村番号を入力してください。",
        )
    ]
    assert messages.size_set_reply(village, god_mode=True, illust=ILLUST)[0].image == f"{BASE}/static/roles/GOD.png"


def test_random_size_set_reply_includes_the_owners_role():
    village = Village("owner")
    village.number = 1234
    village.set_topic("すいか")
    village.mark_god_mode()
    village.random_mode = True
    # インサイダーは3番目、GM は1番目 → オーナーは GM
    village.configure(4, FixedRandom(2, 0))
    reply = messages.random_size_set_reply(village, 4, ILLUST)
    assert reply[0] == Text("1234村：人数を『4人』に設定しました。\n皆さんに村番号を伝えてください。")
    assert reply[1:] == messages.role_reply(village, "owner", ILLUST)


def test_topic_set_reply_depends_on_god_mode():
    village = Village("owner")
    village.number = 1234
    village.set_topic("すいか")
    assert messages.topic_set_reply(village) == [Text("1234村 のお題を『すいか』に設定しました。\n" + texts.OWNER_NUMSET_MESSAGE)]
    village.mark_god_mode()
    assert messages.topic_set_reply(village) == [Text("1234村 のお題を『すいか』に設定しました。\n" + texts.GOD_NUMSET_MESSAGE)]


def test_reverse_set_reply():
    village = village_with(3, insider_at=1)
    assert messages.reverse_set_reply(village) == [Text("1234村 を『逆村』に設定しました。\nお題を知らない村人が1人となります。")]


def test_werewords_created_reply():
    assert messages.werewords_created_reply("すいか", 12345, god_mode=True) == [
        Text("お題を『すいか』として新たにワーワーズの『12345』村を作成しました。参加者へ『12345』を伝えてください。")
    ]
    assert messages.werewords_created_reply("すいか", 12345, god_mode=False) == [
        Text(
            "お題を『すいか』として新たにワーワーズの『12345』村を作成しました。参加者へ『12345』を伝え、あなたも入室してください。\n"
            "\n■注意\nあなたはGMです。入室時に表示された役職が欠けた役職となります。"
        )
    ]


def test_candidate_reply_offers_confirm_and_three_difficulties():
    text = "お題は「すいか」です。確定しますか？"
    assert messages.candidate_reply("すいか") == [
        Buttons(
            text,
            (
                MessageAction("確定", "すいか"),
                PostbackAction("初心者", "2"),
                PostbackAction("上級者", "3"),
                PostbackAction("変態", "4"),
            ),
            alt_text=text,
        )
    ]


def test_candidate_reply_with_a_broken_dictionary_shows_null_like_java():
    assert messages.candidate_reply(None)[0].text == "お題は「null」です。確定しますか？"
    assert messages.candidate_reply(None)[0].actions[0] == MessageAction("確定", "null")


def test_invitation_reply():
    url = f"{BASE}/static/roles/966mpnqz.png"
    assert messages.invitation_reply(ILLUST) == [Image(url), Text("https://line.me/R/ti/p/%40966mpnqz"), Text("お友達ID\n@966mpnqz")]


def test_simple_text_replies():
    assert messages.special_form_reply("https://x/village/special") == [Text("https://x/village/special")]
    assert messages.size_error_reply() == [Text(texts.ERR_NUMSET_MESSAGE)]
    assert messages.full_reply() == [Text("村がいっぱいです。")]
    assert messages.random_numset_reply() == [Text(texts.RANDOM_NUMSET_MESSAGE)]
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_village_messages.py -q`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 実装する**

```python
# src/insider_bot/village/messages.py
"""返事の組み立て。状態から返事モデルへの純粋関数で、文言は Java の LineBot と一字一句同じ。

LINE のボタンテンプレートの文字数制限（画像つき 60、画像なし 160）で Java が Text に落としていた分岐は、
Buttons.overflow として表す。収まるかどうかの判断は LINE の入口が行い、Web は常に本体を描く。
"""

from __future__ import annotations

from insider_bot.village import texts
from insider_bot.village.illust import Illustrations
from insider_bot.village.model import Role, SpecialVillage, Village
from insider_bot.village.reply import Buttons, Confirm, Image, MessageAction, PostbackAction, Reply, Text
from insider_bot.village.words import ADVANCED_RANK, BEGINNER_RANK, EXPERT_RANK


def _shown(topic: str | None) -> str:
    """Java の文字列連結と同じく、未設定のお題は「null」と書く。"""
    return "null" if topic is None else topic


def _status_text(village: Village | SpecialVillage, user_id: str) -> str:
    return f"あなたは{village.seat_number_of(user_id)}番目の参加者です。\n　入室状況：{village.member_count()}/{village.capacity() if isinstance(village, SpecialVillage) else village.size}人"


def status_reply(village: Village | SpecialVillage, user_id: str) -> list[Reply]:
    return [Text(_status_text(village, user_id))]


def role_reply(village: Village, user_id: str, illust: Illustrations) -> list[Reply]:
    role = village.role_of(user_id)
    if role is None:
        return [Text(texts.DEFAULT_MESSAGE)]
    status = Text(_status_text(village, user_id))
    check = (PostbackAction("入室状況確認", str(village.number)),)
    if role is Role.INSIDER:
        text = f"あなたの役職は{texts.INSIDER_ROLE}です。お題は『{_shown(village.topic)}』です。"
        return [Buttons(text, check, image=illust.url_for("INSIDER"), overflow=(Text(text), status))]
    if role is Role.VILLAGER:
        text = f"あなたの役職は{texts.VILLAGER_ROLE}です。"
        return [Buttons(text, check, image=illust.url_for("VILLAGERS"))]
    text = (
        f"役職は{texts.GAME_MASTER_ROLE}です。\n"
        f"{village.member_count()}/{village.size}人にお題を配りました。お題は『{_shown(village.topic)}』です。"
    )
    # 画像つき（60 文字）→ 画像なし（160 文字）→ Text＋入室状況 の 3 段
    return [Buttons(text, check, image=illust.url_for("GM"), overflow=(Buttons(text, check, overflow=(Text(text), status)),))]


def owner_reply(village: Village) -> list[Reply]:
    text = f"{village.number}村：{village.member_count()}/{village.size}人にお題を配りました。お題は『{_shown(village.topic)}』です。"
    return [Buttons(text, (MessageAction("再確認", str(village.number)),), overflow=(Text(text),))]


def special_role_reply(village: SpecialVillage, user_id: str) -> list[Reply] | None:
    text = village.message_for(user_id)
    if text is None:
        return None
    status = Text(_status_text(village, user_id))
    return [Buttons(text, (PostbackAction("入室状況確認", str(village.number)),), overflow=(Text(text), status))]


def default_reply() -> list[Reply]:
    """対象の村がないときの、村の作成を促す応答。"""
    return [
        Confirm(
            texts.DEFAULT_CONFIRM_TEXT,
            (MessageAction("GM", "お題"), MessageAction("神", "神")),
            alt_text=texts.DEFAULT_MESSAGE,
        )
    ]


def created_reply(number: int) -> list[Reply]:
    text = f"{number}村 を新しく作成しました。{texts.OWNER_ODAI_MESSAGE}"
    return [Buttons(text + "\nお題の自動取得もできます。", (PostbackAction("お題の自動取得", "0"),), alt_text=text)]


def random_created_reply(number: int) -> list[Reply]:
    return [Text(f"{number}村 を新しく作成しました。{texts.RANDOM_NUMSET_MESSAGE}")]


def size_set_reply(village: Village, god_mode: bool, illust: Illustrations) -> list[Reply]:
    number = str(village.number)
    text = f"人数を『{village.size}人』に設定しました。\n皆さんに村番号を伝えてください。"
    return [
        Buttons(
            text,
            (MessageAction("確認", number),),
            image=illust.url_for("GOD" if god_mode else "GM"),
            title=f"{number}村",
            alt_text=text + "配布状況の確認は村番号を入力してください。",
        )
    ]


def random_size_set_reply(village: Village, size: int, illust: Illustrations) -> list[Reply]:
    """ランダム村はオーナーも参加者なので、案内と一緒に自分の役職を返す。"""
    return [Text(f"{village.number}村：人数を『{size}人』に設定しました。\n皆さんに村番号を伝えてください。")] + role_reply(
        village, village.owner_id, illust
    )


def topic_set_reply(village: Village) -> list[Reply]:
    hint = texts.GOD_NUMSET_MESSAGE if village.is_god_mode_awaiting_size() else texts.OWNER_NUMSET_MESSAGE
    return [Text(f"{village.number}村 のお題を『{village.topic}』に設定しました。\n{hint}")]


def reverse_set_reply(village: Village) -> list[Reply]:
    return [Text(f"{village.number}村 を『逆村』に設定しました。\nお題を知らない村人が1人となります。")]


def werewords_created_reply(topic: str, number: int, god_mode: bool) -> list[Reply]:
    text = f"お題を『{topic}』として新たにワーワーズの『{number}』村を作成しました。"
    if god_mode:
        return [Text(text + f"参加者へ『{number}』を伝えてください。")]
    return [
        Text(
            text + f"参加者へ『{number}』を伝え、あなたも入室してください。\n"
            "\n■注意\nあなたはGMです。入室時に表示された役職が欠けた役職となります。"
        )
    ]


def candidate_reply(topic: str | None) -> list[Reply]:
    """お題候補と引き直しのボタン。辞書が壊れていると Java の文字列連結と同じく「null」が出る。

    Java は確定ボタンの text にも null をそのまま渡していた。返事モデルの型を str に保つため、ここでは表示と
    同じ「null」を入れる。同梱の辞書は Task 4 のテストで読めることを確かめているので、通常は通らない。
    """
    shown = _shown(topic)
    text = f"お題は「{shown}」です。確定しますか？"
    return [
        Buttons(
            text,
            (
                MessageAction("確定", shown),
                PostbackAction("初心者", str(BEGINNER_RANK)),
                PostbackAction("上級者", str(ADVANCED_RANK)),
                PostbackAction("変態", str(EXPERT_RANK)),
            ),
            alt_text=text,
        )
    ]


def invitation_reply(illust: Illustrations) -> list[Reply]:
    return [Image(illust.invitation_image_url), Text(texts.OFFICIAL_ACCOUNT_URL), Text(texts.OFFICIAL_ACCOUNT_ID_MESSAGE)]


def special_form_reply(url: str) -> list[Reply]:
    return [Text(url)]


def size_error_reply() -> list[Reply]:
    return [Text(texts.ERR_NUMSET_MESSAGE)]


def full_reply() -> list[Reply]:
    return [Text(texts.VILLAGE_FULL)]


def random_numset_reply() -> list[Reply]:
    return [Text(texts.RANDOM_NUMSET_MESSAGE)]
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_messages.py -q`
Expected: `23 passed`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/village/messages.py tests/test_village_messages.py
git commit -m "feat: 村の返事（役職・配布状況・案内）を返事モデルで組み立てる"
```

---

### Task 8: 構造化操作（VillageService）

**Files:**
- Create: `src/insider_bot/village/service.py`
- Test: `tests/test_village_service.py`

**Interfaces:**
- Consumes: Task 3 のレジストリ、Task 4 の `Dictionary`、Task 5 の `Illustrations`、Task 6 の `werewords_messages`、Task 7 の `messages`
- Produces: `service.py` の `VillageService(villages: VillageRegistry, specials: SpecialVillageRegistry, dictionary: Dictionary, illust: Illustrations, rng: Rng | None = None)`。すべて同期メソッドで、戻り値は `list[Reply] | None`（`None` = 対象の村がない）
  - `create_village(user_id, god_mode: bool) -> list[Reply]`
  - `create_random_village(user_id) -> list[Reply]`
  - `set_size(user_id, number: int) -> list[Reply] | None`
  - `set_topic(user_id, topic: str) -> list[Reply] | None`
  - `set_reverse(user_id) -> list[Reply] | None`
  - `convert_to_werewords(user_id) -> list[Reply] | None`
  - `join_village(user_id, number: int) -> list[Reply] | None`
  - `village_status(user_id, number) -> list[Reply] | None`
  - `join_special_village(user_id, number) -> list[Reply] | None`
  - `special_village_status(user_id, number) -> list[Reply] | None`
  - `create_special_village(messages: Sequence[str | None]) -> int`（複製して並べ替え、登録して番号を返す）
  - `pick_topic(rank: int) -> str | None`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_village_service.py
import random

from insider_bot.village import messages
from insider_bot.village.illust import Illustrations
from insider_bot.village.model import Role
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.service import VillageService
from insider_bot.village.words import BEGINNER_RANK, parse_dictionary
from tests.fakes import FixedRandom

OWNER = "line:owner"
BASE = "https://game.example.com"
DICTIONARY = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])


def make(*draws: int):
    """配役の乱数だけを固定し、採番は本物の乱数に任せる（Java と同じ分担）。"""
    villages = VillageRegistry(random.Random(1))
    specials = SpecialVillageRegistry(random.Random(2))
    rng = FixedRandom(*draws) if draws else random.Random(3)
    illust = Illustrations(BASE, FixedRandom(0))
    return VillageService(villages, specials, DICTIONARY, illust, rng), villages, specials, illust


def latest(villages, owner=OWNER):
    return villages.find_latest_owned(owner, lambda v: True)


def join_all(village, *users):
    for user in users:
        assert village.join(user) is not None, user


# --- 作成 ---


def test_create_village_registers_and_replies():
    service, villages, _, _ = make()
    reply = service.create_village(OWNER, god_mode=False)
    village = latest(villages)
    assert 1000 <= village.number <= 9999
    assert reply == messages.created_reply(village.number)
    assert not village.has_game_master()


def test_create_god_village_awaits_size():
    service, villages, _, _ = make()
    service.create_village(OWNER, god_mode=True)
    assert latest(villages).is_god_mode_awaiting_size()


def test_create_random_village_picks_a_topic_and_marks_god_mode():
    service, villages, _, _ = make(0)
    reply = service.create_random_village(OWNER)
    village = latest(villages)
    assert village.random_mode
    assert village.is_god_mode_awaiting_size()
    assert village.topic == "a"  # 初心者の 1 行目
    assert reply == messages.random_created_reply(village.number)


# --- 人数 ---


def test_insider_seat_follows_the_draw():
    service, villages, _, illust = make(2)
    service.create_village(OWNER, False)
    village = latest(villages)
    village.set_topic("すいか")
    reply = service.set_size(OWNER, 5)
    assert village.insider_seat == 3
    assert village.size == 5
    assert reply == messages.size_set_reply(village, god_mode=False, illust=illust)
    join_all(village, "u1", "u2", "u3", "u4", "u5")
    assert village.role_of("u3") is Role.INSIDER
    assert village.role_of("u1") is Role.VILLAGER


def test_god_mode_draws_a_game_master_distinct_from_the_insider():
    service, villages, _, illust = make(1, 1, 3)
    service.create_village(OWNER, True)
    reply = service.set_size(OWNER, 5)
    village = latest(villages)
    assert (village.insider_seat, village.gm_seat) == (2, 4)
    assert reply[0].image == illust.default_url("GOD")


def test_size_below_two_is_rejected_with_guidance_and_leaves_the_village_unset():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    assert service.set_size(OWNER, 1) == messages.size_error_reply()
    assert service.set_size(OWNER, 0) == messages.size_error_reply()
    assert service.set_size(OWNER, -3) == messages.size_error_reply()
    assert latest(villages).size == 0


def test_second_size_setting_is_rejected_instead_of_reshuffling():
    service, villages, _, _ = make(2, 0)
    service.create_village(OWNER, False)
    assert service.set_size(OWNER, 5) is not None
    assert service.set_size(OWNER, 9) is None
    village = latest(villages)
    assert (village.size, village.insider_seat) == (5, 3)


def test_size_without_a_village_is_none():
    service, _, _, _ = make()
    assert service.set_size(OWNER, 3) is None


def test_random_village_size_seats_the_owner_and_replies_with_their_role():
    service, villages, _, illust = make(0, 2, 0)  # お題の抽選、インサイダー 3 番目、GM 1 番目
    service.create_random_village(OWNER)
    reply = service.set_size(OWNER, 4)
    village = latest(villages)
    assert village.role_of(OWNER) is Role.GAME_MASTER
    assert reply == messages.random_size_set_reply(village, 4, illust)
    join_all(village, "u2", "u3", "u4")
    assert village.role_of("u3") is Role.INSIDER


# --- お題 ---


def test_topic_is_set_only_once():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    village = latest(villages)
    assert service.set_topic(OWNER, "すいか") == messages.topic_set_reply(village)
    assert service.set_topic(OWNER, "めろん") is None
    assert village.topic == "すいか"


def test_topic_keeps_surrounding_whitespace_and_commas():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    service.set_topic(OWNER, " りんご,みかん ")
    assert latest(villages).topic == " りんご,みかん "


def test_topic_goes_to_the_latest_village_without_a_topic():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    first = latest(villages)
    service.set_topic(OWNER, "一つ目")
    service.create_village(OWNER, False)
    second = latest(villages)
    service.set_topic(OWNER, "二つ目")
    assert (first.topic, second.topic) == ("一つ目", "二つ目")


# --- 逆村 ---


def test_reverse_is_confirmed_before_anyone_joins():
    service, villages, _, _ = make(1)
    service.create_village(OWNER, False)
    service.set_size(OWNER, 3)
    village = latest(villages)
    assert service.set_reverse(OWNER) == messages.reverse_set_reply(village)
    assert village.reverse


def test_reverse_is_rejected_once_participants_joined():
    service, villages, _, _ = make(1)
    service.create_village(OWNER, False)
    service.set_size(OWNER, 3)
    village = latest(villages)
    join_all(village, "u1")
    assert service.set_reverse(OWNER) is None
    assert not village.reverse


def test_random_village_is_not_turned_into_a_reverse_village():
    service, villages, _, _ = make(0)
    service.create_random_village(OWNER)
    assert service.set_reverse(OWNER) is None


def test_reverse_without_a_village_is_none():
    service, _, _, _ = make()
    assert service.set_reverse(OWNER) is None


# --- 参加 ---


def test_participants_join_until_full_and_rejoining_is_idempotent():
    service, villages, _, illust = make(0)
    service.create_village(OWNER, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 2)
    number = latest(villages).number
    first = service.join_village("line:m1", number)
    assert first == messages.role_reply(latest(villages), "line:m1", illust)
    assert service.join_village("line:m1", number) == first
    assert service.join_village("line:m2", number)[0].text.startswith("あなたの役職は")
    assert service.join_village("line:m3", number) == messages.full_reply()


def test_joining_before_the_size_is_set_is_full():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    assert service.join_village("line:m1", latest(villages).number) == messages.full_reply()


def test_owner_sees_the_distribution_status():
    service, villages, _, _ = make(0)
    service.create_village(OWNER, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 2)
    village = latest(villages)
    service.join_village("line:m1", village.number)
    assert service.join_village(OWNER, village.number) == messages.owner_reply(village)
    assert village.member_count() == 1  # オーナーは着席しない


def test_random_village_owner_sees_their_own_role_or_is_asked_for_the_size():
    service, villages, _, illust = make(0, 1, 2)
    service.create_random_village(OWNER)
    village = latest(villages)
    assert service.join_village(OWNER, village.number) == messages.random_numset_reply()
    service.set_size(OWNER, 3)
    assert village.role_of(OWNER) is Role.VILLAGER
    assert service.join_village(OWNER, village.number) == messages.role_reply(village, OWNER, illust)


def test_unknown_village_number_is_none():
    service, _, _, _ = make()
    assert service.join_village("line:m1", 1234) is None
    assert service.village_status("line:m1", 1234) is None


def test_village_status():
    service, villages, _, _ = make(0)
    service.create_village(OWNER, False)
    service.set_size(OWNER, 3)
    village = latest(villages)
    service.join_village("line:m1", village.number)
    assert service.village_status("line:m1", village.number) == messages.status_reply(village, "line:m1")


# --- 特殊村 ---


def test_create_special_village_shuffles_a_copy_and_registers_it():
    service, _, specials, _ = make()
    source = ["1人目", "2人目", "3人目"]
    number = service.create_special_village(source)
    assert source == ["1人目", "2人目", "3人目"]
    village = specials.get(number)
    assert 10000 <= number <= 99998
    assert sorted(village.messages) == sorted(source)


def test_special_village_join_and_status():
    service, _, specials, _ = make()
    number = service.create_special_village(["only", None])
    village = specials.get(number)
    reply = service.join_special_village("line:a", number)
    assert reply == messages.special_role_reply(village, "line:a")
    assert service.join_special_village("line:a", number) == reply
    assert service.join_special_village("line:b", number) is not None
    assert service.join_special_village("line:c", number) == messages.full_reply()
    assert service.special_village_status("line:a", number) == messages.status_reply(village, "line:a")
    assert service.join_special_village("line:a", 99999) is None
    assert service.special_village_status("line:a", 99999) is None


# --- Werewords ---


def test_werewords_from_a_god_village_distributes_size_messages():
    service, villages, specials, _ = make(0, 1)
    service.create_village(OWNER, True)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 3)
    original = latest(villages)
    reply = service.convert_to_werewords(OWNER)
    number = int(reply[0].text.split("『")[2].split("』")[0])
    assert reply == messages.werewords_created_reply("すいか", number, god_mode=True)
    assert specials.get(number).capacity() == 3
    assert sum(1 for m in specials.get(number).messages if m.startswith("あなたの役職はGMです。")) == 1
    # 元の村は残る
    assert villages.get(original.number) is original


def test_werewords_from_a_normal_village_adds_one_message_for_the_owner():
    service, villages, specials, _ = make(0)
    service.create_village(OWNER, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 3)
    reply = service.convert_to_werewords(OWNER)
    number = int(reply[0].text.split("『")[2].split("』")[0])
    assert reply == messages.werewords_created_reply("すいか", number, god_mode=False)
    assert specials.get(number).capacity() == 4


def test_werewords_needs_three_participants_and_a_topic_on_the_latest_empty_village():
    service, _, _, _ = make(0, 0)
    service.create_village(OWNER, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 2)
    assert service.convert_to_werewords(OWNER) is None
    service.create_village(OWNER, False)
    service.set_size(OWNER, 3)
    assert service.convert_to_werewords(OWNER) is None  # お題がない。古い村へは遡らない
    assert service.convert_to_werewords("line:nobody") is None


# --- 辞書 ---


def test_pick_topic_delegates_to_the_dictionary():
    service, _, _, _ = make(0)
    assert service.pick_topic(BEGINNER_RANK) == "a"
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_village_service.py -q`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 実装する**

```python
# src/insider_bot/village/service.py
"""村の構造化操作。LINE と Web で共通のゲーム規則で、経路を知らない。

対象の村が見つからない場合はどのメソッドも None を返す。村が消えている、まだ作っていない、条件を満たさない、
はいずれも利用者の操作として起こりうることで、例外ではない。呼び出し側が経路に応じた既定応答へ変換する。

どのメソッドも同期で、途中に await を挟まない。asyncio 単一スレッドでは、これが Java の synchronized と
同じ「途中経過が他から観測されない」保証になる。
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from insider_bot.village import messages
from insider_bot.village.illust import Illustrations
from insider_bot.village.model import Rng, SpecialVillage, Village
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.reply import Reply
from insider_bot.village.werewords import MIN_WEREWORDS_SIZE, werewords_messages
from insider_bot.village.words import BEGINNER_RANK, Dictionary


class VillageService:
    def __init__(
        self,
        villages: VillageRegistry,
        specials: SpecialVillageRegistry,
        dictionary: Dictionary,
        illust: Illustrations,
        rng: Rng | None = None,
    ) -> None:
        self._villages = villages
        self._specials = specials
        self._dictionary = dictionary
        self._illust = illust
        self._rng: Rng = rng if rng is not None else random.Random()

    @property
    def illust(self) -> Illustrations:
        return self._illust

    # --- 作成 ---

    def create_village(self, user_id: str, god_mode: bool) -> list[Reply]:
        village = Village(user_id)
        if god_mode:
            village.mark_god_mode()
        number = self._villages.add(village)
        return messages.created_reply(number)

    def create_random_village(self, user_id: str) -> list[Reply]:
        """お題は初心者から自動で引き、GM も抽選する。オーナーに聞くのは人数だけ。"""
        village = Village(user_id)
        village.mark_god_mode()
        village.random_mode = True
        topic = self.pick_topic(BEGINNER_RANK)
        if topic is not None:
            # 辞書が壊れていると引けない。Java と同じくお題は未設定のまま残り、次の自由文入力がお題になる
            village.set_topic(topic)
        number = self._villages.add(village)
        return messages.random_created_reply(number)

    # --- 設定 ---

    def set_size(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._villages.find_latest_owned(user_id, lambda v: v.size == 0)
        if village is None:
            return None
        if number <= 1:
            return messages.size_error_reply()
        # 神モードかどうかは人数確定で上書きされるので先に控える
        god_mode = village.is_god_mode_awaiting_size()
        random_mode = village.random_mode
        if not village.configure(number, self._rng):
            return None
        if random_mode:
            return messages.random_size_set_reply(village, number, self._illust)
        return messages.size_set_reply(village, god_mode, self._illust)

    def set_topic(self, user_id: str, topic: str) -> list[Reply] | None:
        village = self._villages.find_latest_owned(user_id, lambda v: v.topic is None)
        if village is None or not village.set_topic(topic):
            return None
        return messages.topic_set_reply(village)

    def set_reverse(self, user_id: str) -> list[Reply] | None:
        # ランダム村は GM とインサイダーを 1 人ずつ配るので逆村にしない
        village = self._villages.find_latest_owned(user_id, lambda v: not v.has_members() and not v.random_mode)
        if village is None or not village.apply_reverse():
            return None
        return messages.reverse_set_reply(village)

    def convert_to_werewords(self, user_id: str) -> list[Reply] | None:
        """元の村は残し、配布メッセージだけを持つ特殊村を新しく作る。人数とお題が揃っていなければ None。"""
        village = self._villages.find_latest_owned(user_id, lambda v: not v.has_members())
        if village is None or village.size < MIN_WEREWORDS_SIZE or village.topic is None:
            return None
        god_mode = village.has_game_master()
        number = self.create_special_village(werewords_messages(god_mode, village.size, village.topic, self._rng))
        return messages.werewords_created_reply(village.topic, number, god_mode)

    # --- 参加と状況 ---

    def join_village(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._villages.get(number)
        if village is None:
            return None
        if user_id == village.owner_id:
            if not village.random_mode:
                return messages.owner_reply(village)
            if village.role_of(user_id) is None:
                # 人数未設定で、まだ配役されていない
                return messages.random_numset_reply()
        elif village.role_of(user_id) is None and village.join(user_id) is None:
            return messages.full_reply()
        return messages.role_reply(village, user_id, self._illust)

    def village_status(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._villages.get(number)
        return None if village is None else messages.status_reply(village, user_id)

    def join_special_village(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._specials.get(number)
        if village is None:
            return None
        if not village.join(user_id):
            return messages.full_reply()
        return messages.special_role_reply(village, user_id)

    def special_village_status(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._specials.get(number)
        return None if village is None else messages.status_reply(village, user_id)

    # --- 特殊村と辞書 ---

    def create_special_village(self, texts: Sequence[str | None]) -> int:
        """複製して並べ替え、登録して番号を返す。呼び出し元の列は変えない。"""
        shuffled = list(texts)
        self._rng.shuffle(shuffled)
        return self._specials.add(SpecialVillage(shuffled))

    def pick_topic(self, rank: int) -> str | None:
        return self._dictionary.pick(rank, self._rng)
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_service.py -q`
Expected: `28 passed`

ランダム村のテストで `FixedRandom` の値が足りないときは、`create_random_village` が辞書の抽選で 1 つ、`configure` がインサイダーで 1 つ、GM で 1 つ以上使うことを思い出す。

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/village/service.py tests/test_village_service.py
git commit -m "feat: 村の構造化操作（作成・設定・参加・特殊村・Werewords）を追加"
```

---

### Task 9: テキストの解釈（CommandHandler）と経路一致

**Files:**
- Create: `src/insider_bot/village/commands.py`
- Test: `tests/test_village_commands.py`

**Interfaces:**
- Consumes: Task 1 の `parsing.java_trim` / `parse_java_int`、Task 8 の `VillageService`、Task 7 の `messages`
- Produces: `commands.py` の `MAX_SIZE_INPUT = 100`、`CommandHandler(service: VillageService, special_form_url: str)`。メソッド `handle(user_id: str, text: str) -> list[Reply] | None`、`topic_candidate(rank: int) -> list[Reply]`
- 入力の解釈（Java の TextCommandHandler と同じ）: `java_trim` で前後の U+0020 以下の文字を除き、`parse_java_int` で読めれば数値。10000 以上は特殊村へ参加、101〜9999 は通常村へ参加、100 以下は人数。数値でなければコマンド表（`お題`/`題`/`神`/`ランダム`/`@配布`/`＠配布`/`@特殊`/`＠特殊`/`@取得`/`＠取得`/`@逆村`/`＠逆村`/`@わーわーず`/`＠わーわーず`）、それ以外はお題（**trim しない元の文字列**）
- 全角数字「３」は数値として扱い、全角スペースは除かない。「1_0」や int の範囲外は数値として読まずお題にする（Java の `Integer.parseInt` と `String.trim()` と同じ。Java 11 で確認済み）。Python の `int()` と `str.strip()` はどれも Java と違う結果になるので使わない

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_village_commands.py
import random

from insider_bot.village import messages
from insider_bot.village.commands import MAX_SIZE_INPUT, CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.reply import Image, MessageAction, PostbackAction, Text
from insider_bot.village.service import VillageService
from insider_bot.village.words import UNSPECIFIED_RANK, parse_dictionary
from tests.fakes import FixedRandom

OWNER = "line:owner"
MEMBER = "line:member"
FORM_URL = "https://game.example.com/village/special"
DICTIONARY = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])


def make(*draws: int):
    villages = VillageRegistry(random.Random(1))
    specials = SpecialVillageRegistry(random.Random(2))
    rng = FixedRandom(*draws) if draws else random.Random(3)
    service = VillageService(villages, specials, DICTIONARY, Illustrations("https://game.example.com", FixedRandom(0)), rng)
    return CommandHandler(service, FORM_URL), service, villages, specials


def latest(villages, owner=OWNER):
    return villages.find_latest_owned(owner, lambda v: True)


# --- 村の作成 ---


def test_village_creation_commands():
    handler, _, villages, _ = make()
    assert handler.handle(OWNER, "お題") == messages.created_reply(latest(villages).number)
    assert handler.handle(OWNER, "題") == messages.created_reply(latest(villages).number)
    assert handler.handle("line:god", "神") == messages.created_reply(latest(villages, "line:god").number)
    assert latest(villages, "line:god").is_god_mode_awaiting_size()
    assert handler.handle("line:rnd", "ランダム") == messages.random_created_reply(latest(villages, "line:rnd").number)


# --- 数値の解釈 ---


def test_numbers_up_to_100_are_sizes_and_101_onwards_are_village_numbers():
    handler, _, villages, _ = make(0, 0)
    assert MAX_SIZE_INPUT == 100
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, "1") == messages.size_error_reply()
    assert handler.handle(OWNER, "0") == messages.size_error_reply()
    assert handler.handle(OWNER, "-5") == messages.size_error_reply()
    assert handler.handle(OWNER, "100")[0].text.startswith("人数を『100人』に設定しました。")
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, "101") is None  # 該当なしの村番号
    assert handler.handle(OWNER, "999") is None
    assert latest(villages).size == 0


def test_surrounding_whitespace_is_ignored_for_numbers():
    handler, _, villages, _ = make(0)
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, " 3 ")[0].text.startswith("人数を『3人』に設定しました。")


def test_fullwidth_digits_are_numbers_like_java():
    # Java の Integer.parseInt は全角数字を読む
    handler, _, villages, _ = make(0)
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, "３")[0].text.startswith("人数を『3人』に設定しました。")
    assert latest(villages).size == 3


def test_fullwidth_village_numbers_join_too():
    handler, _, villages, _ = make(0)
    handler.handle(OWNER, "お題")
    handler.handle(OWNER, "すいか")
    handler.handle(OWNER, "2")
    number = str(latest(villages).number).translate(str.maketrans("0123456789", "０１２３４５６７８９"))
    assert handler.handle(MEMBER, number)[0].text.startswith("あなたの役職は")


def test_ideographic_spaces_are_not_trimmed():
    # Java の trim() は全角スペースを除かないので、数値にもコマンドにもならずお題になる
    handler, _, villages, _ = make()
    handler.handle(OWNER, "お題")
    first = latest(villages)
    assert handler.handle(OWNER, "　3　") == messages.topic_set_reply(first)
    assert first.topic == "　3　"
    handler.handle(OWNER, "お題")
    second = latest(villages)
    assert handler.handle(OWNER, "　神　") == messages.topic_set_reply(second)
    assert latest(villages) is second  # 神モードの村は作られていない
    assert second.topic == "　神　"


def test_numbers_java_cannot_read_are_topics():
    # Integer.parseInt は「_」と int の範囲外を読めない。Java ではお題になる
    for text in ("1_0", "2147483648", "-2147483649", "99999999999"):
        handler, _, villages, _ = make()
        handler.handle(OWNER, "お題")
        assert handler.handle(OWNER, text) == messages.topic_set_reply(latest(villages)), text
        assert latest(villages).topic == text


def test_five_digit_numbers_join_special_villages():
    handler, service, _, specials = make()
    number = service.create_special_village(["a", "b"])
    reply = handler.handle(MEMBER, str(number))
    assert reply == messages.special_role_reply(specials.get(number), MEMBER)
    assert handler.handle(MEMBER, "99999") is None


def test_four_digit_numbers_join_villages_until_full():
    handler, _, villages, _ = make(0)
    handler.handle(OWNER, "お題")
    handler.handle(OWNER, "すいか")
    handler.handle(OWNER, "2")
    number = str(latest(villages).number)
    assert handler.handle(MEMBER, number)[0].text.startswith("あなたの役職は")
    assert handler.handle(MEMBER, number) == handler.handle(MEMBER, number)
    assert handler.handle("line:second", number)[0].text.startswith("あなたの役職は")
    assert handler.handle("line:third", number) == messages.full_reply()
    assert handler.handle(OWNER, number) == messages.owner_reply(latest(villages))


# --- お題 ---


def test_free_text_becomes_the_topic_with_whitespace_kept():
    handler, _, villages, _ = make()
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, " すいか ") == messages.topic_set_reply(latest(villages))
    assert latest(villages).topic == " すいか "


def test_unknown_text_without_a_village_is_none():
    handler, _, _, _ = make()
    assert handler.handle(OWNER, "知らない文字列") is None


def test_an_at_command_that_is_not_defined_is_a_topic():
    handler, _, villages, _ = make()
    handler.handle(OWNER, "お題")
    handler.handle(OWNER, "@あ")
    assert latest(villages).topic == "@あ"


# --- @ コマンド ---


def test_reverse_and_werewords_commands_accept_both_at_signs():
    handler, _, villages, specials = make(0, 0)
    handler.handle(OWNER, "お題")
    handler.handle(OWNER, "すいか")
    handler.handle(OWNER, "3")
    assert handler.handle(OWNER, "＠逆村") == messages.reverse_set_reply(latest(villages))
    reply = handler.handle(OWNER, "@わーわーず")
    assert reply is not None and "ワーワーズ" in reply[0].text
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, "@逆村") is not None
    assert handler.handle(OWNER, "＠わーわーず") is None  # 人数もお題もない


def test_distribution_command_replies_with_the_invitation():
    handler, service, _, _ = make()
    expected = [
        Image("https://game.example.com/static/roles/966mpnqz.png"),
        Text("https://line.me/R/ti/p/%40966mpnqz"),
        Text("お友達ID\n@966mpnqz"),
    ]
    assert handler.handle(OWNER, "@配布") == expected
    assert handler.handle(OWNER, "＠配布") == expected


def test_special_command_replies_with_the_form_url():
    handler, _, _, _ = make()
    assert handler.handle(OWNER, "@特殊") == [Text(FORM_URL)]
    assert handler.handle(OWNER, "＠特殊") == [Text(FORM_URL)]


def test_lookup_command_offers_a_candidate_from_the_unspecified_range():
    handler, _, _, _ = make(3)
    reply = handler.handle(OWNER, "@取得")
    assert reply == messages.candidate_reply("d")
    assert reply[0].actions[0] == MessageAction("確定", "d")
    assert reply[0].actions[1:] == (PostbackAction("初心者", "2"), PostbackAction("上級者", "3"), PostbackAction("変態", "4"))


def test_topic_candidate_uses_the_given_rank():
    handler, _, _, _ = make(0, 0, 0, 0)
    assert handler.topic_candidate(2) == messages.candidate_reply("a")
    assert handler.topic_candidate(3) == messages.candidate_reply("c")
    assert handler.topic_candidate(4) == messages.candidate_reply("e")
    assert handler.topic_candidate(UNSPECIFIED_RANK) == messages.candidate_reply("a")


# --- 経路一致 ---

SCRIPT = ["お題", "すいか", "3", "<現在の村>", "@逆村", "＠わーわーず", "@特殊", "@配布", "101", "9999", " 3 ", "知らない文字列", "３", "　3　"]


def run_through_text(handler, villages):
    answers = []
    for text in SCRIPT:
        if text == "<現在の村>":
            text = str(latest(villages).number)
        answers.append(handler.handle(OWNER, text))
    return answers


def run_through_service(service, villages):
    def number():
        return latest(villages).number

    return [
        service.create_village(OWNER, False),
        service.set_topic(OWNER, "すいか"),
        service.set_size(OWNER, 3),
        service.join_village(OWNER, number()),
        service.set_reverse(OWNER),
        service.convert_to_werewords(OWNER),
        messages.special_form_reply(FORM_URL),
        messages.invitation_reply(service.illust),
        service.join_village(OWNER, 101),
        service.join_village(OWNER, 9999),
        service.set_size(OWNER, 3),
        service.set_topic(OWNER, "知らない文字列"),
        service.set_size(OWNER, 3),
        service.set_topic(OWNER, "　3　"),
    ]


def normalize(reply):
    """村番号は実行ごとに採番されるので 4 桁以上の数字を伏せる。人数や入室状況は 3 桁以下なので残る。"""
    import re

    return None if reply is None else re.sub(r"\d{4,}", "<村番号>", repr(reply))


def test_text_commands_and_structured_operations_answer_the_same_script_the_same_way():
    handler, _, villages_a, _ = make(0, 0)
    through_text = run_through_text(handler, villages_a)
    _, service, villages_b, _ = make(0, 0)
    through_service = run_through_service(service, villages_b)
    assert len(through_text) == len(SCRIPT)
    for text, a, b in zip(SCRIPT, through_text, through_service):
        assert normalize(a) == normalize(b), f"入力『{text}』への応答が経路で異なる"
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_village_commands.py -q`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 実装する**

```python
# src/insider_bot/village/commands.py
"""テキスト入力の解釈。LINE のトークと Web のチャット入力で共通の 1 組だけを持つ。

経路ごとに違ってよいのは、入力の取り出し方と結果の返し方、対象の村がないときの応答だけ。
入力の解釈（数値の境界、コマンド表、空白の扱い）をここに集めるのは、片方だけを直して配布結果が
分岐しても、突き合わせる利用者がいないため誰も気付けないから。

対象の村がないときは None を返し、呼び出し側が経路に応じた既定応答へ変換する。
"""

from __future__ import annotations

from insider_bot.village import messages
from insider_bot.village.parsing import java_trim, parse_java_int
from insider_bot.village.registry import MAX_VILLAGE_NUMBER
from insider_bot.village.reply import Reply
from insider_bot.village.service import VillageService
from insider_bot.village.words import UNSPECIFIED_RANK

# 設定できる参加人数の上限。これを超える数値は通常村の番号として扱う
MAX_SIZE_INPUT = 100

_CREATE = ("お題", "題", "神")
_RANDOM = ("ランダム",)
_INVITATION = ("@配布", "＠配布")
_SPECIAL = ("@特殊", "＠特殊")
_LOOKUP = ("@取得", "＠取得")
_REVERSE = ("@逆村", "＠逆村")
_WEREWORDS = ("@わーわーず", "＠わーわーず")


class CommandHandler:
    def __init__(self, service: VillageService, special_form_url: str) -> None:
        self._service = service
        self._special_form_url = special_form_url

    def handle(self, user_id: str, text: str) -> list[Reply] | None:
        # Java の String.trim() と Integer.parseInt() と同じ規則。全角数字は数値、全角スペースは除かない
        command = java_trim(text)
        number = parse_java_int(command)
        if number is not None:
            if number > MAX_VILLAGE_NUMBER:
                return self._service.join_special_village(user_id, number)
            if number > MAX_SIZE_INPUT:
                return self._service.join_village(user_id, number)
            return self._service.set_size(user_id, number)
        if command in _CREATE:
            return self._service.create_village(user_id, god_mode=command == "神")
        if command in _RANDOM:
            return self._service.create_random_village(user_id)
        if command in _INVITATION:
            return messages.invitation_reply(self._service.illust)
        if command in _SPECIAL:
            return messages.special_form_reply(self._special_form_url)
        if command in _LOOKUP:
            return self.topic_candidate(UNSPECIFIED_RANK)
        if command in _REVERSE:
            return self._service.set_reverse(user_id)
        if command in _WEREWORDS:
            return self._service.convert_to_werewords(user_id)
        # 残りはお題。前後の空白は利用者が入力したお題の一部として保つ
        return self._service.set_topic(user_id, text)

    def topic_candidate(self, rank: int) -> list[Reply]:
        """お題候補と引き直しのボタン。村を持っていなくても引けるので利用者の識別は要らない。"""
        return messages.candidate_reply(self._service.pick_topic(rank))
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_commands.py -q`
Expected: `18 passed`

- [ ] **Step 5: 全テストを流す**

Run: `uv run pytest -q`
Expected: 既存の 193 件＋今回の分がすべて PASS

- [ ] **Step 6: コミット**

```bash
git add src/insider_bot/village/commands.py tests/test_village_commands.py
git commit -m "feat: 村のテキスト解釈（数値の境界とコマンド表）を追加し、構造化操作との一致を固定"
```

---

### Task 10: ドキュメント

**Files:**
- Create: `docs/village.md`
- Modify: `docs/spec.md`（「目的と範囲」の対象外と「将来の拡張」、末尾に「村の中核」の節）

**Interfaces:**
- Consumes: Task 1〜9 の全モジュール（記述がコードと一致していること）

- [ ] **Step 1: `docs/village.md` を書く**

LineBot の `/Users/fukasedaichi/git/LineBot/docs/game-spec.md` を土台にし、次を直して `docs/village.md` として保存する。現在形で書き、日付と経緯は書かない。

- 冒頭を「村（インサイダーゲームと Werewords の配役）の外部仕様。ここに書かれた入力と応答の対応が、LINE と Web の両方の入口が守る契約である」とする
- 「特殊村」の作成方法 `POST /specialvillage` を「Web 版の特殊村フォーム（`/village/special`）」に、`@特殊` の応答を「Web 版の特殊村フォームの URL」に書き換える（入口そのものは M2 で作るが、docs は到達点の仕様として書く）
- 「ユーザーを識別できない場合」は LINE 固有の制約なので、節の冒頭に「LINE の入口に固有」と注記する
- game-spec.md が参照している `interfaces.md` の「数値の解釈」は insider に移さないので、表（10000 以上は特殊村、1000〜9999 は通常村、101〜999 は該当なしの村番号、100 以下は人数）を `docs/village.md` に取り込み、リンクを外す。「前後の空白を除いてから判定」は「前後の U+0020 以下の文字（半角スペース・タブ・改行）を除いてから判定。全角スペースは除かない」と正確に書き、全角数字は数値として読むこと、「1_0」や int の範囲外はお題になることを足す（`commands.py` と `parsing.py` の挙動）
- 末尾に「実装の対応」の表を足す: 村の状態 → `village/model.py`、採番と上限 → `village/registry.py`、辞書 → `village/words.py`、Werewords → `village/werewords.py`、役職画像 → `village/illust.py`、文言 → `village/texts.py`、操作 → `village/service.py`、テキストの解釈 → `village/commands.py`、返事モデル → `village/reply.py`
- 「返事モデル」の節を足し、`Text` / `Image` / `Buttons` / `Confirm`、`overflow` の意味（LINE の文字数制限で Java が Text に落としていた分岐）、`alt_text`、「対象の村がない」= `None` を説明する
- 「並行性」の節を足し、asyncio 単一スレッドで「1 操作は同期関数で完結し、途中で await しない」ことが Java の `synchronized` に相当すると書く
- 「参加者の識別子」の節を足し、`line:<ユーザー ID>` / `web:<トークン>` の不透明な文字列で、LINE と Web の同一人物は紐づけないと書く
- 役職画像の節で、既定画像は `web/static/roles/` から自前で配信し、`ILLUSTRATION_CATALOG_URL` を設定したときだけ外部カタログを 5 分ごとに取り直すと書く

- [ ] **Step 2: `docs/spec.md` を直す**

- 「目的と範囲」の対象外から「インサイダーゲームの役職」を外し、「インサイダーの投票・タイマー」だけ残す
- 「将来の拡張」の「制限時間、インサイダーの役職・投票」を「制限時間、インサイダーの投票。Jev のお題当てルームへの配役の持ち込み」に直す
- 末尾に次の節を足す:

```markdown
## 村の中核（インサイダーゲームの配役）

LINE Bot が担っていた「参加者それぞれに役職とお題を配る」機能の中核。外部仕様は [村の外部仕様](village.md)。

- `insider_bot.village` は、お題当ての `GameService` とは独立したモジュールで、互いを知らない。同じプロセスに置くが結合しない。将来 Jev ルームに配役を混ぜるときは、両方を知る進行役を足す。
- 中核は LINE の形ではなく経路中立の返事モデル（`village/reply.py`）を返す。LINE と Web の入口がそれぞれの形に描く。
- 状態はプロセスメモリだけに持ち、再起動で失われる（お題当てのルームと同じ判断）。
```

- [ ] **Step 3: 記述とコードの一致を確かめる**

Run: `grep -n "village/" docs/village.md | head -20 && ls src/insider_bot/village/`
Expected: 表に挙げたファイルがすべて存在する

- [ ] **Step 4: コミット**

```bash
git add docs/village.md docs/spec.md
git commit -m "docs: 村の外部仕様を追加し、設計書に村の中核の節を足す"
```

---

## 完了の確認

- `uv run pytest -q` がすべて PASS
- `docs/village.md` の入力と応答の対応が、`tests/test_village_commands.py` と `tests/test_village_service.py` の期待値と食い違っていない
- `git log --oneline` に Task ごとのコミットが並んでいる
- LINE・Web の入口はまだ `insider_bot.village` を import していない（M2・M3 の仕事）
