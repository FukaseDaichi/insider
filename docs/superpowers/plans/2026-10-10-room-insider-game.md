# ルームのインサイダーゲーム 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Web 版のお題当てルームで、参加者をタップで選んで役職（インサイダー 1 人・村人）を配り、AI が GM として答え、当たったら画面で投票してインサイダーを探せるようにする。

**Architecture:** 1 回分の状態と決まりは通信を知らない `web/insider.py` に置き、`RoomHub` がそれを使って `GameService`（変更しない）でお題当てを進める。役職とお題は `_room_state` を接続ごとに作るところでだけ入れる。画面は純粋関数の `insider.js` と描画の `insiderview.js` を足し、`app.js` からは受け渡しだけをする。

**Tech Stack:** Python 3.12 / aiohttp / pytest（`uv run pytest`）、素の JS モジュール（`node --test tests/js/*.test.mjs`）。

**Spec:** `docs/superpowers/specs/2026-10-10-room-insider-game-design.md`

## Global Constraints

- Python は必ず `uv run`（pip やシステムの python は使わない）。
- 参加者は 3 人以上。制限時間は 1〜30 分（オンにしたときの初期値 5 分）。お題は 1〜50 文字。
- ランダムのお題は `VillageService.pick_topic(BEGINNER_RANK)`。役職画像は `Illustrations.url_for("INSIDER" / "VILLAGERS")`。
- 役職・お題・誰が誰に入れたかは、本人の接続以外に送らない（終わった後の `result` だけは全員に送る。誰が誰に入れたかは結果にも入れない）。
- 状態を変えてから積むまでの間に `await` を挟まない（`hub.py` の冒頭のコメントの原則）。
- 文字は `textContent` で描き、`innerHTML` は使わない。押せるものは 44px 以上。
- 文言・コメント・コミットメッセージは日本語。コミットの末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- docs/ は「現在形・経緯を書かない」（`docs/AGENTS.md`）。

## Review Focus

- インサイダーが「お題を決める」を 2 回続けて押す（通信の再送・連打）→ ゲームは 1 回だけ始まり、2 回目は断られる（Task 4 にテスト）。
- 選ばれなかった人が、投票中に `vote` や `close_vote` を直接送る → 断られ、票は変わらない（Task 5 にテスト）。
- 時間切れの予約が、当たって投票に進んだ後や、次のゲームが始まった後に発火する → 何もしない（Task 6 にテスト）。
- 投票中に、通常の「お題を出す」やもう一度の「インサイダーゲーム開始」を送る → 断られる（Task 6 にテスト）。
- 同じ名前の参加者が 2 人いる → ID で選び・投票でき、取り違えない（Task 3 にテスト）。

## File Structure

| ファイル | 役目 | 変え方 |
| --- | --- | --- |
| `src/insider_bot/web/insider.py` | 1 回分の状態（`InsiderRound`）と決まり（設定の検査・くじ・投票・開票） | 新規 |
| `src/insider_bot/web/rooms.py` | `Room.insider` と、`Entry` の `kind` / `data` | 変更 |
| `src/insider_bot/web/hub.py` | インサイダーゲームの操作、`room` の `insider` 欄、時間切れの予約 | 変更 |
| `src/insider_bot/web/server.py` | 新しい 4 つのメッセージの受け口 | 変更 |
| `src/insider_bot/web/__main__.py` | 辞書と役職画像を `RoomHub` に渡す | 変更 |
| `src/insider_bot/web/static/insider.js` | 画面の判断（設定の検査・残り時間・投票の相手・結果の組み立て） | 新規 |
| `src/insider_bot/web/static/insiderview.js` | 設定のシート・役職のカード・お題の入力・投票・結果のカードの描画 | 新規 |
| `src/insider_bot/web/static/app.js` | `insider` と `insider_result` の受け渡し、残り時間の表示 | 変更 |
| `src/insider_bot/web/static/index.html` / `style.css` | 部品の追加 | 変更 |
| `tests/test_web_insider.py` | `insider.py` のテスト | 新規 |
| `tests/test_web_hub.py` / `tests/test_web_server.py` | 進行と受け口のテスト | 変更 |
| `tests/js/insider.test.mjs` | `insider.js` のテスト | 新規 |
| `docs/spec.md` / `README.md` | 仕様と遊び方 | 変更 |

---

### Task 1: `insider.py`（1 回分の状態と決まり）

**Files:**
- Create: `src/insider_bot/web/insider.py`
- Test: `tests/test_web_insider.py`

**Interfaces:**
- Produces:
  - 定数 `MIN_PARTICIPANTS = 3`, `MIN_MINUTES = 1`, `MAX_MINUTES = 30`, `TOPIC_MAX = 50`, `TOPIC_MODES = ("random", "self", "insider")`
  - `class Phase(StrEnum)`: `CHOOSING="choosing"`, `ASKING="asking"`, `VOTING="voting"`, `DONE="done"`／`ACTIVE_PHASES`
  - `class Ending(StrEnum)`: `VOTED="voted"`, `TIME_UP="time_up"`, `GIVEUP="giveup"`
  - `class InvalidSetup(Exception)`（`str(error)` が押した人に見せる文）
  - `@dataclass(frozen=True) class Setup(participants: tuple[int, ...], topic_mode: str, topic: str | None, minutes: int | None)`
  - `check_setup(room_player_ids: Collection[int], starter_id: int, participants: Sequence[int], topic_mode: str, topic: str | None, minutes: int | None) -> Setup`
  - `check_topic(topic: str) -> str`
  - `@dataclass(frozen=True) class Tally(counts: dict[int, int], villagers_win: bool)`
  - `@dataclass(eq=False) class InsiderRound`（フィールドと方法は下のコード）
  - `deal(setup: Setup, rng: Rng) -> InsiderRound`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_web_insider.py`:

```python
import pytest

from insider_bot.web.insider import (
    Ending,
    InsiderRound,
    InvalidSetup,
    Phase,
    Setup,
    check_setup,
    check_topic,
    deal,
)
from tests.fakes import FixedRandom

ROOM = {1, 2, 3, 4}


def round_of(*participants: int, insider: int = 1, minutes: int | None = None) -> InsiderRound:
    return InsiderRound(participants=tuple(participants), insider_id=insider, topic_mode="random", minutes=minutes)


# --- 設定の検査 ---


def test_setup_keeps_order_and_drops_duplicates():
    setup = check_setup(ROOM, 1, [3, 1, 3, 2], "random", None, None)
    assert setup == Setup((3, 1, 2), "random", None, None)


@pytest.mark.parametrize(
    ("participants", "mode", "topic", "minutes", "message"),
    [
        ([1, 2], "random", None, None, "参加者を3人以上選んでください"),
        ([1, 2, 9], "random", None, None, "ルームにいない人は選べません"),
        ([1, 2, 3], "dance", None, None, "お題の決め方が正しくありません"),
        ([1, 2, 3], "random", None, 0, "制限時間は1〜30分で選んでください"),
        ([1, 2, 3], "random", None, 31, "制限時間は1〜30分で選んでください"),
        ([2, 3, 4], "self", "  ", None, "お題は1〜50文字で入力してください"),
        ([2, 3, 4], "self", "あ" * 51, None, "お題は1〜50文字で入力してください"),
        ([1, 2, 3, 4], "self", "りんご", None, "お題を決める人は参加者になれません"),
    ],
)
def test_setup_rejects(participants, mode, topic, minutes, message):
    with pytest.raises(InvalidSetup, match=message):
        check_setup(ROOM, 1, participants, mode, topic, minutes)


def test_self_topic_is_trimmed_and_other_modes_drop_topic():
    assert check_setup(ROOM, 1, [2, 3, 4], "self", " りんご ", 5).topic == "りんご"
    assert check_setup(ROOM, 1, [1, 2, 3], "insider", "りんご", None).topic is None
    assert check_setup(ROOM, 1, [1, 2, 3], "random", "りんご", None).topic is None


def test_check_topic():
    assert check_topic(" みかん ") == "みかん"
    with pytest.raises(InvalidSetup, match="お題は1〜50文字で入力してください"):
        check_topic("")


# --- くじと役職 ---


def test_deal_picks_insider_by_rng():
    rnd = deal(Setup((3, 1, 2), "random", None, 5), FixedRandom(2))
    assert rnd.insider_id == 2
    assert rnd.phase is Phase.CHOOSING
    assert (rnd.role_of(2), rnd.role_of(3), rnd.role_of(4)) == ("insider", "villager", None)


def test_begin_sets_deadline_only_with_minutes():
    timed = round_of(1, 2, 3, minutes=5)
    timed.begin("りんご", game_id=7, now=100.0)
    assert (timed.phase, timed.topic, timed.game_id, timed.deadline) == (Phase.ASKING, "りんご", 7, 400.0)
    assert timed.remaining(now=160.0) == 240.0
    assert timed.remaining(now=999.0) == 0.0
    untimed = round_of(1, 2, 3)
    untimed.begin("りんご", game_id=8, now=100.0)
    assert untimed.deadline is None and untimed.remaining(now=500.0) is None


# --- 投票 ---


def voting(*participants: int, insider: int = 1) -> InsiderRound:
    rnd = round_of(*participants, insider=insider)
    rnd.begin("りんご", game_id=1, now=0.0)
    rnd.start_voting("はなこ")
    return rnd


def test_start_voting_clears_deadline_and_records_guesser():
    rnd = round_of(1, 2, 3, minutes=3)
    rnd.begin("りんご", game_id=1, now=0.0)
    rnd.start_voting("はなこ")
    assert (rnd.phase, rnd.deadline, rnd.guesser) == (Phase.VOTING, None, "はなこ")


@pytest.mark.parametrize(
    ("voter", "target", "message"),
    [
        (1, 1, "自分には投票できません"),
        (9, 2, "参加者だけが投票できます"),
        (1, 9, "参加者の中から選んでください"),
    ],
)
def test_vote_rejects(voter, target, message):
    rnd = voting(1, 2, 3)
    assert rnd.vote(voter, target) == message
    assert rnd.votes == {}


def test_vote_is_rejected_outside_voting():
    rnd = round_of(1, 2, 3)
    assert rnd.vote(1, 2) == "いまは投票できません"


def test_vote_can_be_changed_and_all_voted():
    rnd = voting(1, 2, 3)
    assert rnd.vote(1, 2) is None
    assert rnd.vote(1, 3) is None
    assert rnd.votes == {1: 3}
    assert not rnd.all_voted()
    rnd.vote(2, 1)
    rnd.vote(3, 1)
    assert rnd.all_voted()


@pytest.mark.parametrize(
    ("votes", "counts", "villagers_win"),
    [
        ({1: 2, 2: 1, 3: 1}, {1: 2, 2: 1, 3: 0}, True),  # インサイダー 1 が単独最多
        ({1: 2, 2: 3, 3: 2}, {1: 0, 2: 2, 3: 1}, False),  # 別の人が最多
        ({1: 2, 2: 1}, {1: 1, 2: 1, 3: 0}, False),  # 同票
    ],
)
def test_tally(votes, counts, villagers_win):
    rnd = voting(1, 2, 3, insider=1)
    rnd.votes = dict(votes)
    tally = rnd.tally()
    assert tally.counts == counts
    assert tally.villagers_win is villagers_win


def test_finish():
    rnd = voting(1, 2, 3)
    rnd.finish(Ending.VOTED)
    assert (rnd.phase, rnd.ending) == (Phase.DONE, Ending.VOTED)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run pytest tests/test_web_insider.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'insider_bot.web.insider'`）

- [ ] **Step 3: 実装する**

`src/insider_bot/web/insider.py`:

```python
"""ルームのインサイダーゲーム 1 回分の状態と決まり。ネットワーク・asyncio・GameService に依存しない。

段階は お題待ち（choosing）→ 質問（asking）→ 投票（voting）→ 終わり（done）。
お題がランダムか始める人が決める場合は、配ってすぐ質問に進む（choosing を通らない）。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

MIN_PARTICIPANTS = 3
MIN_MINUTES = 1
MAX_MINUTES = 30
TOPIC_MAX = 50
TOPIC_MODES = ("random", "self", "insider")


class Rng(Protocol):
    def randrange(self, n: int) -> int: ...


class Phase(StrEnum):
    CHOOSING = "choosing"
    ASKING = "asking"
    VOTING = "voting"
    DONE = "done"


# この段階の間は、ルームでほかのゲームを始められない
ACTIVE_PHASES = (Phase.CHOOSING, Phase.ASKING, Phase.VOTING)


class Ending(StrEnum):
    VOTED = "voted"
    TIME_UP = "time_up"
    GIVEUP = "giveup"


class InvalidSetup(Exception):
    """設定やお題が正しくない。文はそのまま押した人に見せる。"""


@dataclass(frozen=True)
class Setup:
    participants: tuple[int, ...]
    topic_mode: str
    topic: str | None
    minutes: int | None


def check_topic(topic: str) -> str:
    topic = topic.strip()
    if not 1 <= len(topic) <= TOPIC_MAX:
        raise InvalidSetup(f"お題は1〜{TOPIC_MAX}文字で入力してください")
    return topic


def check_setup(
    room_player_ids: Collection[int],
    starter_id: int,
    participants: Sequence[int],
    topic_mode: str,
    topic: str | None,
    minutes: int | None,
) -> Setup:
    """画面から届いた設定を確かめて整える。正しくなければ InvalidSetup。"""
    if topic_mode not in TOPIC_MODES:
        raise InvalidSetup("お題の決め方が正しくありません")
    # 同じ人を 2 回送られても 1 人に数える。並びは選んだ順のまま
    chosen = tuple(dict.fromkeys(participants))
    if any(player_id not in room_player_ids for player_id in chosen):
        raise InvalidSetup("ルームにいない人は選べません")
    if topic_mode == "self" and starter_id in chosen:
        # お題を知る人が質問に紛れると、ゲームが成り立たない
        raise InvalidSetup("お題を決める人は参加者になれません")
    if len(chosen) < MIN_PARTICIPANTS:
        raise InvalidSetup(f"参加者を{MIN_PARTICIPANTS}人以上選んでください")
    if minutes is not None and not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise InvalidSetup(f"制限時間は{MIN_MINUTES}〜{MAX_MINUTES}分で選んでください")
    checked = check_topic(topic or "") if topic_mode == "self" else None
    return Setup(chosen, topic_mode, checked, minutes)


@dataclass(frozen=True)
class Tally:
    """counts は参加者 → 得票（0 票の人も、参加者の並びで入れる）。"""

    counts: dict[int, int]
    villagers_win: bool


@dataclass(eq=False)
class InsiderRound:
    participants: tuple[int, ...]
    insider_id: int
    topic_mode: str
    minutes: int | None
    # 参加者 → 役職画像の URL。表示のたびに変わらないよう、配るときに 1 度だけ選ぶ
    images: dict[int, str] = field(default_factory=dict)
    topic: str | None = None
    phase: Phase = Phase.CHOOSING
    game_id: int | None = None
    deadline: float | None = None
    guesser: str | None = None
    votes: dict[int, int] = field(default_factory=dict)
    ending: Ending | None = None
    # 終わったときに全員へ見せる結果。hub が名前を入れて組み立てる
    result: dict[str, Any] | None = None

    def is_participant(self, player_id: int) -> bool:
        return player_id in self.participants

    def role_of(self, player_id: int) -> str | None:
        if not self.is_participant(player_id):
            return None
        return "insider" if player_id == self.insider_id else "villager"

    def begin(self, topic: str, game_id: int, now: float) -> None:
        """お題当てのゲームが始まった。制限時間はここから数える。"""
        self.topic = topic
        self.game_id = game_id
        self.phase = Phase.ASKING
        self.deadline = None if self.minutes is None else now + self.minutes * 60

    def remaining(self, now: float) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - now)

    def start_voting(self, guesser: str) -> None:
        self.phase = Phase.VOTING
        self.deadline = None
        self.guesser = guesser

    def vote(self, voter: int, target: int) -> str | None:
        """投票する。断るときは押した人に見せる文を返す。開票までは入れ直せる。"""
        if self.phase is not Phase.VOTING:
            return "いまは投票できません"
        if not self.is_participant(voter):
            return "参加者だけが投票できます"
        if voter == target:
            return "自分には投票できません"
        if not self.is_participant(target):
            return "参加者の中から選んでください"
        self.votes[voter] = target
        return None

    def all_voted(self) -> bool:
        return all(player_id in self.votes for player_id in self.participants)

    def tally(self) -> Tally:
        counts = {player_id: 0 for player_id in self.participants}
        for target in self.votes.values():
            counts[target] += 1
        top = max(counts.values())
        leaders = [player_id for player_id, count in counts.items() if count == top]
        # 最多票がインサイダー 1 人だけのときだけ村人の勝ち。同票はインサイダーが逃げ切る
        return Tally(counts, leaders == [self.insider_id] and top > 0)

    def finish(self, ending: Ending) -> None:
        self.phase = Phase.DONE
        self.ending = ending
        self.deadline = None


def deal(setup: Setup, rng: Rng) -> InsiderRound:
    """参加者の中からインサイダーを 1 人くじで選ぶ。"""
    insider = setup.participants[rng.randrange(len(setup.participants))]
    return InsiderRound(
        participants=setup.participants, insider_id=insider, topic_mode=setup.topic_mode, minutes=setup.minutes
    )
```

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run pytest tests/test_web_insider.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/insider.py tests/test_web_insider.py
git commit -m "feat: ルームのインサイダーゲーム 1 回分の状態と決まりを足す"
```

---

### Task 2: ルームの持ち物と、`room` の参加者の ID

**Files:**
- Modify: `src/insider_bot/web/rooms.py`（`Entry`・`Room`）
- Modify: `src/insider_bot/web/hub.py`（`_room_state`）
- Modify: `tests/test_web_hub.py`（参加者一覧と `you` の形の期待値）
- Test: `tests/test_web_rooms.py`, `tests/test_web_hub.py`

**Interfaces:**
- Consumes: Task 1 の `InsiderRound`
- Produces:
  - `Entry(entry_id, author, text, pending=False, kind=None, data=None)`。`to_message()` は `kind` があるときだけ `kind` と `data` を足す
  - `Room.add_entry(author, text, pending=False, kind=None, data=None) -> Entry`
  - `Room.insider: InsiderRound | None = None`
  - `room` の `players` の各要素が `{"id": int, "name": str, "online": bool}`、`you` が `{"id": int, "is_setter": bool, ...}`、`room` に `"insider": None | dict`（中身は Task 3）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_web_rooms.py` の末尾に足す:

```python
def test_entry_kind_and_data_are_sent_only_when_set():
    room = RoomRegistry().create()
    plain = room.add_entry(None, "本文")
    card = room.add_entry(None, "結果", kind="insider_result", data={"winner": "insider"})
    assert plain.to_message() == {"id": plain.entry_id, "author": None, "text": "本文", "pending": False}
    assert card.to_message() == {
        "id": card.entry_id,
        "author": None,
        "text": "結果",
        "pending": False,
        "kind": "insider_result",
        "data": {"winner": "insider"},
    }


def test_room_starts_without_insider_round():
    assert RoomRegistry().create().insider is None
```

（`RoomRegistry` が import 済みでなければ、ファイル冒頭の import に足す。）

`tests/test_web_hub.py` の既存の期待値を新しい形に直す:

```python
def test_join_enqueues_welcome_then_snapshot():
    world = World()
    conn, player = world.join("はなこ")
    assert conn.messages == [
        {"type": "welcome", "token": player.token},
        {
            "type": "snapshot",
            "room": {
                "players": [{"id": player.player_id, "name": "はなこ", "online": True}],
                "game": None,
                "you": {"id": player.player_id, "is_setter": False},
                "insider": None,
            },
            "log": [],
        },
    ]
```

同じファイルの `{"name": ..., "online": ...}` を比べている箇所（`test_others_see_arrival_and_departure` など）は、`{"id": <その人の player_id>, "name": ..., "online": ...}` に直す。`you` を比べている箇所（`{"is_setter": True, "topic": "りんご", "hint": "赤い果物"}`）は `{"id": setter[1].player_id, "is_setter": True, "topic": "りんご", "hint": "赤い果物"}` に直す。`tests/test_web_server.py:152` の `you` も同じく `id` を含めた比較にする（`snapshot["room"]["you"]["is_setter"] is True` と `topic`・`hint` を個別に比べる形でよい）。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run pytest tests/test_web_rooms.py tests/test_web_hub.py tests/test_web_server.py -q`
Expected: FAIL（`add_entry() got an unexpected keyword argument 'kind'`、期待値の `id` / `insider` の不一致）

- [ ] **Step 3: 実装する**

`src/insider_bot/web/rooms.py`:

```python
from insider_bot.web.insider import InsiderRound
```

```python
@dataclass(eq=False)
class Entry:
    entry_id: int
    author: str | None
    text: str
    pending: bool = False
    # 文字の読み解きではなく構造で描く記録（インサイダーゲームの結果）。ほかの記録は None のまま
    kind: str | None = None
    data: dict[str, Any] | None = None

    def to_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "id": self.entry_id,
            "author": self.author,
            "text": self.text,
            "pending": self.pending,
        }
        if self.kind is not None:
            message["kind"] = self.kind
            message["data"] = self.data
        return message
```

`Room` に `insider: InsiderRound | None = None` を `log` の次に足し、`add_entry` を次にする:

```python
    def add_entry(
        self,
        author: str | None,
        text: str,
        pending: bool = False,
        kind: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Entry:
        entry = Entry(next(self._entry_ids), author, text, pending, kind, data)
        self.log.append(entry)
        del self.log[:-LOG_LIMIT]
        return entry
```

`src/insider_bot/web/hub.py` の `_room_state` を次にする（`insider` の中身は Task 3 で作るので、ここでは `None` を返すだけの `_insider_state` を置く）:

```python
    def _room_state(self, room: Room, player: Player) -> dict[str, Any]:
        game = self._manager.get(room.room_id)
        header = None
        you: dict[str, Any] = {"id": player.player_id, "is_setter": False}
        if game is not None:
            header = {
                "id": game.game_id,
                "questions": game.question_count,
                "elapsed": round(self._clock() - game.started_at, 1),
            }
            if game.setter_id == player.player_id:
                # お題と補足は出題者の接続にだけ入れる。誰が出題者かはほかの接続に送らない
                you = {"id": player.player_id, "is_setter": True, "topic": game.topic, "hint": game.hint}
        # 名前は重なりうるので、画面は参加者を ID で選ぶ（連番で、秘密ではない）
        players = [
            {"id": p.player_id, "name": p.name, "online": room.is_online(p)} for p in room.players.values()
        ]
        return {"players": players, "game": header, "you": you, "insider": self._insider_state(room, player)}

    def _insider_state(self, room: Room, player: Player) -> dict[str, Any] | None:
        return None
```

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run pytest -q`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/rooms.py src/insider_bot/web/hub.py tests/test_web_rooms.py tests/test_web_hub.py tests/test_web_server.py
git commit -m "feat: ルームにインサイダーゲームの置き場と、記録の種類・参加者の ID を足す"
```

---

### Task 3: 配って始める（ランダム・自分で決める）と、役職の秘匿

**Files:**
- Modify: `src/insider_bot/web/hub.py`
- Test: `tests/test_web_hub.py`

**Interfaces:**
- Consumes: Task 1（`check_setup`・`deal`・`InsiderRound`・`Phase`・`ACTIVE_PHASES`・`InvalidSetup`）、Task 2（`Room.insider`・`add_entry(kind=, data=)`）
- Produces:
  - `RoomHub.__init__(..., pick_topic: Callable[[], str | None] = lambda: None, role_image: Callable[[str], str] = _default_role_image, rng: Rng = random.Random())`
  - `async RoomHub.insider_start(room, player, participants: list[int], topic_mode: str, topic: str | None, minutes: int | None) -> None`
  - `RoomHub._busy(room) -> bool`
  - `room` の `insider`: `{"phase", "participants", "topic_mode", "remaining", "voted", "you": {"role", "topic", "image", "vote"}, "result"}`
  - 定数 `GM_SETTER_ID = 0`, `INSIDER_STARTED`, `INSIDER_CHOOSING`, `MODE_LABELS`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_web_hub.py` の `World` を拡張する（既存の呼び出しはそのまま動く）:

```python
from insider_bot.web.hub import INSIDER_STARTED
from tests.fakes import FixedRandom


class World:
    def __init__(self, judge: FakeJudge | None = None, choose=None, topic: str | None = "すいか", rng=None) -> None:
        self.clock = FakeClock()
        self.judge = judge or FakeJudge()
        self.manager = GameManager(clock=self.clock)
        service = GameService(self.manager, self.judge, clock=self.clock)
        registry = RoomRegistry(clock=self.clock, on_remove=lambda room: self.manager.end(room.room_id))
        options = {} if choose is None else {"choose": choose}
        self.hub = RoomHub(
            registry,
            service,
            self.manager,
            clock=self.clock,
            pick_topic=lambda: topic,
            role_image=lambda role: f"/static/roles/{role}.png",
            rng=rng or FixedRandom(*([0] * 20)),
            **options,
        )
        self.room = self.hub.create_room()
```

テストを足す:

```python
# --- インサイダーゲーム: 配って始める ---


def trio(world: World):
    """たろう・はなこ・じろう の 3 人と、見るだけの さぶろう。"""
    return [world.join(name) for name in ("たろう", "はなこ", "じろう", "さぶろう")]


async def test_insider_random_start_deals_roles_and_starts_game():
    world = World(rng=FixedRandom(1))  # 2 番目（はなこ）がインサイダー
    (t, tp), (h, hp), (j, jp), (s, sp) = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "random", None, None)
    game = world.manager.get(world.room.room_id)
    assert game.topic == "すいか"
    assert world.judge.calls == []
    insider = h.last_room()["insider"]
    assert insider["phase"] == "asking"
    assert insider["participants"] == [tp.player_id, hp.player_id, jp.player_id]
    assert insider["you"] == {"role": "insider", "topic": "すいか", "image": "/static/roles/INSIDER.png", "vote": None}
    assert t.last_room()["insider"]["you"] == {
        "role": "villager",
        "topic": None,
        "image": "/static/roles/VILLAGERS.png",
        "vote": None,
    }
    assert s.last_room()["insider"]["you"] == {"role": None, "topic": None, "image": None, "vote": None}
    texts = [entry["text"] for entry in t.entries()]
    assert texts[-1] == INSIDER_STARTED
    assert "たろう・はなこ・じろう" in texts[-2]
    assert "すいか" not in "".join(texts)
    assert t.of("sound")


async def test_insider_role_is_kept_only_in_own_snapshot():
    world = World(rng=FixedRandom(0))
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, hp, [tp.player_id, hp.player_id, jp.player_id], "random", None, None)
    again, _ = world.join("たろう", tp.token)
    snapshot = again.of("snapshot")[0]["room"]
    assert snapshot["insider"]["you"]["role"] == "insider"
    assert snapshot["insider"]["you"]["topic"] == "すいか"
    # ほかの人の接続には、誰がインサイダーかもお題も入らない
    for conn in (h, j):
        dumped = json.dumps(conn.messages, ensure_ascii=False)
        assert "すいか" not in dumped
        assert "INSIDER.png" not in dumped


async def test_insider_self_topic_excludes_starter():
    world = World()
    (t, tp), (h, hp), (j, jp), (s, sp) = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "self", "ぶどう", None)
    assert t.notices()[-1] == "お題を決める人は参加者になれません"
    assert world.room.insider is None
    await world.hub.insider_start(world.room, tp, [hp.player_id, jp.player_id, sp.player_id], "self", "ぶどう", 3)
    assert world.manager.get(world.room.room_id).topic == "ぶどう"
    assert t.last_room()["insider"]["you"]["role"] is None
    assert t.last_room()["insider"]["remaining"] == 180.0


async def test_insider_start_rejects_invalid_setup_and_busy_room():
    world = World()
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id], "random", None, None)
    assert t.notices()[-1] == "参加者を3人以上選んでください"
    await world.hub.start(world.room, tp, "りんご", "")
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "random", None, None)
    assert t.notices()[-1] == "このルームではゲームが進行中です"


async def test_insider_random_start_needs_dictionary():
    world = World(topic=None)
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "random", None, None)
    assert t.notices()[-1] == "お題の辞書が使えないため、ランダムでは始められません"
    assert world.room.insider is None


async def test_players_with_the_same_name_are_told_apart_by_id():
    world = World(rng=FixedRandom(2))
    (t, tp), (h, hp) = world.join("たろう"), world.join("はなこ")
    (t2, t2p) = world.join("たろう")
    await world.hub.insider_start(world.room, hp, [tp.player_id, hp.player_id, t2p.player_id], "random", None, None)
    assert t2.last_room()["insider"]["you"]["role"] == "insider"
    assert t.last_room()["insider"]["you"]["role"] == "villager"
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run pytest tests/test_web_hub.py -q -k insider`
Expected: FAIL（`RoomHub.__init__() got an unexpected keyword argument 'pick_topic'`）

- [ ] **Step 3: 実装する**

`src/insider_bot/web/hub.py` に import と定数を足す:

```python
from insider_bot.village.illust import Illustrations
from insider_bot.web.insider import ACTIVE_PHASES, InsiderRound, InvalidSetup, Phase, Rng, check_setup, deal
```

```python
# インサイダーゲームでは、お題当ての出題者は人ではなく AI の GM。参加者の ID（1 から）と重ならない番兵
GM_SETTER_ID = 0
GM_NAME = "GM"
# 先頭の 🎮 で画面が開始の案内（GM の吹き出し）と見分け、質問番号を数え直す
INSIDER_STARTED = "🎮 インサイダーゲーム開始！\n役職を確かめて、質問どうぞ。"
INSIDER_CHOOSING = "🕵️ インサイダーがお題を考えています…"
MODE_LABELS = {
    "random": "お題はランダム",
    "self": "お題は出した人が決めました",
    "insider": "お題はインサイダーが決めます",
}


def _default_role_image(role: str) -> str:
    return Illustrations("").default_url(role)
```

`RoomHub.__init__` に引数を足す:

```python
    def __init__(
        self,
        registry: RoomRegistry,
        service: GameService,
        manager: GameManager,
        clock: Clock = time.monotonic,
        choose: Callable[[Sequence[str]], str] = random.choice,
        pick_topic: Callable[[], str | None] = lambda: None,
        role_image: Callable[[str], str] = _default_role_image,
        rng: Rng | None = None,
    ) -> None:
        self._registry = registry
        self._service = service
        self._manager = manager
        self._clock = clock
        self._choose = choose
        # ランダムのお題（配役ツールと同じ辞書）と役職画像。__main__ が配役ツールの中核から渡す
        self._pick_topic = pick_topic
        self._role_image = role_image
        self._rng: Rng = rng if rng is not None else random.Random()
        # 判定中のタスクが途中で回収されないよう、終わるまで参照を持つ
        self._tasks: set[asyncio.Task[None]] = set()
```

`start` の「進行中」の判定を `_busy` に替え、通常のゲームが始まったら終わった回を片付ける:

```python
        if self._busy(room):
            self._notify(room, player, "このルームではゲームが進行中です")
            return
        outcome = await self._service.start(room.room_id, player.player_id, player.name, topic, hint)
        if outcome.public is not None:
            # 前のインサイダーゲームの役職のカードは、次のゲームが始まるまでしか出さない
            room.insider = None
            ...（既存のまま）
```

メソッドを足す:

```python
    def _busy(self, room: Room) -> bool:
        """お題当てのゲームが進行中か、インサイダーゲームがお題待ち・質問・投票のどれか。"""
        if self._manager.get(room.room_id) is not None:
            return True
        return room.insider is not None and room.insider.phase in ACTIVE_PHASES

    def _name_of(self, room: Room, player_id: int) -> str:
        for candidate in room.players.values():
            if candidate.player_id == player_id:
                return candidate.name
        return "?"

    async def insider_start(
        self,
        room: Room,
        player: Player,
        participants: list[int],
        topic_mode: str,
        topic: str | None,
        minutes: int | None,
    ) -> None:
        if self._busy(room):
            self._notify(room, player, "このルームではゲームが進行中です")
            return
        try:
            setup = check_setup(
                [p.player_id for p in room.players.values()], player.player_id, participants, topic_mode, topic, minutes
            )
        except InvalidSetup as error:
            self._notify(room, player, str(error))
            return
        chosen = setup.topic
        if setup.topic_mode == "random":
            chosen = self._pick_topic()
            if chosen is None:
                self._notify(room, player, "お題の辞書が使えないため、ランダムでは始められません")
                return
        insider = deal(setup, self._rng)
        insider.images = {
            player_id: self._role_image("INSIDER" if player_id == insider.insider_id else "VILLAGERS")
            for player_id in insider.participants
        }
        # 次の await より前に置く。始まるまでの間に届いた別の開始は _busy で断られる
        room.insider = insider
        names = "・".join(self._name_of(room, player_id) for player_id in insider.participants)
        self._broadcast_entry(
            room, room.add_entry(None, f"🕵️ インサイダーゲーム　参加者: {names}（{MODE_LABELS[setup.topic_mode]}）")
        )
        if chosen is None:
            self._broadcast_entry(room, room.add_entry(None, INSIDER_CHOOSING))
            self._broadcast_room(room)
            return
        await self._begin_insider(room, insider, chosen)

    async def _begin_insider(self, room: Room, insider: InsiderRound, topic: str) -> None:
        """お題当てのゲームを AI の GM で始める。参加者は全員（インサイダーも）質問する。"""
        outcome = await self._service.start(room.room_id, GM_SETTER_ID, GM_NAME, topic, "")
        game = self._manager.get(room.room_id)
        if outcome.public is None or game is None or room.insider is not insider:
            # _busy で防いでいるので起きないはず。起きたらこの回を捨て、画面を戻す
            log.warning("インサイダーゲームを始められませんでした（room=%s）", room.code)
            if room.insider is insider:
                room.insider = None
            self._broadcast_room(room)
            return
        insider.begin(topic, game.game_id, self._clock())
        self._broadcast(room, {"type": "sound", "src": self._choose(START_SOUNDS)})
        self._broadcast_entry(room, room.add_entry(None, INSIDER_STARTED))
        self._broadcast_room(room)
```

`_insider_state` を本物にする:

```python
    def _insider_state(self, room: Room, player: Player) -> dict[str, Any] | None:
        insider = room.insider
        if insider is None:
            return None
        role = insider.role_of(player.player_id)
        # 役職・お題・自分の票は、その人の接続にだけ入れる。ほかの接続には誰がインサイダーかを送らない
        you = {
            "role": role,
            "topic": insider.topic if role == "insider" else None,
            "image": insider.images.get(player.player_id),
            "vote": insider.votes.get(player.player_id),
        }
        return {
            "phase": insider.phase.value,
            "participants": list(insider.participants),
            "topic_mode": insider.topic_mode,
            "remaining": insider.remaining(self._clock()),
            "voted": [player_id for player_id in insider.participants if player_id in insider.votes],
            "you": you,
            "result": insider.result,
        }
```

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run pytest tests/test_web_hub.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/hub.py tests/test_web_hub.py
git commit -m "feat: ルームでインサイダーゲームを配って始め、役職とお題を本人の接続にだけ送る"
```

---

### Task 4: インサイダーがお題を決める

**Files:**
- Modify: `src/insider_bot/web/hub.py`
- Test: `tests/test_web_hub.py`

**Interfaces:**
- Consumes: Task 1 の `check_topic`、Task 3 の `_begin_insider`
- Produces: `async RoomHub.insider_topic(room, player, topic: str) -> None`

- [ ] **Step 1: 失敗するテストを書く**

```python
async def test_insider_chooses_topic_then_game_starts():
    world = World(rng=FixedRandom(2))  # じろう がインサイダー
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "insider", None, 5)
    assert world.manager.get(world.room.room_id) is None
    assert t.last_room()["insider"]["phase"] == "choosing"
    assert t.entries()[-1]["text"] == "🕵️ インサイダーがお題を考えています…"
    assert j.last_room()["insider"]["you"]["topic"] is None
    await world.hub.insider_topic(world.room, tp, "もも")
    assert t.notices()[-1] == "いまはお題を決められません"
    await world.hub.insider_topic(world.room, jp, "  ")
    assert j.notices()[-1] == "お題は1〜50文字で入力してください"
    world.clock.advance(30)
    await world.hub.insider_topic(world.room, jp, "もも")
    assert world.manager.get(world.room.room_id).topic == "もも"
    assert j.last_room()["insider"]["you"]["topic"] == "もも"
    # 制限時間はお題が決まった時点から数える
    assert j.last_room()["insider"]["remaining"] == 300.0


async def test_insider_topic_twice_starts_only_one_game():
    world = World(rng=FixedRandom(0))
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, hp, [tp.player_id, hp.player_id, jp.player_id], "insider", None, None)
    await asyncio.gather(
        world.hub.insider_topic(world.room, tp, "もも"),
        world.hub.insider_topic(world.room, tp, "なし"),
    )
    assert world.manager.get(world.room.room_id).topic == "もも"
    assert t.notices()[-1] == "いまはお題を決められません"
    assert [e["text"] for e in t.entries()].count(INSIDER_STARTED) == 1
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run pytest tests/test_web_hub.py -q -k insider_topic or insider_chooses`
Expected: FAIL（`AttributeError: 'RoomHub' object has no attribute 'insider_topic'`）

- [ ] **Step 3: 実装する**

import に `check_topic` を足し、メソッドを足す:

```python
    async def insider_topic(self, room: Room, player: Player, topic: str) -> None:
        insider = room.insider
        # お題を先に置いてから await する。連打や再送で 2 回届いても、ゲームは 1 回だけ始まる
        if (
            insider is None
            or insider.phase is not Phase.CHOOSING
            or insider.insider_id != player.player_id
            or insider.topic is not None
        ):
            self._notify(room, player, "いまはお題を決められません")
            return
        try:
            insider.topic = check_topic(topic)
        except InvalidSetup as error:
            self._notify(room, player, str(error))
            return
        await self._begin_insider(room, insider, insider.topic)
```

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run pytest tests/test_web_hub.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/hub.py tests/test_web_hub.py
git commit -m "feat: インサイダーがお題を決めてからゲームを始められるようにする"
```

---

### Task 5: 参加者だけの質問、当たりから投票・開票

**Files:**
- Modify: `src/insider_bot/web/hub.py`
- Test: `tests/test_web_hub.py`

**Interfaces:**
- Consumes: Task 1 の `InsiderRound.start_voting / vote / all_voted / tally / finish`、`Ending`
- Produces:
  - `RoomHub.vote(room, player, target: int) -> None`、`RoomHub.close_vote(room, player) -> None`
  - `RoomHub._finish_insider(room, insider, ending) -> None`（Task 6 でも使う）
  - 結果の記録: `kind="insider_result"`、`data = {"ending", "topic", "insider", "insider_id", "guesser", "winner", "votes"}`（`winner` は `"villagers"` / `"insider"` / `"none"`、`votes` は `[{"id", "name", "count"}]`、投票で終わったときだけ中身がある）
  - 定数 `INSIDER_VOTING`

- [ ] **Step 1: 失敗するテストを書く**

```python
from insider_bot.web.hub import INSIDER_VOTING

CORRECT_SUIKA = FakeJudge(answers={"すいかですか？": CORRECT})


async def insider_playing(rng_index: int = 0):
    """たろう・はなこ・じろう が参加者（rng_index 番目がインサイダー）、さぶろう は見るだけ。お題は すいか。"""
    world = World(judge=FakeJudge(answers={"すいかですか？": CORRECT}), rng=FixedRandom(rng_index))
    people = trio(world)
    ids = [p.player_id for _, p in people[:3]]
    await world.hub.insider_start(world.room, people[0][1], ids, "random", None, 5)
    return world, people


async def test_spectator_cannot_ask():
    world, people = await insider_playing()
    s, sp = people[3]
    await world.hub.ask(world.room, sp, "果物ですか", world.game_id())
    assert s.notices()[-1] == "インサイダーゲームの参加者だけが質問できます"
    assert world.judge.calls == []


async def test_correct_guess_opens_voting_then_all_votes_close_it():
    world, people = await insider_playing(rng_index=0)  # たろう がインサイダー
    (t, tp), (h, hp), (j, jp), (s, sp) = people
    await world.hub.ask(world.room, hp, "すいかですか", world.game_id())
    insider = t.last_room()["insider"]
    assert insider["phase"] == "voting"
    assert insider["remaining"] is None
    assert t.entries()[-1]["text"] == INSIDER_VOTING
    world.hub.vote(world.room, sp, tp.player_id)
    assert s.notices()[-1] == "参加者だけが投票できます"
    world.hub.vote(world.room, hp, tp.player_id)
    world.hub.vote(world.room, jp, hp.player_id)
    world.hub.vote(world.room, jp, tp.player_id)  # 入れ直し
    assert t.last_room()["insider"]["voted"] == [hp.player_id, jp.player_id]
    # 誰が誰に入れたかは、本人の接続以外に送らない
    assert t.last_room()["insider"]["you"]["vote"] is None
    assert j.last_room()["insider"]["you"]["vote"] == tp.player_id
    world.hub.vote(world.room, tp, hp.player_id)
    result = t.entries()[-1]
    assert result["kind"] == "insider_result"
    assert result["data"] == {
        "ending": "voted",
        "topic": "すいか",
        "insider": "たろう",
        "insider_id": tp.player_id,
        "guesser": "はなこ",
        "winner": "villagers",
        "votes": [
            {"id": tp.player_id, "name": "たろう", "count": 2},
            {"id": hp.player_id, "name": "はなこ", "count": 1},
            {"id": jp.player_id, "name": "じろう", "count": 0},
        ],
    }
    assert "村人の勝ち" in result["text"]
    assert t.last_room()["insider"]["phase"] == "done"
    assert s.last_room()["insider"]["result"] == result["data"]


async def test_close_vote_by_participant_with_tie_lets_insider_win():
    world, people = await insider_playing(rng_index=0)
    (t, tp), (h, hp), (j, jp), (s, sp) = people
    await world.hub.ask(world.room, hp, "すいかですか", world.game_id())
    world.hub.close_vote(world.room, hp)
    assert h.notices()[-1] == "まだ誰も投票していません"
    world.hub.vote(world.room, hp, tp.player_id)
    world.hub.vote(world.room, tp, jp.player_id)
    world.hub.close_vote(world.room, sp)
    assert s.notices()[-1] == "参加者だけが開票できます"
    world.hub.close_vote(world.room, jp)
    data = t.entries()[-1]["data"]
    assert data["winner"] == "insider"
    assert "インサイダーの勝ち" in t.entries()[-1]["text"]
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run pytest tests/test_web_hub.py -q -k "spectator or voting or close_vote"`
Expected: FAIL（`ImportError: cannot import name 'INSIDER_VOTING'`）

- [ ] **Step 3: 実装する**

import に `Ending` を足し、定数を足す:

```python
INSIDER_VOTING = "🗳️ お題が当たりました！インサイダーは誰？\n話し合って、自分以外の 1 人に投票してください。"
```

`_ask` の冒頭（文字数の検査の前）に足す:

```python
        insider = room.insider
        if insider is not None and insider.phase is Phase.ASKING and not insider.is_participant(player.player_id):
            self._notify(room, player, "インサイダーゲームの参加者だけが質問できます")
            return
```

`_ask` の終わり（`self._broadcast_entry(room, entry)` の後、`self._broadcast_room(room)` の前）に足す:

```python
        # インサイダーゲームのお題が当たったら、投票に進む。判定中に別の回へ替わっていたら触らない
        if (
            outcome.is_correct
            and insider is not None
            and insider is room.insider
            and insider.phase is Phase.ASKING
            and insider.game_id == game.game_id
        ):
            self._cancel_timer(room)
            insider.start_voting(player.name)
            self._broadcast_entry(room, room.add_entry(None, INSIDER_VOTING))
```

（`_cancel_timer` は Task 6 で中身を作る。ここでは何もしないメソッドを置く:）

```python
    def _cancel_timer(self, room: Room) -> None:
        pass
```

メソッドを足す:

```python
    def vote(self, room: Room, player: Player, target: int) -> None:
        insider = room.insider
        if insider is None:
            self._notify(room, player, "いまは投票できません")
            return
        problem = insider.vote(player.player_id, target)
        if problem is not None:
            self._notify(room, player, problem)
            return
        if insider.all_voted():
            self._finish_insider(room, insider, Ending.VOTED)
            return
        self._broadcast_room(room)

    def close_vote(self, room: Room, player: Player) -> None:
        """接続が切れた人を待たずに締め切る。"""
        insider = room.insider
        if insider is None or insider.phase is not Phase.VOTING:
            self._notify(room, player, "いまは開票できません")
            return
        if not insider.is_participant(player.player_id):
            self._notify(room, player, "参加者だけが開票できます")
            return
        if not insider.votes:
            self._notify(room, player, "まだ誰も投票していません")
            return
        self._finish_insider(room, insider, Ending.VOTED)

    def _finish_insider(self, room: Room, insider: InsiderRound, ending: Ending) -> None:
        """回を終え、インサイダーを明かした結果のカードを全員に送る。誰が誰に入れたかは出さない。"""
        insider.finish(ending)
        name = self._name_of(room, insider.insider_id)
        votes: list[dict[str, Any]] = []
        if ending is Ending.VOTED:
            tally = insider.tally()
            winner = "villagers" if tally.villagers_win else "insider"
            votes = [
                {"id": player_id, "name": self._name_of(room, player_id), "count": count}
                for player_id, count in tally.counts.items()
            ]
            text = f"🕵️ インサイダーは {name} でした。{'村人の勝ち！' if tally.villagers_win else 'インサイダーの勝ち！'}"
        else:
            winner = "none"
            text = f"🕵️ インサイダーは {name} でした。全員の負け…"
        insider.result = {
            "ending": ending.value,
            "topic": insider.topic,
            "insider": name,
            # 同じ名前の人がいても、結果のカードでインサイダーの行を取り違えないよう ID も入れる
            "insider_id": insider.insider_id,
            "guesser": insider.guesser,
            "winner": winner,
            "votes": votes,
        }
        self._broadcast_entry(room, room.add_entry(None, text, kind="insider_result", data=insider.result))
        self._broadcast_room(room)
```

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run pytest tests/test_web_hub.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/hub.py tests/test_web_hub.py
git commit -m "feat: インサイダーゲームの質問を参加者に限り、当たったら投票して開票する"
```

---

### Task 6: 制限時間・ギブアップ・ほかのゲームの締め出し

**Files:**
- Modify: `src/insider_bot/web/hub.py`
- Test: `tests/test_web_hub.py`

**Interfaces:**
- Consumes: Task 5 の `_finish_insider`・`_cancel_timer`
- Produces: `async RoomHub.time_up(room, game_id: int) -> None`、`RoomHub._schedule_time_up(room, game_id, seconds)`

- [ ] **Step 1: 失敗するテストを書く**

```python
async def test_time_up_ends_game_with_everyone_losing():
    world, people = await insider_playing(rng_index=1)
    (t, tp), (h, hp), (j, jp), _ = people
    game_id = world.game_id()
    await world.hub.ask(world.room, jp, "果物ですか", game_id)
    await world.hub.time_up(world.room, game_id)
    assert world.manager.get(world.room.room_id) is None
    texts = [entry["text"] for entry in t.entries()]
    assert texts[-2] == "🏳️ 時間切れ！お題は『すいか』でした（質問数: 1）"
    data = t.entries()[-1]["data"]
    assert (data["ending"], data["winner"], data["insider"], data["votes"]) == ("time_up", "none", "はなこ", [])
    assert t.of("sound")[-1]["src"] == GIVEUP_SOUND


async def test_time_up_after_correct_or_for_old_game_does_nothing():
    world, people = await insider_playing()
    (t, tp), (h, hp), (j, jp), _ = people
    game_id = world.game_id()
    await world.hub.ask(world.room, hp, "すいかですか", game_id)
    before = list(t.messages)
    await world.hub.time_up(world.room, game_id)
    assert t.messages == before
    assert world.room.insider.phase.value == "voting"


async def test_timer_fires_time_up(monkeypatch):
    world, people = await insider_playing()
    fired = []

    async def fake_time_up(room, game_id):
        fired.append(game_id)

    monkeypatch.setattr(world.hub, "time_up", fake_time_up)
    world.hub._schedule_time_up(world.room, 42, 0.01)
    await asyncio.sleep(0.05)
    assert fired == [42]


async def test_giveup_is_for_participants_and_reveals_insider():
    world, people = await insider_playing(rng_index=2)
    (t, tp), (h, hp), (j, jp), (s, sp) = people
    await world.hub.giveup(world.room, sp)
    assert s.notices()[-1] == "インサイダーゲームの参加者だけがギブアップできます"
    assert world.manager.get(world.room.room_id) is not None
    await world.hub.giveup(world.room, hp)
    data = t.entries()[-1]["data"]
    assert (data["ending"], data["insider"], data["winner"]) == ("giveup", "じろう", "none")


async def test_giveup_while_insider_is_choosing_cancels_round():
    world = World(rng=FixedRandom(0))
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, hp, [tp.player_id, hp.player_id, jp.player_id], "insider", None, None)
    await world.hub.giveup(world.room, jp)
    data = t.entries()[-1]["data"]
    assert (data["ending"], data["topic"], data["insider"]) == ("giveup", None, "たろう")
    assert t.last_room()["insider"]["phase"] == "done"


async def test_other_games_are_refused_while_voting():
    world, people = await insider_playing()
    (t, tp), (h, hp), (j, jp), _ = people
    await world.hub.ask(world.room, hp, "すいかですか", world.game_id())
    await world.hub.start(world.room, tp, "りんご", "")
    assert t.notices()[-1] == "このルームではゲームが進行中です"
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "random", None, None)
    assert t.notices()[-1] == "このルームではゲームが進行中です"


async def test_normal_game_after_done_round_clears_role_card():
    world, people = await insider_playing()
    (t, tp), (h, hp), (j, jp), _ = people
    await world.hub.giveup(world.room, hp)
    assert t.last_room()["insider"]["phase"] == "done"
    await world.hub.start(world.room, tp, "りんご", "")
    assert t.last_room()["insider"] is None
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run pytest tests/test_web_hub.py -q -k "time_up or timer or giveup or refused or done_round"`
Expected: FAIL（`AttributeError: 'RoomHub' object has no attribute 'time_up'`）

- [ ] **Step 3: 実装する**

`__init__` に `self._timers: dict[int, asyncio.TimerHandle] = {}` を足す。

`_begin_insider` の `insider.begin(...)` の直後に足す:

```python
        if insider.minutes is not None:
            self._schedule_time_up(room, game.game_id, insider.minutes * 60)
```

メソッドを足し、`_cancel_timer` を本物にする:

```python
    def _schedule_time_up(self, room: Room, game_id: int, seconds: float) -> None:
        """締め切りに時間切れの処理を 1 つ予約する。ルームが片付けられてもゲームが消えるので、発火しても何もしない。"""
        self._cancel_timer(room)

        def fire() -> None:
            self._timers.pop(room.room_id, None)
            task = asyncio.create_task(self.time_up(room, game_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        self._timers[room.room_id] = asyncio.get_running_loop().call_later(seconds, fire)

    def _cancel_timer(self, room: Room) -> None:
        handle = self._timers.pop(room.room_id, None)
        if handle is not None:
            handle.cancel()

    async def time_up(self, room: Room, game_id: int) -> None:
        """制限時間が来た。そのゲームがまだ質問の段階のときだけ、全員の負けで終える。"""
        insider = room.insider
        if insider is None or insider.phase is not Phase.ASKING or insider.game_id != game_id:
            return
        game = self._manager.get(room.room_id)
        outcome = await self._service.giveup(room.room_id)
        # 判定の順番待ちの間に当たって投票へ進んだら、もうゲームはない
        if outcome.public is None or game is None or room.insider is not insider or insider.phase is not Phase.ASKING:
            return
        self._broadcast(room, {"type": "sound", "src": GIVEUP_SOUND})
        # 🏳️ で始めると、画面はギブアップと同じお題の公開カードで描く
        self._broadcast_entry(
            room, room.add_entry(None, f"🏳️ 時間切れ！お題は『{insider.topic}』でした（質問数: {game.question_count}）")
        )
        self._finish_insider(room, insider, Ending.TIME_UP)
```

`giveup` を次にする:

```python
    async def giveup(self, room: Room, player: Player) -> None:
        insider = room.insider
        if insider is not None and insider.phase in (Phase.CHOOSING, Phase.ASKING):
            if not insider.is_participant(player.player_id):
                self._notify(room, player, "インサイダーゲームの参加者だけがギブアップできます")
                return
            if insider.phase is Phase.CHOOSING:
                # お題が決まる前はお題当てのゲームがない。中止して全員の負けにする
                self._finish_insider(room, insider, Ending.GIVEUP)
                return
        outcome = await self._service.giveup(room.room_id)
        if outcome.public is not None:
            self._broadcast(room, {"type": "sound", "src": GIVEUP_SOUND})
        self._apply(room, player, outcome, author=player.name)
        if (
            outcome.public is not None
            and insider is not None
            and insider is room.insider
            and insider.phase is Phase.ASKING
        ):
            self._cancel_timer(room)
            self._finish_insider(room, insider, Ending.GIVEUP)
```

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run pytest -q`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/hub.py tests/test_web_hub.py
git commit -m "feat: インサイダーゲームに制限時間とギブアップを足し、進行中はほかのゲームを断る"
```

---

### Task 7: WebSocket の受け口と、辞書・役職画像の配線

**Files:**
- Modify: `src/insider_bot/web/server.py`（`_dispatch`）
- Modify: `src/insider_bot/web/__main__.py`（`make_app`）
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: Task 3〜6 の `insider_start`・`insider_topic`・`vote`・`close_vote`
- Produces: 画面からの `insider_start` / `insider_topic` / `vote` / `close_vote`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_web_server.py` の `serve` に `pick_topic` を渡せるようにする:

```python
@contextlib.asynccontextmanager
async def serve(static_dir, judge=None, village=None, **limits):
    """static_dir が None なら、本物の STATIC_DIR（既定）で組み立てる。"""
    clock = FakeClock()
    manager = GameManager(clock=clock)
    service = GameService(manager, judge or FakeJudge(), clock=clock)
    registry = RoomRegistry(clock=clock, on_remove=lambda room: manager.end(room.room_id), **limits)
    hub = RoomHub(registry, service, manager, clock=clock, pick_topic=lambda: "すいか", rng=FixedRandom(*([0] * 20)))
    kwargs = {} if static_dir is None else {"static_dir": static_dir}
    async with TestClient(TestServer(create_app(hub, village=village, **kwargs))) as client:
        yield client
```

テストを足す:

```python
async def test_insider_game_over_websocket(static_dir):
    judge = FakeJudge(answers={"すいかですか？": Verdict(1.0, True, "exact")})
    async with serve(static_dir, judge=judge) as client:
        code = await create_room(client)
        players = [await join(client, code, name) for name in ("たろう", "はなこ", "じろう")]
        ws = [p[0] for p in players]
        ids = [player["id"] for player in players[-1][2]["room"]["players"]]
        await ws[0].send_json(
            {"type": "insider_start", "participants": ids, "topic_mode": "random", "topic": None, "minutes": None}
        )
        room = await receive_until(ws[0], lambda m: m["type"] == "room" and (m["insider"] or {}).get("phase") == "asking")
        assert room["insider"]["you"]["role"] == "insider"  # FixedRandom(0) で 1 人目
        await ws[1].send_json({"type": "ask", "text": "すいかですか", "game_id": room["game"]["id"]})
        await receive_until(ws[1], lambda m: m["type"] == "room" and (m["insider"] or {}).get("phase") == "voting")
        for voter, target in ((0, 1), (1, 0), (2, 0)):
            await ws[voter].send_json({"type": "vote", "target": ids[target]})
        result = await receive_until(ws[2], lambda m: m["type"] == "entry" and m["entry"].get("kind") == "insider_result")
        assert result["entry"]["data"]["winner"] == "villagers"


@pytest.mark.parametrize(
    "junk",
    [
        {"type": "insider_start", "participants": "1,2,3", "topic_mode": "random"},
        {"type": "insider_start", "participants": [1, True, 3], "topic_mode": "random"},
        {"type": "insider_start", "participants": [1, 2, 3], "topic_mode": 5},
        {"type": "insider_start", "participants": [1, 2, 3], "topic_mode": "random", "minutes": "5"},
        {"type": "insider_topic", "topic": 3},
        {"type": "vote", "target": "1"},
        {"type": "vote", "target": False},
    ],
)
async def test_malformed_insider_messages_are_ignored(static_dir, junk):
    async with serve(static_dir) as client:
        code = await create_room(client)
        ws, _, _ = await join(client, code, "たろう")
        await ws.send_json(junk)
        await ws.send_json({"type": "start", "topic": "りんご", "hint": ""})
        notice = await receive_until(ws, lambda m: m["type"] == "notice")
        assert notice["text"] == "お題『りんご』を登録しました"
```

（`Verdict` を `from insider_bot.judge import Verdict` で import する。）

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run pytest tests/test_web_server.py -q -k insider`
Expected: FAIL（`insider_start` が無視され、`receive_until` が TimeoutError）

- [ ] **Step 3: 実装する**

`src/insider_bot/web/server.py` に整数の検査と分岐を足す:

```python
def _is_int(value: object) -> bool:
    # JSON の true / false は Python で int の仲間になるので除く
    return isinstance(value, int) and not isinstance(value, bool)
```

`_dispatch` の `elif kind == "giveup":` の後に足す:

```python
    elif kind == "insider_start":
        participants, mode = message.get("participants"), message.get("topic_mode")
        topic, minutes = message.get("topic"), message.get("minutes")
        if (
            isinstance(participants, list)
            and all(_is_int(p) for p in participants)
            and isinstance(mode, str)
            and (topic is None or isinstance(topic, str))
            and (minutes is None or _is_int(minutes))
        ):
            await hub.insider_start(room, player, participants, mode, topic, minutes)
    elif kind == "insider_topic":
        topic = message.get("topic")
        if isinstance(topic, str):
            await hub.insider_topic(room, player, topic)
    elif kind == "vote":
        target = message.get("target")
        if _is_int(target):
            hub.vote(room, player, target)
    elif kind == "close_vote":
        hub.close_vote(room, player)
```

`src/insider_bot/web/__main__.py` の `make_app` で、配役ツールの中核をルームにも渡す（村の組み立てを `RoomHub` より前に移す）:

```python
from insider_bot.village.words import BEGINNER_RANK
```

```python
    registry = RoomRegistry(on_remove=lambda room: manager.end(room.room_id))
    village = build_village(config.public_base_url)
    # ルームのインサイダーゲームも、配役ツールと同じ辞書（初心者の範囲）と役職画像を使う
    hub = RoomHub(
        registry,
        service,
        manager,
        pick_topic=lambda: village.service.pick_topic(BEGINNER_RANK),
        role_image=village.service.illust.url_for,
    )
    app = create_app(hub, village=village)
```

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run pytest -q`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/server.py src/insider_bot/web/__main__.py tests/test_web_server.py
git commit -m "feat: インサイダーゲームの操作を WebSocket で受け、配役ツールの辞書と役職画像をルームに渡す"
```

---

### Task 8: 画面の判断 `insider.js`

**Files:**
- Create: `src/insider_bot/web/static/insider.js`
- Test: `tests/js/insider.test.mjs`

**Interfaces:**
- Produces（すべて純粋関数）:
  - 定数 `MIN_PARTICIPANTS = 3`, `MIN_MINUTES = 1`, `MAX_MINUTES = 30`, `DEFAULT_MINUTES = 5`, `TOPIC_MAX = 50`
  - `selectable(players, myId, topicMode) -> players`（`self` なら自分を外す）
  - `initialSelection(players, myId, topicMode) -> Set<number>`（接続中の人。`self` なら自分を外す）
  - `setupProblem({ selected, topicMode, topic, minutes }) -> string | null`
  - `startMessage({ selected, topicMode, topic, minutes }) -> { type: "insider_start", participants, topic_mode, topic, minutes }`
  - `formatRemaining(seconds) -> "m:ss"`
  - `voteTargets(insider, players, myId) -> [{ id, name }]`
  - `resultView(data) -> { title, headline, topic, rows: [{ name, count, insider }], guesser }`
  - `ROLE_LABELS = { insider: "インサイダー", villager: "村人" }`

- [ ] **Step 1: 失敗するテストを書く**

`tests/js/insider.test.mjs`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatRemaining,
  initialSelection,
  resultView,
  selectable,
  setupProblem,
  startMessage,
  voteTargets,
} from "../../src/insider_bot/web/static/insider.js";

const PLAYERS = [
  { id: 1, name: "たろう", online: true },
  { id: 2, name: "はなこ", online: true },
  { id: 3, name: "じろう", online: false },
  { id: 4, name: "さぶろう", online: true },
];

test("自分で決めるときは自分を選べない", () => {
  assert.deepEqual(
    selectable(PLAYERS, 1, "self").map((p) => p.id),
    [2, 3, 4],
  );
  assert.deepEqual(
    selectable(PLAYERS, 1, "random").map((p) => p.id),
    [1, 2, 3, 4],
  );
});

test("最初は接続中の人を選んでおく", () => {
  assert.deepEqual([...initialSelection(PLAYERS, 1, "random")], [1, 2, 4]);
  assert.deepEqual([...initialSelection(PLAYERS, 1, "self")], [2, 4]);
});

test("設定の検査", () => {
  const ok = { selected: new Set([1, 2, 4]), topicMode: "random", topic: "", minutes: null };
  assert.equal(setupProblem(ok), null);
  assert.equal(setupProblem({ ...ok, selected: new Set([1, 2]) }), "参加者を3人以上選んでください");
  assert.equal(setupProblem({ ...ok, topicMode: "self", topic: "  " }), "お題を入力してください");
  assert.equal(setupProblem({ ...ok, topicMode: "self", topic: "あ".repeat(51) }), "お題は50文字までです");
  assert.equal(setupProblem({ ...ok, minutes: 31 }), "制限時間は1〜30分で選んでください");
});

test("始めるメッセージ。お題は自分で決めるときだけ送る", () => {
  assert.deepEqual(startMessage({ selected: new Set([2, 4, 3]), topicMode: "self", topic: " もも ", minutes: 5 }), {
    type: "insider_start",
    participants: [2, 4, 3],
    topic_mode: "self",
    topic: "もも",
    minutes: 5,
  });
  assert.equal(startMessage({ selected: new Set([1, 2, 3]), topicMode: "random", topic: "もも", minutes: null }).topic, null);
});

test("残り時間", () => {
  assert.equal(formatRemaining(300), "5:00");
  assert.equal(formatRemaining(61.4), "1:02");
  assert.equal(formatRemaining(0), "0:00");
  assert.equal(formatRemaining(-3), "0:00");
});

test("投票の相手は自分以外の参加者", () => {
  const insider = { participants: [1, 2, 3] };
  assert.deepEqual(voteTargets(insider, PLAYERS, 2), [
    { id: 1, name: "たろう" },
    { id: 3, name: "じろう" },
  ]);
});

test("結果の表示", () => {
  const view = resultView({
    ending: "voted",
    topic: "すいか",
    insider: "たろう",
    insider_id: 1,
    guesser: "はなこ",
    winner: "villagers",
    votes: [
      { id: 1, name: "たろう", count: 2 },
      { id: 2, name: "はなこ", count: 1 },
    ],
  });
  assert.equal(view.headline, "村人の勝ち！");
  assert.equal(view.title, "インサイダーは たろう");
  assert.deepEqual(view.rows, [
    { name: "たろう", count: 2, insider: true },
    { name: "はなこ", count: 1, insider: false },
  ]);
  assert.equal(resultView({ ending: "time_up", topic: "すいか", insider: "たろう", winner: "none", votes: [] }).headline, "時間切れ　全員の負け…");
  assert.equal(resultView({ ending: "giveup", topic: null, insider: "たろう", winner: "none", votes: [] }).topic, null);
});
```

- [ ] **Step 2: 失敗を確かめる**

Run: `node --test tests/js/insider.test.mjs`
Expected: FAIL（`Cannot find module .../insider.js`）

- [ ] **Step 3: 実装する**

`src/insider_bot/web/static/insider.js`:

```js
// ルームのインサイダーゲームの、画面の判断だけを持つ純粋関数。描画は insiderview.js
export const MIN_PARTICIPANTS = 3;
export const MIN_MINUTES = 1;
export const MAX_MINUTES = 30;
export const DEFAULT_MINUTES = 5;
export const TOPIC_MAX = 50;
export const ROLE_LABELS = { insider: "インサイダー", villager: "村人" };

/** 参加者に選べる人。お題を自分で決めるときは、お題を知るので自分を外す。 */
export function selectable(players, myId, topicMode) {
  return topicMode === "self" ? players.filter((player) => player.id !== myId) : players;
}

/** 設定のシートを開いたときに選んでおく人（接続中の人）。 */
export function initialSelection(players, myId, topicMode) {
  return new Set(selectable(players, myId, topicMode).filter((player) => player.online).map((player) => player.id));
}

/** 始められない理由。始められるなら null。サーバーも同じ検査をする。 */
export function setupProblem({ selected, topicMode, topic, minutes }) {
  if (selected.size < MIN_PARTICIPANTS) return `参加者を${MIN_PARTICIPANTS}人以上選んでください`;
  if (topicMode === "self") {
    const trimmed = topic.trim();
    if (trimmed === "") return "お題を入力してください";
    if (trimmed.length > TOPIC_MAX) return `お題は${TOPIC_MAX}文字までです`;
  }
  if (minutes !== null && !(minutes >= MIN_MINUTES && minutes <= MAX_MINUTES)) {
    return `制限時間は${MIN_MINUTES}〜${MAX_MINUTES}分で選んでください`;
  }
  return null;
}

export function startMessage({ selected, topicMode, topic, minutes }) {
  return {
    type: "insider_start",
    participants: [...selected],
    topic_mode: topicMode,
    topic: topicMode === "self" ? topic.trim() : null,
    minutes,
  };
}

export function formatRemaining(seconds) {
  const total = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** 投票できる相手（自分以外の参加者）。名前はルームの参加者一覧から引く。 */
export function voteTargets(insider, players, myId) {
  const names = new Map(players.map((player) => [player.id, player.name]));
  return insider.participants.filter((id) => id !== myId).map((id) => ({ id, name: names.get(id) ?? "?" }));
}

const HEADLINES = {
  villagers: "村人の勝ち！",
  insider: "インサイダーの勝ち！",
};

/** 結果のカードに出す形。誰が誰に入れたかはサーバーも送らない。 */
export function resultView(data) {
  let headline = HEADLINES[data.winner] ?? "全員の負け…";
  if (data.ending === "time_up") headline = "時間切れ　全員の負け…";
  if (data.ending === "giveup") headline = "ギブアップ　全員の負け…";
  return {
    title: `インサイダーは ${data.insider}`,
    headline,
    topic: data.topic ?? null,
    guesser: data.guesser ?? null,
    // 同じ名前の人がいても取り違えないよう、インサイダーの行は ID で見分ける
    rows: (data.votes ?? []).map((vote) => ({ name: vote.name, count: vote.count, insider: vote.id === data.insider_id })),
  };
}
```

- [ ] **Step 4: 通ることを確かめる**

Run: `node --test tests/js/*.test.mjs`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/static/insider.js tests/js/insider.test.mjs
git commit -m "feat: インサイダーゲームの画面の判断を insider.js に足す"
```

---

### Task 9: 画面（設定のシート・役職のカード・お題の入力・投票・結果のカード）

**Files:**
- Create: `src/insider_bot/web/static/insiderview.js`
- Modify: `src/insider_bot/web/static/index.html`（`#start-panel` の中、`#controls` の中、ダイアログ）
- Modify: `src/insider_bot/web/static/app.js`（`renderRoom`・`renderStatus`・`upsertEntry`・`bindControls`）
- Modify: `src/insider_bot/web/static/style.css`（末尾に節を足す）

**Interfaces:**
- Consumes: Task 8 の `insider.js`、Task 2〜7 の `room.insider`・`you.id`・`players[].id`・`kind: "insider_result"`
- Produces: `insiderview.js` の `class InsiderView`:
  - `constructor({ send, notice })`
  - `bind()`（ボタンとダイアログのイベントを結ぶ。1 回だけ呼ぶ）
  - `render(room)`（`room` は `{ players, game, you, insider }`）
  - `get deadlineAt()`（残り時間を出す基準。制限時間がなければ `null`）
  - `static resultNodes(data) -> Node[]`

- [ ] **Step 1: `index.html` に部品を足す**

`#start-open` ボタンの直後に:

```html
            <button id="insider-open" type="button" class="secondary wide insider-open">
              インサイダーゲーム開始 <span aria-hidden="true">🕵️</span>
            </button>
```

`#asker-panel` の直前に:

```html
          <div id="insider-panel" class="insider-panel" hidden>
            <p id="insider-status" class="insider-status" role="status"></p>
            <button id="role-open" type="button" class="secondary wide" hidden>
              自分の役職を見る
            </button>
            <form id="insider-topic-form" class="row" hidden>
              <input
                id="insider-topic-input"
                aria-label="お題"
                maxlength="50"
                autocomplete="off"
                placeholder="お題を決めてください（50文字まで）"
                required
              /><button type="submit" class="primary">決める</button>
            </form>
            <div id="vote-panel" class="stack" hidden>
              <p class="insider-lead">インサイダーだと思う人に投票（開票まで入れ直せます）</p>
              <div id="vote-targets" class="pick-grid"></div>
              <button id="vote-close" type="button" class="secondary wide">開票する</button>
            </div>
            <button id="insider-cancel" type="button" class="link muted-link" hidden>
              中止する（全員の負け）
            </button>
          </div>
```

ダイアログ（`#giveup-dialog` の後）に:

```html
    <dialog id="insider-setup" class="sheet insider-sheet" aria-labelledby="insider-setup-title">
      <p class="eyebrow">INSIDER GAME</p>
      <h2 id="insider-setup-title">インサイダーゲームを始める</h2>
      <form id="insider-form" class="stack">
        <fieldset class="field-group">
          <legend>参加者 <span id="insider-count" class="field-note"></span></legend>
          <div id="insider-players" class="pick-grid"></div>
        </fieldset>
        <fieldset class="field-group">
          <legend>お題</legend>
          <div class="segmented">
            <label class="segment"><input type="radio" name="topic-mode" value="random" checked /><span>ランダム</span></label>
            <label class="segment"><input type="radio" name="topic-mode" value="self" /><span>自分で決める</span></label>
            <label class="segment"><input type="radio" name="topic-mode" value="insider" /><span>インサイダーが決める</span></label>
          </div>
          <label id="insider-topic-field" class="field" hidden
            >お題 <span class="field-note">50文字まで・あなたは参加できません</span
            ><input id="insider-topic" maxlength="50" autocomplete="off"
          /></label>
        </fieldset>
        <fieldset class="field-group">
          <legend>制限時間</legend>
          <label class="check-row"><input id="insider-timer" type="checkbox" /> 制限時間をつける</label>
          <div id="insider-minutes-row" class="stepper" hidden>
            <button id="minutes-down" type="button" aria-label="1分減らす">−</button
            ><output id="insider-minutes" aria-live="polite">5</output><span>分</span
            ><button id="minutes-up" type="button" aria-label="1分増やす">＋</button>
          </div>
        </fieldset>
        <p id="insider-problem" class="message" role="status"></p>
        <div class="row">
          <button type="submit" class="primary">配って始める</button
          ><button id="insider-setup-cancel" type="button" class="secondary">やめる</button>
        </div>
      </form>
    </dialog>

    <dialog id="role-dialog" class="sheet role-sheet" aria-labelledby="role-title">
      <p class="eyebrow">YOUR ROLE</p>
      <h2 id="role-title"></h2>
      <img id="role-image" class="role-image" alt="" />
      <p id="role-topic" class="role-topic"></p>
      <button id="role-close" type="button" class="primary wide">閉じる</button>
    </dialog>

    <dialog id="close-vote-dialog" class="sheet" aria-labelledby="close-vote-title">
      <h2 id="close-vote-title">開票しますか？</h2>
      <p class="dialog-lead">まだ投票していない人がいても締め切ります。</p>
      <div class="row">
        <button id="close-vote-cancel" type="button" class="secondary" autofocus>やめる</button
        ><button id="close-vote-confirm" type="button" class="primary">開票する</button>
      </div>
    </dialog>
```

- [ ] **Step 2: `insiderview.js` を書く**

```js
// ルームのインサイダーゲームの描画。判断は insider.js にあり、ここは DOM に描いてボタンを結ぶだけ
import {
  DEFAULT_MINUTES,
  formatRemaining,
  initialSelection,
  MAX_MINUTES,
  MIN_MINUTES,
  resultView,
  ROLE_LABELS,
  selectable,
  setupProblem,
  startMessage,
  voteTargets,
} from "./insider.js";

const $ = (id) => document.getElementById(id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// 名前ごとの大きなボタン。押すと選ぶ・外す（aria-pressed）
function pickButton(label, pressed, onClick) {
  const button = element("button", "pick", label);
  button.type = "button";
  button.setAttribute("aria-pressed", String(pressed));
  button.addEventListener("click", onClick);
  return button;
}

export class InsiderView {
  constructor({ send, notice }) {
    this.send = send;
    this.notice = notice;
    this.room = null;
    this.selected = new Set();
    this.minutes = DEFAULT_MINUTES;
    this.deadline = null;
  }

  get deadlineAt() {
    return this.deadline;
  }

  topicMode() {
    return document.querySelector('input[name="topic-mode"]:checked').value;
  }

  bind() {
    $("insider-open").addEventListener("click", () => this.openSetup());
    $("insider-setup-cancel").addEventListener("click", () => $("insider-setup").close());
    for (const radio of document.querySelectorAll('input[name="topic-mode"]')) {
      radio.addEventListener("change", () => {
        $("insider-topic-field").hidden = this.topicMode() !== "self";
        // 自分で決めるときは自分を選べないので、選択から外す
        if (this.topicMode() === "self") this.selected.delete(this.room.you.id);
        this.renderPicker();
      });
    }
    $("insider-timer").addEventListener("change", () => {
      $("insider-minutes-row").hidden = !$("insider-timer").checked;
    });
    const step = (delta) => {
      this.minutes = Math.min(MAX_MINUTES, Math.max(MIN_MINUTES, this.minutes + delta));
      $("insider-minutes").textContent = String(this.minutes);
    };
    $("minutes-down").addEventListener("click", () => step(-1));
    $("minutes-up").addEventListener("click", () => step(1));
    $("insider-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const setup = {
        selected: this.selected,
        topicMode: this.topicMode(),
        topic: $("insider-topic").value,
        minutes: $("insider-timer").checked ? this.minutes : null,
      };
      const problem = setupProblem(setup);
      $("insider-problem").textContent = problem ?? "";
      if (problem !== null) return;
      if (!this.send(startMessage(setup))) {
        $("insider-problem").textContent = "接続が切れているため送れませんでした";
        return;
      }
      $("insider-topic").value = "";
      $("insider-setup").close();
    });
    $("role-open").addEventListener("click", () => $("role-dialog").showModal());
    $("role-close").addEventListener("click", () => $("role-dialog").close());
    $("insider-topic-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const topic = $("insider-topic-input").value.trim();
      if (!topic) return;
      if (this.send({ type: "insider_topic", topic })) $("insider-topic-input").value = "";
    });
    $("vote-close").addEventListener("click", () => $("close-vote-dialog").showModal());
    $("close-vote-cancel").addEventListener("click", () => $("close-vote-dialog").close());
    $("close-vote-confirm").addEventListener("click", () => {
      this.send({ type: "close_vote" });
      $("close-vote-dialog").close();
    });
    $("insider-cancel").addEventListener("click", () => this.send({ type: "giveup" }));
  }

  openSetup() {
    const { players, you } = this.room;
    this.selected = initialSelection(players, you.id, this.topicMode());
    $("insider-problem").textContent = "";
    this.renderPicker();
    $("insider-setup").showModal();
  }

  renderPicker() {
    const { players, you } = this.room;
    const choices = selectable(players, you.id, this.topicMode());
    $("insider-players").replaceChildren(
      ...choices.map((player) =>
        pickButton(player.id === you.id ? `${player.name}（自分）` : player.name, this.selected.has(player.id), () => {
          if (this.selected.has(player.id)) this.selected.delete(player.id);
          else this.selected.add(player.id);
          this.renderPicker();
        }),
      ),
    );
    $("insider-count").textContent = `${this.selected.size} 人選択中（3 人以上）`;
  }

  /** room の変化を描く。返り値は「質問の操作（押して話す）を出してよいか」。 */
  render(room) {
    this.room = room;
    const { insider, you, players, game } = room;
    const active = insider && insider.phase !== "done";
    $("insider-open").hidden = Boolean(game) || Boolean(active);
    this.deadline = insider?.remaining == null ? null : performance.now() / 1000 + insider.remaining;
    const panel = $("insider-panel");
    panel.hidden = !insider;
    if (!insider) return true;
    const role = insider.you.role;
    // 役職のカード
    $("role-open").hidden = role === null;
    if (role !== null) {
      $("role-title").textContent = `あなたは${ROLE_LABELS[role]}`;
      $("role-image").src = insider.you.image ?? "";
      $("role-image").hidden = !insider.you.image;
      $("role-topic").textContent =
        role === "insider"
          ? insider.you.topic
            ? `お題：${insider.you.topic}`
            : "お題を決めてください"
          : "お題はわかりません。質問して当てましょう";
    }
    const status = $("insider-status");
    $("insider-topic-form").hidden = !(insider.phase === "choosing" && role === "insider");
    $("vote-panel").hidden = !(insider.phase === "voting" && role !== null);
    $("insider-cancel").hidden = !(insider.phase === "choosing" && role !== null);
    if (insider.phase === "choosing") {
      status.textContent = role === "insider" ? "あなたがインサイダーです。お題を決めてください" : "インサイダーがお題を考えています…";
    } else if (insider.phase === "asking") {
      status.textContent = role === null ? "見学中（質問・投票はできません）" : "";
    } else if (insider.phase === "voting") {
      status.textContent = `投票 ${insider.voted.length} / ${insider.participants.length} 人`;
      if (role !== null) this.renderVotes(insider, players, you.id);
    } else {
      status.textContent = "";
    }
    return role !== null || insider.phase === "done";
  }

  renderVotes(insider, players, myId) {
    $("vote-targets").replaceChildren(
      ...voteTargets(insider, players, myId).map((target) =>
        pickButton(target.name, insider.you.vote === target.id, () => this.send({ type: "vote", target: target.id })),
      ),
    );
  }

  remainingLabel() {
    if (this.deadline === null) return null;
    return formatRemaining(this.deadline - performance.now() / 1000);
  }

  static resultNodes(data) {
    const view = resultView(data);
    const nodes = [element("p", "insider-result-headline", view.headline), element("p", "insider-result-title", view.title)];
    if (view.topic) nodes.push(element("p", "insider-result-topic", `お題：${view.topic}`));
    if (view.guesser) nodes.push(element("p", "insider-result-meta", `正解者：${view.guesser}`));
    if (view.rows.length) {
      const list = element("ul", "insider-result-votes");
      for (const row of view.rows) {
        const item = element("li", row.insider ? "is-insider" : "");
        item.append(element("span", "", row.name), element("span", "count", `${row.count} 票`));
        list.append(item);
      }
      nodes.push(list);
    }
    return nodes;
  }
}
```

- [ ] **Step 3: `app.js` につなぐ**

import を足す:

```js
import { InsiderView } from "./insiderview.js";
```

`RoomPage` の `constructor` の末尾に:

```js
    this.insider = new InsiderView({
      send: (message) => this.send(message),
      notice: (text) => this.notice(text),
    });
```

`start()` の `this.bindControls();` の直後に `this.insider.bind();` を足す。

`renderRoom` を次にする（引数に `insider` を足し、質問の操作を参加者だけに出す）:

```js
  renderRoom(room) {
    const { players, game, you } = room;
    if (this.game?.id !== game?.id && $("giveup-dialog").open)
      $("giveup-dialog").close();
    this.game = game;
    ...（参加者一覧・secret の描画は既存のまま）
    const canAsk = this.insider.render(room);
    const busy = Boolean(game) || (room.insider && room.insider.phase !== "done");
    $("start-panel").hidden = busy;
    // 出題者も質問者に紛れて遊ぶので、全員に同じ操作を出す。インサイダーゲームでは見るだけの人に出さない
    $("asker-panel").hidden = !game || !canAsk;
    if (game) this.closeStartForm();
    if (!game) this.talk?.cancel("ゲームが終わったため取り消しました");
    this.renderStatus();
  }
```

`renderStatus` の `["経過", formatElapsed(elapsed)]` を、制限時間があるときは残り時間にする:

```js
    const remaining = this.insider.remainingLabel();
    ...
      ...[
        ["質問", `${this.game.questions} 回`],
        remaining === null ? ["経過", formatElapsed(elapsed)] : ["残り", remaining],
      ].map(...)
```

`upsertEntry` の `const answer = ...` の前に、結果のカードの分岐を足す:

```js
    if (entry.kind === "insider_result" && entry.data) {
      item.className = "entry result insider-result";
      item.dataset.kind = "result";
      item.replaceChildren(...InsiderView.resultNodes(entry.data));
      this.renumber();
      if (atBottom) log.scrollTop = log.scrollHeight;
      return;
    }
```

- [ ] **Step 4: `style.css` の末尾に節を足す**

```css
/* --- ルームのインサイダーゲーム --- */

.insider-open {
  margin-top: 10px;
}

.insider-panel {
  display: grid;
  gap: 10px;
  margin-bottom: 10px;
}

.insider-status:empty {
  display: none;
}

.insider-status,
.insider-lead {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.pick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 8px;
}

.pick {
  min-height: 52px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: transparent;
  color: var(--text);
  font-weight: 700;
  overflow-wrap: anywhere;
}

.pick[aria-pressed="true"] {
  border-color: var(--accent);
  background: #dfef7826;
}

.pick[aria-pressed="true"]::before {
  content: "✓ ";
  color: var(--accent);
}

.field-group {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  border: 0;
}

.field-group legend {
  margin-bottom: 8px;
  padding: 0;
  font-weight: 700;
}

.segmented {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.segment {
  position: relative;
}

.segment input {
  position: absolute;
  opacity: 0;
}

.segment span {
  display: grid;
  place-items: center;
  min-height: 48px;
  padding: 6px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  font-size: 13px;
  font-weight: 700;
  text-align: center;
}

.segment input:checked + span {
  border-color: var(--accent);
  background: #dfef7826;
}

.segment input:focus-visible + span {
  outline: 3px solid var(--accent);
  outline-offset: 2px;
}

.check-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
}

.check-row input {
  width: 22px;
  height: 22px;
}

.stepper {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stepper button {
  width: 48px;
  height: 48px;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: transparent;
  color: var(--text);
  font-size: 22px;
}

.stepper output {
  min-width: 2ch;
  font-size: 28px;
  font-weight: 800;
  text-align: center;
}

.role-image {
  display: block;
  width: min(240px, 100%);
  margin: 0 auto;
  border-radius: var(--radius);
}

.role-topic {
  font-size: 20px;
  font-weight: 700;
  text-align: center;
}

.insider-result {
  display: grid;
  gap: 6px;
  padding: 18px;
  border: 1px solid var(--accent);
  border-radius: var(--radius);
}

.insider-result p {
  margin: 0;
}

.insider-result-headline {
  color: var(--accent);
  font-size: 22px;
  font-weight: 800;
}

.insider-result-title {
  font-size: 18px;
  font-weight: 700;
}

.insider-result-topic,
.insider-result-meta {
  color: var(--muted);
}

.insider-result-votes {
  display: grid;
  gap: 4px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}

.insider-result-votes li {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  border-radius: var(--radius);
  background: #ffffff0d;
}

.insider-result-votes li.is-insider {
  outline: 1px solid var(--accent);
}
```

- [ ] **Step 5: テストと画面で確かめる**

Run: `node --test tests/js/*.test.mjs && uv run pytest -q`
Expected: PASS（全件）

手元のサーバー（`.claude/launch.json` の `insider-web-local`）を起動し、内蔵ブラウザで `http://localhost:8080` からルームを作って 1 人目（たろう）で入る。2 人目以降は、同じページの JavaScript から WebSocket でつなぐ:

```js
const code = location.pathname.split("/")[2];
const bot = (name) =>
  new Promise((resolve) => {
    const ws = new WebSocket(`ws://${location.host}/r/${code}/ws`);
    const box = { ws, messages: [] };
    ws.onopen = () => ws.send(JSON.stringify({ type: "join", name, token: null }));
    ws.onmessage = (event) => {
      box.messages.push(JSON.parse(event.data));
      if (box.messages.length === 2) resolve(box);
    };
  });
window.bots = [await bot("はなこ"), await bot("じろう")];
```

スマホ幅（`resize_window` の mobile）で次を確かめ、スクリーンショットを撮る:

1. 「インサイダーゲーム開始」→ 参加者 3 人を選んでランダムで配る → 役職のカードが開ける。ボットの `messages` の最後の `room` で、ほかの人の役職が見えないこと
2. ボットから当てる質問を送る（`{type:"ask", text:"<お題>ですか", game_id}`。お題はインサイダーのボットの `room.insider.you.topic` か、自分がインサイダーなら役職のカード）→ 投票のパネルが出る → 3 人が投票 → 結果のカード
3. 制限時間 1 分で配り、1 分待って時間切れのカードが出ること
4. 「インサイダーが決める」で配り、インサイダーがお題を決めると始まること
5. 見るだけの人（自分を外して配る）には押して話すが出ず「見学中」と出ること

- [ ] **Step 6: コミット**

```bash
git add src/insider_bot/web/static/insiderview.js src/insider_bot/web/static/index.html src/insider_bot/web/static/app.js src/insider_bot/web/static/style.css
git commit -m "feat: ルームの画面からインサイダーゲームを配って遊び、投票と結果を見られるようにする"
```

---

### Task 10: ドキュメントの蒸留

**Files:**
- Modify: `docs/spec.md`（「目的と範囲」の対象外、「Web 版」のルール・画面・設計上の判断、「将来の拡張」）
- Modify: `README.md`（遊び方）
- Delete: `docs/superpowers/specs/2026-10-10-room-insider-game-design.md`, `docs/superpowers/plans/2026-10-10-room-insider-game.md`

- [ ] **Step 1: `docs/spec.md` を直す**

- 「対象外」の「インサイダーの投票・タイマー」を消す。
- 「Web 版」の「ルールの違い」の後に「### インサイダーゲーム」の節を足し、設計書の「遊び方の流れと決まり」（始める・配る・質問の時間・投票）を現在形で写す。
- 「設計上の判断」に足す:
  - **インサイダーゲームの状態は `web/insider.py`**: 通信を知らない 1 回分の状態と決まり。`GameService` は変えず、出題者を番兵の ID（0）と「GM」にして AI に答えさせる。
  - **役職は本人の接続にだけ**: `_room_state` を接続ごとに作るところでだけ役職・お題・自分の票を入れる。誰が誰に入れたかは結果にも入れない。
  - **時間切れは予約 1 つ**: `call_later` で締め切りに 1 つ置き、発火したときにまだそのゲームの質問の段階なら終える。当たり・ギブアップで取り消す。
  - **辞書と役職画像は配役ツールと共有**: 起動時に 1 回だけ読む。
- 「将来の拡張」の「制限時間、インサイダーの投票。」を消す（「Jev のお題当てルームへの配役の持ち込み」も実現したので消す）。

- [ ] **Step 2: README の遊び方に足す**

「### インサイダーの配役」の前に、ルームでインサイダーゲームを遊ぶ手順（開始 → 参加者を選ぶ → お題の決め方 → 制限時間 → 当たったら投票）を 3〜5 行で足す。

- [ ] **Step 3: 設計書と計画を消し、確かめてコミット**

```bash
git rm docs/superpowers/specs/2026-10-10-room-insider-game-design.md docs/superpowers/plans/2026-10-10-room-insider-game.md
uv run pytest -q && node --test tests/js/*.test.mjs
git add docs/spec.md README.md
git commit -m "docs: ルームのインサイダーゲームを仕様書と README に蒸留し、設計書と計画を消す"
```
