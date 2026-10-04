# M2: Web の配役ツール 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M1 で作った村の中核（`insider_bot.village`）を Web 版につなぎ、ブラウザで村を作る・村に入る・特殊村を作るができる配役ツール（`/village`）を、API・画面・`/healthz` とともに足す。

**Architecture:** 中核に Web と LINE の両方が使う小さな追加（ポストバックの解釈、オーナーから見た村の要約、Web の既定応答、UTF-16 の文字数）を入れ、`web/village_api.py` が JSON の API で中核の構造化操作を 1 対 1 で呼ぶ。中核は `web/village_setup.py` でプロセスに 1 つだけ組み立て、既存の `create_app` に任意で差し込む。画面は 1 枚の `village.html` を 4 つのパスで配り、`village.js` がパスで画面を選び、返事モデルを `reply.js` で描く。

**Tech Stack:** Python 3.13、uv、aiohttp、pytest（pytest-asyncio の auto モード）、httpx2。画面は素の ES モジュールと既存の `style.css`、テストは `node --test`。

**Spec:** [docs/superpowers/specs/2026-10-03-unify-line-web-discord-design.md](../specs/2026-10-03-unify-line-web-discord-design.md)（マイルストーン M2）。村の振る舞いの契約は [docs/village.md](../../village.md)。

## Global Constraints

- Python は `>=3.13`、パッケージ管理は uv。`pip` や system python は使わない。テストは `uv run pytest`、画面のテストは `node --test tests/js/*.test.mjs`
- 新しい実行時依存を足さない。HTTP は既存の `httpx2`。画面は外部の CDN を使わず、`static/` に置いたモジュールだけを読む
- 中核の 1 操作の途中で `await` を挟まない（本文を読み終えてから、中核の同期の操作を 1 回呼ぶ）
- 返事の文言は中核の `texts.py` / `messages.py` をそのまま出す。LINE と「全く同じ」に揃えるため、Web だけ言い回しを変えない（画面の見出し・入力欄の説明・入力の誤りの案内は Web 自身の文言でよい）
- 参加者の識別子は `web:<トークン>`。トークンを知る人がその参加者として振る舞えるので、トークンは URL にもログにも出さない。お題もログに出さない
- 「対象の村がない」は 200 の案内文（`docs/village.md` の「既定の応答」の Web の文）。本文の形の誤りは 400。CORS のヘッダーは出さない（同じオリジンだけ）
- 画面は `textContent` だけで文字を入れ、`innerHTML` を使わない。操作対象は 44px 以上。アニメーションは `prefers-reduced-motion` で止める（`style.css` の全体の規則がすでに止める。新しいアニメーションは足さない）。既存のダーク＋ライムの配色（`style.css` の変数）を使う
- 文字数は LINE と同じく UTF-16 の符号単位で数える（Python は `parsing.java_length`、JS は `String.prototype.length`）
- `docs/` は現在形で、コードの現状と一致させる（docs/AGENTS.md）
- コミットメッセージは日本語、既存の書き方（`feat:` / `fix:` / `test:` / `docs:` の接頭辞）。`.claude/launch.json` と `assets/` の未追跡ファイルはコミットしない

## Review Focus

仕様が黙っているが、使う人に当たりそうな入力。各行のテストを所有タスクに入れてある。

1. **村番号の入力欄に全角数字や前後の空白（全角スペースを含む）を入れる** → 「１２３４」も「　1234　」も 1234 として入る。4〜5 桁でない・範囲外は送らずに案内する（Task 5 の `parseVillageInput`）
2. **特殊村のテキストエリアの末尾に改行や空行が残る・Windows の改行（CRLF）** → 末尾の空行は数えず、途中の空行は空のメッセージ（「メッセージは特にありません。」）になる（Task 5 の `parseMessages`）
3. **絵文字を含むお題や特殊村のメッセージがちょうど 5,000 文字・1 文字超え** → UTF-16 で数えて 5,000 までは通り、超えたら 400。画面も同じ数え方で先に案内する（Task 3・Task 5）
4. **村を作る途中で再読み込みする・別のタブで開く** → 作りかけの村の続き（お題・人数・配布状況）から表示する（Task 1 の `latest_owned`、Task 3 の `mine`）
5. **壊れた本文（JSON でない・配列・型違い・`true` を数値として送る・巨大な本文）** → 500 にならず 400。特殊村の最大（100 通×5,000 文字の日本語）は 413 にならず通る（Task 3・Task 4）

---

## ファイル構成

```
src/insider_bot/village/
  parsing.py        java_length を追加（UTF-16 の文字数）
  messages.py       guide_reply を追加（Web の既定応答）
  service.py        OwnedVillage と latest_owned を追加（オーナーから見た最新の村の要約）
  commands.py       postback を追加（LINE と Web で共通のポストバックの解釈）
src/insider_bot/web/
  replyjson.py      返事モデル → Web の JSON
  village_api.py    /api/village/… と画面のパス（VillageApp、add_village_routes）
  village_setup.py  中核をプロセスに 1 つ組み立てる build_village と、カタログの取り直し catalog_refresh
  server.py         create_app に village を差し込む、/healthz、本文の上限、キャッシュの指定
  __main__.py       起動時に build_village と catalog_refresh をつなぐ
  static/
    village.html    配役ツールの画面（4 つのパスで同じ HTML）
    village.css     返事のカードなど配役ツールだけの見た目
    village.js      画面の制御（パスで画面を選ぶ）
    reply.js        返事モデルの描画
    villageurl.js   村番号の読み取り（パス・QR の URL・入力欄）
    villagetoken.js 利用者のトークン
    specialform.js  特殊村フォームの 1 行 1 通の解析と検査
    qr.js           Scanner に読み取り結果の解析関数を渡せるようにする
    index.html      トップページに「インサイダーの配役」への入口を足す
src/insider_bot/config.py   PUBLIC_BASE_URL と ILLUSTRATION_CATALOG_URL
tests/
  test_village_parsing.py / test_village_messages.py / test_village_service.py / test_village_commands.py  追記
  test_web_replyjson.py
  test_web_village_api.py
  test_web_village_setup.py
  test_web_server.py / test_web_config.py  追記
  js/reply.test.mjs  js/villageurl.test.mjs  js/villagetoken.test.mjs  js/specialform.test.mjs
docs/spec.md  docs/village.md  README.md  .env.example
```

## 表記の約束

- 「新規 `パス`:」の直後のコードブロックは、そのファイルの中身すべて。
- 「追記 `パス`（末尾）:」の直後のコードブロックは、ファイルの末尾に足す。足す前に空行を 2 行入れる（Python のトップレベル）か、そのままメソッドとして続ける（クラスの末尾。インデントはブロックのとおり）。
- 「置き換え `パス`:」の直後のコードブロックがいまの文字列で、`↓` の後のコードブロックが置き換え後の文字列。いまの文字列はファイルの中で 1 か所だけに現れる。

---

### Task 1: 中核の追加（ポストバック・村の要約・既定応答・文字数）

**Files:**
- Modify: `src/insider_bot/village/parsing.py`、`src/insider_bot/village/messages.py`、`src/insider_bot/village/service.py`、`src/insider_bot/village/commands.py`
- Test: `tests/test_village_parsing.py`、`tests/test_village_messages.py`、`tests/test_village_service.py`、`tests/test_village_commands.py`（いずれも追記）

**Interfaces:**
- Produces: `parsing.java_length(text: str) -> int`（UTF-16 の符号単位の数）
- Produces: `messages.guide_reply() -> list[Reply]`（`[Text(texts.DEFAULT_MESSAGE)]`）
- Produces: `service.OwnedVillage`（frozen dataclass: `number: int`、`mode: str`（`"normal"` / `"god"` / `"random"`）、`has_topic: bool`、`size: int`、`member_count: int`、`reverse: bool`）と `VillageService.latest_owned(user_id: str) -> OwnedVillage | None`
- Produces: `commands.TOPIC_RANK_LIMIT = 10` と `CommandHandler.postback(user_id: str | None, data: str) -> list[Reply] | None`。値の読み方は Java の `LineEventHandler.handlePostbackEvent` と同じ: `parse_java_int(data)`（前後の空白は除かない）で読めなければ `None`。0〜9 はお題候補（利用者の識別は要らない）、`user_id` が `None` なら `[Text(texts.ERR_UNIDENTIFIED_USER)]`、10000 未満（負の値を含む）は通常村の入室状況、それ以上は特殊村の入室状況

- [ ] **Step 1: 失敗するテストを書く**

置き換え `tests/test_village_parsing.py`:

```python
from insider_bot.village.parsing import java_split, java_trim, parse_java_int
```

↓

```python
from insider_bot.village.parsing import java_length, java_split, java_trim, parse_java_int
```

追記 `tests/test_village_parsing.py`（末尾）:

```python
def test_java_length_counts_utf16_code_units():
    assert java_length("") == 0
    assert java_length("abc") == 3
    assert java_length("あいう") == 3
    # 絵文字はサロゲートペアなので 2
    assert java_length("😀") == 2
    assert java_length("a😀b") == 4
```

追記 `tests/test_village_messages.py`（末尾）:

```python
def test_guide_reply_is_the_default_message_text():
    assert messages.guide_reply() == [
        Text("お題を配りたい方は「お題」または「神」を、\nお題及び役職を確認したい場合は村番号（数字4桁）を入力してください。")
    ]
```

置き換え `tests/test_village_service.py`:

```python
from insider_bot.village.service import VillageService
```

↓

```python
from insider_bot.village.service import OwnedVillage, VillageService
```

追記 `tests/test_village_service.py`（末尾）:

```python
# --- オーナーから見た村 ---


def test_latest_owned_follows_the_setup_of_the_newest_village():
    service, villages, _, _ = make(0)
    assert service.latest_owned(OWNER) is None
    service.create_village(OWNER, god_mode=False)
    number = latest(villages).number
    assert service.latest_owned(OWNER) == OwnedVillage(number, "normal", False, 0, 0, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 2)
    service.join_village("line:m1", number)
    assert service.latest_owned(OWNER) == OwnedVillage(number, "normal", True, 2, 1, False)


def test_latest_owned_reports_the_mode_and_reverse():
    service, _, _, _ = make(0)
    service.create_village(OWNER, god_mode=True)
    assert service.latest_owned(OWNER).mode == "god"
    service.create_village(OWNER, god_mode=False)
    service.set_reverse(OWNER)
    assert service.latest_owned(OWNER).reverse
    service.create_random_village(OWNER)
    owned = service.latest_owned(OWNER)
    assert (owned.mode, owned.has_topic) == ("random", True)
    assert service.latest_owned("line:other") is None
```

追記 `tests/test_village_commands.py`（末尾）:

```python
# --- ポストバック ---


def test_postback_0_to_9_offers_a_topic_candidate_without_a_user():
    handler, _, _, _ = make(0, 0)
    assert handler.postback(None, "2") == messages.candidate_reply("a")
    # 0 は「お題の自動取得」。2・3・4 以外は指定なしの範囲
    assert handler.postback(OWNER, "0") == messages.candidate_reply("a")


def test_postback_with_a_village_number_shows_the_status():
    handler, _, villages, _ = make(0)
    handler.handle(OWNER, "お題")
    handler.handle(OWNER, "2")
    number = latest(villages).number
    handler.handle(MEMBER, str(number))
    assert handler.postback(MEMBER, str(number)) == messages.status_reply(latest(villages), MEMBER)


def test_postback_with_a_special_village_number_shows_the_special_status():
    handler, service, _, specials = make()
    number = service.create_special_village(["a", "b"])
    handler.handle(MEMBER, str(number))
    assert handler.postback(MEMBER, str(number)) == messages.status_reply(specials.get(number), MEMBER)


def test_postback_without_a_user_is_refused_unless_it_is_a_topic_candidate():
    handler, _, villages, _ = make()
    handler.handle(OWNER, "お題")
    assert handler.postback(None, str(latest(villages).number)) == [
        Text("ユーザーを識別できないため操作できません。\nbotとの1対1のトークから操作してください。")
    ]


def test_postback_for_unknown_or_unreadable_data_is_none():
    handler, _, _, _ = make()
    # 「１０」は全角でも数値（10）として読み、該当する村がない。「 3」は前後の空白を除かないので読めない
    for data in ("1234", "99999", "-5", "すいか", "", " 3", "１０"):
        assert handler.postback(OWNER, data) is None, data
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_village_parsing.py tests/test_village_messages.py tests/test_village_service.py tests/test_village_commands.py -q`
Expected: `ImportError: cannot import name 'java_length'` と `ImportError: cannot import name 'OwnedVillage'` で収集に失敗する

- [ ] **Step 3: 中核に足す**

追記 `src/insider_bot/village/parsing.py`（末尾）:

```python
def java_length(text: str) -> int:
    """Java の String.length() と同じく UTF-16 の符号単位で数える（絵文字は 2）。LINE の文字数の上限はこの数え方。"""
    return len(text.encode("utf-16-le")) // 2
```

追記 `src/insider_bot/village/messages.py`（末尾）:

```python
def guide_reply() -> list[Reply]:
    """Web の入口の既定応答（対象の村がないとき）。LINE の確認テンプレートの代替文と同じ案内文を出す。"""
    return [Text(texts.DEFAULT_MESSAGE)]
```

置き換え `src/insider_bot/village/service.py`:

```python
from collections.abc import Sequence
```

↓

```python
from collections.abc import Sequence
from dataclasses import dataclass
```

置き換え `src/insider_bot/village/service.py`:

```python
class VillageService:
```

↓

```python
@dataclass(frozen=True)
class OwnedVillage:
    """オーナーから見た、自分の最新の村の進み具合。画面が次に聞くこと（お題・人数）を決めるのに使う。

    お題そのものは持たない（配布状況の返事で本人には見える）。
    """

    number: int
    mode: str
    has_topic: bool
    size: int
    member_count: int
    reverse: bool


class VillageService:
```

追記 `src/insider_bot/village/service.py`（末尾。`VillageService` のメソッドとして続ける）:

```python
    # --- オーナーから見た村 ---

    def latest_owned(self, user_id: str) -> OwnedVillage | None:
        """利用者がオーナーの、最も新しい村の要約。作成の直後に呼べば、いま作った村を指す。"""
        village = self._villages.find_latest_owned(user_id, lambda v: True)
        if village is None:
            return None
        if village.random_mode:
            mode = "random"
        elif village.has_game_master():
            mode = "god"
        else:
            mode = "normal"
        return OwnedVillage(
            number=village.number,
            mode=mode,
            has_topic=village.topic is not None,
            size=village.size,
            member_count=village.member_count(),
            reverse=village.reverse,
        )
```

置き換え `src/insider_bot/village/commands.py`:

```python
from insider_bot.village import messages
from insider_bot.village.parsing import java_trim, parse_java_int
from insider_bot.village.registry import MAX_VILLAGE_NUMBER
from insider_bot.village.reply import Reply
```

↓

```python
from insider_bot.village import messages, texts
from insider_bot.village.parsing import java_trim, parse_java_int
from insider_bot.village.registry import MAX_VILLAGE_NUMBER, MIN_SPECIAL_NUMBER
from insider_bot.village.reply import Reply, Text
```

置き換え `src/insider_bot/village/commands.py`:

```python
# 設定できる参加人数の上限。これを超える数値は通常村の番号として扱う
MAX_SIZE_INPUT = 100
```

↓

```python
# 設定できる参加人数の上限。これを超える数値は通常村の番号として扱う
MAX_SIZE_INPUT = 100
# ポストバックの値がこれ未満なら、村番号ではなくお題候補の難易度
TOPIC_RANK_LIMIT = 10
```

追記 `src/insider_bot/village/commands.py`（末尾。`CommandHandler` のメソッドとして続ける）:

```python
    def postback(self, user_id: str | None, data: str) -> list[Reply] | None:
        """ボタンのポストバック。LINE と Web で共通の 1 組だけを持つ。

        0〜9 はお題候補で、利用者の識別は要らない。それ以外は入室状況で、識別できない利用者には状態を変えずに
        1 対 1 のトークを促す。値は Integer.parseInt と同じ規則で読み、前後の空白は除かない。読めなければ None。
        """
        number = parse_java_int(data)
        if number is None:
            return None
        if 0 <= number < TOPIC_RANK_LIMIT:
            return self.topic_candidate(number)
        if user_id is None:
            return [Text(texts.ERR_UNIDENTIFIED_USER)]
        if number < MIN_SPECIAL_NUMBER:
            return self._service.village_status(user_id, number)
        return self._service.special_village_status(user_id, number)
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_village_parsing.py tests/test_village_messages.py tests/test_village_service.py tests/test_village_commands.py -q`
Expected: `117 passed`

Run: `uv run pytest -q`
Expected: `376 passed, 4 deselected`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/village/parsing.py src/insider_bot/village/messages.py src/insider_bot/village/service.py src/insider_bot/village/commands.py tests/test_village_parsing.py tests/test_village_messages.py tests/test_village_service.py tests/test_village_commands.py
git commit -m "feat: 村の中核にポストバックの解釈・オーナーから見た村の要約・Web の既定応答を足す"
```

---

### Task 2: 返事モデルの Web 向け JSON

**Files:**
- Create: `src/insider_bot/web/replyjson.py`
- Test: `tests/test_web_replyjson.py`

**Interfaces:**
- Consumes: `insider_bot.village.reply` の `Text` / `Image` / `Buttons` / `Confirm` / `MessageAction` / `PostbackAction` / `UriAction`
- Produces: `action_json(action) -> dict[str, str]`、`reply_json(reply) -> dict[str, Any]`、`replies_json(replies) -> list[dict[str, Any]]`。形は次のとおり（Web には文字数の制限がないので `overflow` と `alt_text` は送らない）:
  - `{"type": "text", "text": str}`、`{"type": "image", "url": str}`
  - `{"type": "buttons", "text": str, "image": str | None, "title": str | None, "actions": [...]}`
  - `{"type": "confirm", "text": str, "actions": [...]}`
  - ボタン: `{"type": "message", "label", "text"}`、`{"type": "postback", "label", "data"}`、`{"type": "uri", "label", "uri"}`
  - 知らない型は `TypeError`

- [ ] **Step 1: 失敗するテストを書く**

新規 `tests/test_web_replyjson.py`:

```python
import pytest

from insider_bot.village import messages
from insider_bot.village.illust import Illustrations
from insider_bot.village.model import Village
from insider_bot.village.reply import Buttons, Image, MessageAction, PostbackAction, Text, UriAction
from insider_bot.web.replyjson import action_json, replies_json, reply_json
from tests.fakes import FixedRandom


def test_text_and_image():
    assert reply_json(Text("本文\n2 行目")) == {"type": "text", "text": "本文\n2 行目"}
    assert reply_json(Image("/static/roles/GM.png")) == {"type": "image", "url": "/static/roles/GM.png"}


def test_actions():
    assert action_json(MessageAction("確定", "すいか")) == {"type": "message", "label": "確定", "text": "すいか"}
    assert action_json(PostbackAction("初心者", "2")) == {"type": "postback", "label": "初心者", "data": "2"}
    assert action_json(UriAction("ご意見", "https://x")) == {"type": "uri", "label": "ご意見", "uri": "https://x"}


def test_buttons_drop_overflow_and_alt_text_because_the_web_has_no_length_limit():
    buttons = Buttons(
        "本文",
        (PostbackAction("入室状況確認", "1234"),),
        image="/static/roles/INSIDER.png",
        title="1234村",
        alt_text="代替",
        overflow=(Text("本文"),),
    )
    assert reply_json(buttons) == {
        "type": "buttons",
        "text": "本文",
        "image": "/static/roles/INSIDER.png",
        "title": "1234村",
        "actions": [{"type": "postback", "label": "入室状況確認", "data": "1234"}],
    }


def test_buttons_without_image_or_title():
    assert reply_json(Buttons("本文", ())) == {"type": "buttons", "text": "本文", "image": None, "title": None, "actions": []}


def test_confirm():
    assert reply_json(messages.default_reply()[0]) == {
        "type": "confirm",
        "text": "村の作成をしますか？",
        "actions": [
            {"type": "message", "label": "GM", "text": "お題"},
            {"type": "message", "label": "神", "text": "神"},
        ],
    }


def test_the_web_draws_only_the_body_of_the_same_reply_model():
    # GM の返事は 3 段の overflow を持つが、Web は本体だけを描く
    village = Village("owner")
    village.number = 1234
    village.set_topic("すいか")
    village.mark_god_mode()
    assert village.configure(2, FixedRandom(0, 1))
    village.join("a")
    village.join("gm")
    reply = messages.role_reply(village, "gm", Illustrations("", FixedRandom(0)))
    assert replies_json(reply) == [
        {
            "type": "buttons",
            "text": "役職はＧＭです。\n2/2人にお題を配りました。お題は『すいか』です。",
            "image": "/static/roles/GM.png",
            "title": None,
            "actions": [{"type": "postback", "label": "入室状況確認", "data": "1234"}],
        }
    ]


def test_unknown_types_are_rejected():
    with pytest.raises(TypeError):
        reply_json(object())
    with pytest.raises(TypeError):
        action_json(object())
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_web_replyjson.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.web.replyjson'`

- [ ] **Step 3: 実装する**

新規 `src/insider_bot/web/replyjson.py`:

```python
"""返事モデルを Web の画面向けの JSON にする。

Web には文字数の制限がないので、LINE 向けの代わりの返事（overflow）と代替文（alt_text）は送らない。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from insider_bot.village.reply import Action, Buttons, Confirm, Image, MessageAction, PostbackAction, Reply, Text, UriAction


def action_json(action: Action) -> dict[str, str]:
    if isinstance(action, MessageAction):
        return {"type": "message", "label": action.label, "text": action.text}
    if isinstance(action, PostbackAction):
        return {"type": "postback", "label": action.label, "data": action.data}
    if isinstance(action, UriAction):
        return {"type": "uri", "label": action.label, "uri": action.uri}
    raise TypeError(f"未知のボタン: {type(action).__name__}")


def reply_json(reply: Reply) -> dict[str, Any]:
    if isinstance(reply, Text):
        return {"type": "text", "text": reply.text}
    if isinstance(reply, Image):
        return {"type": "image", "url": reply.url}
    if isinstance(reply, Buttons):
        return {
            "type": "buttons",
            "text": reply.text,
            "image": reply.image,
            "title": reply.title,
            "actions": [action_json(action) for action in reply.actions],
        }
    if isinstance(reply, Confirm):
        return {"type": "confirm", "text": reply.text, "actions": [action_json(action) for action in reply.actions]}
    raise TypeError(f"未知の返事: {type(reply).__name__}")


def replies_json(replies: Iterable[Reply]) -> list[dict[str, Any]]:
    return [reply_json(reply) for reply in replies]
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_web_replyjson.py -q`
Expected: `7 passed`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/replyjson.py tests/test_web_replyjson.py
git commit -m "feat: 返事モデルを Web の画面向けの JSON にする"
```

---

### Task 3: 配役ツールの API（/api/village/…）と画面のパス

**Files:**
- Create: `src/insider_bot/web/village_api.py`
- Test: `tests/test_web_village_api.py`

**Interfaces:**
- Consumes: Task 1 の `VillageService.latest_owned` / `OwnedVillage`、`CommandHandler.postback`、`messages.guide_reply`、`parsing.java_length`。Task 2 の `replies_json`。M1 の `VillageService`（`create_village(user_id, god_mode)`、`create_random_village`、`set_topic`、`set_size`、`set_reverse`、`convert_to_werewords`、`join_village`、`join_special_village`、`create_special_village(texts) -> int`）、`CommandHandler.handle`、`commands.MAX_SIZE_INPUT`、`registry.MIN_SPECIAL_NUMBER`
- Produces: `VillageApp(service: VillageService, commands: CommandHandler)`（frozen dataclass）、`VILLAGE`（`web.AppKey`）、`add_village_routes(app: web.Application, village: VillageApp, page: Path) -> None`、定数 `TOKEN_PATTERN`、`MAX_TEXT_LENGTH = 5000`、`MAX_POSTBACK_LENGTH = 300`、`MAX_SPECIAL_MESSAGES = 100`、`MAX_SPECIAL_MESSAGE_LENGTH = 5000`、`PAGE_PATHS`
- HTTP の契約:
  - `POST /api/village/{create,mine,topic,size,reverse,werewords,join,text,postback}` 本文 `{"token": str, ...}` → 200 `{"found": bool, "replies": [...], "village": {...} | null}`。`village` は `{"number", "mode", "has_topic", "size", "member_count", "reverse"}`（その利用者が作った最新の村）。対象の村がないときは `found: false` で `replies` は `guide_reply()` の JSON
  - `POST /api/village/special` 本文 `{"messages": [str | null, ...]}`（`token` は要らない）→ 200 `{"number": int}`
  - 本文の形の誤り → 400 `{"error": "入力が正しくありません"}`
  - `GET /village`、`/village/`、`/village/new`、`/village/special`、`/v/{number}`、`/v/{number}/` → `page` の HTML

- [ ] **Step 1: 失敗するテストを書く**

新規 `tests/test_web_village_api.py`:

```python
import contextlib
import logging
import random

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from insider_bot.village import messages
from insider_bot.village.commands import CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.service import VillageService
from insider_bot.village.words import parse_dictionary
from insider_bot.web.replyjson import replies_json
from insider_bot.web.village_api import VillageApp, add_village_routes
from tests.fakes import FixedRandom

OWNER = "owner-token-0123456789"
MEMBER = "member-token-012345678"
DICTIONARY = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])
GUIDE = replies_json(messages.guide_reply())


@pytest.fixture
def page(tmp_path):
    path = tmp_path / "village.html"
    path.write_text("<!doctype html><title>配役</title>", encoding="utf-8")
    return path


@contextlib.asynccontextmanager
async def serve(page, *draws):
    """配役の乱数だけを固定し、採番は本物の乱数に任せる。"""
    rng = FixedRandom(*draws) if draws else random.Random(3)
    service = VillageService(
        VillageRegistry(random.Random(1)),
        SpecialVillageRegistry(random.Random(2)),
        DICTIONARY,
        Illustrations("", FixedRandom(0)),
        rng,
    )
    app = web.Application()
    add_village_routes(app, VillageApp(service, CommandHandler(service, "/village/special")), page)
    async with TestClient(TestServer(app)) as client:
        yield client


async def call(client, name, token=OWNER, **fields):
    response = await client.post(f"/api/village/{name}", json={"token": token, **fields})
    assert response.status == 200, await response.text()
    return await response.json()


async def create_special(client, messages_):
    response = await client.post("/api/village/special", json={"messages": messages_})
    assert response.status == 200, await response.text()
    return (await response.json())["number"]


# --- 村を作る ---


async def test_create_returns_the_reply_and_the_new_village(page):
    async with serve(page) as client:
        body = await call(client, "create", kind="normal")
        number = body["village"]["number"]
        assert 1000 <= number <= 9999
        assert body["found"] is True
        assert body["replies"] == replies_json(messages.created_reply(number))
        assert body["village"] == {
            "number": number,
            "mode": "normal",
            "has_topic": False,
            "size": 0,
            "member_count": 0,
            "reverse": False,
        }


async def test_create_god_and_random_villages(page):
    async with serve(page, 0) as client:
        assert (await call(client, "create", kind="god"))["village"]["mode"] == "god"
        body = await call(client, "create", kind="random")
        assert (body["village"]["mode"], body["village"]["has_topic"]) == ("random", True)
        assert body["replies"] == replies_json(messages.random_created_reply(body["village"]["number"]))


async def test_mine_resumes_the_newest_village_without_changing_it(page):
    async with serve(page) as client:
        assert await call(client, "mine") == {"found": True, "replies": [], "village": None}
        number = (await call(client, "create", kind="normal"))["village"]["number"]
        body = await call(client, "mine")
        assert (body["replies"], body["village"]["number"], body["village"]["has_topic"]) == ([], number, False)


# --- お題と人数 ---


async def test_topic_then_size_then_the_status(page):
    async with serve(page, 0) as client:
        number = (await call(client, "create", kind="normal"))["village"]["number"]
        body = await call(client, "topic", topic="すいか")
        assert body["village"]["has_topic"] is True
        body = await call(client, "size", size=3)
        assert body["village"]["size"] == 3
        assert body["replies"][0]["image"] == "/static/roles/GM.png"
        assert body["replies"][0]["title"] == f"{number}村"
        # オーナーが自分の村番号で入ると配布状況
        status = await call(client, "join", number=number)
        assert status["replies"][0]["text"] == f"{number}村：0/3人にお題を配りました。お題は『すいか』です。"


async def test_a_topic_cannot_be_set_twice_and_the_guide_is_returned(page):
    async with serve(page) as client:
        await call(client, "create", kind="normal")
        await call(client, "topic", topic="すいか")
        body = await call(client, "topic", topic="めろん")
        assert (body["found"], body["replies"]) == (False, GUIDE)


async def test_topic_of_exactly_5000_utf16_units_is_accepted(page):
    async with serve(page) as client:
        await call(client, "create", kind="normal")
        body = await call(client, "topic", topic="😀" * 2500)
        assert body["village"]["has_topic"] is True


async def test_size_of_one_or_less_is_answered_with_the_core_message(page):
    async with serve(page) as client:
        await call(client, "create", kind="normal")
        for size in (1, 0, -3):
            body = await call(client, "size", size=size)
            assert body["replies"] == replies_json(messages.size_error_reply()), size
        assert body["village"]["size"] == 0


async def test_random_village_size_returns_the_owners_role(page):
    async with serve(page, 0, 0, 1) as client:
        await call(client, "create", kind="random")
        body = await call(client, "size", size=3)
        assert body["replies"][0]["text"].endswith("人』に設定しました。\n皆さんに村番号を伝えてください。")
        assert body["replies"][1]["image"] == "/static/roles/INSIDER.png"


# --- 逆村と Werewords ---


async def test_reverse_and_werewords(page):
    async with serve(page, 0) as client:
        number = (await call(client, "create", kind="normal"))["village"]["number"]
        await call(client, "topic", topic="すいか")
        await call(client, "size", size=3)
        body = await call(client, "reverse")
        assert body["replies"] == [
            {"type": "text", "text": f"{number}村 を『逆村』に設定しました。\nお題を知らない村人が1人となります。"}
        ]
        assert body["village"]["reverse"] is True
        body = await call(client, "werewords")
        assert "ワーワーズ" in body["replies"][0]["text"]


# --- 村に入る ---


async def test_participants_join_with_their_own_token(page):
    async with serve(page, 0) as client:
        number = (await call(client, "create", kind="normal"))["village"]["number"]
        await call(client, "topic", topic="すいか")
        await call(client, "size", size=2)
        body = await call(client, "join", token=MEMBER, number=number)
        assert body["replies"][0]["text"] == "あなたの役職はインサイダーです。お題は『すいか』です。"
        assert body["replies"][0]["image"] == "/static/roles/INSIDER.png"
        # 参加者には自分の村がない
        assert body["village"] is None
        # 再表示しても同じ役職
        assert await call(client, "join", token=MEMBER, number=number) == body


async def test_special_village_numbers_join_the_special_village(page):
    async with serve(page) as client:
        number = await create_special(client, ["占い師", None, ""])
        body = await call(client, "join", token=MEMBER, number=number)
        assert body["found"] is True
        assert body["replies"][0]["type"] == "buttons"


async def test_unknown_village_numbers_get_the_guide(page):
    async with serve(page) as client:
        for number in (0, 50, 1234, 99999):
            body = await call(client, "join", number=number)
            assert (body["found"], body["replies"]) == (False, GUIDE), number


# --- 返事のボタン ---


async def test_message_buttons_are_read_like_a_line_message(page):
    async with serve(page) as client:
        body = await call(client, "text", text="お題")
        assert body["replies"] == replies_json(messages.created_reply(body["village"]["number"]))
        # お題の候補の「確定」は、その文字列を送ったことになる
        body = await call(client, "text", text="a")
        assert body["village"]["has_topic"] is True


async def test_postback_buttons(page):
    async with serve(page, 0) as client:
        body = await call(client, "postback", data="0")
        assert body["replies"] == replies_json(messages.candidate_reply("a"))
        body = await call(client, "postback", data="すいか")
        assert (body["found"], body["replies"]) == (False, GUIDE)


# --- 特殊村 ---


async def test_special_village_creation(page):
    async with serve(page) as client:
        assert 10000 <= await create_special(client, ["a"] * 100) <= 99998
        # UTF-16 でちょうど 5,000
        await create_special(client, ["😀" * 2500])


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"messages": []},
        {"messages": ["a"] * 101},
        {"messages": "a"},
        {"messages": [1]},
        {"messages": ["😀" * 2500 + "a"]},
    ],
)
async def test_special_village_rejects_undeliverable_messages(page, payload):
    async with serve(page) as client:
        response = await client.post("/api/village/special", json=payload)
        assert response.status == 400


# --- 入力の誤り ---


@pytest.mark.parametrize(
    ("name", "fields"),
    [
        ("create", {"kind": "secret"}),
        ("create", {}),
        ("topic", {"topic": ""}),
        ("topic", {"topic": 3}),
        ("topic", {"topic": "😀" * 2500 + "a"}),
        ("size", {"size": "3"}),
        ("size", {"size": True}),
        ("size", {"size": 101}),
        ("join", {"number": "1234"}),
        ("join", {"number": -1}),
        ("join", {"number": 2**31}),
        ("text", {"text": ""}),
        ("postback", {"data": 3}),
        ("postback", {"data": "1" * 301}),
    ],
)
async def test_malformed_fields_are_rejected(page, name, fields):
    async with serve(page) as client:
        response = await client.post(f"/api/village/{name}", json={"token": OWNER, **fields})
        assert response.status == 400
        assert await response.json() == {"error": "入力が正しくありません"}


@pytest.mark.parametrize("token", [None, "", "short", "has space 0123456789", "あ" * 22, "x" * 65])
async def test_missing_or_malformed_tokens_are_rejected(page, token):
    async with serve(page) as client:
        response = await client.post("/api/village/mine", json={"token": token})
        assert response.status == 400


async def test_non_json_bodies_are_rejected(page):
    async with serve(page) as client:
        for data in (b"", b"not json", b"[1, 2]", b"\xff\xfe"):
            response = await client.post("/api/village/mine", data=data, headers={"Content-Type": "application/json"})
            assert response.status == 400, data


async def test_the_token_and_the_topic_are_not_logged(page, caplog):
    with caplog.at_level(logging.DEBUG):
        async with serve(page, 0) as client:
            await call(client, "create", kind="normal")
            await call(client, "topic", topic="ひみつのおだい")
            await call(client, "size", size=2)
    assert OWNER not in caplog.text
    assert "ひみつのおだい" not in caplog.text


# --- 画面 ---


async def test_the_page_is_served_on_every_village_path(page):
    async with serve(page) as client:
        for path in ("/village", "/village/", "/village/new", "/village/special", "/v/1234", "/v/12345/"):
            response = await client.get(path)
            assert response.status == 200, path
            assert "配役" in await response.text()
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_web_village_api.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.web.village_api'`

- [ ] **Step 3: 実装する**

新規 `src/insider_bot/web/village_api.py`:

```python
"""配役ツールの HTTP API（/api/village/…）と画面のパス。

中核の構造化操作を 1 対 1 で呼び、返事モデルを JSON で返す。画面の進み方の判断はブラウザ側にあり、
ここは入力の検査と中核の呼び出しだけを持つ。本文を読み終えてから中核の同期の操作を 1 回呼ぶので、
中核の 1 操作の途中で await を挟まない。

利用者は本文の token で識別する（web:<トークン>）。トークンを知る人がその参加者として振る舞えるので、
トークンとお題はログに出さない。
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from insider_bot.village import messages
from insider_bot.village.commands import MAX_SIZE_INPUT, CommandHandler
from insider_bot.village.parsing import java_length
from insider_bot.village.registry import MIN_SPECIAL_NUMBER
from insider_bot.village.reply import Reply
from insider_bot.village.service import OwnedVillage, VillageService
from insider_bot.web.replyjson import replies_json

# 推測されにくい長さの英数字と - _。ブラウザは 16 バイトの乱数を base64url にした 22 文字を使う
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}")
# LINE のテキストメッセージの上限にそろえる。数え方も LINE と同じ UTF-16 の符号単位
MAX_TEXT_LENGTH = 5000
# LINE のポストバックの data の上限
MAX_POSTBACK_LENGTH = 300
# 特殊村は通常村の参加人数の上限にそろえる（LineBot の特殊村フォームと同じ）
MAX_SPECIAL_MESSAGES = 100
MAX_SPECIAL_MESSAGE_LENGTH = 5000
# 村番号として受け付ける整数の範囲（Java の int）。範囲内で村がなければ「対象の村がない」
_MAX_NUMBER = 2**31 - 1
_KINDS = ("normal", "god", "random")
_BAD_REQUEST = {"error": "入力が正しくありません"}

# 画面はどのパスでも同じ HTML で、何を表示するかは画面側がパスで決める
PAGE_PATHS = ("/village", "/village/", "/village/new", "/village/special", "/v/{number}", "/v/{number}/")

# 日本語を \uXXXX に膨らませない（外向き通信を抑えるため）
_dumps = functools.partial(json.dumps, ensure_ascii=False)


@dataclass(frozen=True)
class VillageApp:
    """Web と LINE の入口が共有する村の中核。同じプロセスに 1 つだけ作る。"""

    service: VillageService
    commands: CommandHandler


VILLAGE = web.AppKey("village", VillageApp)


class BadRequest(Exception):
    """本文の形が違う。400 で返す。"""


async def _read_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        # JSON として読めない本文と、UTF-8 でない本文（UnicodeDecodeError も ValueError）
        raise BadRequest from None
    if not isinstance(body, dict):
        raise BadRequest
    return body


def _user_of(body: dict[str, Any]) -> str:
    token = body.get("token")
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise BadRequest
    return f"web:{token}"


def _text_field(body: dict[str, Any], name: str, max_length: int) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value or java_length(value) > max_length:
        raise BadRequest
    return value


def _int_field(body: dict[str, Any], name: str) -> int:
    value = body.get(name)
    # JSON の true / false は Python では int の仲間なので、明示的に除く
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequest
    return value


def _owned_json(owned: OwnedVillage | None) -> dict[str, Any] | None:
    if owned is None:
        return None
    return {
        "number": owned.number,
        "mode": owned.mode,
        "has_topic": owned.has_topic,
        "size": owned.size,
        "member_count": owned.member_count,
        "reverse": owned.reverse,
    }


def _bad_request() -> web.Response:
    return web.json_response(_BAD_REQUEST, status=400, dumps=_dumps)


# --- 操作。本文の検査を先に済ませてから中核を 1 回だけ呼ぶ ---


def _create(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    kind = body.get("kind")
    if kind not in _KINDS:
        raise BadRequest
    if kind == "random":
        return village.service.create_random_village(user_id)
    return village.service.create_village(user_id, god_mode=kind == "god")


def _mine(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    """何も変えず、最新の村の要約だけを返す。画面の再読み込みで続きから表示するため。"""
    return []


def _topic(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    return village.service.set_topic(user_id, _text_field(body, "topic", MAX_TEXT_LENGTH))


def _size(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    size = _int_field(body, "size")
    # 101 以上は LINE では村番号として扱う入力なので、人数としては受け付けない。1 以下は中核が案内する
    if size > MAX_SIZE_INPUT:
        raise BadRequest
    return village.service.set_size(user_id, size)


def _reverse(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    return village.service.set_reverse(user_id)


def _werewords(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    return village.service.convert_to_werewords(user_id)


def _join(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    number = _int_field(body, "number")
    if not 0 <= number <= _MAX_NUMBER:
        raise BadRequest
    # 入る画面の入力なので、100 以下を人数として扱う LINE のテキストの解釈は通さない
    if number >= MIN_SPECIAL_NUMBER:
        return village.service.join_special_village(user_id, number)
    return village.service.join_village(user_id, number)


def _text(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    """返事のメッセージのボタン。LINE でその文字列を送ったのと同じ解釈をする。"""
    return village.commands.handle(user_id, _text_field(body, "text", MAX_TEXT_LENGTH))


def _postback(village: VillageApp, user_id: str, body: dict[str, Any]) -> list[Reply] | None:
    """返事のポストバックのボタン。LINE のポストバックと同じ解釈をする。"""
    data = body.get("data")
    if not isinstance(data, str) or java_length(data) > MAX_POSTBACK_LENGTH:
        raise BadRequest
    return village.commands.postback(user_id, data)


Operation = Callable[[VillageApp, str, dict[str, Any]], "list[Reply] | None"]

_OPERATIONS: dict[str, Operation] = {
    "create": _create,
    "mine": _mine,
    "topic": _topic,
    "size": _size,
    "reverse": _reverse,
    "werewords": _werewords,
    "join": _join,
    "text": _text,
    "postback": _postback,
}


def _api(operation: Operation) -> Callable[[web.Request], Any]:
    """本文を読み、利用者を識別し、中核の操作を 1 回呼んで返事を返すハンドラを作る。"""

    async def handler(request: web.Request) -> web.Response:
        village = request.app[VILLAGE]
        try:
            body = await _read_body(request)
            user_id = _user_of(body)
            replies = operation(village, user_id, body)
        except BadRequest:
            return _bad_request()
        # 対象の村がない（None）は Web の既定応答（案内文）にする。画面が次に何を聞くかを決められるよう、
        # 利用者が作った最新の村の要約を毎回添える
        payload = {
            "found": replies is not None,
            "replies": replies_json(replies if replies is not None else messages.guide_reply()),
            "village": _owned_json(village.service.latest_owned(user_id)),
        }
        return web.json_response(payload, dumps=_dumps)

    return handler


def _special_messages(body: dict[str, Any]) -> list[str | None]:
    items = body.get("messages")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_SPECIAL_MESSAGES:
        raise BadRequest
    for item in items:
        # null と空文字は中核で「メッセージは特にありません。」になる
        if item is not None and (not isinstance(item, str) or java_length(item) > MAX_SPECIAL_MESSAGE_LENGTH):
            raise BadRequest
    return items


async def create_special(request: web.Request) -> web.Response:
    """特殊村を作る。配るメッセージの列だけを受け取り、利用者の識別は要らない。"""
    village = request.app[VILLAGE]
    try:
        items = _special_messages(await _read_body(request))
    except BadRequest:
        return _bad_request()
    return web.json_response({"number": village.service.create_special_village(items)}, dumps=_dumps)


def add_village_routes(app: web.Application, village: VillageApp, page: Path) -> None:
    """配役ツールの API と画面のパスを足す。"""
    app[VILLAGE] = village
    for name, operation in _OPERATIONS.items():
        app.router.add_post(f"/api/village/{name}", _api(operation))
    app.router.add_post("/api/village/special", create_special)

    async def serve_page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(page)

    for path in PAGE_PATHS:
        app.router.add_get(path, serve_page)
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_web_village_api.py -q`
Expected: `44 passed`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/village_api.py tests/test_web_village_api.py
git commit -m "feat: 配役ツールの API（/api/village）と画面のパスを足す"
```

---

### Task 4: 起動と配線（設定・create_app・/healthz・カタログの取り直し）

**Files:**
- Create: `src/insider_bot/web/village_setup.py`
- Modify: `src/insider_bot/config.py`、`src/insider_bot/web/server.py`、`src/insider_bot/web/__main__.py`
- Test: `tests/test_web_village_setup.py`（新規）、`tests/test_web_config.py`・`tests/test_web_server.py`（追記）

**Interfaces:**
- Consumes: Task 3 の `VillageApp`、`add_village_routes`。M1 の `Illustrations(base_url, rng=None, catalog_url=None)` と `refresh(client)`、`load_dictionary()`、`VillageRegistry()`、`SpecialVillageRegistry()`、`VillageService`、`CommandHandler(service, special_form_url)`
- Produces: `village_setup.build_village(public_base_url: str, catalog_url: str | None) -> VillageApp`、`village_setup.catalog_refresh(illust, interval=CATALOG_REFRESH_SECONDS, client_factory=httpx2.AsyncClient)`（aiohttp の `cleanup_ctx` に渡す関数を返す）、`CATALOG_REFRESH_SECONDS = 300.0`、`SPECIAL_FORM_PATH = "/village/special"`
- Produces: `WebConfig.public_base_url: str`（既定 `""`、末尾の `/` なし）、`WebConfig.illustration_catalog_url: str | None`（既定 `None`）
- Produces: `create_app(hub, static_dir=STATIC_DIR, cleanup_interval=CLEANUP_INTERVAL_SECONDS, village: VillageApp | None = None)`。`village` を渡したときだけ配役ツールのパスが生える。`GET /healthz` は常に 200 `ok`。本文の上限は `MAX_REQUEST_BYTES = 2 * 1024 * 1024`

- [ ] **Step 1: 失敗するテストを書く**

新規 `tests/test_web_village_setup.py`:

```python
import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from insider_bot.village.reply import Text
from insider_bot.web.village_setup import build_village, catalog_refresh


def test_build_village_uses_the_bundled_dictionary_and_root_relative_images():
    village = build_village("", None)
    assert village.service.pick_topic(2) is not None
    assert village.service.illust.default_url("GM") == "/static/roles/GM.png"
    assert village.commands.handle("web:someone", "@特殊") == [Text("/village/special")]


def test_build_village_uses_the_public_base_url():
    village = build_village("https://game.example.com", None)
    assert village.service.illust.default_url("GM") == "https://game.example.com/static/roles/GM.png"
    assert village.commands.handle("web:someone", "@特殊") == [Text("https://game.example.com/village/special")]


class RecordingIllust:
    def __init__(self):
        self.clients = []

    async def refresh(self, client):
        self.clients.append(client)


class FakeClient:
    closed = False

    async def aclose(self):
        self.closed = True


async def test_the_catalog_is_refreshed_at_start_and_periodically_and_the_client_is_closed():
    illust = RecordingIllust()
    client = FakeClient()
    app = web.Application()
    app.cleanup_ctx.append(catalog_refresh(illust, interval=0.01, client_factory=lambda: client))
    async with TestClient(TestServer(app)):
        async with asyncio.timeout(2):
            while len(illust.clients) < 3:
                await asyncio.sleep(0.01)
    assert illust.clients[0] is client
    assert client.closed
```

追記 `tests/test_web_config.py`（末尾）:

```python
def test_web_village_urls_are_unset_by_default():
    config = load_web_config({"TYPESAFE_API_KEY": "ts-key"})
    assert (config.public_base_url, config.illustration_catalog_url) == ("", None)


def test_web_village_urls():
    config = load_web_config(
        {
            "TYPESAFE_API_KEY": "ts-key",
            "PUBLIC_BASE_URL": "https://game.example.com/",
            "ILLUSTRATION_CATALOG_URL": "https://script.google.com/macros/s/x/exec",
        }
    )
    assert config.public_base_url == "https://game.example.com"
    assert config.illustration_catalog_url == "https://script.google.com/macros/s/x/exec"


@pytest.mark.parametrize(
    "value",
    ["game.example.com", "ftp://game.example.com", "https://", "https://game.example.com/sub", "https://game.example.com/?x=1"],
)
def test_web_public_base_url_must_be_an_origin(value):
    with pytest.raises(ConfigError, match="PUBLIC_BASE_URL"):
        load_web_config({"TYPESAFE_API_KEY": "ts-key", "PUBLIC_BASE_URL": value})


@pytest.mark.parametrize("value", ["http://script.google.com/macros/s/x/exec", "script.google.com/macros/s/x/exec"])
def test_web_catalog_url_must_be_https(value):
    with pytest.raises(ConfigError, match="ILLUSTRATION_CATALOG_URL"):
        load_web_config({"TYPESAFE_API_KEY": "ts-key", "ILLUSTRATION_CATALOG_URL": value})
```

置き換え `tests/test_web_server.py`:

```python
from insider_bot.web.server import WsConnection, create_app
```

↓

```python
from insider_bot.web.server import WsConnection, create_app
from insider_bot.web.village_setup import build_village
```

置き換え `tests/test_web_server.py`:

```python
async def serve(static_dir, judge=None, **limits):
```

↓

```python
async def serve(static_dir, judge=None, village=None, **limits):
```

置き換え `tests/test_web_server.py`:

```python
    async with TestClient(TestServer(create_app(hub, static_dir=static_dir))) as client:
```

↓

```python
    async with TestClient(TestServer(create_app(hub, static_dir=static_dir, village=village))) as client:
```

追記 `tests/test_web_server.py`（末尾）:

```python
# --- 配役ツールと /healthz ---


async def test_healthz_answers_ok(static_dir):
    async with serve(static_dir) as client:
        response = await client.get("/healthz")
        assert (response.status, await response.text()) == (200, "ok")


async def test_village_routes_exist_only_when_the_village_is_given(static_dir):
    (static_dir / "village.html").write_text("<!doctype html><title>配役</title>", encoding="utf-8")
    async with serve(static_dir) as client:
        assert (await client.get("/village")).status == 404
    async with serve(static_dir, village=build_village("", None)) as client:
        response = await client.get("/v/1234")
        assert response.status == 200
        assert response.headers["Cache-Control"] == "no-cache"
        response = await client.post("/api/village/create", json={"token": "a" * 22, "kind": "normal"})
        assert response.status == 200


async def test_the_largest_special_village_fits_the_request_size_limit(static_dir):
    async with serve(static_dir, village=build_village("", None)) as client:
        # 100 通×5,000 文字の日本語は UTF-8 で約 1.5MB。aiohttp の既定の上限（1MiB）では 413 になる。
        # ブラウザの JSON.stringify と同じく、日本語を \uXXXX にエスケープせずに送る
        body = json.dumps({"messages": ["あ" * 5000] * 100}, ensure_ascii=False).encode()
        response = await client.post("/api/village/special", data=body, headers={"Content-Type": "application/json"})
        assert response.status == 200
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_web_village_setup.py tests/test_web_config.py tests/test_web_server.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.web.village_setup'` で収集に失敗する

- [ ] **Step 3: 中核をプロセスに 1 つ組み立てる部品を書く**

新規 `src/insider_bot/web/village_setup.py`:

```python
"""村の中核をプロセスに 1 つだけ組み立て、役職画像のカタログを取り直し続ける。

Web と LINE の入口は同じ VillageApp を共有する。村のレジストリはメモリにしかないので、
「LINE で作った村に Web から入る」には同じプロセスの同じ中核を使うしかない。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx2
from aiohttp import web

from insider_bot.village.commands import CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.service import VillageService
from insider_bot.village.words import load_dictionary
from insider_bot.web.village_api import VillageApp

# 外部カタログを取り直す間隔
CATALOG_REFRESH_SECONDS = 300.0
SPECIAL_FORM_PATH = "/village/special"


def build_village(public_base_url: str, catalog_url: str | None) -> VillageApp:
    """辞書を 1 度だけ読み、画像とフォームの URL は公開 URL から組み立てる。

    公開 URL が空なら、サイト内の絶対パス（/static/roles/…、/village/special）になる。Web だけならこれで足りる。
    """
    illust = Illustrations(public_base_url, catalog_url=catalog_url)
    service = VillageService(VillageRegistry(), SpecialVillageRegistry(), load_dictionary(), illust)
    return VillageApp(service, CommandHandler(service, public_base_url.rstrip("/") + SPECIAL_FORM_PATH))


def catalog_refresh(
    illust: Any,
    interval: float = CATALOG_REFRESH_SECONDS,
    client_factory: Callable[[], Any] = httpx2.AsyncClient,
) -> Callable[[web.Application], AsyncIterator[None]]:
    """起動直後と以降 interval 秒ごとにカタログを取り直す、aiohttp の cleanup_ctx。

    取り直しの失敗は Illustrations.refresh が WARNING にして前回分を使い続けるので、ここでは扱わない。
    """

    async def run(app: web.Application) -> AsyncIterator[None]:
        client = client_factory()
        task = asyncio.create_task(_refresh_forever(illust, client, interval))
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await client.aclose()

    return run


async def _refresh_forever(illust: Any, client: Any, interval: float) -> None:
    while True:
        await illust.refresh(client)
        await asyncio.sleep(interval)
```

- [ ] **Step 4: 設定に公開 URL とカタログの URL を足す**

置き換え `src/insider_bot/config.py`:

```python
import os
from collections.abc import Mapping
from dataclasses import dataclass
```

↓

```python
import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit
```

置き換え `src/insider_bot/config.py`:

```python
    host: str
    port: int


def _get(env: Mapping[str, str], name: str) -> str:
```

↓

```python
    host: str
    port: int
    # 役職画像と特殊村フォームの URL を組み立てる公開 URL（末尾の / なし）。空ならサイト内の絶対パス
    public_base_url: str = ""
    # 役職画像の外部カタログ（Google Apps Script のデプロイ URL）。None なら取りに行かない
    illustration_catalog_url: str | None = None


def _get(env: Mapping[str, str], name: str) -> str:
```

置き換え `src/insider_bot/config.py`:

```python
def load_config(env: Mapping[str, str] | None = None) -> Config:
```

↓

```python
def _public_base_url(env: Mapping[str, str]) -> str:
    raw = _get(env, "PUBLIC_BASE_URL")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    # 画面と画像はサイトの根から配るので、パスやクエリを持つ URL は受け付けない
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ConfigError(f"PUBLIC_BASE_URL は https://example.com のようにパスなしの URL で指定してください（現在: {raw!r}）")
    return raw.rstrip("/")


def _catalog_url(env: Mapping[str, str]) -> str | None:
    raw = _get(env, "ILLUSTRATION_CATALOG_URL")
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(f"ILLUSTRATION_CATALOG_URL は https:// で始まる URL で指定してください（現在: {raw!r}）")
    return raw


def load_config(env: Mapping[str, str] | None = None) -> Config:
```

置き換え `src/insider_bot/config.py`:

```python
        host=_get(env, "WEB_HOST") or "127.0.0.1",
        port=port,
    )
```

↓

```python
        host=_get(env, "WEB_HOST") or "127.0.0.1",
        port=port,
        public_base_url=_public_base_url(env),
        illustration_catalog_url=_catalog_url(env),
    )
```

- [ ] **Step 5: create_app に配役ツールと /healthz をつなぐ**

置き換え `src/insider_bot/web/server.py`:

```python
from insider_bot.web.rooms import InvalidName, Player, Room, RoomFull, RoomLimitReached, RoomNotFound
```

↓

```python
from insider_bot.web.rooms import InvalidName, Player, Room, RoomFull, RoomLimitReached, RoomNotFound
from insider_bot.web.village_api import VillageApp, add_village_routes
```

置き換え `src/insider_bot/web/server.py`:

```python
VENDOR_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
```

↓

```python
VENDOR_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
# 特殊村は 100 通×5,000 文字まで受け取る（日本語の UTF-8 で約 1.5MB）。本番の Caddy の本文上限 2MB にそろえる
MAX_REQUEST_BYTES = 2 * 1024 * 1024
```

置き換え `src/insider_bot/web/server.py`:

```python
async def _cache_headers(request: web.Request, response: web.StreamResponse) -> None:
```

↓

```python
async def healthz(request: web.Request) -> web.Response:
    """HTTP を受け付けていることだけを示す。外形監視は本文の ok で判定する。"""
    return web.Response(text="ok")


async def _cache_headers(request: web.Request, response: web.StreamResponse) -> None:
```

置き換え `src/insider_bot/web/server.py`:

```python
    elif path == "/" or (path.startswith(("/static/", "/r/")) and not path.endswith("/ws")):
```

↓

```python
    elif path == "/" or (path.startswith(("/static/", "/r/", "/village", "/v/")) and not path.endswith("/ws")):
```

置き換え `src/insider_bot/web/server.py`:

```python
    cleanup_interval: float = CLEANUP_INTERVAL_SECONDS,
) -> web.Application:
    app = web.Application()
```

↓

```python
    cleanup_interval: float = CLEANUP_INTERVAL_SECONDS,
    village: VillageApp | None = None,
) -> web.Application:
    app = web.Application(client_max_size=MAX_REQUEST_BYTES)
```

置き換え `src/insider_bot/web/server.py`:

```python
    app.router.add_static("/static/", static_dir)
```

↓

```python
    app.router.add_static("/static/", static_dir)
    app.router.add_get("/healthz", healthz)
    if village is not None:
        add_village_routes(app, village, static_dir / "village.html")
```

置き換え `src/insider_bot/web/__main__.py`:

```python
from insider_bot.web.server import create_app
```

↓

```python
from insider_bot.web.server import create_app
from insider_bot.web.village_setup import build_village, catalog_refresh
```

置き換え `src/insider_bot/web/__main__.py`:

```python
    app = create_app(RoomHub(registry, service, manager))
```

↓

```python
    village = build_village(config.public_base_url, config.illustration_catalog_url)
    app = create_app(RoomHub(registry, service, manager), village=village)
    if config.illustration_catalog_url is not None:
        app.cleanup_ctx.append(catalog_refresh(village.service.illust))
```

- [ ] **Step 6: テストが通ることを確認する**

Run: `uv run pytest tests/test_web_village_setup.py tests/test_web_config.py tests/test_web_server.py -q`
Expected: `42 passed`

Run: `uv run pytest -q`
Expected: `442 passed, 4 deselected`

- [ ] **Step 7: 起動して確かめる**

`.env` に `TYPESAFE_API_KEY` がある前提で、別の端末で起動する（M2 の時点では `village.html` がまだないので、画面のパスは 404 でよい。API と `/healthz` だけを見る）:

```bash
uv run --env-file .env python -m insider_bot.web
```

```bash
curl -s localhost:8080/healthz
curl -s -X POST localhost:8080/api/village/create -H 'Content-Type: application/json' -d '{"token":"aaaaaaaaaaaaaaaaaaaaaa","kind":"normal"}'
```

Expected: 1 行目は `ok`。2 行目は `{"found": true, "replies": [{"type": "buttons", "text": "NNNN村 を新しく作成しました。お題を入力してください。\nお題の自動取得もできます。", ...}], "village": {"number": NNNN, ...}}`（日本語がエスケープされずに出る）。確かめたら Ctrl+C で止める。

- [ ] **Step 8: コミット**

```bash
git add src/insider_bot/web/village_setup.py src/insider_bot/config.py src/insider_bot/web/server.py src/insider_bot/web/__main__.py tests/test_web_village_setup.py tests/test_web_config.py tests/test_web_server.py
git commit -m "feat: 配役ツールを Web 版の起動につなぎ、/healthz とカタログの取り直しを足す"
```

---

### Task 5: 画面の部品（返事の描画・村番号・トークン・特殊村フォーム）

**Files:**
- Create: `src/insider_bot/web/static/reply.js`、`src/insider_bot/web/static/villageurl.js`、`src/insider_bot/web/static/villagetoken.js`、`src/insider_bot/web/static/specialform.js`
- Test: `tests/js/reply.test.mjs`、`tests/js/villageurl.test.mjs`、`tests/js/villagetoken.test.mjs`、`tests/js/specialform.test.mjs`

**Interfaces:**
- Consumes: Task 3 の API の JSON の形（Task 2 の返事の JSON）
- Produces（`reply.js`）: `safeUrl(url, origin) -> string | null`（https か同じオリジンだけ）、`actionView(action, origin) -> {label, kind: "text" | "postback" | "link", value} | null`、`replyView(reply, origin) -> {kind: "text", text} | {kind: "image", src} | {kind: "card", title, text, image, actions} | null`、DOM を描く `renderReplies(container, replies, onAction, origin = location.origin)`（ボタンが押されたら `onAction({label, kind, value})`）
- Produces（`villageurl.js`）: `MIN_VILLAGE_NUMBER = 1000`、`MAX_VILLAGE_NUMBER = 99998`、`villageFromPath(pathname) -> number | null`、`parseVillageUrl(text, origin) -> number | null`、`parseVillageInput(text) -> number | null`、`villageUrl(number, origin) -> string`
- Produces（`villagetoken.js`）: `TOKEN_KEY = "village:token"`、`newToken(bytes: Uint8Array) -> string`（base64url、`=` なし）、`villageToken(storage, cryptoObject) -> string`
- Produces（`specialform.js`）: `MAX_MESSAGES = 100`、`MAX_MESSAGE_LENGTH = 5000`、`parseMessages(text) -> string[]`、`messagesProblem(messages) -> string | null`

- [ ] **Step 1: 失敗するテストを書く**

新規 `tests/js/reply.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";

import { actionView, replyView, safeUrl } from "../../src/insider_bot/web/static/reply.js";

const ORIGIN = "https://game.example.com";

test("自サイトの絶対パスと https の URL だけを使う", () => {
  assert.equal(safeUrl("/static/roles/GM.png", ORIGIN), `${ORIGIN}/static/roles/GM.png`);
  assert.equal(safeUrl("https://lh3.googleusercontent.com/x", ORIGIN), "https://lh3.googleusercontent.com/x");
  for (const url of ["javascript:alert(1)", "data:image/png;base64,AAAA", "http://evil.example/x.png", "", null, undefined, 3]) {
    assert.equal(safeUrl(url, ORIGIN), null, String(url));
  }
});

test("手元の http で動かしていても、自サイトの画像は使う", () => {
  assert.equal(safeUrl("/static/roles/GM.png", "http://localhost:8080"), "http://localhost:8080/static/roles/GM.png");
});

test("文字と画像", () => {
  assert.deepEqual(replyView({ type: "text", text: "本文\n2 行目" }, ORIGIN), { kind: "text", text: "本文\n2 行目" });
  assert.deepEqual(replyView({ type: "image", url: "/static/roles/966mpnqz.png" }, ORIGIN), {
    kind: "image",
    src: `${ORIGIN}/static/roles/966mpnqz.png`,
  });
});

test("ボタンはカードにし、押したときの動作を種類ごとに決める", () => {
  const reply = {
    type: "buttons",
    text: "お題は「すいか」です。確定しますか？",
    image: null,
    title: null,
    actions: [
      { type: "message", label: "確定", text: "すいか" },
      { type: "postback", label: "初心者", data: "2" },
      { type: "uri", label: "ご意見", uri: "https://forms.example/x" },
    ],
  };
  assert.deepEqual(replyView(reply, ORIGIN), {
    kind: "card",
    title: null,
    text: "お題は「すいか」です。確定しますか？",
    image: null,
    actions: [
      { label: "確定", kind: "text", value: "すいか" },
      { label: "初心者", kind: "postback", value: "2" },
      { label: "ご意見", kind: "link", value: "https://forms.example/x" },
    ],
  });
});

test("画像と見出しのあるボタン（人数設定の返事）", () => {
  const view = replyView(
    { type: "buttons", text: "人数を『3人』に設定しました。", image: "/static/roles/GM.png", title: "1234村", actions: [] },
    ORIGIN,
  );
  assert.equal(view.image, `${ORIGIN}/static/roles/GM.png`);
  assert.equal(view.title, "1234村");
});

test("確認テンプレートもカードにする", () => {
  const view = replyView(
    { type: "confirm", text: "村の作成をしますか？", actions: [{ type: "message", label: "GM", text: "お題" }] },
    ORIGIN,
  );
  assert.equal(view.kind, "card");
  assert.deepEqual(view.actions, [{ label: "GM", kind: "text", value: "お題" }]);
});

test("知らない形・使えない URL の画像やリンクは描かない", () => {
  assert.equal(replyView({ type: "video" }, ORIGIN), null);
  assert.equal(replyView(null, ORIGIN), null);
  assert.equal(replyView({ type: "image", url: "javascript:alert(1)" }, ORIGIN), null);
  assert.equal(actionView({ type: "uri", label: "x", uri: "javascript:alert(1)" }, ORIGIN), null);
  assert.equal(actionView({ type: "camera", label: "x" }, ORIGIN), null);
  const view = replyView(
    { type: "buttons", text: "本文", image: "http://evil.example/x.png", title: null, actions: [{ type: "camera" }] },
    ORIGIN,
  );
  assert.equal(view.image, null);
  assert.deepEqual(view.actions, []);
});
```

新規 `tests/js/villageurl.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  parseVillageInput,
  parseVillageUrl,
  villageFromPath,
  villageUrl,
} from "../../src/insider_bot/web/static/villageurl.js";

const ORIGIN = "https://game.example.com";

test("パスの /v/<村番号> から村番号を取り出す", () => {
  assert.equal(villageFromPath("/v/1234"), 1234);
  assert.equal(villageFromPath("/v/12345/"), 12345);
  assert.equal(villageFromPath("/v/99998"), 99998);
});

test("村番号の範囲や形が違うパスは拒む", () => {
  for (const path of ["/v/0999", "/v/999", "/v/99999", "/v/123456", "/v/12a4", "/v/1234/x", "/v/", "/village", "/r/1234"]) {
    assert.equal(villageFromPath(path), null, path);
  }
});

test("同じオリジンの村の URL から村番号を取り出す（クエリとハッシュは無視）", () => {
  assert.equal(parseVillageUrl(`${ORIGIN}/v/1234`, ORIGIN), 1234);
  assert.equal(parseVillageUrl(`${ORIGIN}/v/12345?x=1#y`, ORIGIN), 12345);
});

test("別のオリジンや URL でない文字列は拒む", () => {
  for (const text of ["https://evil.example/v/1234", "http://game.example.com/v/1234", "1234", "", "javascript:alert(1)"]) {
    assert.equal(parseVillageUrl(text, ORIGIN), null, text);
  }
});

test("入力欄は全角数字と前後の空白（全角スペースを含む）を許す", () => {
  assert.equal(parseVillageInput("1234"), 1234);
  assert.equal(parseVillageInput("１２３４"), 1234);
  assert.equal(parseVillageInput(" 1234 "), 1234);
  assert.equal(parseVillageInput("　１２３４５　"), 12345);
});

test("入力欄の 4〜5 桁でない数字や範囲外は拒む", () => {
  for (const text of ["", "123", "123456", "12-34", "abcd", "99999", "0999", "1 234"]) {
    assert.equal(parseVillageInput(text), null, text);
  }
});

test("参加用の URL", () => {
  assert.equal(villageUrl(1234, ORIGIN), `${ORIGIN}/v/1234`);
});
```

新規 `tests/js/villagetoken.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";

import { newToken, TOKEN_KEY, villageToken } from "../../src/insider_bot/web/static/villagetoken.js";

const TOKEN = /^[A-Za-z0-9_-]{22}$/;
const fixedCrypto = { getRandomValues: (array) => array.fill(7) };

class MemoryStorage {
  constructor(entries = {}) {
    this.map = new Map(Object.entries(entries));
  }

  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }

  setItem(key, value) {
    this.map.set(key, value);
  }
}

class BrokenStorage {
  getItem() {
    throw new Error("blocked");
  }

  setItem() {
    throw new Error("blocked");
  }
}

test("16 バイトの乱数を、= のない base64url の 22 文字にする", () => {
  assert.equal(newToken(new Uint8Array(16)), "A".repeat(22));
  // + と / は URL で意味を持つので - と _ にする
  assert.equal(newToken(new Uint8Array([0xfb, 0xff, 0xbf])), "-_-_");
});

test("保存済みのトークンを使い続ける", () => {
  const storage = new MemoryStorage({ [TOKEN_KEY]: "saved-token-0123456789" });
  assert.equal(villageToken(storage, fixedCrypto), "saved-token-0123456789");
});

test("なければ作って保存する", () => {
  const storage = new MemoryStorage();
  const token = villageToken(storage, fixedCrypto);
  assert.match(token, TOKEN);
  assert.equal(storage.getItem(TOKEN_KEY), token);
});

test("形の壊れた保存値は作り直す", () => {
  const storage = new MemoryStorage({ [TOKEN_KEY]: "bad token" });
  const token = villageToken(storage, fixedCrypto);
  assert.match(token, TOKEN);
  assert.equal(storage.getItem(TOKEN_KEY), token);
});

test("保存できない環境や storage がない環境でも、その場のトークンで動く", () => {
  assert.match(villageToken(new BrokenStorage(), fixedCrypto), TOKEN);
  assert.match(villageToken(null, fixedCrypto), TOKEN);
});
```

新規 `tests/js/specialform.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";

import { messagesProblem, parseMessages } from "../../src/insider_bot/web/static/specialform.js";

test("1 行 1 通。CRLF と CR も区切りにする", () => {
  assert.deepEqual(parseMessages("a\r\nb\nc\rd"), ["a", "b", "c", "d"]);
});

test("末尾の空行は数えず、途中の空行は空のメッセージにする", () => {
  assert.deepEqual(parseMessages("a\n\nb\n\n \n"), ["a", "", "b"]);
  assert.deepEqual(parseMessages("\na"), ["", "a"]);
});

test("空白だけの行も、途中にあればそのまま送る", () => {
  assert.deepEqual(parseMessages("a\n \nb"), ["a", " ", "b"]);
});

test("何も書いていなければ 0 通", () => {
  assert.deepEqual(parseMessages(""), []);
  assert.deepEqual(parseMessages("\n \n"), []);
});

test("送れない理由を返し、送れるなら null", () => {
  assert.equal(messagesProblem([]), "メッセージを 1 行以上入力してください");
  assert.equal(messagesProblem(Array(101).fill("a")), "メッセージは 100 通までです（いま 101 通）");
  assert.equal(messagesProblem(["a", "😀".repeat(2500) + "a"]), "2 行目が 5000 文字を超えています");
  assert.equal(messagesProblem(Array(100).fill("😀".repeat(2500))), null);
});
```

- [ ] **Step 2: 失敗を確認する**

Run: `node --test tests/js/reply.test.mjs tests/js/villageurl.test.mjs tests/js/villagetoken.test.mjs tests/js/specialform.test.mjs`
Expected: 4 ファイルとも `ERR_MODULE_NOT_FOUND` で失敗する

- [ ] **Step 3: 部品を書く**

新規 `src/insider_bot/web/static/reply.js`:

```javascript
// 返事モデル（/api/village の JSON）を画面に描く。文字はすべて textContent で入れ、innerHTML は使わない。
// Web には文字数の制限がないので、LINE 向けの代わりの返事は届かず、本体だけを描く。

/** 画像やリンクに使ってよい URL。https か、このサイト（origin）の URL だけを許す。 */
export function safeUrl(url, origin) {
  if (typeof url !== "string" || url === "") return null;
  let parsed;
  try {
    parsed = new URL(url, origin);
  } catch {
    return null;
  }
  if (parsed.origin === origin || parsed.protocol === "https:") return parsed.href;
  return null;
}

/** ボタン 1 つ。押したときの動作（文字列の送信・ポストバック・リンク）と値に直す。 */
export function actionView(action, origin) {
  if (action?.type === "message") return { label: action.label, kind: "text", value: action.text };
  if (action?.type === "postback") return { label: action.label, kind: "postback", value: action.data };
  if (action?.type === "uri") {
    const href = safeUrl(action.uri, origin);
    return href ? { label: action.label, kind: "link", value: href } : null;
  }
  return null;
}

/** 返事 1 つを描く部品の形にする。知らない形と、使えない URL の画像は描かない。 */
export function replyView(reply, origin) {
  if (reply?.type === "text") return { kind: "text", text: reply.text };
  if (reply?.type === "image") {
    const src = safeUrl(reply.url, origin);
    return src ? { kind: "image", src } : null;
  }
  if (reply?.type === "buttons" || reply?.type === "confirm") {
    return {
      kind: "card",
      title: reply.title ?? null,
      text: reply.text,
      image: safeUrl(reply.image, origin),
      actions: (reply.actions ?? []).map((action) => actionView(action, origin)).filter(Boolean),
    };
  }
  return null;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function image(className, src) {
  const node = element("img", className);
  node.src = src;
  // 役職は本文にも書いてあるので、読み上げでは画像を飛ばす
  node.alt = "";
  return node;
}

function renderActions(actions, onAction) {
  const row = element("div", "reply-actions");
  for (const action of actions) {
    if (action.kind === "link") {
      const link = element("a", "button secondary", action.label);
      link.href = action.value;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      row.append(link);
      continue;
    }
    const button = element("button", "secondary", action.label);
    button.type = "button";
    button.addEventListener("click", () => onAction(action));
    row.append(button);
  }
  return row;
}

function renderView(view, onAction) {
  if (view.kind === "text") return element("p", "reply-text", view.text);
  if (view.kind === "image") return image("reply-image", view.src);
  const card = element("div", "reply-card");
  if (view.image) card.append(image("reply-card-image", view.image));
  if (view.title) card.append(element("p", "reply-card-title", view.title));
  card.append(element("p", "reply-text", view.text));
  if (view.actions.length) card.append(renderActions(view.actions, onAction));
  return card;
}

/** 返事の列で container の中身を置き換える。ボタンが押されたら onAction({label, kind, value}) を呼ぶ。 */
export function renderReplies(container, replies, onAction, origin = location.origin) {
  container.replaceChildren();
  for (const reply of replies) {
    const view = replyView(reply, origin);
    if (view) container.append(renderView(view, onAction));
  }
}
```

新規 `src/insider_bot/web/static/villageurl.js`:

```javascript
// 配役ツールの村番号。ページのパス・QR の URL・入力欄から読み取る
export const MIN_VILLAGE_NUMBER = 1000;
export const MAX_VILLAGE_NUMBER = 99998;

function toNumber(digits) {
  const number = Number(digits);
  return number >= MIN_VILLAGE_NUMBER && number <= MAX_VILLAGE_NUMBER ? number : null;
}

/** パスが /v/<村番号> なら村番号を、それ以外は null を返す。 */
export function villageFromPath(pathname) {
  const match = /^\/v\/(\d{4,5})\/?$/.exec(pathname);
  return match ? toNumber(match[1]) : null;
}

/** このサイト（origin）の /v/<村番号> の URL なら村番号を、それ以外は null を返す。 */
export function parseVillageUrl(text, origin) {
  let url;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  // 読み取った見知らぬ URL へは移動しない
  if (url.origin !== origin) return null;
  return villageFromPath(url.pathname);
}

/** 入力欄の村番号。全角数字と前後の空白は許し、4〜5 桁の数字だけを受け付ける。 */
export function parseVillageInput(text) {
  const normalized = text.normalize("NFKC").trim();
  return /^\d{4,5}$/.test(normalized) ? toNumber(normalized) : null;
}

/** 村に入るための URL。 */
export function villageUrl(number, origin) {
  return `${origin}/v/${number}`;
}
```

新規 `src/insider_bot/web/static/villagetoken.js`:

```javascript
// 配役ツールで自分を表すトークン。知っている人がその参加者として振る舞えるので、URL やログに出さない
export const TOKEN_KEY = "village:token";
const TOKEN_BYTES = 16;
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{16,64}$/;

/** 乱数のバイト列を、= のない base64url にする。 */
export function newToken(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

/** 保存済みのトークン。なければ作って保存する。保存できない環境では、その場かぎりのトークンになる。 */
export function villageToken(storage, cryptoObject) {
  let saved = null;
  try {
    saved = storage?.getItem(TOKEN_KEY) ?? null;
  } catch {
    // プライベートブラウズなどで読めない
  }
  if (saved !== null && TOKEN_PATTERN.test(saved)) return saved;
  const token = newToken(cryptoObject.getRandomValues(new Uint8Array(TOKEN_BYTES)));
  try {
    storage?.setItem(TOKEN_KEY, token);
  } catch {
    // 保存できなくても、このページを開いている間は同じトークンで動く
  }
  return token;
}
```

新規 `src/insider_bot/web/static/specialform.js`:

```javascript
// 特殊村フォーム: 1 行 1 通。末尾の空行は数えず、途中の空行は空のメッセージ（「メッセージは特にありません。」）になる。
// 文字数は LINE と同じく UTF-16 の符号単位（String の length）で数える
export const MAX_MESSAGES = 100;
export const MAX_MESSAGE_LENGTH = 5000;

export function parseMessages(text) {
  const lines = text.split(/\r\n|\r|\n/);
  while (lines.length > 0 && lines.at(-1).trim() === "") lines.pop();
  return lines;
}

/** 送れない理由。送れるなら null。 */
export function messagesProblem(messages) {
  if (messages.length === 0) return "メッセージを 1 行以上入力してください";
  if (messages.length > MAX_MESSAGES) return `メッセージは ${MAX_MESSAGES} 通までです（いま ${messages.length} 通）`;
  const tooLong = messages.findIndex((message) => message.length > MAX_MESSAGE_LENGTH);
  if (tooLong >= 0) return `${tooLong + 1} 行目が ${MAX_MESSAGE_LENGTH} 文字を超えています`;
  return null;
}
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `node --test tests/js/reply.test.mjs tests/js/villageurl.test.mjs tests/js/villagetoken.test.mjs tests/js/specialform.test.mjs`
Expected: `ℹ pass 24` と `ℹ fail 0`

Run: `node --test tests/js/*.test.mjs`
Expected: `ℹ fail 0`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/web/static/reply.js src/insider_bot/web/static/villageurl.js src/insider_bot/web/static/villagetoken.js src/insider_bot/web/static/specialform.js tests/js/reply.test.mjs tests/js/villageurl.test.mjs tests/js/villagetoken.test.mjs tests/js/specialform.test.mjs
git commit -m "feat: 配役ツールの画面の部品（返事の描画・村番号・トークン・特殊村フォーム）を足す"
```

---

### Task 6: 配役ツールの画面（/village、/village/new、/village/special、/v/<村番号>）

**Files:**
- Create: `src/insider_bot/web/static/village.html`、`src/insider_bot/web/static/village.css`、`src/insider_bot/web/static/village.js`
- Modify: `src/insider_bot/web/static/qr.js`（`Scanner` に読み取り結果の解析関数を渡せるようにする）、`src/insider_bot/web/static/index.html`（トップページに入口）

**Interfaces:**
- Consumes: Task 5 の `renderReplies`、`parseVillageInput`、`parseVillageUrl`、`villageFromPath`、`villageUrl`、`villageToken`、`parseMessages`、`messagesProblem`。既存の `qr.js` の `renderQr(canvas, text)` と `Scanner`。Task 3 の API
- Produces: `Scanner(dialog, video, message, onFound, parse = (text) => parseRoomCode(text, location.origin))`。`parse` が `null` 以外を返したら閉じて `onFound(結果)` を呼ぶ。既存の `app.js` の呼び出し（引数 4 つ）は今までどおり動く
- 画面の進み方（`/village/new`）: 応答の `village`（最新の村の要約）で決める。`null` か「新しい村を作る」の後 → 種類、`has_topic` が false → お題、`size` が 0 → 人数、それ以外 → 配布状況（村番号・QR・URL・5 秒ごとの配布状況・逆村とワーワーズのボタン）

- [ ] **Step 1: Scanner に解析関数を渡せるようにする**

置き換え `src/insider_bot/web/static/qr.js`:

```javascript
  constructor(dialog, video, message, onRoom) {
    this.dialog = dialog;
    this.video = video;
    this.message = message;
    this.onRoom = onRoom;
```

↓

```javascript
  // parse は読み取った文字列から行き先（ルーム番号・村番号）を取り出し、このサイトのものでなければ null を返す
  constructor(dialog, video, message, onFound, parse = (text) => parseRoomCode(text, location.origin)) {
    this.dialog = dialog;
    this.video = video;
    this.message = message;
    this.onFound = onFound;
    this.parse = parse;
```

置き換え `src/insider_bot/web/static/qr.js`:

```javascript
    const code = parseRoomCode(found.data, location.origin);
    if (!code) {
      this.say("このゲームの QR コードではありません");
      return;
    }
    this.close();
    this.onRoom(code);
```

↓

```javascript
    const target = this.parse(found.data);
    if (target === null) {
      this.say("このゲームの QR コードではありません");
      return;
    }
    this.close();
    this.onFound(target);
```

- [ ] **Step 2: 画面の HTML を書く**

新規 `src/insider_bot/web/static/village.html`:

```html
<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8" />
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1, viewport-fit=cover"
    />
    <meta name="color-scheme" content="dark" />
    <meta name="theme-color" content="#191a20" />
    <meta
      name="description"
      content="インサイダーゲームの役職とお題を、参加者それぞれのスマホに配ります。"
    />
    <title>INSIDER — インサイダーの配役</title>
    <link rel="icon" href="/static/mark.svg" type="image/svg+xml" />
    <link rel="stylesheet" href="/static/style.css" />
    <link rel="stylesheet" href="/static/village.css" />
    <script type="module" src="/static/village.js"></script>
  </head>
  <body>
    <a class="skip-link" href="#main">コンテンツへ</a>
    <header class="site-header">
      <a class="brand" href="/" aria-label="INSIDER ホーム"
        ><span class="brand-mark" aria-hidden="true"></span>INSIDER<span
          class="brand-dot"
          aria-hidden="true"
          >✳</span
        ></a
      >
      <span class="header-caption">インサイダーの配役</span>
    </header>
    <main id="main" class="village">
      <section id="village-home" class="page entrance" hidden>
        <p class="eyebrow">INSIDER CASTING</p>
        <h1>役職とお題を、<br />ひとりずつに。</h1>
        <p class="lead">
          村を作って番号を伝えると、参加した人のスマホに、それぞれの役職とお題が届きます。
        </p>
        <div class="stack">
          <a class="button primary arrow-button" href="/village/new"
            ><span>村を作る</span><span aria-hidden="true">↗</span></a
          >
          <form id="join-form" class="stack">
            <label class="field" for="join-number"
              >村番号<input
                id="join-number"
                inputmode="numeric"
                autocomplete="off"
                placeholder="4〜5 桁の数字"
                required
            /></label>
            <button type="submit" class="secondary">村に入る</button>
          </form>
          <button id="scan-open" type="button" class="secondary wide">
            QR で村に入る
          </button>
          <a class="button secondary wide" href="/village/special"
            >特殊村を作る</a
          >
          <p id="home-message" class="message" role="status"></p>
        </div>
      </section>

      <section id="village-new" class="page entrance" hidden>
        <p class="eyebrow">NEW VILLAGE</p>
        <h1>村を作る</h1>
        <div id="step-kind" class="stack" hidden>
          <p class="lead">遊び方を選んでください。</p>
          <button type="button" class="secondary kind-button" data-kind="normal">
            <span>通常の村</span
            ><small>あなたが GM。参加者にインサイダー 1 人と村人を配ります</small>
          </button>
          <button type="button" class="secondary kind-button" data-kind="god">
            <span>神モード</span
            ><small>GM も参加者から選びます。あなたは配るだけ</small>
          </button>
          <button type="button" class="secondary kind-button" data-kind="random">
            <span>ランダム</span
            ><small>あなたも参加します。お題も役職もランダム</small>
          </button>
        </div>
        <form id="step-topic" class="stack" hidden>
          <label class="field" for="topic-input"
            >お題<input id="topic-input" maxlength="5000" autocomplete="off" required
          /></label>
          <button type="submit" class="primary">お題を決める</button>
        </form>
        <form id="step-size" class="stack" hidden>
          <label class="field" for="size-input"
            >人数<input
              id="size-input"
              type="number"
              inputmode="numeric"
              max="100"
              required
          /></label>
          <button type="submit" class="primary">人数を決める</button>
        </form>
        <div id="step-status" class="stack" hidden>
          <p class="village-number">村番号<strong id="status-number"></strong></p>
          <canvas
            id="status-qr"
            class="qr"
            width="1"
            height="1"
            aria-label="村に入る QR コード"
          ></canvas>
          <p id="status-url" class="url"></p>
          <button id="status-copy" type="button" class="secondary">
            URL をコピー
          </button>
          <div id="status-replies" class="replies" aria-live="polite"></div>
          <div class="row">
            <button id="reverse-button" type="button" class="secondary" hidden>
              逆村にする</button
            ><button id="werewords-button" type="button" class="secondary" hidden>
              ワーワーズにする
            </button>
          </div>
          <button id="restart-button" type="button" class="link">
            新しい村を作る
          </button>
        </div>
        <div id="new-replies" class="replies" aria-live="polite"></div>
        <p id="new-message" class="message" role="status"></p>
      </section>

      <section id="village-card" class="page entrance" hidden>
        <p class="eyebrow">YOUR ROLE</p>
        <h1>村 <span id="card-number"></span></h1>
        <div id="card-replies" class="replies" aria-live="polite"></div>
        <div id="card-status" class="replies" aria-live="polite"></div>
        <div class="stack">
          <button id="card-reload" type="button" class="secondary wide">
            もう一度表示する
          </button>
          <a class="button secondary wide" href="/village">配役ツールのトップへ</a>
        </div>
        <p id="card-message" class="message" role="status"></p>
      </section>

      <section id="village-special" class="page entrance" hidden>
        <p class="eyebrow">CUSTOM VILLAGE</p>
        <h1>配る言葉から、<br />村をつくる。</h1>
        <p class="lead">
          1 行に 1 通。参加した人に 1 通ずつ届きます（届く順は作るときにシャッフルします）。途中の空の行には「メッセージは特にありません。」が届きます。
        </p>
        <form id="special-form" class="stack">
          <label class="field" for="special-input"
            ><span
              >メッセージ
              <span id="special-count" class="field-note">0 通</span></span
            ><textarea id="special-input" rows="8" required></textarea>
          </label>
          <button
            id="special-submit"
            type="submit"
            class="primary arrow-button"
          >
            <span>特殊村を作る</span><span aria-hidden="true">↗</span>
          </button>
        </form>
        <div id="special-result" class="stack" hidden>
          <p class="village-number">村番号<strong id="special-number"></strong></p>
          <canvas
            id="special-qr"
            class="qr"
            width="1"
            height="1"
            aria-label="村に入る QR コード"
          ></canvas>
          <p id="special-url" class="url"></p>
          <button id="special-copy" type="button" class="secondary">
            URL をコピー
          </button>
          <button id="special-again" type="button" class="link">
            もう 1 つ作る
          </button>
        </div>
        <p id="special-message" class="message" role="status"></p>
      </section>
    </main>

    <dialog id="scanner" class="sheet" aria-labelledby="scanner-title">
      <p class="eyebrow">JOIN THE VILLAGE</p>
      <h2 id="scanner-title">QR で村に入る</h2>
      <video id="scanner-video" class="scanner-video" playsinline muted></video>
      <p id="scanner-message" class="message" role="status"></p>
      <button id="scanner-close" type="button" class="secondary wide">
        閉じる
      </button>
    </dialog>
  </body>
</html>
```

- [ ] **Step 3: 配役ツールだけの見た目を書く**

新規 `src/insider_bot/web/static/village.css`:

```css
/* 配役ツール。トップやルームと同じ夜の配色（style.css の変数）を使い、返事のカードと村番号だけを足す */

.replies {
  display: grid;
  gap: 14px;
  margin-top: 24px;
}

.replies:empty {
  display: none;
}

.reply-text {
  margin: 0;
  line-height: 1.8;
  white-space: pre-line;
  overflow-wrap: anywhere;
}

.reply-card {
  display: grid;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}

.reply-image,
.reply-card-image {
  justify-self: center;
  width: 100%;
  max-width: 320px;
  height: auto;
  border-radius: var(--radius);
}

.reply-card-title {
  margin: 0;
  color: var(--accent);
  font-weight: 700;
  letter-spacing: 0.08em;
}

.reply-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.reply-actions > * {
  flex: 1 1 auto;
  min-height: 44px;
}

.village-number {
  margin: 0;
  color: var(--muted);
  letter-spacing: 0.12em;
}

.village-number strong {
  display: block;
  color: var(--accent);
  font-size: 48px;
  letter-spacing: 0.06em;
}

.kind-button {
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  text-align: left;
}

.kind-button small {
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
}

#special-input {
  width: 100%;
  min-height: 200px;
  resize: vertical;
}
```

- [ ] **Step 4: 画面の制御を書く**

新規 `src/insider_bot/web/static/village.js`:

```javascript
// 配役ツールの画面。サーバーの返事モデルを reply.js で描き、返事のボタンは LINE と同じ意味で送り返す。
// 画面は /village（入口）、/village/new（村を作る）、/village/special（特殊村）、/v/<村番号>（村に入る）の 4 つ
import { renderQr, Scanner } from "./qr.js";
import { renderReplies } from "./reply.js";
import { messagesProblem, parseMessages } from "./specialform.js";
import { parseVillageInput, parseVillageUrl, villageFromPath, villageUrl } from "./villageurl.js";
import { villageToken } from "./villagetoken.js";

const $ = (id) => document.getElementById(id);
// 配布状況の自動更新の間隔。1 秒を争わないので数秒で足りる
const STATUS_REFRESH_MS = 5000;
const NETWORK_ERROR = "通信に失敗しました。少し待ってからもう一度どうぞ";

function localStorageOrNull() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

const token = villageToken(localStorageOrNull(), crypto);

function showPage(id) {
  for (const page of document.querySelectorAll(".page")) page.hidden = page.id !== id;
}

async function post(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

function call(name, fields = {}) {
  return post(`/api/village/${name}`, { token, ...fields });
}

// 返事のボタン。LINE でその文字列を送った・ポストバックが届いたのと同じ解釈をサーバーがする
function actionCall(action) {
  return action.kind === "text"
    ? call("text", { text: action.value })
    : call("postback", { data: action.value });
}

let busy = false;

// 利用者の操作を 1 つずつ送る。連打で村が 2 つできないよう、応答を待つ間の操作は捨てる
async function run(message, task) {
  if (busy) return null;
  busy = true;
  message.textContent = "";
  try {
    return await task();
  } catch {
    message.textContent = NETWORK_ERROR;
    return null;
  } finally {
    busy = false;
  }
}

// 村に入る URL を、QR・文字・コピーのボタンで見せる
function showInvite(number, { canvas, url, copy, message }) {
  const link = villageUrl(number, location.origin);
  url.textContent = link;
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(link);
      message.textContent = "URL をコピーしました";
    } catch {
      message.textContent = "コピーできませんでした。URL を長押ししてコピーしてください";
    }
  };
  canvas.hidden = false;
  renderQr(canvas, link).catch(() => {
    canvas.hidden = true;
  });
}

function initHome(notice = "") {
  showPage("village-home");
  $("home-message").textContent = notice;
  $("join-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const number = parseVillageInput($("join-number").value);
    if (number === null) {
      $("home-message").textContent = "村番号は 4〜5 桁の数字で入力してください";
      return;
    }
    location.href = `/v/${number}`;
  });
  const scanner = new Scanner(
    $("scanner"),
    $("scanner-video"),
    $("scanner-message"),
    (number) => {
      location.href = `/v/${number}`;
    },
    (text) => parseVillageUrl(text, location.origin),
  );
  $("scan-open").addEventListener("click", () => scanner.open());
  $("scanner-close").addEventListener("click", () => scanner.close());
}

function initCard(number) {
  showPage("village-card");
  $("card-number").textContent = String(number);
  const message = $("card-message");

  async function onAction(action) {
    const body = await run(message, () => actionCall(action));
    if (body !== null) renderReplies($("card-status"), body.replies, onAction);
  }

  // 参加済みなら同じ役職が返るので、何度押しても席は増えない
  async function join() {
    const body = await run(message, () => call("join", { number }));
    if (body === null) return;
    renderReplies($("card-replies"), body.replies, onAction);
    $("card-status").replaceChildren();
  }

  $("card-reload").addEventListener("click", join);
  join();
}

function initNew() {
  showPage("village-new");
  const message = $("new-message");
  const steps = ["step-kind", "step-topic", "step-size", "step-status"];
  let village = null;
  // 「新しい村を作る」を押したあとは、作りかけの村があっても種類から聞く
  let startingOver = false;
  let invited = null;
  let timer = null;

  function stepOf(owned) {
    if (owned === null || startingOver) return "step-kind";
    if (!owned.has_topic) return "step-topic";
    if (owned.size === 0) return "step-size";
    return "step-status";
  }

  function updateOwnerButtons(owned) {
    // 中核も同じ条件で断るが、押しても案内文しか返らないボタンは出さない
    $("reverse-button").hidden = owned.member_count > 0 || owned.mode === "random" || owned.reverse;
    $("werewords-button").hidden = owned.member_count > 0 || owned.size < 3 || !owned.has_topic;
  }

  // オーナーが自分の村番号で入ると配布状況が返る。画面が隠れている間は取りに行かない
  async function refreshStatus() {
    if (village === null || document.visibilityState !== "visible") return;
    const number = village.number;
    let body;
    try {
      body = await call("join", { number });
    } catch {
      return; // 次の更新で取り直す
    }
    if (village === null || village.number !== number) return;
    renderReplies($("status-replies"), body.replies, onAction);
    if (body.village?.number === number) {
      village = body.village;
      updateOwnerButtons(village);
    }
  }

  function startStatus() {
    $("status-number").textContent = String(village.number);
    if (invited !== village.number) {
      invited = village.number;
      $("status-replies").replaceChildren();
      showInvite(village.number, { canvas: $("status-qr"), url: $("status-url"), copy: $("status-copy"), message });
    }
    updateOwnerButtons(village);
    if (timer === null) {
      refreshStatus();
      timer = setInterval(refreshStatus, STATUS_REFRESH_MS);
    }
  }

  function stopStatus() {
    clearInterval(timer);
    timer = null;
  }

  function show(owned) {
    village = owned;
    const step = stepOf(owned);
    for (const id of steps) $(id).hidden = id !== step;
    if (step === "step-status") startStatus();
    else stopStatus();
  }

  // 返事を描き、最新の村の要約から次に聞くことを決める
  function apply(body) {
    if (body === null) return;
    renderReplies($("new-replies"), body.replies, onAction);
    show(body.village);
  }

  async function onAction(action) {
    apply(await run(message, () => actionCall(action)));
  }

  for (const button of document.querySelectorAll("[data-kind]")) {
    button.addEventListener("click", async () => {
      const body = await run(message, () => call("create", { kind: button.dataset.kind }));
      if (body === null) return;
      startingOver = false;
      apply(body);
    });
  }

  $("step-topic").addEventListener("submit", async (event) => {
    event.preventDefault();
    const topic = $("topic-input").value;
    if (topic === "") return;
    const body = await run(message, () => call("topic", { topic }));
    if (body?.found) $("topic-input").value = "";
    apply(body);
  });

  $("step-size").addEventListener("submit", async (event) => {
    event.preventDefault();
    const size = Number.parseInt($("size-input").value, 10);
    if (!Number.isInteger(size) || size > 100) {
      message.textContent = "人数は 100 人までの数字で入力してください";
      return;
    }
    apply(await run(message, () => call("size", { size })));
  });

  $("reverse-button").addEventListener("click", async () => apply(await run(message, () => call("reverse"))));
  $("werewords-button").addEventListener("click", async () => apply(await run(message, () => call("werewords"))));
  $("restart-button").addEventListener("click", () => {
    startingOver = true;
    $("new-replies").replaceChildren();
    show(village);
  });
  document.addEventListener("visibilitychange", () => {
    if (timer !== null) refreshStatus();
  });

  // 再読み込みや別のタブでは、作りかけの村の続きから表示する
  run(message, () => call("mine")).then((body) => show(body === null ? null : body.village));
}

function initSpecial() {
  showPage("village-special");
  const input = $("special-input");
  const message = $("special-message");
  const submit = $("special-submit");
  const count = () => {
    $("special-count").textContent = `${parseMessages(input.value).length} 通`;
  };
  input.addEventListener("input", count);
  count();

  $("special-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const messages = parseMessages(input.value);
    const problem = messagesProblem(messages);
    if (problem !== null) {
      message.textContent = problem;
      return;
    }
    submit.disabled = true;
    const body = await run(message, () => post("/api/village/special", { messages }));
    submit.disabled = false;
    if (body === null) return;
    $("special-form").hidden = true;
    $("special-result").hidden = false;
    $("special-number").textContent = String(body.number);
    showInvite(body.number, { canvas: $("special-qr"), url: $("special-url"), copy: $("special-copy"), message });
  });

  $("special-again").addEventListener("click", () => {
    input.value = "";
    count();
    message.textContent = "";
    $("special-result").hidden = true;
    $("special-form").hidden = false;
  });
}

const path = location.pathname.replace(/\/$/, "") || "/";
if (path === "/village/new") initNew();
else if (path === "/village/special") initSpecial();
else if (path.startsWith("/v/")) {
  const number = villageFromPath(path);
  if (number === null) initHome("村番号が正しくありません（URL を確かめてください）");
  else initCard(number);
} else initHome();
```

- [ ] **Step 5: トップページに入口を足す**

置き換え `src/insider_bot/web/static/index.html`:

```html
            <p class="entry-note">ルームの URL を送るだけで、集まれる。</p>
```

↓

```html
            <a class="button secondary wide" href="/village">
              インサイダーの配役
              <span class="join-arrow" aria-hidden="true">↗</span>
            </a>
            <p class="entry-note">ルームの URL を送るだけで、集まれる。</p>
```

- [ ] **Step 6: 構文とテストを確かめる**

`node --check` は import を含む `.js` の構文の誤りを見逃すので、モジュールとして標準入力から読ませる。

```bash
for f in village reply villageurl villagetoken specialform qr app; do node --input-type=module --check < src/insider_bot/web/static/$f.js || echo "NG: $f"; done
```

Expected: 何も表示されない（`NG:` が出ない）

Run: `node --test tests/js/*.test.mjs`
Expected: `ℹ fail 0`

Run: `uv run pytest -q`
Expected: `442 passed, 4 deselected`

- [ ] **Step 7: ブラウザで確かめる**

```bash
uv run --env-file .env python -m insider_bot.web
```

`http://localhost:8080/` を開き、次を確かめる。確かめたら Ctrl+C で止める。

1. トップページに「インサイダーの配役」があり、押すと `/village` が開く。ヘッダーの INSIDER でトップに戻れる
2. `/village` →「村を作る」→「通常の村」で、作成の返事（「お題の自動取得」のボタンつき）とお題の入力欄が出る。「お題の自動取得」→ 候補と「確定 / 初心者 / 上級者 / 変態」が出て、「確定」で人数の入力欄に進む
3. 人数に 1 を入れると「村の人数は2人以上に設定してください。」の返事が出て人数の入力欄のまま。3 を入れると村番号・QR・URL・配布状況（「NNNN村：0/3人にお題を配りました。…」）と「逆村にする」「ワーワーズにする」が出る
4. 別のブラウザ（シークレットウィンドウなど）で `/village` に村番号を全角で入れて「村に入る」→ `/v/NNNN` で役職のカード（画像つき）が出る。「入室状況確認」で「あなたは1番目の参加者です。…」が出る。「もう一度表示する」でも同じ役職
5. 1 つ目のブラウザに戻ると、5 秒以内に配布状況が「1/3人」になり、「逆村にする」「ワーワーズにする」が消える
6. 1 つ目のブラウザで `/village/new` を再読み込みしても配布状況の画面に戻る。「新しい村を作る」で種類の選択に戻る
7. `/village/special` で 3 行（2 行目は空）入れて作る → 5 桁の村番号と QR が出る。別のブラウザでその番号に 3 回（3 つのウィンドウで）入ると、空の行の人に「メッセージは特にありません。」が届く
8. `/v/abc` を開くと `/village` の画面で「村番号が正しくありません」と出る
9. 狭い幅（スマホ幅）でも、ボタンが 44px 以上で横にはみ出さない

- [ ] **Step 8: コミット**

```bash
git add src/insider_bot/web/static/village.html src/insider_bot/web/static/village.css src/insider_bot/web/static/village.js src/insider_bot/web/static/qr.js src/insider_bot/web/static/index.html
git commit -m "feat: 配役ツールの画面（村を作る・村に入る・特殊村）を足す"
```

---

### Task 7: ドキュメント

**Files:**
- Modify: `docs/spec.md`、`docs/village.md`、`README.md`、`.env.example`

**Interfaces:**
- Consumes: Task 1〜6 の挙動（記述がコードと一致していること）

- [ ] **Step 1: docs/spec.md に配役ツールを足す**

置き換え `docs/spec.md`:

```markdown
対象外: インサイダーの投票・タイマー、ボイスチャンネルの聞き取り、ゲーム状態の永続化（再起動で進行中ゲームは消える）、Web 版のログイン・ルームの保存・サーバー側での文字起こし・サイト内の通話。
```

↓

```markdown
配役ツール: Web 版の `/village` で、インサイダーゲームの役職とお題を参加者それぞれのスマホに配る。LINE Bot と同じ村の中核を使い、同じ文言で答える（下記「配役ツール（Web）」）。

対象外: インサイダーの投票・タイマー、ボイスチャンネルの聞き取り、ゲーム状態の永続化（再起動で進行中ゲームは消える）、Web 版のログイン・ルームの保存・サーバー側での文字起こし・サイト内の通話。
```

追記 `docs/spec.md`（末尾）:

```markdown
## 配役ツール（Web）

Web 版の `/village` で、村の中核を LINE と同じ文言のまま使う。外部仕様は [村の外部仕様](village.md)。

### 画面

- `/village` は入口で、村を作る・村番号か QR で村に入る・特殊村を作るの 3 つを置く。お題当てのトップページからも入れる。
- `/village/new` は村を作る画面。種類（通常・神モード・ランダム）→ お題 → 人数の順に聞き、人数が決まると村番号・参加用の QR と URL・配布状況を出す。お題は手で入れるか、返事の「お題の自動取得」と難易度のボタンで辞書から引く。ランダム村はお題を聞かない。配布状況は 5 秒ごとと「再確認」で取り直し、画面が隠れている間は取りに行かない。参加者がいない間は、逆村とワーワーズへの切り替えのボタンを出す。
- `/v/<村番号>` は村に入る画面。開くと参加して役職を表示し、「もう一度表示する」で同じ役職を出し直す。特殊村の番号もここで入る。
- `/village/special` は特殊村を作る画面。1 行 1 通で入力し（末尾の空行は数えない。途中の空行は「メッセージは特にありません。」になる）、1〜100 通・各 5,000 文字まで受け付ける。
- 返事は返事モデルのまま描き（`reply.js`）、ボタンは LINE と同じ意味で送り返す。メッセージのボタンはその文字列を送ったのと同じテキストの解釈を、ポストバックのボタンは LINE のポストバックと同じ解釈を通す。Web には文字数の制限がないので、`overflow` は使わず本体だけを描く。
- 文字は `textContent` で描く。画像とリンクは https か自サイトの URL だけを使う。

### 識別

ブラウザが 16 バイトの乱数を base64url にしたトークンを `localStorage` に持ち、本文の `token` で送る。サーバーは `web:<トークン>` を利用者の識別子にする。トークンを知る人がその人として振る舞えるので、URL とログに出さない。`localStorage` が使えないブラウザでは、ページを開いている間だけのトークンになる。

### API

`POST /api/village/<操作>` に JSON を送り、中核の構造化操作を 1 回だけ呼ぶ。

| 操作 | 本文 | 中核 |
| --- | --- | --- |
| `create` | `kind`（`normal` / `god` / `random`） | 村を作る |
| `mine` | — | 何も変えない（画面の再読み込みで続きから表示する） |
| `topic` | `topic` | お題を設定する |
| `size` | `size`（100 以下の整数） | 人数を設定する |
| `reverse` / `werewords` | — | 逆村にする / Werewords の特殊村を作る |
| `join` | `number` | 10000 以上は特殊村、それ以外は通常村に入る（オーナーには配布状況） |
| `text` | `text` | テキストの解釈（返事のメッセージのボタン） |
| `postback` | `data` | ポストバックの解釈（返事のポストバックのボタン） |
| `special` | `messages`（`token` は不要） | 特殊村を作り、`number` を返す |

- 応答は `found`（対象の村があったか）、`replies`（返事モデルの JSON）、`village`（その利用者が作った最新の村の要約: 番号・種類・お題の有無・人数・参加人数・逆村か。お題そのものは含めない）。画面は `village` から次に聞くことを決める。
- 「対象の村がない」は 200 で、`found` が false、`replies` は LINE の既定応答の代替文と同じ案内文になる。本文の形の誤り（JSON でない・型が違う・トークンの形が違う・文字数の超過）は 400。文字数は LINE と同じく UTF-16 の符号単位で数える。
- 同じオリジンからだけ呼ぶ（CORS のヘッダーを出さない）。本文は 2MB まで受け付ける（特殊村の最大の 100 通×5,000 文字が収まり、本番の Caddy の上限と同じ）。

### 設計上の判断

- **村の要約を毎回返す**: 作成の返事の本文には村番号が文字でしか入らない。画面が QR や配布状況のために番号を文字から読み取らなくて済むよう、構造化した要約を添える。作成の直後は「その利用者の最新の村」が作った村なので、作成の応答から番号がわかる。
- **配布状況はポーリング**: お題当てのような 1 秒を争う更新ではないので、WebSocket を使わない。
- **画像の URL**: `PUBLIC_BASE_URL` を設定すると、画像と特殊村フォームの URL をそこから組み立てる（LINE は https の公開 URL しか受け取れない）。未設定ならサイト内の絶対パス（`/static/roles/…`）にし、Web だけならこれで足りる。`ILLUSTRATION_CATALOG_URL` を設定したときだけ、起動直後と 5 分ごとに外部カタログを取り直す。
- **`/healthz`**: HTTP を受け付けていることだけを示し、本文 `ok` を返す。
```

- [ ] **Step 2: docs/village.md のポストバックを中核の解釈として書き直す**

置き換え `docs/village.md`:

```markdown
ポストバックの値は数値で、値域によって意味が変わる。数値でない値は既定の応答になる。

| 値 | 意味 |
| --- | --- |
| 0〜9 | お題候補の取得。`2` 初心者、`3` 上級者、`4` 変態、それ以外は指定なし。ユーザーの識別を必要としない |
| 10〜9999 | 通常村の入室状況確認 |
| 10000 以上 | 特殊村の入室状況確認 |
```

↓

```markdown
ポストバックの値は数値で、中核（`CommandHandler.postback`）が値域によって解釈する。数値の読み方は入力の数値と同じ（全角数字も読む）だが、前後の空白は除かない。数値として読めない値は既定の応答になる。LINE と Web のどちらのボタンも、この解釈を通る。

| 値 | 意味 |
| --- | --- |
| 0〜9 | お題候補の取得。`2` 初心者、`3` 上級者、`4` 変態、それ以外は指定なし。ユーザーの識別を必要としない |
| 10〜9999 と負の値 | 通常村の入室状況確認（負の値の村はないので既定の応答になる） |
| 10000 以上 | 特殊村の入室状況確認 |

Web のメッセージのボタン（確定・確認・再確認・GM / 神）は、その文字列を送ったのと同じテキストの解釈を通る。
```

- [ ] **Step 3: README と .env.example に配役ツールを足す**

置き換え `README.md`:

```markdown
`localhost` 以外からマイクを使うには HTTPS が必要です。
```

↓

```markdown
`localhost` 以外からマイクを使うには HTTPS が必要です。

### インサイダーの配役

Web 版の `/village`（トップページの「インサイダーの配役」）で、LINE Bot と同じように役職とお題を配れます。

1. 「村を作る」で種類・お題・人数を決め、表示された村番号か QR を参加者に伝える
2. 参加者は `/village` で村番号を入れるか QR を読み取り、自分の役職を見る（同じブラウザなら、もう一度開いても同じ役職）
3. 「特殊村を作る」では、1 行 1 通で入れたメッセージを、参加した人に 1 通ずつ配れる
```

置き換え `README.md`:

```markdown
| `WEB_PORT` | | 8080 | Web 版が待ち受けるポート |
```

↓

```markdown
| `WEB_PORT` | | 8080 | Web 版が待ち受けるポート |
| `PUBLIC_BASE_URL` | | — | Web 版の公開 URL（例 `https://game.example.com`）。配役ツールの役職画像と特殊村フォームの URL に使う。未設定ならサイト内のパス |
| `ILLUSTRATION_CATALOG_URL` | | — | 役職画像の外部カタログ（Google Apps Script のデプロイ URL）。設定すると 5 分ごとに取り直す |
```

追記 `.env.example`（末尾。空行を挟まずに続ける）:

```
# 任意（Web 版）: 公開 URL（例 https://game.example.com）。配役ツールの役職画像と特殊村フォームの URL に使う
PUBLIC_BASE_URL=
# 任意（Web 版）: 役職画像の外部カタログ（Google Apps Script のデプロイ URL /macros/s/<ID>/exec）
ILLUSTRATION_CATALOG_URL=
```

- [ ] **Step 4: 記述とコードの一致を確かめる**

Run: `grep -n "api/village\|/village\|/v/\|healthz\|PUBLIC_BASE_URL\|ILLUSTRATION_CATALOG_URL" docs/spec.md docs/village.md README.md .env.example`
Expected: 表の操作名が `src/insider_bot/web/village_api.py` の `_OPERATIONS` と `create_special` に一致し、環境変数名が `src/insider_bot/config.py` に一致する

Run: `uv run pytest -q && node --test tests/js/*.test.mjs`
Expected: どちらも失敗なし

- [ ] **Step 5: コミット**

```bash
git add docs/spec.md docs/village.md README.md .env.example
git commit -m "docs: 配役ツール（Web）の画面・識別・API を設計書と README に足す"
```

---

## 完了の確認

- `uv run pytest -q` と `node --test tests/js/*.test.mjs` がすべて PASS
- Task 6 の Step 7 の 9 項目をブラウザで確かめた
- `docs/spec.md` の API の表が `village_api.py` と、`docs/village.md` のポストバックの表が `commands.postback` と食い違っていない
- `git log --oneline` に Task ごとのコミットが並んでいる
- LINE の入口（`/line/callback`）はまだない（M3 の仕事）。M3 は `village_setup.build_village` が作った同じ `VillageApp` に LINE のルートを足す
