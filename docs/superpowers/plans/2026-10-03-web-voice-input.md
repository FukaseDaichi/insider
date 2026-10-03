# お題当てゲーム Web 版（押して話す音声入力）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discord の外の Web サイトで、ボタンを押している間に話した質問をお題当てゲームに送れるようにする。

**Architecture:** 既存の `GameService`・`GameManager`・`JevJudge`・`format` は変更せず、新しいパッケージ `insider_bot.web` を別プロセスとして足す。`rooms.py`（ルームと参加者）→ `hub.py`（進行役。送信待ちの列に積むだけで待たない）→ `server.py`（aiohttp の HTTP と WebSocket）の 3 層で、画面はビルド不要の HTML と素の JavaScript。公開は Tailscale Funnel。

**Tech Stack:** Python 3.13・uv・aiohttp 3.14・pytest / pytest-asyncio・素の JavaScript（ES モジュール）・Web Speech API・qrcode-generator 1.4.4・jsQR 1.4.0・Node（`node --test`）

**Spec:** [docs/superpowers/specs/2026-10-03-web-voice-input-design.md](../specs/2026-10-03-web-voice-input-design.md)

## Global Constraints

- Python は uv 経由でだけ動かす（`uv run …`・`uv add …`）。pip やシステムの Python は使わない
- 既存の `src/insider_bot/service.py`・`game.py`・`judge.py`・`format.py`・`bot.py` は変更しない
- 依存の追加は `aiohttp>=3.14` を本番の依存にするだけ（`uv add`。`uv.lock` もコミットする）
- 外部の CDN は使わない。ライブラリは `src/insider_bot/web/static/vendor/` に版番号付きで置く: `qrcode-generator-1.4.4.js`（MIT）、`jsQR-1.4.0.js`（Apache-2.0）
- 長さの上限: 名前 1〜20 文字、お題 1〜50 文字、補足 300 文字まで、質問 200 文字まで
- ルームは同時に 50 個、1 ルームの参加者は 20 人、履歴は最新 300 行
- 片付け: 誰も入らないルームは 10 分、誰も接続していないルームは 6 時間で消す。片付けは 10 分ごと
- ルーム番号は 6 文字、文字種は `ABCDEFGHJKMNPQRSTUVWXYZ23456789`
- WebSocket の終了コード: `4400`（join がない・不正）、`4404`（ルームがない）、`4409`（満員）
- WebSocket: 受け取るメッセージは最大 4096 バイト、死活確認 30 秒、join を待つのは 10 秒、送信待ちは 100 件で接続を閉じる（終了コード 1013）
- 待ち受けの既定は `127.0.0.1:8080`（`WEB_HOST`・`WEB_PORT`）
- `Cache-Control`: `/static/vendor/` は `public, max-age=604800`、それ以外の画面ファイルと `/`・`/r/…` は `no-cache`
- 押して話す: 押し続けは 20 秒で打ち切り、`stop()` 後に `end` を待つのは 2 秒、再接続の間隔は 1→2→4→8→10 秒
- 画面の文言・コメント・コミットメッセージは日本語。コメントは既存コードと同じく少なめで、理由を書く
- コミットメッセージは `feat:`・`docs:` などの接頭辞＋日本語の要約で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` を付ける
- 名前・質問・お題は画面で `textContent` だけを使って出す（`innerHTML` を使わない）

## Review Focus

仕様が明示的には書いていないが、使う人が最も出会いそうな入力と、その期待する動き（それぞれのテストを担当タスクに入れてある）。

1. 音声認識の結果が「。」や「？」だけ → 判定に送らず「質問を入力してください」（Task 3 `test_question_rejected_before_judging`）
2. 2 人がほぼ同時に「お題を出す」 → 先の人のお題で始まり、後の人には「このルームではゲームが進行中です」（Discord 用の「チャンネル」の文言を出さない）（Task 3 `test_near_simultaneous_starts_keep_the_first`）
3. 入室後に壊れたメッセージ（JSON でない・型が違う・知らない種類）が届く → 無視して接続はそのまま使える（Task 4 `test_malformed_messages_are_ignored`）
4. 同じ人が 2 つのタブで入り、片方を閉じる → その人は「接続中」のまま（Task 3 `test_closing_one_of_two_tabs_keeps_player_online`）
5. 声で遊ぶ人がゲーム開始の案内を見る → 「？をつけてね」ではなく「押して話す」で質問するよう案内する（Task 3 `test_start_notifies_setter_and_announces_to_everyone`）

---

## ファイル構成

| ファイル | 役割 |
|---|---|
| `src/insider_bot/config.py`（変更） | `load_web_config` と `WebConfig` を追加。しきい値・タイムアウトの検査を共通化 |
| `src/insider_bot/web/__init__.py` | パッケージの説明だけ |
| `src/insider_bot/web/rooms.py` | ルーム・参加者・履歴の行・上限・片付け（ネットワークにも GameService にも依存しない） |
| `src/insider_bot/web/hub.py` | 進行役 `RoomHub`。操作の検査、GameService の呼び出し、送信待ちの列への積み込み |
| `src/insider_bot/web/server.py` | aiohttp のアプリ。`WsConnection`（送信待ちの列）、HTTP、WebSocket の受信ループ |
| `src/insider_bot/web/__main__.py` | 起動（`python -m insider_bot.web`） |
| `src/insider_bot/web/static/index.html` | 画面の骨組み（トップ・名前入力・ルーム・エラー・招待・読み取り） |
| `src/insider_bot/web/static/style.css` | 見た目 |
| `src/insider_bot/web/static/app.js` | 画面全体と WebSocket の接続・再接続 |
| `src/insider_bot/web/static/speech.js` | 押して話す（Web Speech API） |
| `src/insider_bot/web/static/qr.js` | 招待パネルの QR 描画と QR の読み取り |
| `src/insider_bot/web/static/roomurl.js` | 読み取った文字列がこのサイトのルーム URL かの判定 |
| `src/insider_bot/web/static/vendor/` | qrcode-generator・jsQR とライセンス文 |
| `tests/test_web_config.py`・`test_web_rooms.py`・`test_web_hub.py`・`test_web_server.py` | pytest |
| `tests/js/roomurl.test.mjs`・`tests/js/speech.test.mjs` | `node --test` |
| `deploy/insider-web.service`（新規）・`deploy/setup.sh`・`deploy/README.md` | デプロイ |
| `README.md`・`.env.example`・`docs/spec.md` | ドキュメント |

---

### Task 1: Web 用の設定と aiohttp の依存

**Files:**
- Modify: `src/insider_bot/config.py`（全体を書き換え）
- Modify: `pyproject.toml`・`uv.lock`（`uv add` で）
- Modify: `.env.example`
- Test: `tests/test_web_config.py`

**Interfaces:**
- Consumes: なし
- Produces: `insider_bot.config.WebConfig(typesafe_api_key: str, correct_threshold: float, jev_timeout_seconds: float, host: str, port: int)`、`insider_bot.config.load_web_config(env: Mapping[str, str] | None = None) -> WebConfig`。既存の `load_config`・`Config`・`ConfigError` はそのまま

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_web_config.py`:

```python
import pytest

from insider_bot.config import ConfigError, WebConfig, load_web_config


def test_web_needs_only_typesafe_key():
    assert load_web_config({"TYPESAFE_API_KEY": "ts-key"}) == WebConfig(
        typesafe_api_key="ts-key",
        correct_threshold=0.8,
        jev_timeout_seconds=10.0,
        host="127.0.0.1",
        port=8080,
    )


def test_web_optional_values():
    config = load_web_config(
        {
            "TYPESAFE_API_KEY": "ts-key",
            "WEB_HOST": "0.0.0.0",
            "WEB_PORT": "9000",
            "CORRECT_THRESHOLD": "0.9",
            "JEV_TIMEOUT_SECONDS": "5",
        }
    )
    assert (config.host, config.port, config.correct_threshold, config.jev_timeout_seconds) == (
        "0.0.0.0",
        9000,
        0.9,
        5.0,
    )


def test_web_blank_optional_values_use_defaults():
    config = load_web_config({"TYPESAFE_API_KEY": "ts-key", "WEB_HOST": " ", "WEB_PORT": ""})
    assert (config.host, config.port) == ("127.0.0.1", 8080)


def test_web_missing_key():
    with pytest.raises(ConfigError) as error:
        load_web_config({"DISCORD_TOKEN": "discord-token"})
    assert "TYPESAFE_API_KEY" in str(error.value)
    assert "DISCORD_TOKEN" not in str(error.value)


@pytest.mark.parametrize(
    "extra",
    [
        {"WEB_PORT": "abc"},
        {"WEB_PORT": "0"},
        {"WEB_PORT": "70000"},
        {"CORRECT_THRESHOLD": "2"},
        {"JEV_TIMEOUT_SECONDS": "0"},
    ],
)
def test_web_invalid_values(extra):
    with pytest.raises(ConfigError):
        load_web_config({"TYPESAFE_API_KEY": "ts-key"} | extra)
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_web_config.py -v`
Expected: FAIL（`ImportError: cannot import name 'WebConfig'`）

- [ ] **Step 3: 実装する**

`src/insider_bot/config.py` を次の内容に置き換える:

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


@dataclass(frozen=True)
class WebConfig:
    typesafe_api_key: str
    correct_threshold: float
    jev_timeout_seconds: float
    host: str
    port: int


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


def _require(env: Mapping[str, str], names: tuple[str, ...]) -> None:
    missing = [name for name in names if not _get(env, name)]
    if missing:
        raise ConfigError(f"必須の環境変数が未設定です: {', '.join(missing)}（.env を確認してください）")


def _judge_settings(env: Mapping[str, str]) -> tuple[float, float]:
    """Discord 版と Web 版で共通の、正解のしきい値と Jev のタイムアウト。"""
    threshold = _float(env, "CORRECT_THRESHOLD", 0.8)
    if not 0.0 <= threshold <= 1.0:
        raise ConfigError(f"CORRECT_THRESHOLD は 0〜1 で指定してください（現在: {threshold}）")

    timeout = _float(env, "JEV_TIMEOUT_SECONDS", 10.0)
    if timeout <= 0:
        raise ConfigError(f"JEV_TIMEOUT_SECONDS は 0 より大きい値にしてください（現在: {timeout}）")
    return threshold, timeout


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    _require(env, ("DISCORD_TOKEN", "TYPESAFE_API_KEY"))

    guild_raw = _get(env, "DISCORD_GUILD_ID")
    try:
        guild_id = int(guild_raw) if guild_raw else None
    except ValueError:
        raise ConfigError(f"DISCORD_GUILD_ID は数字で指定してください（現在: {guild_raw!r}）") from None

    threshold, timeout = _judge_settings(env)
    return Config(
        discord_token=_get(env, "DISCORD_TOKEN"),
        typesafe_api_key=_get(env, "TYPESAFE_API_KEY"),
        guild_id=guild_id,
        correct_threshold=threshold,
        jev_timeout_seconds=timeout,
    )


def load_web_config(env: Mapping[str, str] | None = None) -> WebConfig:
    env = os.environ if env is None else env
    _require(env, ("TYPESAFE_API_KEY",))
    threshold, timeout = _judge_settings(env)

    port_raw = _get(env, "WEB_PORT")
    try:
        port = int(port_raw) if port_raw else 8080
    except ValueError:
        raise ConfigError(f"WEB_PORT は数字で指定してください（現在: {port_raw!r}）") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"WEB_PORT は 1〜65535 で指定してください（現在: {port}）")

    return WebConfig(
        typesafe_api_key=_get(env, "TYPESAFE_API_KEY"),
        correct_threshold=threshold,
        jev_timeout_seconds=timeout,
        host=_get(env, "WEB_HOST") or "127.0.0.1",
        port=port,
    )
```

- [ ] **Step 4: テストが通ることを確かめる（既存の設定テストも）**

Run: `uv run pytest tests/test_web_config.py tests/test_config.py -v`
Expected: PASS（すべて）

- [ ] **Step 5: aiohttp を本番の依存に加える**

Run: `uv add "aiohttp>=3.14"`
Expected: `pyproject.toml` の `[project] dependencies` に `"aiohttp>=3.14"` が入り、`uv.lock` が更新される（aiohttp は discord.py 経由で既にロックに入っているので、版は 3.14.3 のまま）

Run: `git diff --stat pyproject.toml uv.lock`
Expected: 2 ファイルとも変更あり

- [ ] **Step 6: `.env.example` に Web 版の設定を足す**

`.env.example` の末尾に追記する:

```
# 任意（Web 版）: 待ち受けるアドレス。サーバーでは 127.0.0.1 のまま Tailscale Funnel で公開する
WEB_HOST=127.0.0.1
# 任意（Web 版）: 待ち受けるポート
WEB_PORT=8080
```

- [ ] **Step 7: 全テストを流す**

Run: `uv run pytest -q`
Expected: すべて PASS

- [ ] **Step 8: コミット**

```bash
git add src/insider_bot/config.py tests/test_web_config.py pyproject.toml uv.lock .env.example
git commit -m "$(cat <<'EOF'
feat: Web版の設定読み込みとaiohttpの依存を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: ルームと参加者の管理（rooms.py）

**Files:**
- Create: `src/insider_bot/web/__init__.py`
- Create: `src/insider_bot/web/rooms.py`
- Test: `tests/test_web_rooms.py`

**Interfaces:**
- Consumes: `insider_bot.game.Clock`
- Produces（`insider_bot.web.rooms`）:
  - 定数 `CODE_ALPHABET`・`CODE_LENGTH = 6`・`MAX_ROOMS = 50`・`MAX_PLAYERS = 20`・`NAME_MAX = 20`・`LOG_LIMIT = 300`・`UNJOINED_TTL_SECONDS = 600`・`IDLE_TTL_SECONDS = 21600`
  - 例外 `RoomNotFound`・`RoomFull`・`RoomLimitReached`・`InvalidName`
  - `Player(player_id: int, name: str, token: str)`
  - `Entry(entry_id: int, author: str | None, text: str, pending: bool = False)` と `Entry.to_message() -> dict`（キーは `id`・`author`・`text`・`pending`）
  - `Room(room_id: int, code: str, last_active: float, joined: bool, players: dict[str, Player], connections: dict[object, Player], log: list[Entry])`、`Room.is_online(player) -> bool`、`Room.add_entry(author, text, pending=False) -> Entry`
  - `RoomRegistry(clock=time.monotonic, on_remove=…, max_rooms=MAX_ROOMS, max_players=MAX_PLAYERS)`、メソッド `get(code) -> Room | None`・`create() -> Room`・`join(room, token, name) -> Player`・`attach(room, conn, player)`・`detach(room, conn)`・`cleanup()`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_web_rooms.py`:

```python
import pytest

from insider_bot.web.rooms import (
    CODE_ALPHABET,
    CODE_LENGTH,
    InvalidName,
    RoomFull,
    RoomLimitReached,
    RoomRegistry,
)
from tests.fakes import FakeClock


def make(**limits):
    clock = FakeClock()
    removed = []
    registry = RoomRegistry(clock=clock, on_remove=removed.append, **limits)
    return registry, clock, removed


# --- 作成 ---


def test_create_gives_unique_codes_and_ids():
    registry, _, _ = make()
    rooms = [registry.create() for _ in range(20)]
    assert len({room.code for room in rooms}) == 20
    assert len({room.room_id for room in rooms}) == 20
    for room in rooms:
        assert len(room.code) == CODE_LENGTH
        assert set(room.code) <= set(CODE_ALPHABET)
        assert registry.get(room.code) is room


def test_code_alphabet_has_no_confusing_characters():
    assert not set("0O1IL") & set(CODE_ALPHABET)


def test_get_unknown_code_is_none():
    registry, _, _ = make()
    assert registry.get("ZZZZZZ") is None


# --- 入室 ---


def test_join_creates_player_with_token():
    registry, _, _ = make()
    room = registry.create()
    player = registry.join(room, None, " はなこ ")
    assert player.name == "はなこ"
    assert len(player.token) >= 16
    assert room.players[player.token] is player


def test_rejoin_with_token_keeps_player_and_name():
    registry, _, _ = make()
    room = registry.create()
    player = registry.join(room, None, "はなこ")
    assert registry.join(room, player.token, "別の名前") is player
    assert player.name == "はなこ"


def test_unknown_token_creates_new_player():
    registry, _, _ = make()
    room = registry.create()
    first = registry.join(room, None, "はなこ")
    second = registry.join(room, "見知らぬ合言葉", "じろう")
    assert second is not first
    assert second.player_id != first.player_id


@pytest.mark.parametrize("name", ["", "   ", "あ" * 21])
def test_join_rejects_invalid_name(name):
    registry, _, _ = make()
    room = registry.create()
    with pytest.raises(InvalidName):
        registry.join(room, None, name)
    assert room.players == {}


def test_player_limit_applies_only_to_new_players():
    registry, _, _ = make(max_players=2)
    room = registry.create()
    first = registry.join(room, None, "たろう")
    registry.join(room, None, "はなこ")
    with pytest.raises(RoomFull):
        registry.join(room, None, "じろう")
    assert registry.join(room, first.token, "たろう") is first


# --- 接続 ---


def test_attach_and_detach_track_online_per_connection():
    registry, _, _ = make()
    room = registry.create()
    player = registry.join(room, None, "はなこ")
    assert not room.is_online(player)
    registry.attach(room, "tab-1", player)
    registry.attach(room, "tab-2", player)
    registry.detach(room, "tab-1")
    assert room.is_online(player)
    registry.detach(room, "tab-2")
    assert not room.is_online(player)


# --- ルーム数の上限 ---


def test_room_limit_evicts_oldest_room_without_connections():
    registry, clock, removed = make(max_rooms=2)
    oldest = registry.create()
    clock.advance(1)
    registry.create()
    clock.advance(1)
    newest = registry.create()
    assert removed == [oldest]
    assert registry.get(oldest.code) is None
    assert registry.get(newest.code) is newest


def test_room_limit_never_evicts_rooms_with_connections():
    registry, clock, removed = make(max_rooms=2)
    playing = registry.create()
    registry.attach(playing, "tab", registry.join(playing, None, "たろう"))
    clock.advance(1)
    empty = registry.create()
    registry.create()
    assert removed == [empty]
    assert registry.get(playing.code) is playing


def test_room_limit_raises_when_every_room_has_connections():
    registry, _, removed = make(max_rooms=2)
    for name in ("たろう", "はなこ"):
        room = registry.create()
        registry.attach(room, name, registry.join(room, None, name))
    with pytest.raises(RoomLimitReached):
        registry.create()
    assert removed == []


# --- 片付け ---


def test_cleanup_removes_room_nobody_joined_after_10_minutes():
    registry, clock, removed = make()
    room = registry.create()
    clock.advance(599)
    registry.cleanup()
    assert registry.get(room.code) is room
    clock.advance(1)
    registry.cleanup()
    assert registry.get(room.code) is None
    assert removed == [room]


def test_cleanup_removes_joined_room_after_6_hours_without_connections():
    registry, clock, removed = make()
    room = registry.create()
    player = registry.join(room, None, "はなこ")
    registry.attach(room, "tab", player)
    clock.advance(7 * 3600)
    registry.cleanup()
    assert registry.get(room.code) is room
    registry.detach(room, "tab")
    clock.advance(6 * 3600 - 1)
    registry.cleanup()
    assert registry.get(room.code) is room
    clock.advance(1)
    registry.cleanup()
    assert removed == [room]


# --- 履歴 ---


def test_add_entry_numbers_entries_and_keeps_latest_300():
    registry, _, _ = make()
    room = registry.create()
    entries = [room.add_entry(None, str(i)) for i in range(305)]
    assert [entry.entry_id for entry in entries[:2]] == [1, 2]
    assert len(room.log) == 300
    assert room.log[0].text == "5"


def test_entry_to_message():
    registry, _, _ = make()
    room = registry.create()
    entry = room.add_entry("はなこ", "❓ 果物ですか？\n… 判定中", pending=True)
    assert entry.to_message() == {"id": 1, "author": "はなこ", "text": "❓ 果物ですか？\n… 判定中", "pending": True}
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_web_rooms.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'insider_bot.web'`）

- [ ] **Step 3: 実装する**

`src/insider_bot/web/__init__.py`:

```python
"""お題当てゲームの Web 版（押して話す音声入力）。起動: python -m insider_bot.web"""
```

`src/insider_bot/web/rooms.py`:

```python
"""Web 版のルームと参加者。ネットワークにも GameService にも依存しない。"""

from __future__ import annotations

import itertools
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from insider_bot.game import Clock

# 紛らわしい 0・O・1・I・L を除く
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
MAX_ROOMS = 50
MAX_PLAYERS = 20
NAME_MAX = 20
LOG_LIMIT = 300
UNJOINED_TTL_SECONDS = 10 * 60
IDLE_TTL_SECONDS = 6 * 60 * 60


class RoomNotFound(Exception):
    """ルームがない（番号違い・片付け済み・サーバーの再起動）。"""


class RoomFull(Exception):
    """参加者が上限に達していて、新しい参加者を作れない。"""


class RoomLimitReached(Exception):
    """ルーム数が上限で、空けられるルームもない。"""


class InvalidName(Exception):
    """名前が空か長すぎる。"""


@dataclass(eq=False)
class Player:
    player_id: int
    name: str
    token: str


@dataclass(eq=False)
class Entry:
    entry_id: int
    author: str | None
    text: str
    pending: bool = False

    def to_message(self) -> dict[str, Any]:
        return {"id": self.entry_id, "author": self.author, "text": self.text, "pending": self.pending}


@dataclass(eq=False)
class Room:
    room_id: int
    code: str
    last_active: float
    joined: bool = False
    players: dict[str, Player] = field(default_factory=dict)
    connections: dict[object, Player] = field(default_factory=dict)
    log: list[Entry] = field(default_factory=list)
    _entry_ids: itertools.count = field(default_factory=lambda: itertools.count(1), init=False, repr=False)

    def is_online(self, player: Player) -> bool:
        return any(owner is player for owner in self.connections.values())

    def add_entry(self, author: str | None, text: str, pending: bool = False) -> Entry:
        entry = Entry(next(self._entry_ids), author, text, pending)
        self.log.append(entry)
        del self.log[:-LOG_LIMIT]
        return entry


class RoomRegistry:
    def __init__(
        self,
        clock: Clock = time.monotonic,
        on_remove: Callable[[Room], None] = lambda room: None,
        max_rooms: int = MAX_ROOMS,
        max_players: int = MAX_PLAYERS,
    ) -> None:
        self._clock = clock
        self._on_remove = on_remove
        self._max_rooms = max_rooms
        self._max_players = max_players
        self._rooms: dict[str, Room] = {}
        self._room_ids = itertools.count(1)
        self._player_ids = itertools.count(1)

    def get(self, code: str) -> Room | None:
        return self._rooms.get(code)

    def create(self) -> Room:
        if len(self._rooms) >= self._max_rooms:
            # 作成に認証がないので、空のルームを大量に作られても遊んでいる人のルームは消さない
            idle = [room for room in self._rooms.values() if not room.connections]
            if not idle:
                raise RoomLimitReached()
            self._remove(min(idle, key=lambda room: room.last_active))
        code = self._new_code()
        room = Room(room_id=next(self._room_ids), code=code, last_active=self._clock())
        self._rooms[code] = room
        return room

    def join(self, room: Room, token: str | None, name: str) -> Player:
        """合言葉が一致すれば既存の参加者を返す（名前は変えない）。それ以外は新しい参加者を作る。"""
        if token is not None and token in room.players:
            return room.players[token]
        name = name.strip()
        if not 1 <= len(name) <= NAME_MAX:
            raise InvalidName(name)
        if len(room.players) >= self._max_players:
            raise RoomFull(room.code)
        player = Player(next(self._player_ids), name, secrets.token_urlsafe(16))
        room.players[player.token] = player
        room.joined = True
        return player

    def attach(self, room: Room, conn: object, player: Player) -> None:
        room.connections[conn] = player
        room.last_active = self._clock()

    def detach(self, room: Room, conn: object) -> None:
        room.connections.pop(conn, None)
        room.last_active = self._clock()

    def cleanup(self) -> None:
        now = self._clock()
        for room in list(self._rooms.values()):
            if room.connections:
                continue
            ttl = IDLE_TTL_SECONDS if room.joined else UNJOINED_TTL_SECONDS
            if now - room.last_active >= ttl:
                self._remove(room)

    def _remove(self, room: Room) -> None:
        del self._rooms[room.code]
        self._on_remove(room)

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._rooms:
                return code
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run pytest tests/test_web_rooms.py -v`
Expected: PASS（すべて）

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/__init__.py src/insider_bot/web/rooms.py tests/test_web_rooms.py
git commit -m "$(cat <<'EOF'
feat: Web版のルームと参加者の管理を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 進行役 RoomHub（hub.py）

**Files:**
- Create: `src/insider_bot/web/hub.py`
- Test: `tests/test_web_hub.py`

**Interfaces:**
- Consumes: Task 2 の `RoomRegistry`・`Room`・`Player`・`Entry`・`RoomNotFound`、既存の `GameService.start/handle_question/giveup`・`GameManager.get`・`Outcome`・`format.format_no_game/format_error`
- Produces（`insider_bot.web.hub`）:
  - 定数 `TOPIC_MAX = 50`・`HINT_MAX = 300`・`QUESTION_MAX = 200`
  - `Connection`（Protocol。`enqueue(message: dict) -> None` を持つ）
  - `prepare_question(text: str) -> str`（空なら `""`）
  - `format_web_started(setter_name: str) -> str`
  - `RoomHub(registry, service, manager, clock=time.monotonic)`、メソッド `create_room() -> Room`・`cleanup() -> None`・`join(conn, code, name, token) -> tuple[Room, Player]`（`RoomNotFound`・`RoomFull`・`InvalidName` を投げる）・`leave(room, conn) -> None`・`async start(room, player, topic, hint) -> None`・`async giveup(room, player) -> None`・`ask(room, player, text, game_id) -> asyncio.Task[None]`
  - 積むメッセージの形: `{"type": "welcome", "token"}`・`{"type": "snapshot", "room": {...}, "log": [...]}`・`{"type": "room", "players", "game", "you"}`・`{"type": "entry", "entry": {...}}`・`{"type": "notice", "text"}`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_web_hub.py`:

```python
import asyncio
import json

import pytest

from insider_bot.game import GameManager
from insider_bot.judge import JudgeError, Verdict
from insider_bot.service import GameService
from insider_bot.web.hub import RoomHub, prepare_question
from insider_bot.web.rooms import InvalidName, RoomNotFound, RoomRegistry
from tests.fakes import FakeClock, FakeJudge

CORRECT = Verdict(1.0, True, "exact")
PENDING = "❓ 果物ですか？\n… 判定中"
ANSWER = "❓ 果物ですか？\n✅ はい　　はい 82% ██████████░░ いいえ 18%"
STARTED = "🎮 ゲーム開始！たろうさんがお題を出しました。「🎙 押して話す」で質問をどうぞ"


class FakeConnection:
    """積まれたメッセージを記録する接続。"""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def enqueue(self, message: dict) -> None:
        self.messages.append(message)

    def of(self, kind: str) -> list[dict]:
        return [message for message in self.messages if message["type"] == kind]

    def entries(self) -> list[dict]:
        return [message["entry"] for message in self.of("entry")]

    def notices(self) -> list[str]:
        return [message["text"] for message in self.of("notice")]

    def last_room(self) -> dict:
        return self.of("room")[-1]


class World:
    def __init__(self, judge: FakeJudge | None = None) -> None:
        self.clock = FakeClock()
        self.judge = judge or FakeJudge()
        self.manager = GameManager(clock=self.clock)
        service = GameService(self.manager, self.judge, clock=self.clock)
        registry = RoomRegistry(clock=self.clock, on_remove=lambda room: self.manager.end(room.room_id))
        self.hub = RoomHub(registry, service, self.manager, clock=self.clock)
        self.room = self.hub.create_room()

    def join(self, name: str, token: str | None = None):
        conn = FakeConnection()
        _, player = self.hub.join(conn, self.room.code, name, token)
        return conn, player

    def game_id(self) -> int:
        return self.manager.get(self.room.room_id).game_id


async def playing(judge: FakeJudge | None = None):
    """出題者「たろう」がお題「りんご」（補足「赤い果物」）で始め、回答者「はなこ」がいる状態。"""
    world = World(judge)
    setter = world.join("たろう")
    asker = world.join("はなこ")
    await world.hub.start(world.room, setter[1], "りんご", "赤い果物")
    return world, setter, asker


async def wait_until(predicate):
    while not predicate():
        await asyncio.sleep(0)


# --- 質問文の整形 ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("果物ですか", "果物ですか？"),
        (" 果物ですか。 ", "果物ですか？"),
        ("りんご?", "りんご？"),
        ("赤い？", "赤い？"),
        ("。", ""),
        ("？", ""),
        ("   ", ""),
    ],
)
def test_prepare_question(text, expected):
    assert prepare_question(text) == expected


# --- 入室・退室 ---


def test_join_enqueues_welcome_then_snapshot():
    world = World()
    conn, player = world.join("はなこ")
    assert conn.messages == [
        {"type": "welcome", "token": player.token},
        {
            "type": "snapshot",
            "room": {"players": [{"name": "はなこ", "online": True}], "game": None, "you": {"is_setter": False}},
            "log": [],
        },
    ]


def test_join_unknown_room_raises():
    world = World()
    with pytest.raises(RoomNotFound):
        world.hub.join(FakeConnection(), "ZZZZZZ", "はなこ", None)


def test_join_with_invalid_name_raises():
    with pytest.raises(InvalidName):
        World().join("")


def test_others_see_arrival_and_departure():
    world = World()
    first, _ = world.join("たろう")
    second, _ = world.join("はなこ")
    assert first.last_room()["players"] == [
        {"name": "たろう", "online": True},
        {"name": "はなこ", "online": True},
    ]
    assert second.of("room") == []
    world.hub.leave(world.room, second)
    assert first.last_room()["players"][1] == {"name": "はなこ", "online": False}


def test_closing_one_of_two_tabs_keeps_player_online():
    world = World()
    observer, _ = world.join("たろう")
    tab1, player = world.join("はなこ")
    world.join("はなこ", player.token)
    world.hub.leave(world.room, tab1)
    assert observer.last_room()["players"][1] == {"name": "はなこ", "online": True}


# --- お題を出す ---


async def test_start_notifies_setter_and_announces_to_everyone():
    world, (setter_conn, _), (asker_conn, _) = await playing()
    assert setter_conn.notices() == ["お題『りんご』を登録しました"]
    assert asker_conn.notices() == []
    for conn in (setter_conn, asker_conn):
        assert conn.entries() == [{"id": 1, "author": None, "text": STARTED, "pending": False}]
        assert conn.messages[-1]["type"] == "room"


async def test_topic_reaches_only_the_setter():
    world, (setter_conn, setter), (asker_conn, _) = await playing()
    late_conn, _ = world.join("じろう")
    assert setter_conn.last_room()["you"] == {"is_setter": True, "topic": "りんご", "hint": "赤い果物"}
    for conn in (asker_conn, late_conn):
        dumped = json.dumps(conn.messages, ensure_ascii=False)
        assert "りんご" not in dumped
        assert "赤い果物" not in dumped
    again_conn, _ = world.join("たろう", setter.token)
    assert again_conn.of("snapshot")[0]["room"]["you"] == {"is_setter": True, "topic": "りんご", "hint": "赤い果物"}


async def test_header_shows_setter_question_count_and_elapsed():
    world, _, (asker_conn, asker) = await playing()
    world.clock.advance(30)
    await world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    assert asker_conn.last_room()["game"] == {"id": 1, "setter": "たろう", "questions": 1, "elapsed": 30.0}


@pytest.mark.parametrize(
    ("topic", "hint", "notice"),
    [
        ("　", "", "お題は1〜50文字で入力してください"),
        ("あ" * 51, "", "お題は1〜50文字で入力してください"),
        ("りんご", "あ" * 301, "補足は300文字までです"),
    ],
)
async def test_start_rejects_invalid_lengths(topic, hint, notice):
    world = World()
    conn, player = world.join("たろう")
    await world.hub.start(world.room, player, topic, hint)
    assert conn.notices() == [notice]
    assert world.manager.get(world.room.room_id) is None


async def test_near_simultaneous_starts_keep_the_first():
    world = World()
    _, first = world.join("たろう")
    second_conn, second = world.join("はなこ")
    await asyncio.gather(
        world.hub.start(world.room, first, "りんご", ""),
        world.hub.start(world.room, second, "みかん", ""),
    )
    assert world.manager.get(world.room.room_id).topic == "りんご"
    assert second_conn.notices() == ["このルームではゲームが進行中です"]


# --- 質問 ---


async def test_question_shows_pending_then_answer_in_order():
    gate = asyncio.Event()
    world, (setter_conn, _), (asker_conn, asker) = await playing(FakeJudge(gate=gate))
    task = world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    await wait_until(lambda: world.judge.calls)
    assert setter_conn.entries()[-1] == {"id": 2, "author": "はなこ", "text": PENDING, "pending": True}
    gate.set()
    await task
    for conn in (setter_conn, asker_conn):
        assert conn.entries()[-2:] == [
            {"id": 2, "author": "はなこ", "text": PENDING, "pending": True},
            {"id": 2, "author": "はなこ", "text": ANSWER, "pending": False},
        ]
        assert conn.messages[-1]["type"] == "room"
    assert world.judge.calls == [("りんご", "赤い果物", "果物ですか？")]


@pytest.mark.parametrize(
    ("text", "notice"),
    [
        ("。", "質問を入力してください"),
        ("？", "質問を入力してください"),
        ("あ" * 201, "質問は200文字までです"),
    ],
)
async def test_question_rejected_before_judging(text, notice):
    world, _, (asker_conn, asker) = await playing()
    await world.hub.ask(world.room, asker, text, world.game_id())
    assert asker_conn.notices() == [notice]
    assert world.judge.calls == []


async def test_question_without_game_is_rejected():
    world = World()
    conn, player = world.join("はなこ")
    await world.hub.ask(world.room, player, "果物ですか", None)
    assert conn.notices() == ["進行中のゲームはありません"]
    assert conn.entries() == []


async def test_setter_cannot_ask():
    world, (setter_conn, setter), _ = await playing()
    await world.hub.ask(world.room, setter, "果物ですか", world.game_id())
    assert setter_conn.notices()[-1] == "出題者は質問できません"
    assert world.judge.calls == []


async def test_question_for_previous_game_is_rejected():
    world, (_, setter), (asker_conn, asker) = await playing()
    previous = world.game_id()
    await world.hub.giveup(world.room, setter)
    await world.hub.start(world.room, setter, "みかん", "")
    await world.hub.ask(world.room, asker, "果物ですか", previous)
    assert asker_conn.notices() == ["ゲームが変わったため、その質問は送りませんでした"]
    assert world.judge.calls == []


async def test_correct_answer_ends_game():
    world, (setter_conn, _), (_, asker) = await playing(FakeJudge(answers={"りんご？": CORRECT}))
    await world.hub.ask(world.room, asker, "りんご", world.game_id())
    assert setter_conn.entries()[-1]["text"] == (
        "🎉 正解です！お題は「りんご」でした\n正解者: はなこ　質問数: 1　経過時間: 0秒"
    )
    assert setter_conn.last_room()["game"] is None
    assert world.manager.get(world.room.room_id) is None


async def test_queued_question_is_cancelled_when_earlier_one_is_correct():
    gate = asyncio.Event()
    world, (setter_conn, _), (_, asker) = await playing(FakeJudge(default=CORRECT, gate=gate))
    first = world.hub.ask(world.room, asker, "りんご", world.game_id())
    await wait_until(lambda: world.judge.calls)
    second = world.hub.ask(world.room, asker, "みかん", world.game_id())
    await wait_until(lambda: sum(entry["pending"] for entry in setter_conn.entries()) == 2)
    gate.set()
    await asyncio.gather(first, second)
    finished = [entry["text"] for entry in setter_conn.entries() if not entry["pending"]]
    assert finished[-2].startswith("🎉 正解です！")
    assert finished[-1] == "❓ みかん？\n— ゲームが終わったため取り消しました"


async def test_giveup_during_judging_comes_after_the_answer():
    gate = asyncio.Event()
    world, (setter_conn, setter), (_, asker) = await playing(FakeJudge(gate=gate))
    question = world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    await wait_until(lambda: world.judge.calls)
    giveup = asyncio.create_task(world.hub.giveup(world.room, setter))
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(question, giveup)
    finished = [entry["text"] for entry in setter_conn.entries() if not entry["pending"]]
    assert finished[-2:] == [ANSWER, "🏳️ ギブアップ！お題は『りんご』でした（質問数: 1）"]


async def test_judge_failure_replaces_pending_with_error():
    world, (setter_conn, _), (_, asker) = await playing(FakeJudge(error=JudgeError("timeout")))
    await world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    assert setter_conn.entries()[-1] == {
        "id": 2,
        "author": "はなこ",
        "text": "⚠️ 判定できませんでした。もう一度どうぞ",
        "pending": False,
    }


async def test_unexpected_error_does_not_leave_pending_entry():
    world, (setter_conn, _), (_, asker) = await playing(FakeJudge(error=RuntimeError("想定外")))
    await world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    assert setter_conn.entries()[-1]["text"] == "⚠️ 判定できませんでした。もう一度どうぞ"
    assert setter_conn.entries()[-1]["pending"] is False


async def test_result_is_kept_when_asker_leaves_during_judging():
    gate = asyncio.Event()
    world, (setter_conn, _), (asker_conn, asker) = await playing(FakeJudge(gate=gate))
    task = world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    await wait_until(lambda: world.judge.calls)
    world.hub.leave(world.room, asker_conn)
    sent_before = len(asker_conn.messages)
    gate.set()
    await task
    assert setter_conn.entries()[-1]["text"] == ANSWER
    assert world.room.log[-1].text == ANSWER
    assert len(asker_conn.messages) == sent_before


# --- ギブアップ・通知 ---


async def test_answerer_can_give_up():
    world, (setter_conn, _), (_, asker) = await playing()
    await world.hub.giveup(world.room, asker)
    assert setter_conn.entries()[-1] == {
        "id": 2,
        "author": "はなこ",
        "text": "🏳️ ギブアップ！お題は『りんご』でした（質問数: 0）",
        "pending": False,
    }
    assert setter_conn.last_room()["game"] is None


async def test_giveup_without_game_notifies_only_that_player():
    world = World()
    conn, player = world.join("はなこ")
    other, _ = world.join("じろう")
    await world.hub.giveup(world.room, player)
    assert conn.notices() == ["進行中のゲームはありません"]
    assert other.notices() == []
    assert conn.entries() == []


async def test_notice_reaches_every_tab_of_that_player_only():
    world = World()
    tab1, setter = world.join("たろう")
    tab2, _ = world.join("たろう", setter.token)
    other, _ = world.join("はなこ")
    await world.hub.start(world.room, setter, "りんご", "")
    assert tab1.notices() == tab2.notices() == ["お題『りんご』を登録しました"]
    assert other.notices() == []
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_web_hub.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'insider_bot.web.hub'`）

- [ ] **Step 3: 実装する**

`src/insider_bot/web/hub.py`:

```python
"""Web 版の進行役。接続から届いた操作を検査して GameService に渡し、結果を接続の送信待ちの列に積む。

送信は列に積むだけで待たず、状態を変えてから積むまでの間に await を挟まない。
asyncio は 1 スレッドなので、こうすると状態を変えた順と画面に届く順が一致する。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol

from insider_bot import format as fmt
from insider_bot.game import Clock, GameManager
from insider_bot.service import GameService, Outcome
from insider_bot.web.rooms import Entry, Player, Room, RoomNotFound, RoomRegistry

log = logging.getLogger(__name__)

TOPIC_MAX = 50
HINT_MAX = 300
QUESTION_MAX = 200
# 音声認識が付けがちな句点や、手で打った「？」をいったん外してから「？」を付け直す
_TRAILING_MARKS = "。．.、？?"


class Connection(Protocol):
    def enqueue(self, message: dict[str, Any]) -> None: ...


def prepare_question(text: str) -> str:
    """押して話す・質問用の入力欄から来た文字を「？」で終わる質問にそろえる。中身がなければ空文字。"""
    text = text.strip().rstrip(_TRAILING_MARKS).rstrip()
    return f"{text}？" if text else ""


def format_web_started(setter_name: str) -> str:
    # Discord 用の「最後に「？」をつけてね」は、「？」を自動で付ける Web では声で「はてな」と言わせかねない
    return f"🎮 ゲーム開始！{setter_name}さんがお題を出しました。「🎙 押して話す」で質問をどうぞ"


class RoomHub:
    def __init__(
        self,
        registry: RoomRegistry,
        service: GameService,
        manager: GameManager,
        clock: Clock = time.monotonic,
    ) -> None:
        self._registry = registry
        self._service = service
        self._manager = manager
        self._clock = clock
        # 判定中のタスクが途中で回収されないよう、終わるまで参照を持つ
        self._tasks: set[asyncio.Task[None]] = set()

    def create_room(self) -> Room:
        return self._registry.create()

    def cleanup(self) -> None:
        self._registry.cleanup()

    def join(self, conn: Connection, code: str, name: str, token: str | None) -> tuple[Room, Player]:
        """接続の登録と snapshot の積み込みを待たずに行い、前後の更新を取りこぼさない。"""
        room = self._registry.get(code)
        if room is None:
            raise RoomNotFound(code)
        player = self._registry.join(room, token, name)
        self._registry.attach(room, conn, player)
        conn.enqueue({"type": "welcome", "token": player.token})
        conn.enqueue(
            {
                "type": "snapshot",
                "room": self._room_state(room, player),
                "log": [entry.to_message() for entry in room.log],
            }
        )
        self._broadcast_room(room, skip=conn)
        return room, player

    def leave(self, room: Room, conn: Connection) -> None:
        self._registry.detach(room, conn)
        self._broadcast_room(room)

    async def start(self, room: Room, player: Player, topic: str, hint: str) -> None:
        topic, hint = topic.strip(), hint.strip()
        if not 1 <= len(topic) <= TOPIC_MAX:
            self._notify(room, player, f"お題は1〜{TOPIC_MAX}文字で入力してください")
            return
        if len(hint) > HINT_MAX:
            self._notify(room, player, f"補足は{HINT_MAX}文字までです")
            return
        if self._manager.get(room.room_id) is not None:
            self._notify(room, player, "このルームではゲームが進行中です")
            return
        outcome = await self._service.start(room.room_id, player.player_id, player.name, topic, hint)
        if outcome.public is not None:
            outcome = Outcome(private=outcome.private, public=format_web_started(player.name))
        self._apply(room, player, outcome, author=None)

    async def giveup(self, room: Room, player: Player) -> None:
        outcome = await self._service.giveup(room.room_id)
        self._apply(room, player, outcome, author=player.name)

    def ask(self, room: Room, player: Player, text: str, game_id: object) -> asyncio.Task[None]:
        """判定は接続の受信ループから切り離して動かす。質問者のタブが閉じても結果は履歴に残る。"""
        task = asyncio.create_task(self._ask(room, player, text, game_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _ask(self, room: Room, player: Player, text: str, game_id: object) -> None:
        # handle_question が対象のゲームを控えるまで await を挟まない。確かめたゲームと判定するゲームを一致させるため
        if len(text.strip()) > QUESTION_MAX:
            self._notify(room, player, f"質問は{QUESTION_MAX}文字までです")
            return
        question = prepare_question(text)
        if not question:
            self._notify(room, player, "質問を入力してください")
            return
        game = self._manager.get(room.room_id)
        if game is None:
            self._notify(room, player, fmt.format_no_game())
            return
        if game.setter_id == player.player_id:
            self._notify(room, player, "出題者は質問できません")
            return
        if game_id != game.game_id:
            # 押している間に次のゲームが始まっていた。前のゲームへの質問を新しいお題で判定しない
            self._notify(room, player, "ゲームが変わったため、その質問は送りませんでした")
            return
        entry = room.add_entry(player.name, f"❓ {question}\n… 判定中", pending=True)
        self._broadcast_entry(room, entry)
        try:
            outcome = await self._service.handle_question(room.room_id, player.player_id, player.name, question)
        except Exception:
            log.exception("質問の処理に失敗しました（room=%s）", room.code)
            outcome = Outcome(public=fmt.format_error())
        entry.pending = False
        if outcome.public is not None:
            entry.text = outcome.public
        else:
            # 判定の順番待ちの間に、先の質問の正解やギブアップでゲームが終わった
            entry.text = f"❓ {question}\n— ゲームが終わったため取り消しました"
        self._broadcast_entry(room, entry)
        self._broadcast_room(room)

    def _apply(self, room: Room, player: Player, outcome: Outcome, author: str | None) -> None:
        if outcome.private is not None:
            self._notify(room, player, outcome.private)
        if outcome.public is not None:
            self._broadcast_entry(room, room.add_entry(author, outcome.public))
        self._broadcast_room(room)

    def _room_state(self, room: Room, player: Player) -> dict[str, Any]:
        game = self._manager.get(room.room_id)
        header = None
        you: dict[str, Any] = {"is_setter": False}
        if game is not None:
            header = {
                "id": game.game_id,
                "setter": game.setter_name,
                "questions": game.question_count,
                "elapsed": round(self._clock() - game.started_at, 1),
            }
            if game.setter_id == player.player_id:
                # お題と補足は出題者の接続にだけ入れる
                you = {"is_setter": True, "topic": game.topic, "hint": game.hint}
        players = [{"name": p.name, "online": room.is_online(p)} for p in room.players.values()]
        return {"players": players, "game": header, "you": you}

    def _broadcast_room(self, room: Room, skip: Connection | None = None) -> None:
        for conn, player in list(room.connections.items()):
            if conn is not skip:
                conn.enqueue({"type": "room", **self._room_state(room, player)})

    def _broadcast_entry(self, room: Room, entry: Entry) -> None:
        message = {"type": "entry", "entry": entry.to_message()}
        for conn in list(room.connections):
            conn.enqueue(message)

    def _notify(self, room: Room, player: Player, text: str) -> None:
        for conn, owner in list(room.connections.items()):
            if owner is player:
                conn.enqueue({"type": "notice", "text": text})
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run pytest tests/test_web_hub.py -v`
Expected: PASS（すべて）。`test_unexpected_error_does_not_leave_pending_entry` は意図した例外のログを出す

- [ ] **Step 5: 全テストを流す**

Run: `uv run pytest -q`
Expected: すべて PASS

- [ ] **Step 6: コミット**

```bash
git add src/insider_bot/web/hub.py tests/test_web_hub.py
git commit -m "$(cat <<'EOF'
feat: Web版の進行役RoomHubを追加

送信は接続ごとの列に積むだけにし、状態を変えた順に画面へ届くようにする。
質問は画面が見ているゲームのIDで照合し、判定は接続から切り離して動かす。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: aiohttp のサーバーと起動（server.py・__main__.py）

**Files:**
- Create: `src/insider_bot/web/server.py`
- Create: `src/insider_bot/web/__main__.py`
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: Task 1 の `load_web_config`・`WebConfig`、Task 2 の例外、Task 3 の `RoomHub`、既存の `create_jev_client`・`JevJudge`・`GameService`・`GameManager`
- Produces（`insider_bot.web.server`）:
  - 定数 `STATIC_DIR`・`SEND_QUEUE_LIMIT = 100`・`CLOSE_BAD_REQUEST = 4400`・`CLOSE_NOT_FOUND = 4404`・`CLOSE_FULL = 4409`
  - `WsConnection(ws, queue_limit=SEND_QUEUE_LIMIT)`: `enqueue(message) -> None`・`async aclose() -> None`・属性 `closed: bool`
  - `create_app(hub: RoomHub, static_dir: Path = STATIC_DIR, cleanup_interval: float = 600.0) -> web.Application`
  - HTTP: `GET /`・`GET /r/{code}`（index.html）・`GET /static/...`・`POST /api/rooms`（201 `{"code"}` / 503 `{"error"}`）・`GET /r/{code}/ws`
- Produces（`insider_bot.web.__main__`）: `async make_app(config: WebConfig) -> web.Application`・`main() -> None`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_web_server.py`:

```python
import asyncio
import contextlib
import re

import pytest
from aiohttp import WSCloseCode, WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from insider_bot.game import GameManager
from insider_bot.service import GameService
from insider_bot.web.hub import RoomHub
from insider_bot.web.rooms import CODE_ALPHABET, RoomRegistry
from insider_bot.web.server import WsConnection, create_app
from tests.fakes import FakeClock, FakeJudge


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>テスト</title>", encoding="utf-8")
    (tmp_path / "app.js").write_text("// app", encoding="utf-8")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "lib-1.0.0.js").write_text("// lib", encoding="utf-8")
    return tmp_path


@contextlib.asynccontextmanager
async def serve(static_dir, judge=None, **limits):
    clock = FakeClock()
    manager = GameManager(clock=clock)
    service = GameService(manager, judge or FakeJudge(), clock=clock)
    registry = RoomRegistry(clock=clock, on_remove=lambda room: manager.end(room.room_id), **limits)
    hub = RoomHub(registry, service, manager, clock=clock)
    async with TestClient(TestServer(create_app(hub, static_dir=static_dir))) as client:
        yield client


async def create_room(client) -> str:
    response = await client.post("/api/rooms")
    assert response.status == 201
    return (await response.json())["code"]


async def join(client, code, name, token=None):
    ws = await client.ws_connect(f"/r/{code}/ws")
    await ws.send_json({"type": "join", "name": name, "token": token})
    welcome = await ws.receive_json()
    snapshot = await ws.receive_json()
    assert (welcome["type"], snapshot["type"]) == ("welcome", "snapshot")
    return ws, welcome["token"], snapshot


async def receive_until(ws, predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while True:
            message = await ws.receive_json()
            if predicate(message):
                return message


def is_entry(text, pending=False):
    return lambda m: m["type"] == "entry" and text in m["entry"]["text"] and m["entry"]["pending"] is pending


async def start_game(setter, asker, topic="りんご", hint="赤い果物"):
    await setter.send_json({"type": "start", "topic": topic, "hint": hint})
    room = await receive_until(asker, lambda m: m["type"] == "room" and m["game"] is not None)
    return room["game"]["id"]


async def wait_until(predicate):
    while not predicate():
        await asyncio.sleep(0)


# --- HTTP ---


async def test_index_is_served_for_top_and_room_paths_without_caching(static_dir):
    async with serve(static_dir) as client:
        for path in ("/", "/r/K7Q2MX"):
            response = await client.get(path)
            assert response.status == 200
            assert "テスト" in await response.text()
            assert response.headers["Cache-Control"] == "no-cache"


async def test_vendor_files_are_cached_but_app_files_are_revalidated(static_dir):
    async with serve(static_dir) as client:
        vendor = await client.get("/static/vendor/lib-1.0.0.js")
        app = await client.get("/static/app.js")
        assert vendor.headers["Cache-Control"] == "public, max-age=604800"
        assert app.headers["Cache-Control"] == "no-cache"


async def test_create_room_returns_code(static_dir):
    async with serve(static_dir) as client:
        assert re.fullmatch(f"[{CODE_ALPHABET}]{{6}}", await create_room(client))


async def test_create_room_returns_503_when_every_room_is_in_use(static_dir):
    async with serve(static_dir, max_rooms=1) as client:
        code = await create_room(client)
        await join(client, code, "はなこ")
        response = await client.post("/api/rooms")
        assert response.status == 503
        assert (await response.json())["error"] == "今はルームを作れません。しばらくしてからどうぞ"


# --- WebSocket ---


async def test_question_reaches_every_player(static_dir):
    async with serve(static_dir) as client:
        code = await create_room(client)
        setter, _, _ = await join(client, code, "たろう")
        asker, _, _ = await join(client, code, "はなこ")
        game_id = await start_game(setter, asker)
        await asker.send_json({"type": "ask", "text": "果物ですか", "game_id": game_id})
        for ws in (setter, asker):
            message = await receive_until(ws, is_entry("果物ですか？"))
            assert "はい 82%" in message["entry"]["text"]


async def test_reconnect_with_token_restores_setter_and_history(static_dir):
    async with serve(static_dir) as client:
        code = await create_room(client)
        setter, token, _ = await join(client, code, "たろう")
        asker, _, _ = await join(client, code, "はなこ")
        await start_game(setter, asker)
        await setter.close()
        _, again_token, snapshot = await join(client, code, "たろう", token)
        assert again_token == token
        assert snapshot["room"]["you"] == {"is_setter": True, "topic": "りんご", "hint": "赤い果物"}
        assert any("ゲーム開始" in entry["text"] for entry in snapshot["log"])


async def test_reconnect_during_judging_gets_pending_entry_then_result(static_dir):
    gate = asyncio.Event()
    async with serve(static_dir, judge=FakeJudge(gate=gate)) as client:
        code = await create_room(client)
        setter, _, _ = await join(client, code, "たろう")
        asker, _, _ = await join(client, code, "はなこ")
        game_id = await start_game(setter, asker)
        await asker.send_json({"type": "ask", "text": "果物ですか", "game_id": game_id})
        await receive_until(asker, is_entry("果物ですか？", pending=True))
        late, _, snapshot = await join(client, code, "じろう")
        assert [entry["pending"] for entry in snapshot["log"] if "果物ですか" in entry["text"]] == [True]
        gate.set()
        await receive_until(late, is_entry("果物ですか？"))


async def test_unknown_room_is_closed_with_4404(static_dir):
    async with serve(static_dir) as client:
        ws = await client.ws_connect("/r/ZZZZZZ/ws")
        await ws.send_json({"type": "join", "name": "はなこ", "token": None})
        message = await ws.receive()
        assert (message.type, message.data) == (WSMsgType.CLOSE, 4404)


@pytest.mark.parametrize(
    "first",
    [
        '{"type": "ask", "text": "果物ですか"}',
        "join",
        '{"type": "join", "name": 5}',
        '{"type": "join", "name": ""}',
    ],
)
async def test_bad_first_message_is_closed_with_4400(static_dir, first):
    async with serve(static_dir) as client:
        code = await create_room(client)
        ws = await client.ws_connect(f"/r/{code}/ws")
        await ws.send_str(first)
        message = await ws.receive()
        assert (message.type, message.data) == (WSMsgType.CLOSE, 4400)


async def test_full_room_turns_away_new_players_but_not_returning_ones(static_dir):
    async with serve(static_dir, max_players=1) as client:
        code = await create_room(client)
        first, token, _ = await join(client, code, "たろう")
        await first.close()
        newcomer = await client.ws_connect(f"/r/{code}/ws")
        await newcomer.send_json({"type": "join", "name": "はなこ", "token": None})
        message = await newcomer.receive()
        assert (message.type, message.data) == (WSMsgType.CLOSE, 4409)
        _, again_token, _ = await join(client, code, "たろう", token)
        assert again_token == token


async def test_malformed_messages_are_ignored(static_dir):
    async with serve(static_dir) as client:
        code = await create_room(client)
        setter, _, _ = await join(client, code, "たろう")
        for junk in ("not json", "[1, 2]", '{"type": "ask", "text": 5}', '{"type": "start"}', '{"type": "dance"}'):
            await setter.send_str(junk)
        await setter.send_json({"type": "start", "topic": "りんご", "hint": ""})
        notice = await receive_until(setter, lambda m: m["type"] == "notice")
        assert notice["text"] == "お題『りんご』を登録しました"


# --- WsConnection（送信待ちの列） ---


class FakeWs:
    def __init__(self, fail: bool = False, gate: asyncio.Event | None = None) -> None:
        self.sent: list[dict] = []
        self.fail = fail
        self.gate = gate
        self.close_code: int | None = None

    async def send_json(self, message: dict) -> None:
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise ConnectionResetError("切断済み")
        self.sent.append(message)

    async def close(self, *, code: int = 1000, message: bytes = b"") -> bool:
        self.close_code = code
        return True


async def test_connection_sends_in_enqueued_order():
    ws = FakeWs()
    conn = WsConnection(ws)
    for n in range(3):
        conn.enqueue({"n": n})
    await wait_until(lambda: len(ws.sent) == 3)
    assert ws.sent == [{"n": 0}, {"n": 1}, {"n": 2}]
    await conn.aclose()


async def test_send_failure_closes_only_that_connection():
    bad_ws, good_ws = FakeWs(fail=True), FakeWs()
    bad, good = WsConnection(bad_ws), WsConnection(good_ws)
    for conn in (bad, good):
        conn.enqueue({"type": "notice", "text": "x"})
    await wait_until(lambda: bad_ws.close_code is not None and good_ws.sent)
    assert bad.closed
    assert not good.closed
    for conn in (bad, good):
        await conn.aclose()


async def test_backlog_over_limit_closes_connection():
    ws = FakeWs(gate=asyncio.Event())
    conn = WsConnection(ws, queue_limit=3)
    for n in range(5):
        conn.enqueue({"n": n})
    await wait_until(lambda: ws.close_code is not None)
    assert conn.closed
    assert ws.close_code == WSCloseCode.TRY_AGAIN_LATER
    await conn.aclose()
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_web_server.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'insider_bot.web.server'`）

- [ ] **Step 3: server.py を実装する**

`src/insider_bot/web/server.py`:

```python
"""aiohttp のアプリ。HTTP の配信と WebSocket の受信ループだけを持ち、判断は RoomHub に任せる。"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from aiohttp import WSCloseCode, WSMsgType, web

from insider_bot.web.hub import RoomHub
from insider_bot.web.rooms import InvalidName, Player, Room, RoomFull, RoomLimitReached, RoomNotFound

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
SEND_QUEUE_LIMIT = 100
CLEANUP_INTERVAL_SECONDS = 600.0
JOIN_TIMEOUT_SECONDS = 10.0
HEARTBEAT_SECONDS = 30.0
MAX_MESSAGE_BYTES = 4096
VENDOR_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

CLOSE_BAD_REQUEST = 4400
CLOSE_NOT_FOUND = 4404
CLOSE_FULL = 4409
# ブラウザは接続に失敗したときの HTTP ステータスを読めないので、接続を受けてから独自のコードで閉じる
_JOIN_ERRORS: dict[type[Exception], tuple[int, bytes]] = {
    RoomNotFound: (CLOSE_NOT_FOUND, b"room not found"),
    RoomFull: (CLOSE_FULL, b"room full"),
    InvalidName: (CLOSE_BAD_REQUEST, b"invalid name"),
}

HUB = web.AppKey("hub", RoomHub)
STATIC = web.AppKey("static_dir", Path)
SOCKETS = web.AppKey("sockets", weakref.WeakSet)


class WsConnection:
    """接続ごとの送信待ちの列。enqueue は積むだけで待たず、送信は専用のタスクが積んだ順に行う。"""

    def __init__(self, ws: Any, queue_limit: int = SEND_QUEUE_LIMIT) -> None:
        self._ws = ws
        self._limit = queue_limit
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._closer: asyncio.Task[Any] | None = None
        self.closed = False
        self._sender = asyncio.create_task(self._send_loop())

    def enqueue(self, message: dict[str, Any]) -> None:
        if self.closed:
            return
        if self._queue.qsize() >= self._limit:
            # 受け取りが極端に遅い。閉じれば画面は再接続して snapshot で追いつく
            log.warning("送信待ちが %d 件たまったため接続を閉じます", self._limit)
            self.closed = True
            self._sender.cancel()
            self._closer = asyncio.create_task(self._ws.close(code=WSCloseCode.TRY_AGAIN_LATER))
            return
        self._queue.put_nowait(message)

    async def aclose(self) -> None:
        """受信ループが終わったときに呼ぶ。送信タスクを止める。"""
        self.closed = True
        self._sender.cancel()
        pending = [self._sender] + ([self._closer] if self._closer is not None else [])
        await asyncio.gather(*pending, return_exceptions=True)

    async def _send_loop(self) -> None:
        try:
            while True:
                await self._ws.send_json(await self._queue.get())
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # 送信の失敗はこの接続だけの問題にする。ほかの接続への配信は続く
            log.info("送信に失敗したため接続を閉じます: %s", error)
            self.closed = True
            await self._ws.close()


def _parse(data: str) -> dict[str, Any] | None:
    try:
        message = json.loads(data)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


async def _read_join(ws: web.WebSocketResponse) -> dict[str, Any] | None:
    try:
        first = await ws.receive(timeout=JOIN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return None
    if first.type != WSMsgType.TEXT:
        return None
    message = _parse(first.data)
    if message is None or message.get("type") != "join":
        return None
    token = message.get("token")
    if not isinstance(message.get("name"), str) or not (token is None or isinstance(token, str)):
        return None
    return message


async def _dispatch(hub: RoomHub, room: Room, player: Player, message: dict[str, Any] | None) -> None:
    if message is None:
        return
    kind = message.get("type")
    if kind == "ask":
        text = message.get("text")
        if isinstance(text, str):
            hub.ask(room, player, text, message.get("game_id"))
    elif kind == "start":
        topic, hint = message.get("topic"), message.get("hint", "")
        if isinstance(topic, str) and isinstance(hint, str):
            await hub.start(room, player, topic, hint)
    elif kind == "giveup":
        await hub.giveup(room, player)


async def websocket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=HEARTBEAT_SECONDS, max_msg_size=MAX_MESSAGE_BYTES)
    await ws.prepare(request)
    request.app[SOCKETS].add(ws)
    join = await _read_join(ws)
    if join is None:
        await ws.close(code=CLOSE_BAD_REQUEST, message=b"join required")
        return ws

    hub = request.app[HUB]
    conn = WsConnection(ws)
    try:
        room, player = hub.join(conn, request.match_info["code"], join["name"], join.get("token"))
    except (RoomNotFound, RoomFull, InvalidName) as error:
        await conn.aclose()
        code, reason = _JOIN_ERRORS[type(error)]
        await ws.close(code=code, message=reason)
        return ws

    try:
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                await _dispatch(hub, room, player, _parse(message.data))
    finally:
        hub.leave(room, conn)
        await conn.aclose()
    return ws


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(request.app[STATIC] / "index.html")


async def create_room(request: web.Request) -> web.Response:
    try:
        room = request.app[HUB].create_room()
    except RoomLimitReached:
        return web.json_response({"error": "今はルームを作れません。しばらくしてからどうぞ"}, status=503)
    return web.json_response({"code": room.code}, status=201)


async def _cache_headers(request: web.Request, response: web.StreamResponse) -> None:
    path = request.path
    if path.startswith("/static/vendor/"):
        # 版番号付きのファイル名なので、中身が変わることはない
        response.headers["Cache-Control"] = f"public, max-age={VENDOR_MAX_AGE_SECONDS}"
    elif path == "/" or (path.startswith(("/static/", "/r/")) and not path.endswith("/ws")):
        # 更新を git pull で配るので毎回確かめる（変わっていなければ 304）
        response.headers["Cache-Control"] = "no-cache"


async def _cleanup_loop(hub: RoomHub, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        hub.cleanup()


def create_app(
    hub: RoomHub,
    static_dir: Path = STATIC_DIR,
    cleanup_interval: float = CLEANUP_INTERVAL_SECONDS,
) -> web.Application:
    app = web.Application()
    app[HUB] = hub
    app[STATIC] = static_dir
    app[SOCKETS] = weakref.WeakSet()
    app.router.add_get("/", index)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_get("/r/{code}", index)
    app.router.add_get("/r/{code}/ws", websocket)
    app.router.add_static("/static/", static_dir)
    app.on_response_prepare.append(_cache_headers)

    async def run_cleanup(app: web.Application) -> AsyncIterator[None]:
        task = asyncio.create_task(_cleanup_loop(hub, cleanup_interval))
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def close_sockets(app: web.Application) -> None:
        for ws in list(app[SOCKETS]):
            await ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown")

    app.cleanup_ctx.append(run_cleanup)
    app.on_shutdown.append(close_sockets)
    return app
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run pytest tests/test_web_server.py -v`
Expected: PASS（すべて）

- [ ] **Step 5: 起動処理を書く**

`src/insider_bot/web/__main__.py`:

```python
"""起動: uv run --env-file .env python -m insider_bot.web"""

from __future__ import annotations

import logging
import sys

from aiohttp import web

from insider_bot.config import ConfigError, WebConfig, load_web_config
from insider_bot.game import GameManager
from insider_bot.judge import JevJudge, create_jev_client
from insider_bot.service import GameService
from insider_bot.web.hub import RoomHub
from insider_bot.web.rooms import RoomRegistry
from insider_bot.web.server import create_app


async def make_app(config: WebConfig) -> web.Application:
    client = create_jev_client(config.typesafe_api_key, config.jev_timeout_seconds)
    manager = GameManager()
    service = GameService(manager, JevJudge(client, config.correct_threshold, config.jev_timeout_seconds))
    registry = RoomRegistry(on_remove=lambda room: manager.end(room.room_id))
    app = create_app(RoomHub(registry, service, manager))

    async def close_client(_app: web.Application) -> None:
        await client.aclose()

    app.on_cleanup.append(close_client)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_web_config()
    except ConfigError as error:
        print(f"設定エラー: {error}", file=sys.stderr)
        sys.exit(1)
    web.run_app(make_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 起動処理が読み込めることを確かめる**

Run: `uv run python -c "import insider_bot.web.__main__ as m; print(m.make_app, m.main)"`
Expected: 2 つの関数が表示される（エラーなし）。実際の起動は Task 7 で画面ができてから行う（`static/` がまだないため）

- [ ] **Step 7: 全テストを流す**

Run: `uv run pytest -q`
Expected: すべて PASS

- [ ] **Step 8: コミット**

```bash
git add src/insider_bot/web/server.py src/insider_bot/web/__main__.py tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat: Web版のaiohttpサーバーと起動処理を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: ルーム URL の判定と QR（roomurl.js・vendor・qr.js）

**Files:**
- Create: `src/insider_bot/web/static/roomurl.js`
- Create: `tests/js/roomurl.test.mjs`
- Create: `src/insider_bot/web/static/vendor/qrcode-generator-1.4.4.js`・`jsQR-1.4.0.js`・`LICENSES.md`
- Create: `src/insider_bot/web/static/qr.js`

**Interfaces:**
- Consumes: なし（ブラウザの `window.qrcode`・`window.jsQR` は vendor のスクリプトが定義する）
- Produces:
  - `roomurl.js`: `ROOM_CODE_PATTERN: RegExp`・`parseRoomCode(text: string, origin: string) -> string | null`
  - `qr.js`: `async renderQr(canvas: HTMLCanvasElement, text: string) -> void`・`class Scanner(dialog, video, message, onRoom: (code) => void)` と `open()`・`close()`

- [ ] **Step 1: 失敗するテストを書く**

`tests/js/roomurl.test.mjs`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";

import { parseRoomCode } from "../../src/insider_bot/web/static/roomurl.js";

const ORIGIN = "https://insider-bot.example.ts.net";

test("同じオリジンのルーム URL からルーム番号を取り出す", () => {
  assert.equal(parseRoomCode(`${ORIGIN}/r/K7Q2MX`, ORIGIN), "K7Q2MX");
});

test("末尾の / とクエリ・ハッシュは無視する", () => {
  assert.equal(parseRoomCode(`${ORIGIN}/r/K7Q2MX/`, ORIGIN), "K7Q2MX");
  assert.equal(parseRoomCode(`${ORIGIN}/r/K7Q2MX?invite=1#x`, ORIGIN), "K7Q2MX");
});

test("別のオリジンは拒む", () => {
  assert.equal(parseRoomCode("https://evil.example/r/K7Q2MX", ORIGIN), null);
  assert.equal(parseRoomCode("http://insider-bot.example.ts.net/r/K7Q2MX", ORIGIN), null);
});

test("ルーム以外のパスは拒む", () => {
  for (const path of ["/r/K7Q2MX/ws", "/x/K7Q2MX", "/r/", "/", "/r/K7Q2MX/extra"]) {
    assert.equal(parseRoomCode(`${ORIGIN}${path}`, ORIGIN), null, path);
  }
});

test("ルーム番号の文字種や長さが違うものは拒む", () => {
  for (const code of ["k7q2mx", "K7Q2M0", "K7Q2MI", "K7Q2M", "K7Q2MXA"]) {
    assert.equal(parseRoomCode(`${ORIGIN}/r/${code}`, ORIGIN), null, code);
  }
});

test("URL でない文字列は拒む", () => {
  for (const text of ["K7Q2MX", "", "javascript:alert(1)", "りんご"]) {
    assert.equal(parseRoomCode(text, ORIGIN), null, text);
  }
});
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `node --test tests/js/roomurl.test.mjs`
Expected: FAIL（`Cannot find module …/roomurl.js`）

- [ ] **Step 3: roomurl.js を実装する**

`src/insider_bot/web/static/roomurl.js`:

```js
// 読み取った QR の文字列が、このサイトのルーム URL かを判定する
export const ROOM_CODE_PATTERN = /^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{6}$/;

/** このサイト（origin）の /r/<ルーム番号> ならルーム番号を、それ以外は null を返す。 */
export function parseRoomCode(text, origin) {
  let url;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  // 読み取った見知らぬ URL へは移動しない
  if (url.origin !== origin) return null;
  const match = /^\/r\/([^/]+)\/?$/.exec(url.pathname);
  if (!match || !ROOM_CODE_PATTERN.test(match[1])) return null;
  return match[1];
}
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `node --test tests/js/roomurl.test.mjs`
Expected: `pass 6`・`fail 0`

- [ ] **Step 5: ライブラリのダウンロードについてユーザーの許可を取る**

ファイルのダウンロードには明示的な許可が要る。次の内容をユーザーに示し、「はい」をもらってから Step 6 に進む:

- `jsqr-1.4.0.tgz`（https://registry.npmjs.org/jsqr/-/jsqr-1.4.0.tgz 、展開後 約 280KB、Apache-2.0）
- `qrcode-generator-1.4.4.tgz`（https://registry.npmjs.org/qrcode-generator/-/qrcode-generator-1.4.4.tgz 、展開後 約 117KB、MIT）
- どちらも `npm pack` で取得し、npm がレジストリの整合性ハッシュで検証する。リポジトリに入れるのは `dist/jsQR.js` と `qrcode.js` の 2 ファイルとライセンス文だけ

- [ ] **Step 6: ライブラリを取得して同梱する**

```bash
SCRATCH="$(mktemp -d)"
VENDOR=src/insider_bot/web/static/vendor
npm pack jsqr@1.4.0 qrcode-generator@1.4.4 --pack-destination "$SCRATCH"
mkdir -p "$SCRATCH/jsqr" "$SCRATCH/qrcode" "$VENDOR"
tar -xzf "$SCRATCH/jsqr-1.4.0.tgz" -C "$SCRATCH/jsqr" --strip-components=1
tar -xzf "$SCRATCH/qrcode-generator-1.4.4.tgz" -C "$SCRATCH/qrcode" --strip-components=1
cp "$SCRATCH/jsqr/dist/jsQR.js" "$VENDOR/jsQR-1.4.0.js"
cp "$SCRATCH/qrcode/qrcode.js" "$VENDOR/qrcode-generator-1.4.4.js"
{
  echo "# 同梱しているライブラリ"
  echo
  echo "- jsQR 1.4.0（Apache-2.0）: https://github.com/cozmo/jsQR — QR の読み取り（jsQR-1.4.0.js）"
  echo "- qrcode-generator 1.4.4（MIT）: https://github.com/kazuhikoarase/qrcode-generator — QR の生成（qrcode-generator-1.4.4.js）"
  for f in "$SCRATCH"/jsqr/LICENSE* "$SCRATCH"/qrcode/LICENSE*; do
    [ -f "$f" ] || continue
    echo
    echo "## $(basename "$(dirname "$f")")/$(basename "$f")"
    echo
    cat "$f"
  done
} > "$VENDOR/LICENSES.md"
ls -la "$VENDOR"
```

Expected: `jsQR-1.4.0.js`・`qrcode-generator-1.4.4.js`・`LICENSES.md` の 3 ファイル

- [ ] **Step 7: 2 つのライブラリがブラウザでグローバル関数を定義する作りか確かめる**

Run: `grep -c 'root\["jsQR"\]' src/insider_bot/web/static/vendor/jsQR-1.4.0.js; grep -n '^var qrcode = function' src/insider_bot/web/static/vendor/qrcode-generator-1.4.4.js`
Expected: 1 つ目は `1` 以上（UMD で `window.jsQR` を定義する）、2 つ目は 1 行ヒット（通常のスクリプトとして読むと `window.qrcode` になる）。どちらかがヒットしなければ作業を止めてユーザーに報告する

- [ ] **Step 8: qr.js を実装する**

`src/insider_bot/web/static/qr.js`:

```js
// 招待パネルの QR 表示と、サイト内の QR 読み取り
import { parseRoomCode } from "./roomurl.js";

const QRCODE_SRC = "/static/vendor/qrcode-generator-1.4.4.js";
const JSQR_SRC = "/static/vendor/jsQR-1.4.0.js";
const QR_SCALE = 8;
const QR_MARGIN = 4;
const SCAN_INTERVAL_MS = 100;
const SCAN_MAX_WIDTH = 640;
const CAMERA_HELP = "スマホ標準のカメラでも読み取れます";

const loading = new Map();

// 使うときだけ読み込む（外向き通信を抑えるため。jsQR は大きい）
function loadScript(src) {
  if (!loading.has(src)) {
    loading.set(
      src,
      new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = src;
        script.onload = () => resolve();
        script.onerror = () => {
          loading.delete(src);
          reject(new Error(`${src} を読み込めませんでした`));
        };
        document.head.append(script);
      }),
    );
  }
  return loading.get(src);
}

/** text の QR をキャンバスに描く。innerHTML を使わないよう、モジュールを 1 つずつ塗る。 */
export async function renderQr(canvas, text) {
  await loadScript(QRCODE_SRC);
  const qr = window.qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const count = qr.getModuleCount();
  const size = (count + QR_MARGIN * 2) * QR_SCALE;
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  context.fillStyle = "#fff";
  context.fillRect(0, 0, size, size);
  context.fillStyle = "#000";
  for (let row = 0; row < count; row++) {
    for (let col = 0; col < count; col++) {
      if (qr.isDark(row, col)) {
        context.fillRect((col + QR_MARGIN) * QR_SCALE, (row + QR_MARGIN) * QR_SCALE, QR_SCALE, QR_SCALE);
      }
    }
  }
}

export class Scanner {
  constructor(dialog, video, message, onRoom) {
    this.dialog = dialog;
    this.video = video;
    this.message = message;
    this.onRoom = onRoom;
    this.stream = null;
    this.timer = null;
    this.canvas = document.createElement("canvas");
    this.context = this.canvas.getContext("2d", { willReadFrequently: true });
    dialog.addEventListener("close", () => this.stop());
  }

  async open() {
    this.dialog.showModal();
    this.say("カメラを起動しています…");
    try {
      await loadScript(JSQR_SRC);
    } catch {
      this.say(`読み取りの準備に失敗しました。${CAMERA_HELP}`);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      this.say(`このブラウザではカメラを使えません。${CAMERA_HELP}`);
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
    } catch {
      this.say(`カメラを使えませんでした。${CAMERA_HELP}`);
      return;
    }
    if (!this.dialog.open) {
      // 起動を待つ間に閉じられた
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    this.stream = stream;
    this.video.srcObject = stream;
    try {
      await this.video.play();
    } catch {
      // 自動再生が止められても、映像のフレームは読める
    }
    this.say("QR コードを枠に合わせてください");
    this.timer = setInterval(() => this.scan(), SCAN_INTERVAL_MS);
  }

  scan() {
    const { videoWidth: width, videoHeight: height } = this.video;
    if (!width || !height) return;
    const scale = Math.min(1, SCAN_MAX_WIDTH / width);
    this.canvas.width = Math.round(width * scale);
    this.canvas.height = Math.round(height * scale);
    this.context.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);
    const image = this.context.getImageData(0, 0, this.canvas.width, this.canvas.height);
    const found = window.jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" });
    if (!found) return;
    const code = parseRoomCode(found.data, location.origin);
    if (!code) {
      this.say("このゲームの QR コードではありません");
      return;
    }
    this.close();
    this.onRoom(code);
  }

  say(text) {
    this.message.textContent = text;
  }

  close() {
    if (this.dialog.open) this.dialog.close();
    else this.stop();
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.video.srcObject = null;
  }
}
```

- [ ] **Step 9: JS の構文を確かめる**

Run: `node --check src/insider_bot/web/static/qr.js && node --check src/insider_bot/web/static/roomurl.js && echo OK`
Expected: `OK`

- [ ] **Step 10: コミット**

```bash
git add src/insider_bot/web/static/roomurl.js src/insider_bot/web/static/qr.js src/insider_bot/web/static/vendor tests/js/roomurl.test.mjs
git commit -m "$(cat <<'EOF'
feat: Web版のQR表示と読み取り、ルームURLの判定を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 押して話す（speech.js）

**Files:**
- Create: `src/insider_bot/web/static/speech.js`
- Create: `tests/js/speech.test.mjs`

**Interfaces:**
- Consumes: ブラウザの `SpeechRecognition` / `webkitSpeechRecognition`
- Produces（`speech.js`）:
  - `speechSupported: boolean`
  - `mergeResults(finals: string, results: SpeechRecognitionResultList, resultIndex: number) -> { finals: string, interim: string }`
  - `class PushToTalk(button: HTMLButtonElement, handlers)`。`handlers` は `onTranscript(text)`（押している間の表示）・`onText(text)`（送る文字）・`onStatus(text)`（案内）・`onUnavailable(text)`（マイクが使えない。文字入力に切り替える合図）。メソッド `cancel(message?: string)`、プロパティ `enabled: boolean`（false の間は新しく押し始められない。押している途中の操作は最後まで続く）

- [ ] **Step 1: 失敗するテストを書く**

`tests/js/speech.test.mjs`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";

import { mergeResults } from "../../src/insider_bot/web/static/speech.js";

// SpeechRecognitionResult の代わり: 候補の配列に isFinal を付けたもの
const result = (transcript, isFinal) => Object.assign([{ transcript }], { isFinal });

test("未確定の結果だけなら、未確定の文字として持つ", () => {
  assert.deepEqual(mergeResults("", [result("くだもの", false)], 0), { finals: "", interim: "くだもの" });
});

test("確定した後に届いた未確定の末尾を捨てない", () => {
  const first = mergeResults("", [result("赤い", true)], 0);
  const second = mergeResults(first.finals, [result("赤い", true), result("果物ですか", false)], 1);
  assert.deepEqual(second, { finals: "赤い", interim: "果物ですか" });
});

test("一度確定した結果を二重に数えない", () => {
  const first = mergeResults("", [result("赤い", true)], 0);
  const second = mergeResults(first.finals, [result("赤い", true), result("果物ですか", true)], 1);
  assert.deepEqual(second, { finals: "赤い果物ですか", interim: "" });
});

test("聞き直した後は、それまでの確定分に新しい結果を足す", () => {
  assert.deepEqual(mergeResults("赤い", [result("丸い", true)], 0), { finals: "赤い丸い", interim: "" });
});
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `node --test tests/js/speech.test.mjs`
Expected: FAIL（`Cannot find module …/speech.js`）

- [ ] **Step 3: 実装する**

`src/insider_bot/web/static/speech.js`:

```js
// 押して話す: ボタン（PC はスペースキー）を押している間だけ Web Speech API で聞き取り、離したら送る
const Recognition = globalThis.SpeechRecognition ?? globalThis.webkitSpeechRecognition;
export const speechSupported = Boolean(Recognition);

const MAX_HOLD_MS = 20000;
const STOP_WAIT_MS = 2000;
const CANCELLED = "取り消しました";
const LABELS = {
  idle: "🎙 押して話す",
  starting: "準備中…",
  listening: "聞いています…",
  outside: "離すと取り消し",
  stopping: "送信中…",
};
const MIC_DENIED = "マイクが許可されていません。ブラウザの設定から許可するか、文字で質問してください";
// 聞き直しても直らないエラー。文字入力に切り替える
const UNAVAILABLE_ERRORS = {
  "not-allowed": MIC_DENIED,
  "service-not-allowed": MIC_DENIED,
  "audio-capture": "マイクが見つかりません",
  "language-not-supported": "このブラウザは日本語の音声認識に対応していません",
};

/**
 * result イベントの内容を、それまでに確定した文字に合わせる。
 * 確定分は resultIndex 以降の新しいものだけを足し（二重に数えない）、未確定の部分はその時点のものに置き換える。
 * stop() は全区間の確定を保証しないので、呼び出し側は「確定分＋未確定の末尾」を送る。
 */
export function mergeResults(finals, results, resultIndex) {
  let added = "";
  for (let i = resultIndex; i < results.length; i++) {
    if (results[i].isFinal) added += results[i][0].transcript;
  }
  let interim = "";
  for (let i = 0; i < results.length; i++) {
    if (!results[i].isFinal) interim += results[i][0].transcript;
  }
  return { finals: finals + added, interim };
}

export class PushToTalk {
  constructor(button, handlers) {
    this.button = button;
    this.handlers = handlers;
    this.state = "idle";
    this.outside = false;
    this.pointerId = null;
    this.keyHeld = false;
    this.everStarted = false;
    this.recognition = null;
    this.finals = "";
    this.interim = "";
    this.error = null;
    this.holdTimer = null;
    this.stopTimer = null;
    this.enabled = true;
    this.bindPointer();
    this.bindKeyboard();
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this.cancel(CANCELLED);
    });
    this.render();
  }

  // 接続が切れている間は新しく押し始めさせない。押している途中で切れた分は、送るときに呼び出し側が扱う
  // （ボタン自体を disabled にすると、押している途中の pointerup が届かないブラウザがある）
  get enabled() {
    return this._enabled;
  }

  set enabled(value) {
    this._enabled = value;
    this.button.classList.toggle("off", !value);
  }

  text() {
    return (this.finals + this.interim).trim();
  }

  press() {
    if (this.state !== "idle") return;
    this.finals = "";
    this.interim = "";
    this.error = null;
    this.outside = false;
    this.state = "starting";
    this.render();
    this.holdTimer = setTimeout(() => {
      // 押しっぱなしの打ち切り。この後に来る pointerup / keyup は無視する
      this.pointerId = null;
      this.keyHeld = false;
      this.release();
    }, MAX_HOLD_MS);
    this.listen();
  }

  listen() {
    const recognition = new Recognition();
    recognition.lang = "ja-JP";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onstart = () => {
      this.everStarted = true;
      if (this.state === "starting") {
        this.state = "listening";
        this.render();
      }
    };
    recognition.onresult = (event) => {
      ({ finals: this.finals, interim: this.interim } = mergeResults(this.finals, event.results, event.resultIndex));
      this.handlers.onTranscript(this.text());
    };
    recognition.onerror = (event) => {
      this.error = event.error;
    };
    recognition.onend = () => this.ended();
    this.recognition = recognition;
    try {
      recognition.start();
    } catch {
      this.finish(null, "音声認識を開始できませんでした");
    }
  }

  ended() {
    const error = this.error;
    this.error = null;
    if (this.state === "stopping") {
      this.finish(this.text());
      return;
    }
    if (this.state !== "starting" && this.state !== "listening") return;
    if (error in UNAVAILABLE_ERRORS) {
      this.finish(null);
      this.handlers.onUnavailable(UNAVAILABLE_ERRORS[error]);
      return;
    }
    if (error === "network") {
      this.finish(null, "音声認識サーバーに接続できませんでした");
      return;
    }
    // 押している間に勝手に終わった（Android などで無音が続くと起きる）。聞き取った分を残して聞き直す
    this.finals += this.interim;
    this.interim = "";
    this.listen();
  }

  release() {
    clearTimeout(this.holdTimer);
    if (this.state === "starting") {
      // 初回はマイクの許可を求める間に指を離しがち
      this.finish(null, this.everStarted ? "長押ししてから話してください" : "マイクの使用を許可したら、もう一度押して話してください");
      return;
    }
    if (this.state !== "listening") return;
    this.state = "stopping";
    this.render();
    this.recognition.stop();
    this.stopTimer = setTimeout(() => {
      if (this.state === "stopping") this.finish(this.text());
    }, STOP_WAIT_MS);
  }

  cancel(message) {
    if (this.state === "idle") return;
    this.finish(null, message);
  }

  /** text が null なら何も送らない。空文字なら「聞き取れませんでした」。 */
  finish(text, message) {
    clearTimeout(this.holdTimer);
    clearTimeout(this.stopTimer);
    const recognition = this.recognition;
    this.recognition = null;
    if (recognition) {
      recognition.onstart = recognition.onresult = recognition.onerror = recognition.onend = null;
      try {
        recognition.abort();
      } catch {
        // すでに終わっている
      }
    }
    this.state = "idle";
    this.outside = false;
    this.pointerId = null;
    this.keyHeld = false;
    this.render();
    this.handlers.onTranscript("");
    if (message) {
      this.handlers.onStatus(message);
      return;
    }
    if (text === null) return;
    if (!text) {
      this.handlers.onStatus("聞き取れませんでした");
      return;
    }
    this.handlers.onText(text);
  }

  render() {
    const state = this.state === "listening" && this.outside ? "outside" : this.state;
    this.button.dataset.state = state;
    this.button.textContent = LABELS[state];
  }

  isInside(event) {
    const rect = this.button.getBoundingClientRect();
    return event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
  }

  bindPointer() {
    const button = this.button;
    button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !this.enabled || this.state !== "idle") return;
      event.preventDefault();
      button.setPointerCapture(event.pointerId);
      this.pointerId = event.pointerId;
      this.press();
    });
    // 指を捕まえている間は pointerleave がボタン基準で届かないので、座標とボタンの矩形を比べる
    button.addEventListener("pointermove", (event) => {
      if (event.pointerId !== this.pointerId) return;
      const outside = !this.isInside(event);
      if (outside !== this.outside) {
        this.outside = outside;
        this.render();
      }
    });
    button.addEventListener("pointerup", (event) => {
      if (event.pointerId !== this.pointerId) return;
      this.pointerId = null;
      if (this.isInside(event)) this.release();
      else this.cancel(CANCELLED);
    });
    // pointerup の後の lostpointercapture は pointerId を消してあるので無視される
    const lost = (event) => {
      if (event.pointerId !== this.pointerId) return;
      this.pointerId = null;
      this.cancel(CANCELLED);
    };
    button.addEventListener("pointercancel", lost);
    button.addEventListener("lostpointercapture", lost);
    button.addEventListener("contextmenu", (event) => event.preventDefault());
  }

  bindKeyboard() {
    window.addEventListener("keydown", (event) => {
      if (event.code === "Escape" && this.keyHeld) {
        this.keyHeld = false;
        this.cancel(CANCELLED);
        return;
      }
      if (event.code !== "Space" || event.repeat || !this.keyboardUsable(event)) return;
      event.preventDefault();
      if (this.state !== "idle") return;
      this.keyHeld = true;
      this.press();
    });
    window.addEventListener("keyup", (event) => {
      if (event.code !== "Space" || !this.keyHeld) return;
      event.preventDefault();
      this.keyHeld = false;
      this.release();
    });
  }

  keyboardUsable(event) {
    const target = event.target;
    if (target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) {
      return false;
    }
    if (document.querySelector("dialog[open]")) return false;
    return this.enabled && this.button.offsetParent !== null;
  }
}
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `node --test tests/js/speech.test.mjs tests/js/roomurl.test.mjs`
Expected: `pass 10`・`fail 0`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/static/speech.js tests/js/speech.test.mjs
git commit -m "$(cat <<'EOF'
feat: Web版の押して話す（Web Speech API）を追加

送る文字は確定分と未確定の末尾をつなぎ、ボタンの外で離したかは座標で判定する。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 画面本体（index.html・style.css・app.js）と起動確認

**Files:**
- Create: `src/insider_bot/web/static/index.html`
- Create: `src/insider_bot/web/static/style.css`
- Create: `src/insider_bot/web/static/app.js`
- Create: `.claude/launch.json`（コミットしない。内蔵ブラウザでの確認用）

**Interfaces:**
- Consumes: Task 5 の `ROOM_CODE_PATTERN`・`renderQr`・`Scanner`、Task 6 の `PushToTalk`・`speechSupported`、Task 4 の HTTP と WebSocket のメッセージ（Task 3 の形）
- Produces: ブラウザで動く画面。保存するキーは `localStorage` の `odai:name` と `odai:token:<ルーム番号>`

- [ ] **Step 1: index.html を書く**

`src/insider_bot/web/static/index.html`:

```html
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="color-scheme" content="light dark">
  <title>お題当てゲーム</title>
  <link rel="stylesheet" href="/static/style.css">
  <script type="module" src="/static/app.js"></script>
</head>
<body>
  <main>
    <section id="home" class="page" hidden>
      <h1>お題当てゲーム</h1>
      <p class="lead">出題者のお題を、はい・いいえで答えられる質問で当てるゲームです。</p>
      <form id="home-form" class="stack">
        <label class="field">名前
          <input id="home-name" maxlength="20" autocomplete="nickname" required>
        </label>
        <button type="submit" class="primary">ルームを作る</button>
      </form>
      <button id="scan-open" type="button" class="secondary wide">📷 QR で参加</button>
      <p id="home-message" class="message" role="status"></p>
    </section>

    <section id="name-page" class="page" hidden>
      <h1>ルーム <span id="name-room-code"></span> に参加</h1>
      <form id="name-form" class="stack">
        <label class="field">名前
          <input id="name-input" maxlength="20" autocomplete="nickname" required>
        </label>
        <button type="submit" class="primary">参加する</button>
      </form>
    </section>

    <section id="room" class="page room" hidden>
      <header class="room-header">
        <div class="room-title">
          <span>ルーム <strong id="room-code"></strong></span>
          <button id="invite-open" type="button" class="secondary small">招待</button>
        </div>
        <p id="game-status" class="game-status"></p>
        <p id="players" class="players"></p>
        <p id="secret" class="secret" hidden></p>
        <p id="offline" class="offline" role="status" hidden></p>
      </header>
      <ol id="log" class="log" aria-live="polite"></ol>
      <footer id="controls" class="controls">
        <p id="notice" class="notice" role="status"></p>

        <div id="start-panel" hidden>
          <button id="start-open" type="button" class="primary wide">お題を出す</button>
          <form id="start-form" class="stack" hidden>
            <label class="field">お題（50文字まで）
              <input id="topic" maxlength="50" autocomplete="off" required>
            </label>
            <label class="field">補足（任意・300文字まで）
              <textarea id="hint" maxlength="300" rows="2"></textarea>
            </label>
            <div class="row">
              <button type="submit" class="primary">開始</button>
              <button id="start-cancel" type="button" class="secondary">やめる</button>
            </div>
          </form>
        </div>

        <div id="setter-panel" hidden>
          <p class="center">あなたは出題者です</p>
          <button id="setter-giveup" type="button" class="secondary wide">ギブアップ（お題を公開）</button>
        </div>

        <div id="asker-panel" hidden>
          <p id="transcript" class="transcript"></p>
          <div id="voice" class="voice">
            <button id="talk" type="button" class="talk">🎙 押して話す</button>
            <p class="hint">離すと送信／外で離すと取消（PC はスペースキー長押し）</p>
          </div>
          <form id="text-form" class="row" hidden>
            <input id="text-input" maxlength="200" autocomplete="off" placeholder="質問（例: 果物ですか）">
            <button type="submit" class="primary">送信</button>
          </form>
          <p id="speech-help" class="hint" hidden></p>
          <div class="row links">
            <button id="mode-toggle" type="button" class="link">⌨ 文字で質問</button>
            <button id="asker-giveup" type="button" class="link">ギブアップ</button>
          </div>
        </div>
      </footer>
    </section>

    <section id="fatal" class="page" hidden>
      <p id="fatal-message"></p>
      <a href="/" class="button primary">トップページへ</a>
    </section>
  </main>

  <dialog id="invite" class="sheet">
    <h2>招待</h2>
    <canvas id="invite-qr" class="qr" width="1" height="1" aria-label="ルームの QR コード"></canvas>
    <p class="center">ルーム <strong id="invite-code"></strong></p>
    <p id="invite-url" class="url"></p>
    <div class="row">
      <button id="invite-copy" type="button" class="primary">URL をコピー</button>
      <button id="invite-close" type="button" class="secondary">閉じる</button>
    </div>
    <p id="invite-message" class="message" role="status"></p>
  </dialog>

  <dialog id="scanner" class="sheet">
    <h2>QR で参加</h2>
    <video id="scanner-video" class="scanner-video" playsinline muted></video>
    <p id="scanner-message" class="message" role="status"></p>
    <button id="scanner-close" type="button" class="secondary wide">閉じる</button>
  </dialog>
</body>
</html>
```

- [ ] **Step 2: style.css を書く**

`src/insider_bot/web/static/style.css`:

```css
:root {
  --bg: #f6f4ef;
  --surface: #ffffff;
  --text: #1d1d1f;
  --muted: #66666c;
  --line: #e2dfd8;
  --accent: #2f6fde;
  --accent-text: #ffffff;
  --danger: #d33a3a;
  --online: #2fa84f;
  --radius: 14px;
  color-scheme: light dark;
  font-family: system-ui, -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #151517;
    --surface: #1f1f23;
    --text: #f2f2f4;
    --muted: #a0a0a8;
    --line: #34343b;
    --accent: #5b8ff0;
  }
}

* { box-sizing: border-box; }
[hidden] { display: none !important; }
html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text); }
main { max-width: 560px; height: 100%; margin: 0 auto; }
.page { padding: 24px 16px; }
h1 { font-size: 1.5rem; margin: 0 0 8px; }
h2 { font-size: 1.15rem; margin: 0 0 12px; }
.lead { color: var(--muted); margin: 0 0 20px; }
.center { text-align: center; }
.stack { display: flex; flex-direction: column; gap: 12px; margin-bottom: 12px; }
.row { display: flex; gap: 8px; align-items: center; }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 0.9rem; color: var(--muted); }

input, textarea {
  width: 100%;
  font: inherit;
  font-size: 16px; /* iOS で入力時に拡大されないように */
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
}

button, .button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 44px;
  padding: 10px 16px;
  font: inherit;
  border: 0;
  border-radius: 10px;
  cursor: pointer;
  text-decoration: none;
}
button:disabled { opacity: 0.5; cursor: default; }
.primary { background: var(--accent); color: var(--accent-text); }
.secondary { background: var(--surface); color: var(--text); border: 1px solid var(--line); }
.wide { width: 100%; }
.small { min-height: 32px; padding: 4px 12px; font-size: 0.9rem; }
.link { min-height: 32px; padding: 4px 8px; background: none; color: var(--accent); }
.message, .notice { min-height: 1.4em; margin: 8px 0; color: var(--muted); }

.room { display: flex; flex-direction: column; height: 100dvh; padding: 0; }
.room-header { padding: 12px 16px 8px; background: var(--surface); border-bottom: 1px solid var(--line); }
.room-title { display: flex; justify-content: space-between; align-items: center; }
.game-status { margin: 6px 0 2px; font-weight: 600; }
.players { display: flex; flex-wrap: wrap; gap: 4px 10px; margin: 0; color: var(--muted); font-size: 0.9rem; }
.player::before { content: "○ "; }
.player.online::before { content: "● "; color: var(--online); }
.secret { margin: 8px 0 0; padding: 8px 10px; border-radius: 8px; background: color-mix(in srgb, var(--accent) 14%, transparent); }
.offline { margin: 8px 0 0; color: var(--danger); }

.log { flex: 1; display: flex; flex-direction: column; gap: 10px; margin: 0; padding: 12px 16px; overflow-y: auto; list-style: none; }
.entry { padding: 10px 12px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); }
.entry .author { display: block; margin-bottom: 2px; font-size: 0.8rem; color: var(--muted); }
.entry .text { white-space: pre-wrap; overflow-wrap: anywhere; }
.entry.pending .text { color: var(--muted); }

.controls { padding: 8px 16px calc(12px + env(safe-area-inset-bottom)); background: var(--surface); border-top: 1px solid var(--line); }
.transcript { min-height: 1.4em; margin: 0 0 8px; text-align: center; }
.voice { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.talk {
  width: min(100%, 320px);
  min-height: 72px;
  font-size: 1.15rem;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-text);
  /* 長押しで文字選択・メニュー・スクロールが起きないように */
  touch-action: none;
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
}
.talk[data-state="starting"], .talk[data-state="stopping"] { background: var(--muted); }
.talk[data-state="listening"] { background: var(--danger); box-shadow: 0 0 0 6px color-mix(in srgb, var(--danger) 30%, transparent); }
.talk[data-state="outside"] { background: var(--surface); color: var(--danger); border: 2px solid var(--danger); }
.talk.off { opacity: 0.5; cursor: default; }
.hint { margin: 0; font-size: 0.85rem; color: var(--muted); text-align: center; }
.links { justify-content: space-between; margin-top: 6px; }
#text-form input { flex: 1; }

dialog.sheet { width: min(92vw, 420px); padding: 20px; color: var(--text); background: var(--surface); border: 0; border-radius: var(--radius); }
dialog::backdrop { background: rgb(0 0 0 / 0.5); }
.qr { display: block; width: min(80vw, 320px); height: auto; margin: 0 auto 12px; image-rendering: pixelated; }
.url { overflow-wrap: anywhere; font-size: 0.9rem; color: var(--muted); user-select: all; }
.scanner-video { width: 100%; aspect-ratio: 3 / 4; object-fit: cover; border-radius: 10px; background: #000; }
```

- [ ] **Step 3: app.js を書く**

`src/insider_bot/web/static/app.js`:

```js
// 画面全体: トップページ、名前の入力、ルーム画面（WebSocket の接続と再接続）
import { renderQr, Scanner } from "./qr.js";
import { ROOM_CODE_PATTERN } from "./roomurl.js";
import { PushToTalk, speechSupported } from "./speech.js";

const $ = (id) => document.getElementById(id);
const NAME_KEY = "odai:name";
const tokenKey = (code) => `odai:token:${code}`;
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 10000];
const NOTICE_MS = 5000;
const LOG_LIMIT = 300;
const CLOSE_MESSAGES = {
  4400: "ルームに入れませんでした。名前を確かめて、もう一度どうぞ",
  4404: "ルームが見つかりません（サーバーが再起動した可能性があります）",
  4409: "このルームは満員です",
};
const NO_SPEECH_HELP =
  "音声入力は Chrome / Edge / Safari で使えます（iPhone は Siri を有効にしてください）。このブラウザでは文字で質問してください";

function load(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // 保存できなくても、このタブの中では遊べる
  }
}

function showPage(id) {
  for (const page of document.querySelectorAll(".page")) page.hidden = page.id !== id;
}

function showFatal(message) {
  $("fatal-message").textContent = message;
  showPage("fatal");
}

function formatElapsed(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hours ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

function initHome() {
  showPage("home");
  $("home-name").value = load(NAME_KEY) ?? "";
  $("home-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = $("home-name").value.trim();
    if (!name) return;
    save(NAME_KEY, name);
    $("home-message").textContent = "";
    let response = null;
    try {
      response = await fetch("/api/rooms", { method: "POST" });
    } catch {
      // 下でまとめて案内する
    }
    if (!response?.ok) {
      $("home-message").textContent = "今はルームを作れません。しばらくしてからどうぞ";
      return;
    }
    const { code } = await response.json();
    location.href = `/r/${code}?invite=1`;
  });
  const scanner = new Scanner($("scanner"), $("scanner-video"), $("scanner-message"), (code) => {
    location.href = `/r/${code}`;
  });
  $("scan-open").addEventListener("click", () => scanner.open());
  $("scanner-close").addEventListener("click", () => scanner.close());
}

function initRoom(code) {
  const openInvite = new URLSearchParams(location.search).has("invite");
  if (openInvite) history.replaceState(null, "", `/r/${code}`);
  const enter = (name) => {
    const page = new RoomPage(code, name);
    page.start();
    if (openInvite) page.openInvite();
  };
  const stored = load(NAME_KEY);
  if (stored) {
    enter(stored);
    return;
  }
  showPage("name-page");
  $("name-room-code").textContent = code;
  $("name-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const name = $("name-input").value.trim();
    if (!name) return;
    save(NAME_KEY, name);
    enter(name);
  });
}

class RoomPage {
  constructor(code, name) {
    this.code = code;
    this.name = name;
    this.token = load(tokenKey(code));
    this.ws = null;
    this.connected = false;
    this.retry = 0;
    this.game = null;
    this.isSetter = false;
    this.startedAt = 0;
    this.items = new Map();
    this.noticeTimer = null;
    this.textMode = !speechSupported;
    this.talk = speechSupported
      ? new PushToTalk($("talk"), {
          onTranscript: (text) => {
            $("transcript").textContent = text;
          },
          onText: (text) => this.ask(text),
          onStatus: (text) => this.notice(text),
          onUnavailable: (text) => {
            this.notice(text);
            this.setTextMode(true);
          },
        })
      : null;
  }

  start() {
    showPage("room");
    $("room-code").textContent = this.code;
    this.bindControls();
    if (!speechSupported) {
      $("speech-help").textContent = NO_SPEECH_HELP;
      $("speech-help").hidden = false;
      $("mode-toggle").hidden = true;
    }
    this.setTextMode(this.textMode);
    $("offline").textContent = "接続中…";
    this.setConnected(false);
    setInterval(() => this.renderStatus(), 1000);
    this.connect();
  }

  connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/r/${this.code}/ws`);
    this.ws = ws;
    ws.addEventListener("open", () => {
      ws.send(JSON.stringify({ type: "join", name: this.name, token: this.token }));
    });
    ws.addEventListener("message", (event) => this.receive(JSON.parse(event.data)));
    ws.addEventListener("close", (event) => this.closed(event.code));
  }

  receive(message) {
    switch (message.type) {
      case "welcome":
        this.token = message.token;
        save(tokenKey(this.code), message.token);
        break;
      case "snapshot":
        this.retry = 0;
        this.setConnected(true);
        this.renderLog(message.log);
        this.renderRoom(message.room);
        break;
      case "room":
        this.renderRoom(message);
        break;
      case "entry":
        this.upsertEntry(message.entry);
        break;
      case "notice":
        this.notice(message.text);
        break;
    }
  }

  closed(code) {
    this.ws = null;
    this.setConnected(false);
    if (code in CLOSE_MESSAGES) {
      showFatal(CLOSE_MESSAGES[code]);
      return;
    }
    $("offline").textContent = "再接続中…";
    const delay = RETRY_DELAYS_MS[Math.min(this.retry, RETRY_DELAYS_MS.length - 1)];
    this.retry += 1;
    setTimeout(() => this.connect(), delay);
  }

  send(message) {
    if (!this.connected) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  ask(text) {
    if (this.send({ type: "ask", text, game_id: this.game?.id ?? null })) return;
    this.notice("接続が切れているため送れませんでした");
    this.setTextMode(true);
    $("text-input").value = text;
  }

  setConnected(connected) {
    this.connected = connected;
    $("offline").hidden = connected;
    for (const control of $("controls").querySelectorAll("button:not(#talk), input, textarea")) {
      control.disabled = !connected;
    }
    // 押して話すボタンは disabled にせず、新しく押し始められないようにするだけ（speech.js の enabled）
    if (this.talk) this.talk.enabled = connected;
  }

  renderRoom({ players, game, you }) {
    this.game = game;
    this.isSetter = you.is_setter;
    // 経過時間はサーバーが送った時点の秒数から画面側で進める
    this.startedAt = game ? performance.now() / 1000 - game.elapsed : 0;
    $("players").replaceChildren(
      ...players.map((player) => {
        const item = document.createElement("span");
        item.className = player.online ? "player online" : "player";
        item.textContent = player.name;
        return item;
      }),
    );
    const secret = $("secret");
    secret.hidden = !you.is_setter;
    secret.textContent = you.is_setter ? `🤫 お題「${you.topic}」${you.hint ? `　補足: ${you.hint}` : ""}` : "";
    $("start-panel").hidden = Boolean(game);
    $("setter-panel").hidden = !game || !you.is_setter;
    $("asker-panel").hidden = !game || you.is_setter;
    if (game) this.closeStartForm();
    if (!game || you.is_setter) this.talk?.cancel("ゲームが終わったため取り消しました");
    this.renderStatus();
  }

  renderStatus() {
    if (!this.game) {
      $("game-status").textContent = "ゲームは始まっていません。誰かが「お題を出す」から始めます";
      return;
    }
    const elapsed = Math.max(0, Math.floor(performance.now() / 1000 - this.startedAt));
    const setter = this.isSetter ? "あなた" : this.game.setter;
    $("game-status").textContent = `出題者 ${setter}・質問 ${this.game.questions}・${formatElapsed(elapsed)}`;
  }

  renderLog(entries) {
    this.items.clear();
    $("log").replaceChildren();
    for (const entry of entries) this.upsertEntry(entry);
  }

  upsertEntry(entry) {
    const log = $("log");
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
    let item = this.items.get(entry.id);
    if (!item) {
      item = document.createElement("li");
      item.dataset.id = String(entry.id);
      this.items.set(entry.id, item);
      log.append(item);
      while (log.children.length > LOG_LIMIT) {
        const oldest = log.firstElementChild;
        this.items.delete(Number(oldest.dataset.id));
        oldest.remove();
      }
    }
    item.className = entry.pending ? "entry pending" : "entry";
    const parts = [];
    if (entry.author) {
      const author = document.createElement("span");
      author.className = "author";
      author.textContent = entry.author;
      parts.push(author);
    }
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = entry.text;
    parts.push(text);
    item.replaceChildren(...parts);
    if (atBottom) log.scrollTop = log.scrollHeight;
  }

  bindControls() {
    $("invite-open").addEventListener("click", () => this.openInvite());
    $("invite-close").addEventListener("click", () => $("invite").close());
    $("invite-copy").addEventListener("click", () => this.copyInvite());
    $("start-open").addEventListener("click", () => {
      $("start-open").hidden = true;
      $("start-form").hidden = false;
      $("topic").focus();
    });
    $("start-cancel").addEventListener("click", () => this.closeStartForm());
    $("start-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const topic = $("topic").value.trim();
      if (!topic) return;
      if (!this.send({ type: "start", topic, hint: $("hint").value.trim() })) return;
      $("topic").value = "";
      $("hint").value = "";
      this.closeStartForm();
    });
    const giveup = () => {
      if (confirm("ギブアップしてお題を公開しますか？")) this.send({ type: "giveup" });
    };
    $("setter-giveup").addEventListener("click", giveup);
    $("asker-giveup").addEventListener("click", giveup);
    $("mode-toggle").addEventListener("click", () => this.setTextMode(!this.textMode));
    $("text-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const text = $("text-input").value.trim();
      if (!text) return;
      $("text-input").value = "";
      this.ask(text);
    });
  }

  closeStartForm() {
    $("start-form").hidden = true;
    $("start-open").hidden = false;
  }

  setTextMode(on) {
    this.textMode = on || !speechSupported;
    $("voice").hidden = this.textMode;
    $("text-form").hidden = !this.textMode;
    $("mode-toggle").textContent = this.textMode ? "🎙 声で質問" : "⌨ 文字で質問";
    if (this.textMode) this.talk?.cancel();
  }

  async openInvite() {
    const url = `${location.origin}/r/${this.code}`;
    $("invite-code").textContent = this.code;
    $("invite-url").textContent = url;
    $("invite-message").textContent = "";
    if (!$("invite").open) $("invite").showModal();
    try {
      await renderQr($("invite-qr"), url);
    } catch {
      $("invite-message").textContent = "QR コードを表示できませんでした。URL を共有してください";
    }
  }

  async copyInvite() {
    try {
      await navigator.clipboard.writeText(`${location.origin}/r/${this.code}`);
      $("invite-message").textContent = "コピーしました";
    } catch {
      $("invite-message").textContent = "コピーできませんでした。URL を長押ししてコピーしてください";
    }
  }

  notice(text) {
    $("notice").textContent = text;
    clearTimeout(this.noticeTimer);
    this.noticeTimer = setTimeout(() => {
      $("notice").textContent = "";
    }, NOTICE_MS);
  }
}

const match = /^\/r\/([^/]+)\/?$/.exec(location.pathname);
if (!match) {
  initHome();
} else {
  const code = match[1].toUpperCase();
  if (!ROOM_CODE_PATTERN.test(code)) showFatal("ルームが見つかりません（URL を確かめてください）");
  else if (code !== match[1]) location.replace(`/r/${code}${location.search}`);
  else initRoom(code);
}
```

- [ ] **Step 4: JS の構文を確かめる**

Run: `for f in app speech qr roomurl; do node --check "src/insider_bot/web/static/$f.js" || exit 1; done && echo OK`
Expected: `OK`

- [ ] **Step 5: 内蔵ブラウザ用の起動設定を作る（コミットしない）**

`.claude/launch.json`:

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "insider-web",
      "runtimeExecutable": "uv",
      "runtimeArgs": ["run", "--env-file", ".env", "python", "-m", "insider_bot.web"],
      "port": 8080
    }
  ]
}
```

- [ ] **Step 6: 起動して HTTP の応答を確かめる**

`preview_start` で `insider-web` を起動し、`preview_logs` に `Running on http://127.0.0.1:8080` が出ることを確かめる。続けて:

Run: `curl -s -o /dev/null -w "%{http_code} " http://127.0.0.1:8080/ && curl -s -o /dev/null -w "%{http_code} " http://127.0.0.1:8080/static/app.js && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/static/vendor/jsQR-1.4.0.js && curl -s -X POST http://127.0.0.1:8080/api/rooms`
Expected: `200 200 200` の後に `{"code": "……"}`

- [ ] **Step 7: コミット**

```bash
git add src/insider_bot/web/static/index.html src/insider_bot/web/static/style.css src/insider_bot/web/static/app.js
git commit -m "$(cat <<'EOF'
feat: Web版の画面（トップ・ルーム・招待・QR読み取り）を追加

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 内蔵ブラウザでの確認

**Files:** なし（不具合が見つかれば、該当タスクのファイルを直してテストを足し、コミットする）

**Interfaces:**
- Consumes: Task 7 で起動したサーバー（`http://localhost:8080`）
- Produces: 確認結果の記録（この後の報告に使う）

- [ ] **Step 1: ルームを作って招待パネルを確かめる**

内蔵ブラウザで `http://localhost:8080` を開き、名前「たろう」で「ルームを作る」。
Expected: `/r/<番号>` に移り、招待パネルが自動で開き、QR コードが描かれ、URL とルーム番号が出る。「URL をコピー」で「コピーしました」。`read_console_messages` にエラーがない

- [ ] **Step 2: 2 つ目のタブで回答者として入る**

`tabs_create` で新しいタブを開き、`http://127.0.0.1:8080/r/<番号>` を開く。1 つ目のタブ（`localhost`）とオリジンを変えるのは、localStorage（名前と合言葉）を別々にして別人として入るため。どちらのオリジンもマイクを使える安全なコンテキストとして扱われる。名前を聞かれたら「はなこ」で参加する。
Expected: 2 つ目のタブに参加者「たろう」「はなこ」が出て、1 つ目のタブの参加者一覧にも「はなこ」が増える

- [ ] **Step 3: お題を出し、お題が出題者にだけ見えることを確かめる**

1 つ目のタブで「お題を出す」→ お題「りんご」、補足「赤い果物」→「開始」。
Expected: 1 つ目のタブに「🤫 お題「りんご」　補足: 赤い果物」と「あなたは出題者です」。2 つ目のタブには押して話すボタンが出て、`get_page_text` の結果に「りんご」が含まれない。両方の履歴に「🎮 ゲーム開始！たろうさんがお題を出しました。「🎙 押して話す」で質問をどうぞ」

- [ ] **Step 4: 文字入力で質問し、全員に同期することを確かめる**

2 つ目のタブで「⌨ 文字で質問」→「果物ですか」→「送信」。
Expected: 両方のタブに「❓ 果物ですか？ … 判定中」が出て、数秒で「✅ はい／❌ いいえ」の行に置き換わる。上部の質問数が 1 になる

- [ ] **Step 5: 再読み込みで同じ人として戻ることを確かめる**

1 つ目のタブ（出題者）を再読み込みする。
Expected: 名前を聞かれずに戻り、お題が引き続き表示され、履歴も残っている。参加者一覧は「たろう」1 人のまま（重複しない）

- [ ] **Step 6: 正解で終わることを確かめる**

2 つ目のタブで「りんご」と送る。
Expected: 「🎉 正解です！お題は「りんご」でした」が両方に出て、操作欄が「お題を出す」に戻る

- [ ] **Step 7: サーバーの停止と再起動を確かめる**

`preview_stop` でサーバーを止める。
Expected: 両方のタブに「再接続中…」。
`preview_start` で起動し直す。
Expected: 再接続のときにルームがないので「ルームが見つかりません（サーバーが再起動した可能性があります）」と「トップページへ」が出る

- [ ] **Step 8: スマホ幅の見た目を確かめる**

`resize_window` を `mobile` にしてルームを作り直し、`computer` の `screenshot` で確かめる。
Expected: 横スクロールがなく、押して話すボタンが下部に収まり、履歴だけがスクロールする。確認後に `resize_window` を `desktop` に戻す

- [ ] **Step 9: 見つかった不具合を直す**

不具合があれば、その場で直し、可能なものは pytest か `node --test` のテストを先に足してから直す。直したら `uv run pytest -q` と `node --test tests/js/*.test.mjs` を流してコミットする（メッセージは `fix: ` で始める）。不具合がなければこのステップは何もしない

---

### Task 9: デプロイとドキュメント

**Files:**
- Create: `deploy/insider-web.service`
- Modify: `deploy/setup.sh`（全体を書き換え）
- Modify: `deploy/README.md`（全体を書き換え）
- Modify: `README.md`
- Modify: `docs/spec.md`

**Interfaces:**
- Consumes: Task 4 の起動コマンド `python -m insider_bot.web`、Task 1 の環境変数
- Produces: サーバーで両方のユニットを動かす手順と、仕様書の Web 版の節

- [ ] **Step 1: systemd のユニットを書く**

`deploy/insider-web.service`:

```ini
# deploy/setup.sh がユーザー名とパスを埋め込んで /etc/systemd/system/ に配置する
[Unit]
Description=お題当てゲーム Web 版
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=__USER__
WorkingDirectory=__APP_DIR__
EnvironmentFile=__APP_DIR__/.env
Environment=PYTHONUNBUFFERED=1
# git pull で依存が変わっていても restart だけで反映されるようにする
ExecStartPre=__UV__ sync --frozen --no-dev
ExecStart=__APP_DIR__/.venv/bin/python -m insider_bot.web
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: setup.sh を両方のユニットを扱うように書き換える**

`deploy/setup.sh` を次の内容に置き換える:

```bash
#!/usr/bin/env bash
# サーバー（Ubuntu 24.04）の初期設定。clone したリポジトリで通常ユーザーとして実行する: bash deploy/setup.sh
# 何度実行してもよい。.env が未記入ならひな形を作って止まるので、記入してからもう一度実行する。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$(id -un)"
UV="$HOME/.local/bin/uv"
# Discord ボットと Web 版。どちらも同じ .env を読む
SERVICES=(insider-bot insider-web)

if [ "$(id -u)" -eq 0 ]; then
  echo "root ではなく通常ユーザーで実行してください（必要な箇所は中で sudo します）" >&2
  exit 1
fi

echo "== スワップ（1GB）"
# e2-micro はメモリが 1GB しかないため
if [ ! -f /swapfile ]; then
  sudo fallocate -l 1G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
fi
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
  sudo swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null

echo "== uv"
if [ ! -x "$UV" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "== 依存パッケージ"
(cd "$APP_DIR" && "$UV" sync --frozen --no-dev)

echo "== systemd"
for service in "${SERVICES[@]}"; do
  sed -e "s|__USER__|$APP_USER|g" -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__UV__|$UV|g" \
    "$APP_DIR/deploy/$service.service" | sudo tee "/etc/systemd/system/$service.service" >/dev/null
done
sudo systemctl daemon-reload

echo "== .env"
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "$APP_DIR/.env.example" "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"
if ! grep -Eq '^DISCORD_TOKEN=[^[:space:]]' "$ENV_FILE" || ! grep -Eq '^TYPESAFE_API_KEY=[^[:space:]]' "$ENV_FILE"; then
  echo
  echo "DISCORD_TOKEN と TYPESAFE_API_KEY を記入してから、もう一度実行してください:"
  echo "  nano $ENV_FILE"
  echo "  bash $APP_DIR/deploy/setup.sh"
  exit 0
fi

echo "== 起動"
sudo systemctl enable "${SERVICES[@]}"
sudo systemctl restart "${SERVICES[@]}"
sleep 5
sudo systemctl status "${SERVICES[@]}" --no-pager || true
echo
echo "ログを見る: journalctl -u insider-bot -f ／ journalctl -u insider-web -f"
```

- [ ] **Step 3: setup.sh の構文を確かめる**

Run: `bash -n deploy/setup.sh && echo OK`
Expected: `OK`

- [ ] **Step 4: deploy/README.md を書き換える**

`deploy/README.md` を次の内容に置き換える:

````markdown
# サーバーへのデプロイ手順

全体の方針は [デプロイ計画](../docs/deploy-google-cloud-plan.md) を参照。

## VM を作る（Google Cloud コンソール）

「Compute Engine → VM インスタンス → インスタンスを作成」（初回は Compute Engine API の有効化を求められる）。

| 項目 | 設定 |
|---|---|
| 名前 | `insider-bot` |
| リージョン | `us-central1`（ゾーンはどれでもよい） |
| マシンタイプ | E2 → `e2-micro` |
| ブートディスク | Ubuntu 24.04 LTS（x86/64）／**標準永続ディスク**／30GB |
| ファイアウォール | HTTP・HTTPS とも許可しない（ボットは外向きの通信だけ。Web 版は Tailscale Funnel で公開する） |
| バックアップ・スナップショット | 設定しない（無料枠の対象外） |

ブートディスクの種類は既定が「バランス永続ディスク」になっていることがあり、そのままだと課金されるので必ず「標準」に変える。

## サーバーで初期設定する

VM 一覧の「SSH」ボタンでブラウザの SSH を開き、次を実行する。

```bash
git clone https://github.com/FukaseDaichi/insider.git
cd insider
bash deploy/setup.sh
```

1 回目は `.env` のひな形を作って止まる。トークンを記入してからもう一度実行すると、Discord ボット（`insider-bot`）と Web 版（`insider-web`）が起動する。

```bash
nano .env               # DISCORD_TOKEN と TYPESAFE_API_KEY を記入（Ctrl+O で保存、Ctrl+X で終了）
bash deploy/setup.sh
```

最後に表示される `systemctl status` が両方とも `active (running)` なら成功。
手元のボットは止めてから Discord で動作確認する（両方動いていると 2 回返信される）。
`DISCORD_GUILD_ID` は手元の `.env` と同じ値にしておくと、スラッシュコマンドがすぐ反映される。

すでにボットだけ動かしているサーバーに Web 版を足すときも、`cd ~/insider && git pull && bash deploy/setup.sh` を実行すればよい。

## Web 版を公開する（Tailscale Funnel）

Web 版は VM の中（`127.0.0.1:8080`）でだけ待ち受ける。マイクを使うには HTTPS が必要なので、Tailscale Funnel で `https://<マシン名>.<tailnet名>.ts.net` として公開する。無料で、ドメインは要らず、VM のファイアウォールも閉じたままでよい。

1. https://login.tailscale.com でアカウントを作る（Google アカウントなどでログインできる）
2. VM に Tailscale を入れてログインする

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up        # 表示された URL をブラウザで開いてログインする
   ```

3. 公開する

   ```bash
   sudo tailscale funnel --bg 8080
   ```

   初回は管理画面で Funnel を有効にするリンクが表示されるので、開いて有効にしてからもう一度実行する。設定は VM を再起動しても残る。公開中の URL は `sudo tailscale funnel status` で確かめられる

4. 表示された `https://….ts.net` をスマホで開き、ルームを作って質問に答えが返ることを確かめる（答えが返れば WebSocket も Funnel を通っている）

公開をやめるときは `sudo tailscale funnel reset`。

## 運用

```bash
cd ~/insider && git pull && sudo systemctl restart insider-bot insider-web   # 更新（依存の変更も起動時に反映される）
systemctl status insider-bot insider-web --no-pager                         # 両方が active (running) か確かめる
journalctl -u insider-bot -f                                                # Discord ボットのログ
journalctl -u insider-web -f                                                # Web 版のログ
sudo systemctl stop insider-bot insider-web                                 # 止める
```

更新のときは必ず両方を再起動する。片方だけだと、もう片方が古いコードのまま動き続ける。
````

- [ ] **Step 5: README.md に Web 版を足す**

`README.md` の冒頭の説明（1 段落目）の直後に次を追加する:

```markdown
ブラウザで遊べる **Web 版** もあります。ボタンを押している間に話した言葉が質問になります（[Web 版](#web-版押して話す音声入力)）。
```

`## セットアップ` の直前に次の節を追加する:

````markdown
## Web 版（押して話す音声入力）

Discord の代わりにブラウザで遊べます。Discord 版とは別のゲームで、会話は Discord や Zoom の通話で行う想定です。

1. トップページで名前を入れて「ルームを作る」→ 招待パネルの URL か QR コードを仲間に共有する
2. 誰かが「お題を出す」でお題を登録する（お題は出題者の画面にだけ表示される）
3. 回答者は「🎙 押して話す」を押しながら質問し、離すと送られる（末尾の「？」は自動で付く）。ボタンの外で指を離すと取り消し。PC はスペースキー長押しでも話せる
4. 正解かギブアップで終了（ギブアップは誰でもできる）

- 音声入力は Chrome / Edge / Safari で使えます（iPhone は Siri を有効に）。使えないブラウザでは文字で質問します
- トップページの「📷 QR で参加」で、カメラから QR コードを読み取って参加できます
- サーバーを再起動するとルームは消えます

```bash
uv run --env-file .env python -m insider_bot.web   # http://localhost:8080 を開く
```

`localhost` 以外からマイクを使うには HTTPS が必要です。サーバーでの公開手順は [deploy/README.md](deploy/README.md) を参照してください。
````

`README.md` の環境変数の表の最後に次の 2 行を追加する:

```markdown
| `WEB_HOST` | | 127.0.0.1 | Web 版が待ち受けるアドレス |
| `WEB_PORT` | | 8080 | Web 版が待ち受けるポート |
```

`## 開発` のコードブロックに次の 1 行を追加する:

```bash
node --test tests/js/*.test.mjs                 # Web 版の画面の単体テスト（Node が必要）
```

- [ ] **Step 6: docs/spec.md に Web 版の節を足す**

`docs/spec.md` の「## 目的と範囲」の 1 段落目の直後に次を追加する:

```markdown
Web 版: Discord の外のサイトで、ボタンを押している間に話した言葉を質問として送れる。ゲームの中核は Discord 版と共通だが、ゲームは別々に進む（Discord のチャンネルと Web のルームはつながらない）。
```

同じ節の「対象外:」の文の末尾の「。」の前に次を追加する:

```
、Web 版のログイン・ルームの保存・サーバー側での文字起こし・サイト内の通話
```

「## 将来の拡張」の直前に次の節を追加する:

```markdown
## Web 版

### ルールの違い

- ルームの URL か QR コードで集まる。お題は誰でも出せ、ギブアップも誰でもできる（出題者が抜けても終えられるように）。
- 押して話すボタンか質問用の入力欄から送ったものは、すべて質問として扱う。末尾の「。．.、？?」を外してから「？」を付け直して `handle_question` に渡すので、「？」の規則は Discord 版と共通のまま、話す人は「？」を気にしなくてよい。「？」だけ・「。」だけの質問は送らない。
- ゲーム開始の通知だけは Web 用の文面にする。Discord 用の「最後に「？」をつけてね」は、声で「はてな」と言わせてしまうおそれがあるため。
- ルームの中での名前は最初の入室時に固定する。ゲームに記録した出題者名と参加者一覧がずれないようにするため。

### 設計上の判断

- **別プロセス**: `python -m insider_bot.web` で Discord ボットとは別に動かす。片方の再起動やエラーがもう片方に及ばないようにするため。中核（`GameService` など）は変更せず、ルームと参加者に振った整数 ID をチャンネル ID・ユーザー ID として渡す。
- **音声認識はブラウザ内蔵（Web Speech API）**: 無料で、押している間に途中結果を出せるため。Firefox など非対応のブラウザでは文字入力に切り替える。`stop()` は全区間の確定を保証しないので、送る文字は「確定分＋未確定の末尾」にする。ボタンの外で離したかは、指を捕まえている間は `pointerleave` が使えないので座標で判定する。
- **公開は Tailscale Funnel**: マイクには HTTPS が必要。Funnel なら無料・固定 URL・ドメイン不要で、VM のファイアウォールも閉じたままにできる。Cloudflare は独自ドメインなしだと固定 URL を得られない（Quick Tunnel は起動ごとに URL が変わる）。
- **配信の順序**: 接続ごとに送信待ちの列を持ち、進行役（`RoomHub`）は列に積むだけで待たない。状態を変えてから積むまでの間に `await` を挟まない。asyncio は 1 スレッドなので「状態を変えた順＝画面に届く順」になり、再接続中の巻き戻りや「判定中」と結果の逆転が起きない。入室時は接続の登録と `snapshot` の積み込みを同じ流れで行うので、取りこぼしも重複もない。
- **判定は接続から切り離す**: 質問の判定を別タスクで動かし、結果を履歴に確定してから配る。判定中に質問者のタブが閉じても「判定中」のまま残らない。送信に失敗した接続と、送信待ちが 100 件たまった接続は、その接続だけを閉じる（画面は再接続して `snapshot` で追いつく）。
- **古い質問の排除（Web）**: 質問には画面が見ているゲームの ID を付け、今のゲームと違えば断る。ボタンを押している間に次のゲームが始まっても、前のゲームへの質問を新しいお題で判定しないため。事前の確認から `handle_question` が対象のゲームを控えるまでの間に `await` を挟まないので、確かめたゲームと判定するゲームが一致する。
- **お題は出題者の接続にだけ送る**: 入室時の `snapshot` と `room` の `you` に、出題者の接続にだけお題と補足を入れる。
- **ルームの上限**: 同時に 50 個、1 ルーム 20 人。作成に認証や頻度制限がないので、上限のときは接続のないルームのうち最も古いものを消して空ける（空のルームを大量に作られても、遊んでいる人を締め出さない）。送信元ごとの制限は Funnel 経由の送信元の見分け方に頼ることになるので採らない。満員の判定は新しい参加者を作るときだけにし、合言葉の一致する参加者は戻れる。
- **QR は画面側で作る**: ブラウザが開いている URL から作れば、サーバーが自分の公開 URL を知らなくて済む。サイト内の読み取りでは同じオリジンの `/r/<ルーム番号>` だけを受け付け、読み取った見知らぬ URL へは移動しない。
- **外部の CDN を使わない**: QR の生成（qrcode-generator 1.4.4）と読み取り（jsQR 1.4.0）は `static/vendor/` に版番号付きで同梱し、使うときだけ読み込む。無料枠の外向き通信（月 1GB）を抑えるため、版番号付きのファイルは 1 週間キャッシュさせ、それ以外は毎回更新を確かめる。
```

- [ ] **Step 7: 全テストを流す**

Run: `uv run pytest -q && node --test tests/js/*.test.mjs`
Expected: pytest がすべて PASS、node が `fail 0`

- [ ] **Step 8: コミット**

```bash
git add deploy/insider-web.service deploy/setup.sh deploy/README.md README.md docs/spec.md
git commit -m "$(cat <<'EOF'
feat: Web版のsystemdユニットとTailscale Funnelでの公開手順を追加

README と仕様書に Web 版の遊び方と設計判断を追記。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: 実機での確認と仕上げ（ユーザーの確認後）

**Files:**
- Delete: `docs/superpowers/specs/2026-10-03-web-voice-input-design.md`
- Delete: `docs/superpowers/plans/2026-10-03-web-voice-input.md`

**Interfaces:**
- Consumes: Task 9 までの成果。サーバーへのデプロイ（`deploy/README.md` の手順）はユーザーが行う
- Produces: なし

- [ ] **Step 1: 実機での確認をユーザーに依頼する**

マイクとカメラは Claude の環境では動かせないので、次の確認表をユーザーに渡す。手元で試す場合は、Mac で `uv run --env-file .env python -m insider_bot.web` を起動したうえで `tailscale funnel 8080` を使うと、スマホから HTTPS で開ける。対象は PC の Chrome、iPhone の Safari、Android の Chrome（Firefox は最後の 2 項目だけ）。

- [ ] 初回の押下でマイクの許可を求められ、許可後に押すと赤くなる
- [ ] 押して話すと認識中の文字が出て、離すと質問が送られる
- [ ] 話し終えてすぐ離しても、質問の末尾が欠けない
- [ ] ボタンの外へずらして離すと取り消される
- [ ] すぐ離すと「長押ししてから話してください」
- [ ] 何も話さずに離すと「聞き取れませんでした」
- [ ] 20 秒押し続けると打ち切られて送られる
- [ ] 長押しで文字選択やメニューが出ない
- [ ] マイクを拒否すると案内が出て文字入力に切り替わる
- [ ] PC でスペースキー長押しで話せ、Esc で取り消せる
- [ ] Firefox では文字入力欄と案内が出る
- [ ] 招待パネルの QR をスマホ標準のカメラで読んで参加できる
- [ ] サイト内の読み取り画面で QR を読んで参加できる。関係ない QR では移動しない

- [ ] **Step 2: 実機で見つかった不具合を直す**

ユーザーから報告があれば、Task 8 Step 9 と同じ進め方で直してコミットする。

- [ ] **Step 3: 設計書と実装計画を片付ける（ユーザーが実機確認を終えてから）**

要点は Task 9 で `docs/spec.md` に移してあるので、前回と同じく両ファイルを削除する。

```bash
git rm docs/superpowers/specs/2026-10-03-web-voice-input-design.md docs/superpowers/plans/2026-10-03-web-voice-input.md
git commit -m "$(cat <<'EOF'
docs: Web版の設計書と実装計画を仕様書へ集約して削除

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```
