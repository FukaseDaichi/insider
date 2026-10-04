# M3: LINE アダプタ 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LINE Bot の webhook（`POST /line/callback`）を Web 版のプロセスで受け、M1 の村の中核を通して、LineBot（Java）と同じ JSON で返信する。Java との突き合わせ（ゴールデン比較）と切替前の検証の道具も用意する。

**Architecture:** `insider_bot/line/` に、返事モデル → LINE の JSON のレンダラ、署名、返信 API のクライアント、webhook を置く。webhook は M2 で `build_village` が組み立てた同じ中核（`CommandHandler` と `Illustrations`）を受け取るので、LINE で作った村に Web から入れる。返信は待たずにタスクで送り、webhook は 200 を先に返す。LINE は `LINE_CHANNEL_SECRET` と `LINE_CHANNEL_TOKEN` を設定したときだけ有効になる。

**Tech Stack:** Python 3.13、uv、aiohttp、httpx2（返信 API）、pytest（pytest-asyncio の auto モード）。LINE の公式 SDK は使わない。

**Spec:** [docs/superpowers/specs/2026-10-03-unify-line-web-discord-design.md](../specs/2026-10-03-unify-line-web-discord-design.md)（マイルストーン M3 と「LINE アダプタ」「テスト」の節）。村の振る舞いの契約は [docs/village.md](../../village.md)。Java の正解は `~/git/LineBot`（`insider-game-bot/src/main/java/insidergame/adapter/LineEventHandler.java`、`StickerReplyEvent.java`、`game/Village.java`）。

## Global Constraints

- Python は `>=3.13`、パッケージ管理は uv。`pip` や system python は使わない。テストは `uv run pytest`
- 新しい実行時依存を足さない。HTTP は既存の `httpx2`。LINE の公式 SDK は入れない
- 中核の 1 操作の途中で `await` を挟まない（本文を読み終えてから、イベントごとに中核の同期の操作を高々 1 回呼ぶ）
- 返事の文言は中核の `texts.py` / `messages.py` をそのまま使い、LINE の JSON は LineBot（Java）と同じ形にする: ボタンテンプレートのサムネイルと見出しは画像とタイトルがあるときだけ、`imageSize` は常に `"contain"`、値のない項目は送らない、代替文は `alt_text`（なければ本文）
- ボタンテンプレートの本文の上限は、画像かタイトルがあれば 60、なければ 160。数え方は UTF-16 の符号単位（`parsing.java_length`）
- 署名は本文の bytes の HMAC-SHA256（チャネルシークレット）を Base64 にしたもの。`X-Line-Signature` と定数時間で比べ、合わなければ 400
- 返信は待たない（`asyncio.create_task`）。返信 API のタイムアウトは 10 秒。失敗は WARNING ログだけで再試行しない
- イベントの本文・LINE ユーザー ID・入力の文・お題をログに出さない。出すのはイベントの種別と処理の結果まで
- 利用者の識別子は `line:<LINE ユーザー ID>`
- 環境変数の名前: `LINE_CHANNEL_SECRET`、`LINE_CHANNEL_TOKEN`、`LINE_API_BASE_URL`（既定 `https://api.line.me`）。LINE を使うときは `PUBLIC_BASE_URL` が https の公開 URL であること
- `@特殊` の案内先は `PUBLIC_BASE_URL + /village/special`（M2 で済み）、スタンプ応答のホームページは `PUBLIC_BASE_URL`、ご意見フォームは Java と同じ Google フォーム
- `docs/` は現在形で、コードの現状と一致させる（docs/AGENTS.md）
- コミットメッセージは日本語、既存の書き方（`feat:` / `fix:` / `test:` / `docs:` の接頭辞）。`.claude/launch.json` と `assets/` の未追跡ファイルはコミットしない

## Review Focus

仕様が黙っているが、使う人に当たりそうな入力。各行のテストを所有タスクに入れてある。

1. **LINE コンソールの「検証」や、1 回の webhook にまとめて届く複数のイベント** → `events` が空でも 200。複数なら、それぞれの replyToken へ届いた順に返す（Task 3）
2. **署名は合うが中身が想定外の webhook**（JSON でない、`events` がない、返信先のないイベント、`text` のないテキストメッセージ、画像メッセージ、follow）→ 500 にならない。読めない本文は 400、読めるが返信しないイベントは 200 で黙って読み飛ばし、返信先のないテキストで村を作らない（Task 3）
3. **絵文字を含むお題で、役職メッセージがボタンの上限ちょうど・1 文字超え** → UTF-16 で数えて Java と同じ形（60 で画像つきのボタン、61 で Text と入室状況）（Task 1、Task 6）
4. **返信 API が遅い・401（トークンの誤り）・400** → webhook は待たずに 200。失敗は本文も ID も含まない WARNING 1 行（Task 3）
5. **グループトークで、ユーザー ID のない人が村を作ろうとする** → 村を作らずに 1 対 1 のトークを促す。お題候補のポストバックとスタンプだけは答える（Task 3）

---

## ファイル構成

```
src/insider_bot/line/
  __init__.py      LINE の入口（パッケージの説明だけ）
  render.py        返事モデル → LINE のメッセージ JSON（render、action_json、fits）
  sticker.py       スタンプ応答（sticker_reply、FEEDBACK_FORM_URL、STICKER_MESSAGE）
  signature.py     webhook の署名（sign、verify）
  client.py        返信 API のクライアント（LineReplyClient）
  webhook.py       POST /line/callback（LineWebhook、add_line_routes）
src/insider_bot/config.py         LineConfig と WebConfig.line、URL の読み取りの誤りを ConfigError に
src/insider_bot/web/__main__.py   LINE を設定したときだけ webhook をつなぐ
deploy/verify/
  line_api_stub.py   返信 API のスタブ（LineBot から移植）
  post_callback.py   署名付きの webhook を送る（LineBot から移植）
tests/
  test_line_render.py / test_line_signature.py / test_line_client.py / test_line_webhook.py
  test_web_config.py（追記） / test_web_main.py / test_deploy_verify.py
  line_golden.py       ゴールデン比較の入力の列・正規化・採取（python -m tests.line_golden）
  test_line_golden.py
  golden/line_callapi.json   Java の /callapi から採った JSON
docs/spec.md  docs/village.md  README.md  .env.example
```

## 表記の約束

- 「新規 `パス`:」の直後のコードブロックは、そのファイルの中身すべて。
- 「追記 `パス`（末尾）:」の直後のコードブロックは、ファイルの末尾に足す。足す前に空行を 2 行入れる（Python のトップレベル）。Markdown と `.env.example` は指示に従う。
- 「置き換え `パス`:」の直後のコードブロックがいまの文字列で、`↓` の後のコードブロックが置き換え後の文字列。いまの文字列はファイルの中で 1 か所だけに現れる。

---

### Task 1: レンダラ（返事モデル → LINE の JSON）とスタンプ応答

**Files:**
- Create: `src/insider_bot/line/__init__.py`、`src/insider_bot/line/render.py`、`src/insider_bot/line/sticker.py`
- Test: `tests/test_line_render.py`

**Interfaces:**
- Consumes: `insider_bot.village.reply` の `Text` / `Image` / `Buttons` / `Confirm` / `MessageAction` / `PostbackAction` / `UriAction` / `Action` / `Reply`、`parsing.java_length`、`Illustrations(base_url, rng=None)` と `url_for(role_key)`（同梱の 5 枚から乱数で選び、URL に `?v=<ROLE_IMAGE_VERSION>` を付ける。テストは `tests.fakes.FirstRandom` で常に 1 枚目にする）
- Produces（`render.py`）: `MAX_BUTTONS_TEXT_WITH_IMAGE = 60`、`MAX_BUTTONS_TEXT = 160`、`action_json(action) -> dict[str, str]`、`fits(buttons: Buttons) -> bool`、`render(replies: Iterable[Reply]) -> list[dict[str, Any]]`（返信 API の `messages` にそのまま渡せる列。overflow に落ちると返事 1 つが 2 通以上になる。知らない型は `TypeError`）
- Produces（`sticker.py`）: `FEEDBACK_FORM_URL`、`STICKER_MESSAGE`、`sticker_reply(illust: Illustrations, homepage_url: str) -> list[Reply]`
- LINE の JSON の形（Java の SDK の JSON から null の項目を除いたもの）:
  - `{"type": "text", "text"}`、`{"type": "image", "originalContentUrl": url, "previewImageUrl": url}`
  - `{"type": "template", "altText", "template": {"type": "buttons", ["thumbnailImageUrl"], "imageSize": "contain", ["title"], "text", "actions"}}`
  - `{"type": "template", "altText", "template": {"type": "confirm", "text", "actions"}}`
  - ボタン: `{"type": "message", "label", "text"}`、`{"type": "postback", "label", "data"}`、`{"type": "uri", "label", "uri"}`

- [ ] **Step 1: 失敗するテストを書く**

新規 `tests/test_line_render.py`:

```python
import pytest

from insider_bot.line.render import action_json, render
from insider_bot.line.sticker import FEEDBACK_FORM_URL, STICKER_MESSAGE, sticker_reply
from insider_bot.village import messages
from insider_bot.village.illust import ROLE_IMAGE_VERSION, Illustrations
from insider_bot.village.model import SpecialVillage, Village
from insider_bot.village.reply import Buttons, Image, MessageAction, PostbackAction, Text, UriAction
from insider_bot.web.replyjson import replies_json
from tests.fakes import FirstRandom, FixedRandom

BASE = "https://game.example.com"
# 役職画像は毎回 5 枚から選ぶので、1 枚目に固定する
ILLUST = Illustrations(BASE, FirstRandom())


def role_image(name: str) -> str:
    return f"{BASE}/static/roles/{name}.png?v={ROLE_IMAGE_VERSION}"


def insider_village(topic: str) -> Village:
    """1 番目の参加者「a」がインサイダーの 2 人村。"""
    village = Village("owner")
    village.number = 1234
    village.set_topic(topic)
    assert village.configure(2, FixedRandom(0))
    village.join("a")
    return village


def gm_village(topic: str) -> Village:
    """1 番目「a」がインサイダー、2 番目「gm」が GM の神モードの 2 人村。全員が揃っている。"""
    village = Village("owner")
    village.number = 1234
    village.set_topic(topic)
    village.mark_god_mode()
    assert village.configure(2, FixedRandom(0, 1))
    village.join("a")
    village.join("gm")
    return village


def owner_village(topic: str) -> Village:
    """お題と人数（2 人）が決まり、まだ誰も入っていない村。"""
    village = Village("owner")
    village.number = 1234
    village.set_topic(topic)
    assert village.configure(2, FixedRandom(0))
    return village


def shape(line_messages):
    """メッセージの形だけを見る: text、画像つきのボタン（buttons+image）、画像なしのボタン（buttons）。"""
    kinds = []
    for message in line_messages:
        if message["type"] == "template":
            template = message["template"]
            kinds.append("buttons+image" if "thumbnailImageUrl" in template else template["type"])
        else:
            kinds.append(message["type"])
    return kinds


def test_text_and_image():
    url = f"{BASE}/static/roles/966mpnqz.png"
    assert render([Text("本文\n2 行目"), Image(url)]) == [
        {"type": "text", "text": "本文\n2 行目"},
        {"type": "image", "originalContentUrl": url, "previewImageUrl": url},
    ]


def test_actions():
    assert action_json(MessageAction("確定", "すいか")) == {"type": "message", "label": "確定", "text": "すいか"}
    assert action_json(PostbackAction("初心者", "2")) == {"type": "postback", "label": "初心者", "data": "2"}
    assert action_json(UriAction("ご意見", "https://x")) == {"type": "uri", "label": "ご意見", "uri": "https://x"}


def test_a_role_with_an_image_is_a_buttons_template_with_a_thumbnail_and_no_title():
    # Java の ButtonsTemplateNonTitle。imageSize は Java と同じく常に contain
    text = "あなたの役職はインサイダーです。お題は『すいか』です。"
    assert render(messages.role_reply(insider_village("すいか"), "a", ILLUST)) == [
        {
            "type": "template",
            "altText": text,
            "template": {
                "type": "buttons",
                "thumbnailImageUrl": role_image("INSIDER"),
                "imageSize": "contain",
                "text": text,
                "actions": [{"type": "postback", "label": "入室状況確認", "data": "1234"}],
            },
        }
    ]


def test_the_size_reply_has_a_thumbnail_a_title_and_its_own_alt_text():
    # Java の ButtonsTemplate（サムネイルと見出しあり）。代替文だけ「配布状況の確認は…」が続く
    text = "人数を『2人』に設定しました。\n皆さんに村番号を伝えてください。"
    assert render(messages.size_set_reply(owner_village("すいか"), False, ILLUST)) == [
        {
            "type": "template",
            "altText": text + "配布状況の確認は村番号を入力してください。",
            "template": {
                "type": "buttons",
                "thumbnailImageUrl": role_image("GM"),
                "imageSize": "contain",
                "title": "1234村",
                "text": text,
                "actions": [{"type": "message", "label": "確認", "text": "1234"}],
            },
        }
    ]


def test_buttons_without_an_image_or_a_title_have_neither_key():
    # Java の ButtonsTemplateNonURL。null を送らず、キーごと持たない
    text = "1234村 を新しく作成しました。お題を入力してください。"
    assert render(messages.created_reply(1234)) == [
        {
            "type": "template",
            "altText": text,
            "template": {
                "type": "buttons",
                "imageSize": "contain",
                "text": text + "\nお題の自動取得もできます。",
                "actions": [{"type": "postback", "label": "お題の自動取得", "data": "0"}],
            },
        }
    ]


def test_the_default_reply_is_the_confirm_template_of_the_java_webhook():
    assert render(messages.default_reply()) == [
        {
            "type": "template",
            "altText": "お題を配りたい方は「お題」または「神」を、\nお題及び役職を確認したい場合は村番号（数字4桁）を入力してください。",
            "template": {
                "type": "confirm",
                "text": "村の作成をしますか？",
                "actions": [
                    {"type": "message", "label": "GM", "text": "お題"},
                    {"type": "message", "label": "神", "text": "神"},
                ],
            },
        }
    ]


@pytest.mark.parametrize("topic", ["あ" * 36, "😀" * 18], ids=["kana", "emoji"])
def test_an_insider_role_of_exactly_60_utf16_units_keeps_the_image(topic):
    assert shape(render(messages.role_reply(insider_village(topic), "a", ILLUST))) == ["buttons+image"]


@pytest.mark.parametrize("topic", ["あ" * 37, "😀" * 18 + "あ"], ids=["kana", "emoji"])
def test_an_insider_role_over_60_utf16_units_becomes_text_and_status(topic):
    # 絵文字は UTF-16 で 2 と数える。len() で数えると「😀」18 個と「あ」は 43 文字になり、テンプレートに収まってしまう
    assert render(messages.role_reply(insider_village(topic), "a", ILLUST)) == [
        {"type": "text", "text": f"あなたの役職はインサイダーです。お題は『{topic}』です。"},
        {"type": "text", "text": "あなたは1番目の参加者です。\n　入室状況：1/2人"},
    ]


def test_the_gm_role_falls_back_from_image_to_plain_buttons_to_text():
    # 「役職はＧＭです。\n2/2人にお題を配りました。お題は『』です。」は 31 文字
    def gm(topic):
        return shape(render(messages.role_reply(gm_village(topic), "gm", ILLUST)))

    assert gm("あ" * 29) == ["buttons+image"]  # 60
    assert gm("あ" * 30) == ["buttons"]  # 61
    assert gm("あ" * 129) == ["buttons"]  # 160
    assert gm("あ" * 130) == ["text", "text"]  # 161


def test_the_owner_status_becomes_a_single_text_over_160():
    # 「1234村：0/2人にお題を配りました。お題は『』です。」は 28 文字
    assert shape(render(messages.owner_reply(owner_village("あ" * 132)))) == ["buttons"]
    text = f"1234村：0/2人にお題を配りました。お題は『{'あ' * 133}』です。"
    assert render(messages.owner_reply(owner_village("あ" * 133))) == [{"type": "text", "text": text}]


def test_a_special_village_message_becomes_text_and_status_over_160():
    def special(message):
        village = SpecialVillage([message])
        village.number = 12345
        village.join("a")
        return render(messages.special_role_reply(village, "a"))

    assert shape(special("あ" * 160)) == ["buttons"]
    assert special("あ" * 161) == [
        {"type": "text", "text": "あ" * 161},
        {"type": "text", "text": "あなたは1番目の参加者です。\n　入室状況：1/1人"},
    ]


def test_buttons_without_overflow_stay_a_template_whatever_the_length():
    # Java も、本文が固定文のボタン（村人の役職・お題候補など）は長さを確かめずにテンプレートで送る
    (message,) = render([Buttons("あ" * 200, (MessageAction("確定", "x"),))])
    assert message["template"]["text"] == "あ" * 200


def test_the_sticker_reply_matches_the_java_sticker_event():
    assert FEEDBACK_FORM_URL == (
        "https://docs.google.com/forms/d/e/1FAIpQLSf5pH-nC86Lb9L18dx9fBJv1ZUu-qdftS_PBkBRA5imjjFVgA/viewform"
    )
    assert render(sticker_reply(ILLUST, BASE)) == [
        {
            "type": "template",
            "altText": f"製作者の「白いフランです。」\n{STICKER_MESSAGE}\n Hp:  {BASE}",
            "template": {
                "type": "buttons",
                "thumbnailImageUrl": role_image("INSIDER"),
                "imageSize": "contain",
                "text": "ご利用ありがとうございます。要望・報告は以下にご連絡ください。",
                "actions": [
                    {"type": "uri", "label": "ご意見", "uri": FEEDBACK_FORM_URL},
                    # 「ホームぺージ」の「ぺ」はひらがな（U+307A）。Java の原文のまま
                    {"type": "uri", "label": "ホームぺージ", "uri": BASE},
                ],
            },
        }
    ]


@pytest.mark.parametrize(
    "replies",
    [
        messages.created_reply(1234),
        messages.default_reply(),
        messages.candidate_reply("すいか"),
        messages.topic_set_reply(owner_village("すいか")),
    ],
    ids=["created", "default", "candidate", "topic"],
)
def test_line_and_web_draw_the_same_words_from_the_same_reply(replies):
    line = render(replies)
    web = replies_json(replies)
    assert len(line) == len(web)
    for line_message, web_message in zip(line, web):
        line_text = line_message["template"]["text"] if line_message["type"] == "template" else line_message["text"]
        assert line_text == web_message["text"]


def test_unknown_types_are_rejected():
    with pytest.raises(TypeError):
        render([object()])
    with pytest.raises(TypeError):
        action_json(object())
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_line_render.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.line'` で収集に失敗する

- [ ] **Step 3: 実装する**

新規 `src/insider_bot/line/__init__.py`:

```python
"""LINE の入口。webhook を受け、村の中核の返事を LINE のメッセージにして返信する。"""
```

新規 `src/insider_bot/line/render.py`:

```python
"""返事モデルを LINE のメッセージ JSON にする。

LineBot（Java）が同梱の SDK で送っていた JSON と同じ形にする。ボタンテンプレートは、Java が SDK に手を入れて
作っていた 3 つの形（サムネイルと見出しあり・サムネイルだけ・どちらもなし）を、画像とタイトルの有無で選ぶ。
imageSize は Java と同じく常に "contain"。Java が null のまま送っていた項目（imageAspectRatio など）は送らない
（LINE はどちらも省略として扱う）。

本文がボタンテンプレートに収まらないとき（画像かタイトルがあれば 60、なければ 160。UTF-16 の符号単位で数える）は
Buttons.overflow を代わりに描く。overflow を持たないボタンは、長さによらずテンプレートで送る（Java と同じ）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from insider_bot.village.parsing import java_length
from insider_bot.village.reply import Action, Buttons, Confirm, Image, MessageAction, PostbackAction, Reply, Text, UriAction

# ボタンテンプレートの本文の上限。画像かタイトルがあると短くなる
MAX_BUTTONS_TEXT_WITH_IMAGE = 60
MAX_BUTTONS_TEXT = 160


def action_json(action: Action) -> dict[str, str]:
    if isinstance(action, MessageAction):
        return {"type": "message", "label": action.label, "text": action.text}
    if isinstance(action, PostbackAction):
        return {"type": "postback", "label": action.label, "data": action.data}
    if isinstance(action, UriAction):
        return {"type": "uri", "label": action.label, "uri": action.uri}
    raise TypeError(f"未知のボタン: {type(action).__name__}")


def fits(buttons: Buttons) -> bool:
    """本文がボタンテンプレートに収まるか。LINE と同じく UTF-16 の符号単位で数える。"""
    with_image = buttons.image is not None or buttons.title is not None
    return java_length(buttons.text) <= (MAX_BUTTONS_TEXT_WITH_IMAGE if with_image else MAX_BUTTONS_TEXT)


def _buttons_template(buttons: Buttons) -> dict[str, Any]:
    template: dict[str, Any] = {"type": "buttons"}
    if buttons.image is not None:
        template["thumbnailImageUrl"] = buttons.image
    template["imageSize"] = "contain"
    if buttons.title is not None:
        template["title"] = buttons.title
    template["text"] = buttons.text
    template["actions"] = [action_json(action) for action in buttons.actions]
    return template


def _template_message(alt_text: str | None, text: str, template: dict[str, Any]) -> dict[str, Any]:
    return {"type": "template", "altText": text if alt_text is None else alt_text, "template": template}


def _render_one(reply: Reply) -> list[dict[str, Any]]:
    if isinstance(reply, Text):
        return [{"type": "text", "text": reply.text}]
    if isinstance(reply, Image):
        return [{"type": "image", "originalContentUrl": reply.url, "previewImageUrl": reply.url}]
    if isinstance(reply, Buttons):
        if reply.overflow and not fits(reply):
            return render(reply.overflow)
        return [_template_message(reply.alt_text, reply.text, _buttons_template(reply))]
    if isinstance(reply, Confirm):
        template = {"type": "confirm", "text": reply.text, "actions": [action_json(action) for action in reply.actions]}
        return [_template_message(reply.alt_text, reply.text, template)]
    raise TypeError(f"未知の返事: {type(reply).__name__}")


def render(replies: Iterable[Reply]) -> list[dict[str, Any]]:
    """返事の列を、返信 API の messages にそのまま渡せる列にする。overflow に落ちた返事は 2 通以上になる。"""
    return [message for reply in replies for message in _render_one(reply)]
```

新規 `src/insider_bot/line/sticker.py`:

```python
"""スタンプへの応答。ゲームの操作ではないので、製作者への連絡先とホームページを案内するだけ。

文言とボタンは LineBot（Java）の StickerReplyEvent と一字一句同じ。「ホームぺージ」の「ぺ」はひらがな（原文のまま）。
ホームページは Web 版の公開 URL、ご意見フォームは Java と同じ Google フォーム。
"""

from __future__ import annotations

from insider_bot.village.illust import Illustrations
from insider_bot.village.reply import Buttons, Reply, UriAction

FEEDBACK_FORM_URL = (
    "https://docs.google.com/forms/d/e/1FAIpQLSf5pH-nC86Lb9L18dx9fBJv1ZUu-qdftS_PBkBRA5imjjFVgA/viewform"
)
STICKER_MESSAGE = "ご利用ありがとうございます。要望・報告は以下にご連絡ください。"


def sticker_reply(illust: Illustrations, homepage_url: str) -> list[Reply]:
    return [
        Buttons(
            STICKER_MESSAGE,
            (UriAction("ご意見", FEEDBACK_FORM_URL), UriAction("ホームぺージ", homepage_url)),
            image=illust.url_for("INSIDER"),
            alt_text=f"製作者の「白いフランです。」\n{STICKER_MESSAGE}\n Hp:  {homepage_url}",
        )
    ]
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_line_render.py -q`
Expected: `20 passed`

Run: `uv run pytest -q`
Expected: `480 passed, 4 deselected`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/line/__init__.py src/insider_bot/line/render.py src/insider_bot/line/sticker.py tests/test_line_render.py
git commit -m "feat: 返事モデルを LineBot と同じ LINE のメッセージ JSON にする"
```

---

### Task 2: 署名と返信 API のクライアント

**Files:**
- Create: `src/insider_bot/line/signature.py`、`src/insider_bot/line/client.py`
- Test: `tests/test_line_signature.py`、`tests/test_line_client.py`

**Interfaces:**
- Produces（`signature.py`）: `sign(channel_secret: str, body: bytes) -> str`、`verify(channel_secret: str, body: bytes, signature: str | None) -> bool`
- Produces（`client.py`）: `DEFAULT_API_BASE_URL = "https://api.line.me"`、`REPLY_PATH = "/v2/bot/message/reply"`、`REPLY_TIMEOUT_SECONDS = 10.0`、`MAX_REPLY_MESSAGES = 5`、`LineReplyClient(channel_token: str, api_base_url: str = DEFAULT_API_BASE_URL, transport: httpx2.AsyncBaseTransport | None = None)` と `async reply(reply_token: str, messages: list[dict[str, Any]]) -> None`（HTTP のエラーと通信の失敗は httpx2 の例外のまま上げる。0 通・6 通以上は送らずに `ValueError`）、`async aclose() -> None`

- [ ] **Step 1: 失敗するテストを書く**

新規 `tests/test_line_signature.py`:

```python
import pytest

from insider_bot.line.signature import sign, verify

SECRET = "channel-secret"
BODY = b'{"events":[]}'


def test_sign_is_base64_of_hmac_sha256_over_the_raw_body():
    # LineBot の deploy/verify と同じ既知のベクトル: HMAC-SHA256("secret", "body") の Base64
    assert sign("secret", b"body") == "3EaYNVf+oSe0OvchRn65s/3iM4/j4U9RlSqoR4wT01U="


def test_verify_accepts_the_signature_of_the_body():
    assert verify(SECRET, BODY, sign(SECRET, BODY))


@pytest.mark.parametrize(
    ("body", "signature"),
    [
        (BODY + b" ", sign(SECRET, BODY)),
        (BODY, sign("other-secret", BODY)),
        (BODY, None),
        (BODY, ""),
        (BODY, "署名"),
        (BODY, "\udc80"),
    ],
    ids=["tampered-body", "other-secret", "missing", "empty", "non-ascii", "lone-surrogate"],
)
def test_verify_rejects_anything_else(body, signature):
    assert not verify(SECRET, body, signature)
```

新規 `tests/test_line_client.py`:

```python
import json

import httpx2
import pytest

from insider_bot.line.client import LineReplyClient

MESSAGES = [{"type": "text", "text": "こんにちは"}]


def recording(status=200):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(status, json={})

    return requests, httpx2.MockTransport(handler)


async def test_reply_posts_the_token_and_the_messages_with_the_bearer_token():
    requests, transport = recording()
    client = LineReplyClient("channel-token", transport=transport)
    await client.reply("reply-token", MESSAGES)
    await client.aclose()
    (request,) = requests
    assert (request.method, str(request.url)) == ("POST", "https://api.line.me/v2/bot/message/reply")
    assert request.headers["Authorization"] == "Bearer channel-token"
    assert json.loads(request.content) == {"replyToken": "reply-token", "messages": MESSAGES}


async def test_the_api_base_url_can_point_at_a_stub():
    requests, transport = recording()
    client = LineReplyClient("channel-token", "http://127.0.0.1:18080", transport=transport)
    await client.reply("reply-token", MESSAGES)
    await client.aclose()
    assert str(requests[0].url) == "http://127.0.0.1:18080/v2/bot/message/reply"


async def test_http_errors_are_raised_for_the_caller_to_log():
    _, transport = recording(status=400)
    client = LineReplyClient("channel-token", transport=transport)
    with pytest.raises(httpx2.HTTPStatusError):
        await client.reply("reply-token", MESSAGES)
    await client.aclose()


@pytest.mark.parametrize("count", [0, 6])
async def test_no_messages_or_more_than_five_are_refused_before_sending(count):
    requests, transport = recording()
    client = LineReplyClient("channel-token", transport=transport)
    with pytest.raises(ValueError):
        await client.reply("reply-token", MESSAGES * count)
    await client.aclose()
    assert requests == []
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_line_signature.py tests/test_line_client.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.line.signature'` と `... 'insider_bot.line.client'` で収集に失敗する

- [ ] **Step 3: 実装する**

新規 `src/insider_bot/line/signature.py`:

```python
"""LINE の webhook の署名。本文の bytes に対する HMAC-SHA256 をチャネルシークレットで計算し、Base64 にしたもの。"""

from __future__ import annotations

import base64
import hashlib
import hmac


def sign(channel_secret: str, body: bytes) -> str:
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify(channel_secret: str, body: bytes, signature: str | None) -> bool:
    """X-Line-Signature が本文の署名と一致するか。一致した長さを時間の差から推測されないよう、定数時間で比べる。"""
    if not signature:
        return False
    # ASCII でない値（壊れたヘッダー）は一致しないだけで、例外にしない
    return hmac.compare_digest(sign(channel_secret, body).encode("ascii"), signature.encode("utf-8", "replace"))
```

新規 `src/insider_bot/line/client.py`:

```python
"""LINE の返信 API（POST /v2/bot/message/reply）のクライアント。公式の SDK は使わず httpx2 で送る。

送るのは返信だけ。replyToken は 1 回限りで短命なので、失敗しても再試行しない（呼び出し側がログに残す）。
"""

from __future__ import annotations

from typing import Any

import httpx2

DEFAULT_API_BASE_URL = "https://api.line.me"
REPLY_PATH = "/v2/bot/message/reply"
REPLY_TIMEOUT_SECONDS = 10.0
# 1 回の返信で送れるメッセージの数の上限
MAX_REPLY_MESSAGES = 5


class LineReplyClient:
    def __init__(
        self,
        channel_token: str,
        api_base_url: str = DEFAULT_API_BASE_URL,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx2.AsyncClient(
            base_url=api_base_url,
            headers={"Authorization": f"Bearer {channel_token}"},
            timeout=REPLY_TIMEOUT_SECONDS,
            transport=transport,
        )

    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> None:
        """返信する。HTTP のエラーと通信の失敗は httpx2 の例外のまま上げる。"""
        if not 1 <= len(messages) <= MAX_REPLY_MESSAGES:
            # LINE が 400 で断る返信を送らない
            raise ValueError(f"返信のメッセージは 1〜{MAX_REPLY_MESSAGES} 通です（{len(messages)} 通）")
        response = await self._client.post(REPLY_PATH, json={"replyToken": reply_token, "messages": messages})
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_line_signature.py tests/test_line_client.py -q`
Expected: `13 passed`

Run: `uv run pytest -q`
Expected: `493 passed, 4 deselected`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/line/signature.py src/insider_bot/line/client.py tests/test_line_signature.py tests/test_line_client.py
git commit -m "feat: LINE の webhook の署名と、返信 API のクライアントを足す"
```

---

### Task 3: webhook（POST /line/callback）

**Files:**
- Create: `src/insider_bot/line/webhook.py`
- Test: `tests/test_line_webhook.py`

**Interfaces:**
- Consumes: Task 1 の `render`、`sticker_reply`。Task 2 の `verify`、`sign`（テスト）。M1 の `CommandHandler.handle(user_id, text)`、`CommandHandler.postback(user_id | None, data)`（M2 で追加）、`messages.default_reply()`、`texts.ERR_UNIDENTIFIED_USER`、`Illustrations`
- Produces: `CALLBACK_PATH = "/line/callback"`、`SIGNATURE_HEADER = "X-Line-Signature"`、`ReplySender`（Protocol: `async reply(reply_token, messages) -> None`。`LineReplyClient` が満たす）、`LineWebhook(channel_secret: str, commands: CommandHandler, illust: Illustrations, sender: ReplySender, homepage_url: str)` と `async handle(request) -> web.Response`、`replies_for(event: dict) -> list[Reply] | None`、`async drain() -> None`、`add_line_routes(app: web.Application, webhook: LineWebhook) -> None`（パスを足し、停止の前に `drain` する）
- HTTP の契約: 署名が合わない・本文が JSON のオブジェクトでない・`events` が配列でない → 400。それ以外は 200（本文 `OK`）。返信は 200 を返した後に送る
- イベントの扱い（Java の `LineEventHandler` と同じ）:
  - テキスト: ユーザー ID がなければ `[Text(ERR_UNIDENTIFIED_USER)]`（中核を呼ばない）。あれば `commands.handle("line:<ID>", text)`、`None` なら既定の確認テンプレート
  - ポストバック: `commands.postback("line:<ID>" か None, data)`、`None`（読めない data を含む）なら既定の確認テンプレート。`data` がなければ既定の確認テンプレート
  - スタンプ: `sticker_reply(illust, homepage_url)`（ユーザー ID は要らない）
  - それ以外・`replyToken` のないイベント・オブジェクトでない要素: 返信しない（中核も呼ばない）

- [ ] **Step 1: 失敗するテストを書く**

新規 `tests/test_line_webhook.py`:

```python
import asyncio
import contextlib
import json
import logging
import random

import httpx2
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from insider_bot.line.render import render
from insider_bot.line.signature import sign
from insider_bot.line.sticker import sticker_reply
from insider_bot.line.webhook import CALLBACK_PATH, LineWebhook, add_line_routes
from insider_bot.village import messages
from insider_bot.village.commands import CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.service import VillageService
from insider_bot.village.words import parse_dictionary
from tests.fakes import FirstRandom, FixedRandom

SECRET = "channel-secret"
BASE = "https://game.example.com"
OWNER = "U0123456789abcdef0123456789abcdef"
MEMBER = "Ufedcba9876543210fedcba9876543210"
DICTIONARY = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])
# 役職画像は毎回 5 枚から選ぶので、1 枚目に固定する（スタンプ応答の期待値と同じ画像になる）
ILLUST = Illustrations(BASE, FirstRandom())
UNIDENTIFIED = [{"type": "text", "text": "ユーザーを識別できないため操作できません。\nbotとの1対1のトークから操作してください。"}]


class CountingRegistry(VillageRegistry):
    """作られた村を数える。識別できない利用者の操作で村が増えないことを確かめる。"""

    def __init__(self) -> None:
        super().__init__(random.Random(1))
        self.added = 0

    def add(self, village):
        self.added += 1
        return super().add(village)


class RecordingSender:
    """返信を記録する。gate を渡すと set されるまで送信中のまま止まり、error を渡すと送信に失敗する。"""

    def __init__(self, gate: asyncio.Event | None = None, error: Exception | None = None) -> None:
        self.sent: list[tuple[str, list[dict]]] = []
        self.gate = gate
        self.error = error

    async def reply(self, reply_token, line_messages):
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        self.sent.append((reply_token, line_messages))


@contextlib.asynccontextmanager
async def serve(sender, *draws):
    """配役の乱数だけを固定し（draws）、採番は本物の乱数に任せる。"""
    villages = CountingRegistry()
    rng = FixedRandom(*draws) if draws else random.Random(3)
    service = VillageService(villages, SpecialVillageRegistry(random.Random(2)), DICTIONARY, ILLUST, rng)
    webhook = LineWebhook(SECRET, CommandHandler(service, f"{BASE}/village/special"), ILLUST, sender, BASE)
    app = web.Application()
    add_line_routes(app, webhook)
    async with TestClient(TestServer(app)) as client:
        yield client, webhook, villages


def source(user):
    return {"type": "user", "userId": user} if user is not None else {"type": "group", "groupId": "Cgroup"}


def text_event(text, user=OWNER, token="token-1"):
    message = {"type": "text", "id": "1", "text": text}
    return {"type": "message", "replyToken": token, "source": source(user), "message": message}


def postback_event(data, user=OWNER, token="token-1"):
    return {"type": "postback", "replyToken": token, "source": source(user), "postback": {"data": data}}


def sticker_event(user=OWNER, token="token-1"):
    message = {"type": "sticker", "id": "1", "packageId": "1", "stickerId": "1"}
    return {"type": "message", "replyToken": token, "source": source(user), "message": message}


async def post(client, *events, body=None, headers=None):
    """署名つきで webhook を送る。body と headers を渡すと、そのまま送る。"""
    if body is None:
        body = json.dumps({"destination": "Ubot", "events": list(events)}, ensure_ascii=False).encode()
    if headers is None:
        headers = {"X-Line-Signature": sign(SECRET, body)}
    return await client.post(CALLBACK_PATH, data=body, headers={"Content-Type": "application/json", **headers})


async def deliver(client, webhook, *events):
    """webhook を送って 200 を確かめ、送りかけの返信を待つ。"""
    response = await post(client, *events)
    assert response.status == 200
    await webhook.drain()


def owned(villages, user=OWNER):
    return villages.find_latest_owned(f"line:{user}", lambda v: True)


# --- テキスト ---


async def test_a_text_message_is_answered_through_the_core():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        await deliver(client, webhook, text_event("お題"))
        # LINE の利用者は line:<ユーザー ID> で識別する
        number = owned(villages).number
    assert sender.sent == [("token-1", render(messages.created_reply(number)))]


async def test_no_village_gets_the_confirm_template_that_suggests_creating_one():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(client, webhook, text_event("500"))
    assert sender.sent == [("token-1", render(messages.default_reply()))]


@pytest.mark.parametrize("text", ["お題", "ランダム", "3", "すいか", "@逆村"])
async def test_text_without_a_user_id_is_refused_without_changing_anything(text):
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        await deliver(client, webhook, text_event(text, user=None))
    assert sender.sent == [("token-1", UNIDENTIFIED)]
    assert villages.added == 0


# --- ポストバック ---


async def test_a_topic_candidate_postback_is_answered_even_without_a_user_id():
    sender = RecordingSender()
    async with serve(sender, 0) as (client, webhook, _):
        await deliver(client, webhook, postback_event("2", user=None))
    assert sender.sent == [("token-1", render(messages.candidate_reply("a")))]


async def test_a_status_postback_without_a_user_id_is_refused():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(client, webhook, postback_event("1234", user=None))
    assert sender.sent == [("token-1", UNIDENTIFIED)]


async def test_a_status_postback_answers_the_seat_and_the_count():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        await deliver(client, webhook, text_event("お題"), text_event("すいか"), text_event("2"))
        number = owned(villages).number
        await deliver(client, webhook, text_event(str(number), user=MEMBER))
        await deliver(client, webhook, postback_event(str(number), user=MEMBER, token="status"))
        village = villages.get(number)
    assert sender.sent[-1] == ("status", render(messages.status_reply(village, f"line:{MEMBER}")))


async def test_unreadable_postback_data_gets_the_default_reply():
    sender = RecordingSender()
    no_data = {"type": "postback", "replyToken": "token-4", "source": source(OWNER), "postback": {}}
    async with serve(sender) as (client, webhook, _):
        # 前後の空白は除かない（Java の Integer.parseInt と同じ）
        await deliver(
            client,
            webhook,
            postback_event("abc"),
            postback_event(" 3", token="token-2"),
            postback_event("", token="token-3"),
            no_data,
        )
    default = render(messages.default_reply())
    assert sender.sent == [("token-1", default), ("token-2", default), ("token-3", default), ("token-4", default)]


# --- スタンプ ---


async def test_a_sticker_gets_the_maker_information_even_without_a_user_id():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(client, webhook, sticker_event(user=None))
    assert sender.sent == [("token-1", render(sticker_reply(ILLUST, BASE)))]


# --- 署名と本文 ---


@pytest.mark.parametrize(
    "headers_for",
    [
        lambda body: {},
        lambda body: {"X-Line-Signature": ""},
        lambda body: {"X-Line-Signature": "wrong"},
        lambda body: {"X-Line-Signature": sign("other-secret", body)},
    ],
    ids=["missing", "empty", "garbage", "other-secret"],
)
async def test_webhooks_without_the_right_signature_are_refused(headers_for):
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        body = json.dumps({"events": [text_event("お題")]}).encode()
        response = await post(client, body=body, headers=headers_for(body))
        assert response.status == 400
        await webhook.drain()
    assert (sender.sent, villages.added) == ([], 0)


async def test_a_body_changed_after_signing_is_refused():
    async with serve(RecordingSender()) as (client, _, villages):
        body = json.dumps({"events": [text_event("お題")]}).encode()
        response = await post(client, body=body + b" ", headers={"X-Line-Signature": sign(SECRET, body)})
        assert response.status == 400
    assert villages.added == 0


@pytest.mark.parametrize("body", [b"not json", b"\xff", b"[]", b"{}", b'{"events": {}}'])
async def test_signed_but_unreadable_bodies_are_refused(body):
    async with serve(RecordingSender()) as (client, _, _):
        assert (await post(client, body=body)).status == 400


async def test_the_console_verification_without_events_is_accepted():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(client, webhook)
    assert sender.sent == []


@pytest.mark.parametrize(
    "event",
    [
        {"type": "follow", "replyToken": "token-1", "source": source(OWNER)},
        {"type": "unfollow", "source": source(OWNER)},
        {"type": "message", "replyToken": "token-1", "source": source(OWNER), "message": {"type": "image", "id": "1"}},
        {"type": "message", "replyToken": "token-1", "source": source(OWNER), "message": {"type": "text", "id": "1"}},
        {"type": "message", "source": source(OWNER), "message": {"type": "text", "id": "1", "text": "お題"}},
        "not an event",
    ],
    ids=["follow", "unfollow", "image", "text-without-text", "without-reply-token", "not-an-object"],
)
async def test_events_that_need_no_reply_are_accepted_quietly(event):
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, villages):
        await deliver(client, webhook, event)
    # 返信先のないテキストでも村を作らない（作っても番号を伝えられない）
    assert (sender.sent, villages.added) == ([], 0)


# --- 返信 ---


async def test_each_event_in_one_webhook_is_answered_with_its_own_token_in_order():
    sender = RecordingSender()
    async with serve(sender) as (client, webhook, _):
        await deliver(
            client,
            webhook,
            text_event("500", token="t1"),
            sticker_event(token="t2"),
            postback_event("abc", token="t3"),
        )
    assert [token for token, _ in sender.sent] == ["t1", "t2", "t3"]


async def test_the_webhook_answers_before_the_reply_is_sent():
    gate = asyncio.Event()
    sender = RecordingSender(gate=gate)
    async with serve(sender) as (client, webhook, _):
        async with asyncio.timeout(2):
            response = await post(client, text_event("500"))
        assert response.status == 200
        assert sender.sent == []
        gate.set()
        await webhook.drain()
    assert len(sender.sent) == 1


@pytest.mark.parametrize(
    "error",
    [
        httpx2.ReadTimeout("timed out"),
        httpx2.HTTPStatusError(
            "401 Unauthorized",
            request=httpx2.Request("POST", "https://api.line.me/v2/bot/message/reply"),
            response=httpx2.Response(401),
        ),
    ],
    ids=["timeout", "unauthorized"],
)
async def test_a_failed_reply_is_only_logged(caplog, error):
    with caplog.at_level(logging.DEBUG):
        async with serve(RecordingSender(error=error)) as (client, webhook, _):
            response = await post(client, text_event("お題"), text_event("ひみつのおだい", token="token-2"))
            assert response.status == 200
            await webhook.drain()
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all("返信を送れませんでした" in warning for warning in warnings)
    assert OWNER not in caplog.text
    assert "ひみつのおだい" not in caplog.text


async def test_event_contents_are_never_logged(caplog):
    with caplog.at_level(logging.DEBUG):
        async with serve(RecordingSender()) as (client, webhook, _):
            await deliver(
                client,
                webhook,
                text_event("お題"),
                text_event("ひみつのおだい", token="t2"),
                postback_event("2", token="t3"),
            )
    assert OWNER not in caplog.text
    assert "ひみつのおだい" not in caplog.text
    # 種別は残す
    assert "message/text" in caplog.text


async def test_replies_in_flight_are_sent_before_the_app_stops():
    gate = asyncio.Event()
    sender = RecordingSender(gate=gate)
    async with serve(sender) as (client, _, _):
        assert (await post(client, text_event("500"))).status == 200
        asyncio.get_running_loop().call_later(0.05, gate.set)
    # serve を抜けるとアプリが止まる。止まる前に、送りかけの返信を待つ
    assert len(sender.sent) == 1
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_line_webhook.py -q`
Expected: `ModuleNotFoundError: No module named 'insider_bot.line.webhook'` で収集に失敗する

- [ ] **Step 3: 実装する**

新規 `src/insider_bot/line/webhook.py`:

```python
"""LINE の webhook（POST /line/callback）。署名を確かめ、イベントごとに村の中核を 1 回呼んで返信する。

- 本文を bytes のまま読んで署名を確かめてから JSON として読む。署名が合わない・読めない本文は 400。
- 返信は待たない。LINE は webhook に 2 秒以内の応答を求め、返信 API の所要時間はこちらで制御できないので、
  送信はタスクに任せて 200 を先に返す。送信の失敗は WARNING に残すだけで再試行しない
  （replyToken は 1 回限りで短命。利用者はもう一度送れば同じ応答を受け取れる）。
- イベントの本文はログに出さない。LINE のユーザー ID とお題（ゲームの答え）が入っているので、
  記録するのはイベントの種別と処理の結果まで。

イベントの扱いは LineBot（Java）の LineEventHandler と同じ。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

import httpx2
from aiohttp import web

from insider_bot.line.render import render
from insider_bot.line.signature import verify
from insider_bot.line.sticker import sticker_reply
from insider_bot.village import messages, texts
from insider_bot.village.commands import CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.reply import Reply, Text

log = logging.getLogger(__name__)

CALLBACK_PATH = "/line/callback"
SIGNATURE_HEADER = "X-Line-Signature"


class ReplySender(Protocol):
    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> None: ...


def _or_default(replies: list[Reply] | None) -> list[Reply]:
    """対象の村がない（None）は、村の作成を促す既定の応答にする。"""
    return messages.default_reply() if replies is None else replies


def _user_id(event: dict[str, Any]) -> str | None:
    """LINE のユーザー ID を村の識別子（line:<ID>）にする。グループで規約に同意していない人は ID がない。"""
    source = event.get("source")
    user_id = source.get("userId") if isinstance(source, dict) else None
    return f"line:{user_id}" if isinstance(user_id, str) and user_id else None


def _kind(event: dict[str, Any]) -> str:
    """ログに出すイベントの種別。LINE が決める語だけで、利用者の入力は含まない。"""
    message = event.get("message")
    if event.get("type") == "message" and isinstance(message, dict):
        return f"message/{message.get('type')}"
    return str(event.get("type"))


def _events_of(body: bytes) -> list[Any] | None:
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return None
    events = payload.get("events") if isinstance(payload, dict) else None
    return events if isinstance(events, list) else None


def _describe(error: Exception) -> str:
    """失敗の原因。例外の文には URL などが入り得るので、種類と HTTP の状態コードだけにする。"""
    if isinstance(error, httpx2.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    return type(error).__name__


class LineWebhook:
    def __init__(
        self,
        channel_secret: str,
        commands: CommandHandler,
        illust: Illustrations,
        sender: ReplySender,
        homepage_url: str,
    ) -> None:
        self._channel_secret = channel_secret
        self._commands = commands
        self._illust = illust
        self._sender = sender
        self._homepage_url = homepage_url
        # 送信中の返信。参照を持たないとタスクが途中で回収され得る
        self._pending: set[asyncio.Task[None]] = set()

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.read()
        if not verify(self._channel_secret, body, request.headers.get(SIGNATURE_HEADER)):
            log.warning("LINE: 署名の合わない webhook を拒否しました")
            return web.Response(status=400, text="invalid signature")
        events = _events_of(body)
        if events is None:
            log.warning("LINE: 読めない webhook の本文を拒否しました")
            return web.Response(status=400, text="invalid body")
        for event in events:
            self._dispatch(event)
        return web.Response(text="OK")

    def _dispatch(self, event: Any) -> None:
        if not isinstance(event, dict):
            log.debug("LINE: イベントでない要素を読み飛ばしました")
            return
        kind = _kind(event)
        token = event.get("replyToken")
        # 返信先のないイベントでは中核を呼ばない（村を作っても番号を伝えられない）
        replies = self.replies_for(event) if isinstance(token, str) and token else None
        if replies is None:
            log.debug("LINE: %s イベントには返信しません", kind)
            return
        log.debug("LINE: %s イベントに返信します", kind)
        task = asyncio.create_task(self._send(kind, token, render(replies)))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def replies_for(self, event: dict[str, Any]) -> list[Reply] | None:
        """イベントへの返事。返信しないイベントは None。村の中核の同期の操作を高々 1 回だけ呼ぶ。"""
        user_id = _user_id(event)
        if event.get("type") == "message":
            message = event.get("message")
            if not isinstance(message, dict):
                return None
            if message.get("type") == "text" and isinstance(message.get("text"), str):
                if user_id is None:
                    # 識別できない利用者の村を作らないよう、状態を変えずに 1 対 1 のトークを促す
                    return [Text(texts.ERR_UNIDENTIFIED_USER)]
                return _or_default(self._commands.handle(user_id, message["text"]))
            if message.get("type") == "sticker":
                return sticker_reply(self._illust, self._homepage_url)
            return None
        if event.get("type") == "postback":
            postback = event.get("postback")
            data = postback.get("data") if isinstance(postback, dict) else None
            # Java は data を Integer.parseInt に渡し、読めなければ既定の応答にしていた。data がない場合も同じ
            return _or_default(self._commands.postback(user_id, data) if isinstance(data, str) else None)
        return None

    async def _send(self, kind: str, reply_token: str, line_messages: list[dict[str, Any]]) -> None:
        try:
            await self._sender.reply(reply_token, line_messages)
        except Exception as error:
            log.warning("LINE: %s イベントへの返信を送れませんでした（%s）", kind, _describe(error))

    async def drain(self) -> None:
        """送信中の返信を待つ。停止の前に呼び、送りかけの返信を落とさない。"""
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)


def add_line_routes(app: web.Application, webhook: LineWebhook) -> None:
    """LINE の webhook のパスを足す。停止するときは、送りかけの返信を待ってから閉じる。"""
    app.router.add_post(CALLBACK_PATH, webhook.handle)

    async def drain(_app: web.Application) -> None:
        await webhook.drain()

    app.on_shutdown.append(drain)
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_line_webhook.py -q`
Expected: `35 passed`

Run: `uv run pytest -q`
Expected: `528 passed, 4 deselected`

- [ ] **Step 5: コミット**

```bash
git add src/insider_bot/line/webhook.py tests/test_line_webhook.py
git commit -m "feat: LINE の webhook を受け、村の中核の返事を待たずに返信する"
```

---

### Task 4: 設定と起動の配線

**Files:**
- Modify: `src/insider_bot/config.py`、`src/insider_bot/web/__main__.py`
- Test: `tests/test_web_config.py`（追記）、`tests/test_web_main.py`（新規）

**Interfaces:**
- Consumes: Task 2 の `DEFAULT_API_BASE_URL`、`LineReplyClient`。Task 3 の `LineWebhook`、`add_line_routes`、`CALLBACK_PATH`。M2 の `build_village(public_base_url)`、`VillageApp`（`commands`、`service.illust`）、`village_api.VILLAGE`（テスト）
- Produces: `config.LineConfig`（frozen dataclass: `channel_secret: str`、`channel_token: str`、`api_base_url: str = DEFAULT_API_BASE_URL`）、`WebConfig.line: LineConfig | None = None`
- 設定の規則（外部カタログの設定は a9d6521 で廃止済み。役職画像は同梱の 5 枚から選ぶ）: `LINE_CHANNEL_SECRET` と `LINE_CHANNEL_TOKEN` が両方空なら `line is None`。片方だけなら `ConfigError`。LINE を使うときは `PUBLIC_BASE_URL` が `https://` で始まらなければ `ConfigError`。`LINE_API_BASE_URL` は空なら既定、あれば http(s) の URL（クエリとフラグメントなし、末尾の `/` は除く）。どの URL も読めなければ（`https://[x` など）その変数名を含む `ConfigError`
- 起動: `config.line` があるときだけ、`LineReplyClient` と `LineWebhook`（`village.commands`、`village.service.illust`、ホームページは `config.public_base_url`）を作って `add_line_routes` し、停止時にクライアントを閉じる

- [ ] **Step 1: 失敗するテストを書く**

置き換え `tests/test_web_config.py`:

```python
from insider_bot.config import ConfigError, WebConfig, load_web_config
```

↓

```python
from insider_bot.config import ConfigError, LineConfig, WebConfig, load_web_config
```

追記 `tests/test_web_config.py`（末尾）:

```python
LINE_ENV = {
    "TYPESAFE_API_KEY": "ts-key",
    "PUBLIC_BASE_URL": "https://game.example.com",
    "LINE_CHANNEL_SECRET": "secret",
    "LINE_CHANNEL_TOKEN": "token",
}


def test_line_is_off_unless_configured():
    assert load_web_config({"TYPESAFE_API_KEY": "ts-key"}).line is None


def test_line_settings():
    assert load_web_config(LINE_ENV).line == LineConfig("secret", "token", "https://api.line.me")
    stub = load_web_config({**LINE_ENV, "LINE_API_BASE_URL": "http://127.0.0.1:18080/"})
    assert stub.line.api_base_url == "http://127.0.0.1:18080"


@pytest.mark.parametrize("missing", ["LINE_CHANNEL_SECRET", "LINE_CHANNEL_TOKEN"])
def test_line_needs_both_the_secret_and_the_token(missing):
    with pytest.raises(ConfigError, match="LINE_CHANNEL_SECRET と LINE_CHANNEL_TOKEN"):
        load_web_config({name: value for name, value in LINE_ENV.items() if name != missing})


@pytest.mark.parametrize("public", ["", "http://game.example.com"])
def test_line_needs_an_https_public_base_url(public):
    with pytest.raises(ConfigError, match="PUBLIC_BASE_URL"):
        load_web_config({**LINE_ENV, "PUBLIC_BASE_URL": public})


@pytest.mark.parametrize("value", ["127.0.0.1:18080", "ftp://127.0.0.1", "http://127.0.0.1:18080/?x=1"])
def test_line_api_base_url_must_be_an_http_url(value):
    with pytest.raises(ConfigError, match="LINE_API_BASE_URL"):
        load_web_config({**LINE_ENV, "LINE_API_BASE_URL": value})


@pytest.mark.parametrize("name", ["PUBLIC_BASE_URL", "LINE_API_BASE_URL"])
def test_unreadable_urls_are_config_errors_naming_the_variable(name):
    # urlsplit は「https://[x」で ValueError を投げる。起動時にトレースバックではなく設定エラーとして伝える
    with pytest.raises(ConfigError, match=name):
        load_web_config({**LINE_ENV, name: "https://[x"})
```

新規 `tests/test_web_main.py`:

```python
import json

from aiohttp.test_utils import TestClient, TestServer

from insider_bot.config import LineConfig, WebConfig
from insider_bot.line.signature import sign
from insider_bot.web.__main__ import make_app
from insider_bot.web.village_api import VILLAGE

BASE = "https://game.example.com"


def web_config(line=None):
    return WebConfig(
        typesafe_api_key="ts-key",
        correct_threshold=0.8,
        jev_timeout_seconds=10.0,
        host="127.0.0.1",
        port=8080,
        public_base_url=BASE,
        line=line,
    )


def fake_line_client(created):
    """LINE へは送らず、返信を記録するクライアント。作られたものを created に積む。"""

    class FakeLineClient:
        def __init__(self, channel_token, api_base_url):
            self.args = (channel_token, api_base_url)
            self.sent = []
            self.closed = False
            created.append(self)

        async def reply(self, reply_token, line_messages):
            self.sent.append((reply_token, line_messages))

        async def aclose(self):
            self.closed = True

    return FakeLineClient


def text_event(text, token):
    return {
        "type": "message",
        "replyToken": token,
        "source": {"type": "user", "userId": "U1"},
        "message": {"type": "text", "id": "1", "text": text},
    }


async def test_the_line_callback_exists_only_when_line_is_configured():
    async with TestClient(TestServer(await make_app(web_config()))) as client:
        assert (await client.post("/line/callback", data=b"{}")).status == 404


async def test_a_village_made_on_line_can_be_joined_from_the_web(monkeypatch):
    created = []
    monkeypatch.setattr("insider_bot.web.__main__.LineReplyClient", fake_line_client(created))
    app = await make_app(web_config(LineConfig("secret", "token")))
    async with TestClient(TestServer(app)) as client:
        for text, token in (("お題", "t1"), ("すいか", "t2"), ("2", "t3")):
            body = json.dumps({"events": [text_event(text, token)]}, ensure_ascii=False).encode()
            response = await client.post("/line/callback", data=body, headers={"X-Line-Signature": sign("secret", body)})
            assert response.status == 200
        # LINE と Web は同じプロセスの同じ中核を使う
        number = app[VILLAGE].service.latest_owned("line:U1").number
        response = await client.post("/api/village/join", json={"token": "web-token-0123456789", "number": number})
        role = (await response.json())["replies"][0]["text"]
        assert role in ("あなたの役職はインサイダーです。お題は『すいか』です。", "あなたの役職は村人です。")
    (line_client,) = created
    assert line_client.args == ("token", "https://api.line.me")
    assert [token for token, _ in line_client.sent] == ["t1", "t2", "t3"]
    assert line_client.closed
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_web_config.py tests/test_web_main.py -q`
Expected: `ImportError: cannot import name 'LineConfig'` で収集に失敗する

- [ ] **Step 3: 設定に LINE を足す**

置き換え `src/insider_bot/config.py`:

```python
from urllib.parse import urlsplit
```

↓

```python
from urllib.parse import SplitResult, urlsplit

from insider_bot.line.client import DEFAULT_API_BASE_URL
```

置き換え `src/insider_bot/config.py`:

```python
    # 役職画像と特殊村フォームの URL を組み立てる公開 URL（末尾の / なし）。空ならサイト内の絶対パス
    public_base_url: str = ""
```

↓

```python
    # 役職画像と特殊村フォームの URL を組み立てる公開 URL（末尾の / なし）。空ならサイト内の絶対パス
    public_base_url: str = ""
    # LINE Bot の webhook。None なら /line/callback を生やさない
    line: LineConfig | None = None


@dataclass(frozen=True)
class LineConfig:
    channel_secret: str
    channel_token: str
    # 返信 API の送り先。切替前の検証でスタブ（deploy/verify/line_api_stub.py）へ向けるときだけ変える
    api_base_url: str = DEFAULT_API_BASE_URL
```

置き換え `src/insider_bot/config.py`:

```python
def _public_base_url(env: Mapping[str, str]) -> str:
    raw = _get(env, "PUBLIC_BASE_URL")
    if not raw:
        return ""
    parsed = urlsplit(raw)
```

↓

```python
def _split_url(name: str, raw: str) -> SplitResult:
    try:
        return urlsplit(raw)
    except ValueError:
        # 「https://[x」のように URL として読めない値。起動時のトレースバックではなく設定エラーで伝える
        raise ConfigError(f"{name} を URL として読めません（現在: {raw!r}）") from None


def _public_base_url(env: Mapping[str, str]) -> str:
    raw = _get(env, "PUBLIC_BASE_URL")
    if not raw:
        return ""
    parsed = _split_url("PUBLIC_BASE_URL", raw)
```

置き換え `src/insider_bot/config.py`:

```python
def load_web_config(env: Mapping[str, str] | None = None) -> WebConfig:
```

↓

```python
def _line_config(env: Mapping[str, str], public_base_url: str) -> LineConfig | None:
    secret = _get(env, "LINE_CHANNEL_SECRET")
    token = _get(env, "LINE_CHANNEL_TOKEN")
    if not secret and not token:
        return None
    if not secret or not token:
        raise ConfigError(
            "LINE を使うときは LINE_CHANNEL_SECRET と LINE_CHANNEL_TOKEN を両方指定してください（使わないなら両方空にする）"
        )
    # LINE は https で公開された画像しか表示できない。@特殊 の案内先とスタンプ応答のホームページもこの URL から作る
    if not public_base_url.startswith("https://"):
        raise ConfigError("LINE を使うときは PUBLIC_BASE_URL を https:// で始まる公開 URL で指定してください")
    raw = _get(env, "LINE_API_BASE_URL")
    if not raw:
        return LineConfig(secret, token)
    parsed = _split_url("LINE_API_BASE_URL", raw)
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ConfigError(f"LINE_API_BASE_URL は http(s):// で始まる URL で指定してください（現在: {raw!r}）")
    return LineConfig(secret, token, raw.rstrip("/"))


def load_web_config(env: Mapping[str, str] | None = None) -> WebConfig:
```

置き換え `src/insider_bot/config.py`:

```python
    return WebConfig(
        typesafe_api_key=_get(env, "TYPESAFE_API_KEY"),
        correct_threshold=threshold,
        jev_timeout_seconds=timeout,
        host=_get(env, "WEB_HOST") or "127.0.0.1",
        port=port,
        public_base_url=_public_base_url(env),
    )
```

↓

```python
    public_base_url = _public_base_url(env)
    return WebConfig(
        typesafe_api_key=_get(env, "TYPESAFE_API_KEY"),
        correct_threshold=threshold,
        jev_timeout_seconds=timeout,
        host=_get(env, "WEB_HOST") or "127.0.0.1",
        port=port,
        public_base_url=public_base_url,
        line=_line_config(env, public_base_url),
    )
```

注意: `WebConfig` の注釈 `line: LineConfig | None` は、`LineConfig` がその後で定義されるが、このファイルは `from __future__ import annotations` を使っているので問題ない。

- [ ] **Step 4: 起動時に LINE をつなぐ**

置き換え `src/insider_bot/web/__main__.py`:

```python
from insider_bot.judge import JevJudge, create_jev_client
```

↓

```python
from insider_bot.judge import JevJudge, create_jev_client
from insider_bot.line.client import LineReplyClient
from insider_bot.line.webhook import CALLBACK_PATH, LineWebhook, add_line_routes
```

置き換え `src/insider_bot/web/__main__.py`:

```python
from insider_bot.web.village_setup import build_village


async def make_app(config: WebConfig) -> web.Application:
```

↓

```python
from insider_bot.web.village_setup import build_village

log = logging.getLogger(__name__)


async def make_app(config: WebConfig) -> web.Application:
```

置き換え `src/insider_bot/web/__main__.py`:

```python
    app = create_app(RoomHub(registry, service, manager), village=village)
```

↓

```python
    app = create_app(RoomHub(registry, service, manager), village=village)
    if config.line is not None:
        # LINE も Web と同じ中核を使うので、LINE で作った村に Web から入れる
        sender = LineReplyClient(config.line.channel_token, config.line.api_base_url)
        webhook = LineWebhook(
            config.line.channel_secret, village.commands, village.service.illust, sender, config.public_base_url
        )
        add_line_routes(app, webhook)
        log.info("LINE の webhook を %s で受け付けます（返信先 %s）", CALLBACK_PATH, config.line.api_base_url)

        async def close_line(_app: web.Application) -> None:
            await sender.aclose()

        app.on_cleanup.append(close_line)
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest tests/test_web_config.py tests/test_web_main.py -q`
Expected: 追記した 11 件と新規の 2 件を含めて失敗なし（`test_web_config.py` の既存分と合わせた件数が出る）

Run: `uv run pytest -q`
Expected: `541 passed, 4 deselected`

- [ ] **Step 6: コミット**

```bash
git add src/insider_bot/config.py src/insider_bot/web/__main__.py tests/test_web_config.py tests/test_web_main.py
git commit -m "feat: LINE のチャネルを設定したときだけ /line/callback をつなぐ"
```

---

### Task 5: 切替前の検証の道具（返信 API のスタブと署名付きの webhook）

**Files:**
- Create: `deploy/verify/line_api_stub.py`、`deploy/verify/post_callback.py`（LineBot の `deploy/verify/` から移植）
- Test: `tests/test_deploy_verify.py`

**Interfaces:**
- Consumes: Task 2 の `sign`（`post_callback.py` が import する。`uv run` で動かすので `insider_bot` が読める）
- Produces（`line_api_stub.py`）: `REPLY_PATH = "/v2/bot/message/reply"`、`ReplyRecorder`（`BaseHTTPRequestHandler`。返信 API のパスなら本文を整形して標準出力へ出し 200 `{}`、それ以外は 404）、`main(argv)`
- Produces（`post_callback.py`）: `REPLY_TOKEN`、`build_body(kind, user_id, arg) -> dict`（`text` / `postback` / `sticker`、それ以外は `ValueError`）、`post(url, secret, body, bad_signature=False) -> tuple[int, float]`（状態コードとミリ秒）、`main(argv) -> int`（環境変数 `LINE_CHANNEL_SECRET`）
- テストは `from deploy.verify.… import …` で読む（`pyproject.toml` の `pythonpath = ["."]` で、`deploy` と `deploy/verify` は名前空間パッケージとして読める。`__init__.py` は置かない）

- [ ] **Step 1: 失敗するテストを書く**

新規 `tests/test_deploy_verify.py`:

```python
import contextlib
import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from deploy.verify.line_api_stub import ReplyRecorder
from deploy.verify.post_callback import build_body, post


@contextlib.contextmanager
def running_stub():
    server = HTTPServer(("127.0.0.1", 0), ReplyRecorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_a_text_event_carries_the_user_and_the_text():
    event = build_body("text", "U1", "お題")["events"][0]
    assert (event["type"], event["message"]["type"], event["message"]["text"]) == ("message", "text", "お題")
    assert event["source"] == {"type": "user", "userId": "U1"}
    assert event["replyToken"]


def test_a_postback_event_carries_the_data():
    event = build_body("postback", "U1", "1234")["events"][0]
    assert (event["type"], event["postback"]["data"]) == ("postback", "1234")


def test_a_sticker_event_has_sticker_ids():
    event = build_body("sticker", "U1", None)["events"][0]
    assert (event["type"], event["message"]["type"]) == ("message", "sticker")
    assert event["message"]["packageId"] and event["message"]["stickerId"]


def test_unknown_kinds_are_rejected():
    with pytest.raises(ValueError):
        build_body("image", "U1", None)


def test_the_stub_prints_the_reply_and_answers_200(capsys):
    payload = {"replyToken": "t", "messages": [{"type": "text", "text": "こんにちは"}]}
    with running_stub() as base:
        request = urllib.request.Request(
            base + "/v2/bot/message/reply",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer x"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert (response.status, response.read()) == (200, b"{}")
    out = capsys.readouterr().out
    assert "Bearer あり" in out
    assert "こんにちは" in out


def test_the_stub_refuses_other_paths():
    with running_stub() as base:
        request = urllib.request.Request(base + "/v2/bot/message/push", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
    assert error.value.code == 404


def test_post_sends_the_body_and_reports_the_status_and_time():
    with running_stub() as base:
        status, elapsed_ms = post(base + "/v2/bot/message/reply", "secret", b"{}")
    assert status == 200
    assert elapsed_ms >= 0
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_deploy_verify.py -q`
Expected: `ModuleNotFoundError: No module named 'deploy.verify'` で収集に失敗する

- [ ] **Step 3: 道具を移す**

新規 `deploy/verify/line_api_stub.py`:

```python
#!/usr/bin/env python3
"""LINE の返信 API（POST /v2/bot/message/reply）のスタブ。外へは何も送らない。

Web 版を LINE_API_BASE_URL=http://127.0.0.1:18080 で起動すると、LINE への返信がここへ届く。
本文を整形して標準出力へ出し、200 {} を返す。切替前の検証で、返信の中身を読むのに使う。

使い方: uv run python deploy/verify/line_api_stub.py [port]   （既定 18080）
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

REPLY_PATH = "/v2/bot/message/reply"


class ReplyRecorder(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        # トークンそのものは出さず、付いているかだけを見る
        bearer = self.headers.get("Authorization", "").startswith("Bearer ")
        print(f"--- {self.command} {self.path}（Authorization: {'Bearer あり' if bearer else 'なし'}）")
        if self.path != REPLY_PATH:
            print(f"!!! 返信 API ではないパスへの POST です: {self.path}")
            sys.stdout.flush()
            self.send_response(404)
            self.end_headers()
            return
        try:
            print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
        except ValueError:
            print(body.decode("utf-8", errors="replace"))
        sys.stdout.flush()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: object) -> None:
        pass


def main(argv: list[str]) -> None:
    port = int(argv[0]) if argv else 18080
    print(f"listening on 127.0.0.1:{port}", flush=True)
    HTTPServer(("127.0.0.1", port), ReplyRecorder).serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
```

新規 `deploy/verify/post_callback.py`:

```python
#!/usr/bin/env python3
"""署名付きの LINE webhook を組み立てて POST し、応答コードと所要時間を出す。

使い方（環境変数 LINE_CHANNEL_SECRET が必要。送り先の Web 版と同じ値）:
  uv run python deploy/verify/post_callback.py <url> text <userId> <本文>      テキストメッセージ
  uv run python deploy/verify/post_callback.py <url> postback <userId> <data>  ポストバック
  uv run python deploy/verify/post_callback.py <url> sticker <userId>          スタンプ
末尾に --bad-signature を付けると署名を壊して送る（拒否されることの確認用）。

所要時間は接続の開始から応答の完了までで、LINE の 2 秒の制限に対する余裕を見るために出す。
返信の中身は、Web 版の LINE_API_BASE_URL を line_api_stub.py へ向けて、スタブ側で読む。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from insider_bot.line.signature import sign

REPLY_TOKEN = "verify-reply-token"


def build_body(kind: str, user_id: str, arg: str | None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "replyToken": REPLY_TOKEN,
        "timestamp": int(time.time() * 1000),
        "source": {"type": "user", "userId": user_id},
        "mode": "active",
    }
    if kind == "text":
        event["type"] = "message"
        event["message"] = {"type": "text", "id": "1", "text": arg}
    elif kind == "postback":
        event["type"] = "postback"
        event["postback"] = {"data": arg}
    elif kind == "sticker":
        event["type"] = "message"
        event["message"] = {"type": "sticker", "id": "1", "packageId": "1", "stickerId": "1"}
    else:
        raise ValueError(f"知らないイベントの種類です: {kind}")
    return {"destination": "Uverify", "events": [event]}


def post(url: str, secret: str, body: bytes, bad_signature: bool = False) -> tuple[int, float]:
    signature = sign(secret + ("x" if bad_signature else ""), body)
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Line-Signature": signature},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    return status, (time.perf_counter() - started) * 1000


def main(argv: list[str]) -> int:
    bad_signature = "--bad-signature" in argv
    args = [arg for arg in argv if arg != "--bad-signature"]
    if len(args) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    secret = os.environ.get("LINE_CHANNEL_SECRET", "")
    if not secret:
        print("LINE_CHANNEL_SECRET を設定してください（送り先の Web 版と同じ値）", file=sys.stderr)
        return 2
    url, kind, user_id = args[0], args[1], args[2]
    arg = args[3] if len(args) > 3 else None
    body = json.dumps(build_body(kind, user_id, arg), ensure_ascii=False).encode("utf-8")
    status, elapsed_ms = post(url, secret, body, bad_signature)
    print(f"status={status} elapsed_ms={elapsed_ms:.0f}")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_deploy_verify.py -q`
Expected: `7 passed`

Run: `uv run pytest -q`
Expected: `548 passed, 4 deselected`

- [ ] **Step 5: 手元で通しで確かめる（LINE へは送らない）**

8765 番と 18080 番が空いていることを確かめてから（`lsof -nP -iTCP:8765 -iTCP:18080 -sTCP:LISTEN` が何も出さない）、スタブと Web 版を裏で起動する。Web 版の Jev は使わないので `TYPESAFE_API_KEY` は仮の値でよく、`.env` は読まない:

```bash
uv run python deploy/verify/line_api_stub.py 18080 > "$TMPDIR/line-stub.log" 2>&1 &
TYPESAFE_API_KEY=verify LINE_CHANNEL_SECRET=verify-secret LINE_CHANNEL_TOKEN=verify-token PUBLIC_BASE_URL=https://game.example.com LINE_API_BASE_URL=http://127.0.0.1:18080 WEB_PORT=8765 uv run python -m insider_bot.web > "$TMPDIR/line-web.log" 2>&1 &
curl -s --retry 30 --retry-connrefused --retry-delay 1 http://127.0.0.1:8765/healthz
```

Expected: 最後の行が `ok`

```bash
export LINE_CHANNEL_SECRET=verify-secret
uv run python deploy/verify/post_callback.py http://127.0.0.1:8765/line/callback text Uverify お題
uv run python deploy/verify/post_callback.py http://127.0.0.1:8765/line/callback postback Uverify 2
uv run python deploy/verify/post_callback.py http://127.0.0.1:8765/line/callback sticker Uverify
uv run python deploy/verify/post_callback.py http://127.0.0.1:8765/line/callback text Uverify お題 --bad-signature
cat "$TMPDIR/line-stub.log"
grep -c "LINE の webhook を /line/callback で受け付けます" "$TMPDIR/line-web.log"
```

Expected:
- 初めの 3 行は `status=200 elapsed_ms=…`（数十ミリ秒以内）、4 行目は `status=400`
- スタブのログに 3 件の返信が出る（`Authorization: Bearer あり`）: 「NNNN村 を新しく作成しました。…」のボタンテンプレート、「お題は「…」です。確定しますか？」のボタンテンプレート、「ご利用ありがとうございます。…」のボタンテンプレート（`thumbnailImageUrl` が `https://game.example.com/static/roles/INSIDER.png`）
- 最後の行が `1`

確かめたら、起動した 2 つを止める（`uv run` の子のプロセスも残さない）:

```bash
lsof -ti tcp:8765 -sTCP:LISTEN | xargs kill
lsof -ti tcp:18080 -sTCP:LISTEN | xargs kill
lsof -nP -iTCP:8765 -iTCP:18080 -sTCP:LISTEN
```

Expected: 最後のコマンドが何も出さない。報告にはコマンドと出力を書く（ログの返信の本文は要約でよい）。

- [ ] **Step 6: コミット**

```bash
git add deploy/verify/line_api_stub.py deploy/verify/post_callback.py tests/test_deploy_verify.py
git commit -m "feat: 切替前の検証に使う LINE の返信 API のスタブと署名付きの webhook の送信を移す"
```

---

### Task 6: Java の LineBot とのゴールデン比較

**Files:**
- Create: `tests/line_golden.py`（入力の列・正規化・採取と Python での再生。`python -m tests.line_golden` で採取できる）、`tests/test_line_golden.py`、`tests/golden/line_callapi.json`（採取したもの）

**Interfaces:**
- Consumes: Task 1 の `render`。M2 の `build_village(public_base_url)`（`commands.handle`）
- Produces: `FIXTURE`、`NO_VILLAGE_TEXT`、`JAVA_SPECIAL_FORM_URL`、`Step`（frozen dataclass: `user`、`text`、`names`、`group`、`check`）、`STEPS`、`first_number(messages) -> str`、`Normalizer(special_form_urls)` と `messages(list) -> list`、`record(callapi_url) -> dict`、`replay(public_base_url) -> list[list[dict] | None]`、`differences(steps, java_steps, python_outputs, python_form_url) -> list[str]`、`main(argv) -> int`
- 比べ方（spec「テスト」の「Java との突き合わせ」）: Java の `/callapi`（テキストだけの入口。対象の村がないときは `村が作成されていません` の Text を返す）へ `STEPS` を送って JSON を採り、同じ `STEPS` を Python の中核と LINE のレンダラに通した JSON と比べる。村番号・画像の URL・お題候補の語・overflow の席番号・特殊村フォームの URL を伏せ、Java の null の項目を除く。配役の抽選で誰に何が当たるかが変わる手順は `group` ごとに順不同で、席で文が変わる手順は `check=False` で比べない。ポストバック・スタンプ・既定の確認テンプレートは `/callapi` に入口がないので、Task 1 と Task 3 の、Java のコードから起こした期待値で確かめてある

- [ ] **Step 1: 失敗するテストを書く**

新規 `tests/test_line_golden.py`:

```python
import json

from tests.line_golden import (
    FIXTURE,
    JAVA_SPECIAL_FORM_URL,
    NO_VILLAGE_TEXT,
    STEPS,
    Normalizer,
    Step,
    differences,
    first_number,
    replay,
)

BASE = "https://game.example.com"
FORM = f"{BASE}/village/special"


def test_village_numbers_become_placeholders_in_order_of_appearance():
    normalizer = Normalizer([])
    assert normalizer.messages([{"type": "text", "text": "1234村 と 56789"}]) == [{"type": "text", "text": "<N1>村 と <N2>"}]
    assert normalizer.messages([{"type": "text", "text": "56789"}]) == [{"type": "text", "text": "<N2>"}]


def test_nulls_images_forms_seats_and_candidate_words_are_hidden():
    java = {
        "type": "template",
        "altText": "お題は「すいか」です。確定しますか？",
        "quickReply": None,
        "template": {
            "type": "buttons",
            "thumbnailImageUrl": "https://lh3.example/abc",
            "imageAspectRatio": None,
            "imageSize": "contain",
            "text": "お題は「すいか」です。確定しますか？",
            "defaultAction": None,
            "actions": [
                {"type": "message", "label": "確定", "text": "すいか"},
                {"type": "postback", "label": "初心者", "data": "2", "displayText": None},
            ],
        },
    }
    texts = [{"type": "text", "text": JAVA_SPECIAL_FORM_URL}, {"type": "text", "text": "あなたは2番目の参加者です。"}]
    assert Normalizer([JAVA_SPECIAL_FORM_URL]).messages([java, *texts]) == [
        {
            "type": "template",
            "altText": "お題は「<WORD>」です。確定しますか？",
            "template": {
                "type": "buttons",
                "thumbnailImageUrl": "<IMAGE>",
                "imageSize": "contain",
                "text": "お題は「<WORD>」です。確定しますか？",
                "actions": [
                    {"type": "message", "label": "確定", "text": "<WORD>"},
                    {"type": "postback", "label": "初心者", "data": "2"},
                ],
            },
        },
        {"type": "text", "text": "<SPECIAL_FORM_URL>"},
        {"type": "text", "text": "あなたは<SEAT>番目の参加者です。"},
    ]


def test_first_number_reads_the_text_not_the_image_urls():
    messages = [{"type": "template", "altText": "1234村 を新しく作成しました。", "template": {"thumbnailImageUrl": "https://x/98765"}}]
    assert first_number(messages) == "1234"


def test_groups_are_compared_without_order_and_no_village_matches_none():
    steps = [Step("A", "x", group="g"), Step("B", "x", group="g"), Step("X", "500")]
    java = [
        {"user": "A", "text": "x", "messages": [{"type": "text", "text": "村人"}]},
        {"user": "B", "text": "x", "messages": [{"type": "text", "text": "インサイダー"}]},
        {"user": "X", "text": "500", "messages": [{"type": "text", "text": NO_VILLAGE_TEXT}]},
    ]
    python = [[{"type": "text", "text": "インサイダー"}], [{"type": "text", "text": "村人"}], None]
    assert differences(steps, java, python, FORM) == []
    python[2] = [{"type": "text", "text": "x"}]
    assert len(differences(steps, java, python, FORM)) == 1


def test_python_answers_line_exactly_like_the_java_linebot():
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # 手順を変えたら、Java から採り直す（tests/line_golden.py の docstring）
    assert [step["user"] for step in golden["steps"]] == [step.user for step in STEPS]
    assert differences(STEPS, golden["steps"], replay(BASE), FORM) == []
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_line_golden.py -q`
Expected: `ModuleNotFoundError: No module named 'tests.line_golden'` で収集に失敗する

- [ ] **Step 3: 入力の列・正規化・採取を書く**

新規 `tests/line_golden.py`:

```python
"""LINE の返信を Java の LineBot と突き合わせる（ゴールデン比較）。

Java の /callapi へ STEPS を送って LINE の JSON を採り（record）、tests/golden/line_callapi.json に保存する。
tests/test_line_golden.py が、同じ STEPS を Python の中核と LINE のレンダラに通し（replay）、保存した JSON と比べる。

比べる前に、どちらの側でも同じように変わる値を伏せる（Normalizer）:
- 村番号（4〜5 桁）: 初めて現れた順に <N1>、<N2>…
- 画像の URL: Java は外部カタログから、Python は同梱の 5 枚から、どちらも毎回ランダムに選ぶので <IMAGE>
- 特殊村フォームの URL: 移行で Netlify から Web 版の /village/special に変わる（設計どおりの差）
- お題候補の語: 辞書から抽選するので <WORD>
- overflow で出る入室状況の席番号: 配役の抽選で、誰がその役職の席に着くかで変わる
- Java が null のまま送っていた項目: Python は送らない（LINE はどちらも省略として扱う）

配役（誰がインサイダーか）は抽選なので、同じ group の手順の応答は順不同の集まりとして比べる。
GM の「k/n人」のように席で文が変わる応答と、お題も役職も抽選のランダム村の人数設定は、check=False で比べない。

採り方（手順を変えたら採り直す）: Java の LineBot を手元で動かし（README の「LINE Bot」）、
  uv run python -m tests.line_golden http://127.0.0.1:18080/callapi
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from insider_bot.line.render import render
from insider_bot.web.village_setup import build_village

FIXTURE = Path(__file__).parent / "golden" / "line_callapi.json"
# /callapi が「対象の村がない」ときに返す文。LINE の webhook は代わりに既定の確認テンプレートを返す
NO_VILLAGE_TEXT = "村が作成されていません"
JAVA_SPECIAL_FORM_URL = "https://insidergametool.netlify.app/form.html"
IMAGE_KEYS = ("thumbnailImageUrl", "originalContentUrl", "previewImageUrl")

_NUMBER = re.compile(r"(?<![0-9])[0-9]{4,5}(?![0-9])")
_CANDIDATE = re.compile(r"^お題は「(.*)」です。確定しますか？$", re.DOTALL)
_SEAT = re.compile(r"あなたは[0-9]+番目")
_HIDDEN_CANDIDATE = "お題は「<WORD>」です。確定しますか？"


@dataclass(frozen=True)
class Step:
    user: str
    text: str
    # この手順の応答に最初に現れた村番号に名前を付け、以降の text で {名前} と書けるようにする
    names: str | None = None
    # 同じ group の応答は順不同で比べる（誰にどの役職が当たるかは抽選）
    group: str | None = None
    # False なら実行するだけで比べない
    check: bool = True


def _joins(name: str, users: str, group: str | None = None, check: bool = True) -> tuple[Step, ...]:
    return tuple(Step(user, "{" + name + "}", group=group, check=check) for user in users)


def _gm_village(name: str, topic: str, group: str) -> tuple[Step, ...]:
    """神モードの 2 人村。参加の直後は GM の「k/2人」が席で変わるので、揃ってからの再表示を比べる。"""
    return (
        Step("G", "神", names=name),
        Step("G", topic),
        Step("G", "2"),
        *_joins(name, "AB", check=False),
        *_joins(name, "AB", group=group),
    )


STEPS: tuple[Step, ...] = (
    # 通常村: 作成・人数の誤り・お題・人数・参加・満員・配布状況・設定済みの村への再設定・参加者のいる村の切替
    Step("O", "お題", names="V1"),
    Step("O", "1"),
    Step("O", "すいか"),
    Step("O", "3"),
    *_joins("V1", "ABC", group="v1"),
    Step("D", "{V1}"),
    Step("O", "{V1}"),
    Step("O", "めろん"),
    Step("O", "5"),
    Step("O", "@逆村"),
    Step("O", "@わーわーず"),
    # 神モード村（人数が先）
    Step("G", "神", names="V2"),
    Step("G", "4"),
    Step("G", "りんご"),
    *_joins("V2", "ABCD", check=False),
    *_joins("V2", "ABCD", group="v2"),
    Step("G", "{V2}"),
    # 神モード村（お題が先）: お題の応答の人数の例が「GM１人、…」になる
    Step("G", "神", names="V3"),
    Step("G", "ぶどう"),
    Step("G", "2"),
    # 逆村
    Step("O", "お題", names="V4"),
    Step("O", "@逆村"),
    Step("O", "みかん"),
    Step("O", "3"),
    *_joins("V4", "ABC", group="v4"),
    # Werewords（神モードでない村と、神モード村）。配られるメッセージは抽選なので比べない
    Step("O", "お題", names="V5"),
    Step("O", "メロン"),
    Step("O", "3"),
    Step("O", "@わーわーず", names="W1"),
    *_joins("W1", "ABCD", check=False),
    Step("G", "神", names="V6"),
    Step("G", "レモン"),
    Step("G", "3"),
    Step("G", "＠わーわーず"),
    # ランダム村: 人数の応答はお題も役職も抽選なので比べない
    Step("R", "ランダム", names="V7"),
    Step("R", "3", check=False),
    # overflow: インサイダーの役職（画像つきで 60 まで）。「😀」は UTF-16 で 2 と数える（len() なら 1）
    Step("O", "お題", names="V8"),
    Step("O", "あ" * 36),
    Step("O", "2"),
    *_joins("V8", "AB", group="v8"),
    Step("O", "お題", names="V9"),
    Step("O", "😀" * 18 + "あ"),
    Step("O", "2"),
    *_joins("V9", "AB", group="v9"),
    # overflow: GM の役職（画像つき 60 → 画像なし 160 → Text と入室状況）
    *_gm_village("V10", "い" * 29, "v10"),
    *_gm_village("V11", "う" * 30, "v11"),
    *_gm_village("V12", "え" * 130, "v12"),
    # overflow: オーナーの配布状況（160 まではボタン、超えると Text だけ）
    Step("O", "お題", names="V13"),
    Step("O", "か" * 132),
    Step("O", "2"),
    Step("O", "{V13}"),
    Step("O", "お題", names="V14"),
    Step("O", "き" * 133),
    Step("O", "2"),
    Step("O", "{V14}"),
    # コマンドと数値の解釈（村を持たない人）
    Step("X", "@取得"),
    Step("X", "＠取得"),
    Step("X", "@配布"),
    Step("X", "@特殊"),
    Step("X", "500"),
    Step("X", "99999"),
    Step("X", "3"),
    Step("X", "　3　"),
    Step("X", "@逆村"),
    Step("X", "こんにちは"),
)


def first_number(messages: list[dict[str, Any]]) -> str:
    """応答の本文に最初に現れた村番号。画像の URL の数字は見ない。"""
    for message in messages:
        text = message.get("altText") or message.get("text") or ""
        match = _NUMBER.search(text)
        if match is not None:
            return match.group()
    raise ValueError("応答に村番号がありません")


def _drop_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_nulls(item) for item in value]
    return value


def _hide_candidate(message: dict[str, Any]) -> dict[str, Any]:
    """お題候補の語を伏せる。辞書から抽選するので、Java と Python で違う語が出る。"""
    template = message.get("template")
    text = template.get("text") if isinstance(template, dict) else None
    if not isinstance(text, str) or _CANDIDATE.match(text) is None:
        return message
    actions = [
        {**action, "text": "<WORD>"} if action.get("label") == "確定" else action for action in template.get("actions", [])
    ]
    return {**message, "altText": _HIDDEN_CANDIDATE, "template": {**template, "text": _HIDDEN_CANDIDATE, "actions": actions}}


class Normalizer:
    """1 回の実行（Java か Python）の応答を比べられる形にする。村番号の対応は、実行の中で手順をまたいで引き継ぐ。"""

    def __init__(self, special_form_urls: Iterable[str]) -> None:
        self._form_urls = frozenset(special_form_urls)
        self._numbers: dict[str, str] = {}

    def messages(self, messages: list[dict[str, Any]]) -> list[Any]:
        return [self._value(_hide_candidate(_drop_nulls(message)), None) for message in messages]

    def _value(self, value: Any, key: str | None) -> Any:
        if isinstance(value, dict):
            return {name: self._value(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [self._value(item, key) for item in value]
        if not isinstance(value, str):
            return value
        if key in IMAGE_KEYS:
            return "<IMAGE>"
        if value in self._form_urls:
            return "<SPECIAL_FORM_URL>"
        return _NUMBER.sub(self._number, _SEAT.sub("あなたは<SEAT>番目", value))

    def _number(self, match: re.Match[str]) -> str:
        return self._numbers.setdefault(match.group(), f"<N{len(self._numbers) + 1}>")


def record(callapi_url: str) -> dict[str, Any]:
    """Java の /callapi へ STEPS を送り、応答をそのまま集める。

    利用者の ID は実行ごとに変え、同じ Java に採り直したときに前の実行の村と混ざらないようにする（ID は応答に現れない）。
    """
    prefix = uuid.uuid4().hex[:8]
    numbers: dict[str, str] = {}
    steps = []
    for step in STEPS:
        text = step.text.format_map(numbers)
        query = urllib.parse.urlencode({"message": text, "userId": f"golden-{prefix}-{step.user}"})
        with urllib.request.urlopen(f"{callapi_url}?{query}", timeout=10) as response:
            messages = json.loads(response.read())
        steps.append({"user": step.user, "text": text, "messages": messages})
        if step.names:
            numbers[step.names] = first_number(messages)
    return {"callapi": callapi_url, "steps": steps}


def replay(public_base_url: str) -> list[list[dict[str, Any]] | None]:
    """STEPS を Python の中核と LINE のレンダラに通す。対象の村がない手順は None。"""
    village = build_village(public_base_url)
    numbers: dict[str, str] = {}
    outputs: list[list[dict[str, Any]] | None] = []
    for step in STEPS:
        replies = village.commands.handle(f"line:{step.user}", step.text.format_map(numbers))
        rendered = None if replies is None else render(replies)
        outputs.append(rendered)
        if step.names:
            if rendered is None:
                raise AssertionError(f"{step} で村ができませんでした")
            numbers[step.names] = first_number(rendered)
    return outputs


def _key(messages: list[Any]) -> str:
    return json.dumps(messages, ensure_ascii=False, sort_keys=True)


def differences(
    steps: Sequence[Step],
    java_steps: list[dict[str, Any]],
    python_outputs: list[list[dict[str, Any]] | None],
    python_form_url: str,
) -> list[str]:
    """Java と Python の応答の違い。同じなら空。"""
    java_normalizer = Normalizer([JAVA_SPECIAL_FORM_URL])
    python_normalizer = Normalizer([python_form_url])
    problems: list[str] = []
    groups: dict[str, tuple[list[str], list[str]]] = {}
    for index, (step, java, python) in enumerate(zip(steps, java_steps, python_outputs, strict=True), start=1):
        if not step.check:
            continue
        label = f"{index} 番目（{step.user}: {java['text'][:20]!r}）"
        if java["messages"] == [{"type": "text", "text": NO_VILLAGE_TEXT}]:
            if python is not None:
                problems.append(f"{label}: Java は対象の村なし、Python は返事あり")
            continue
        if python is None:
            problems.append(f"{label}: Java は返事あり、Python は対象の村なし")
            continue
        java_messages = java_normalizer.messages(java["messages"])
        python_messages = python_normalizer.messages(python)
        if step.group is not None:
            java_group, python_group = groups.setdefault(step.group, ([], []))
            java_group.append(_key(java_messages))
            python_group.append(_key(python_messages))
        elif java_messages != python_messages:
            problems.append(f"{label}:\n  Java   {java_messages}\n  Python {python_messages}")
    for group, (java_group, python_group) in groups.items():
        if sorted(java_group) != sorted(python_group):
            problems.append(f"group {group}:\n  Java   {sorted(java_group)}\n  Python {sorted(python_group)}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("使い方: uv run python -m tests.line_golden <Java の /callapi の URL>", file=sys.stderr)
        return 2
    golden = record(argv[0])
    FIXTURE.parent.mkdir(exist_ok=True)
    FIXTURE.write_text(json.dumps(golden, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(golden['steps'])} 手順の応答を {FIXTURE} に保存しました")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: 正規化のテストが通ることを確認する**

Run: `uv run pytest tests/test_line_golden.py -q`
Expected: `4 passed, 1 failed`。失敗は `test_python_answers_line_exactly_like_the_java_linebot` の `FileNotFoundError`（まだ採っていない）

- [ ] **Step 5: Java の LineBot から採る（人の手が要る）**

Java の実行環境が要る。本番の LineBot は Java 8 で動いているので Temurin 8 を使う（Java 11 以降でも動く。この入力の列は Java 8 と 11 で解釈が分かれる数字を含まない）。**インストールは人の作業**: 手元に `java` がなければ、コントローラーが人に頼む（`brew install --cask temurin@8`）。Heroku の本番の `/callapi` は使わない（本番に村を十数個作り、上限 50 件の FIFO で遊んでいる人の村を押し出し得る）。

手元のビルド済みの jar（`~/git/LineBot/insider-game-bot/build/libs/insider-game-bot-2.7.0-SNAPSHOT.jar`、commit addb598。その後の LineBot の変更は既定の画像 URL と `/actuator/health` だけで、比べる値に効かない）を、仮の LINE の資格情報で起動する。役職画像のカタログを取りに外へ出るが、画像の URL は伏せて比べるので結果に効かない:

```bash
LINE_BOT_CHANNEL_TOKEN=golden LINE_BOT_CHANNEL_SECRET=golden java -jar ~/git/LineBot/insider-game-bot/build/libs/insider-game-bot-2.7.0-SNAPSHOT.jar --server.port=18080 > "$TMPDIR/linebot.log" 2>&1 &
curl -s --retry 60 --retry-connrefused --retry-delay 1 'http://127.0.0.1:18080/callapi?message=500&userId=probe'
```

Expected: `[{"type":"text","text":"村が作成されていません",…}]`（起動に数十秒かかる）

```bash
uv run python -m tests.line_golden http://127.0.0.1:18080/callapi
lsof -ti tcp:18080 -sTCP:LISTEN | xargs kill
```

Expected: `98 手順の応答を …/tests/golden/line_callapi.json に保存しました`（手順の数は `len(STEPS)`）。Java は止める。

- [ ] **Step 6: 突き合わせが通ることを確認する**

Run: `uv run pytest tests/test_line_golden.py -q`
Expected: `5 passed`

差分が出たら、**Java を正として** Python の中核の文言か LINE のレンダラを直し、該当するタスクのテストも直す（どの差分をどう直したかを報告とコミットメッセージに書く）。設計で決めた差（spec に書かれた URL の変更など）だけが残る場合は、`Normalizer` に足して、理由を `tests/line_golden.py` の docstring に書く。どちらとも言えない差分は直さずに報告する。

Run: `uv run pytest -q`
Expected: `553 passed, 4 deselected`

- [ ] **Step 7: コミット**

```bash
git add tests/line_golden.py tests/test_line_golden.py tests/golden/line_callapi.json
git commit -m "test: LINE の返信を Java の LineBot から採った JSON と突き合わせる"
```

---

### Task 7: ドキュメント

**Files:**
- Modify: `docs/spec.md`、`docs/village.md`、`README.md`、`.env.example`

**Interfaces:**
- Consumes: Task 1〜6 の挙動（記述がコードと一致していること）

- [ ] **Step 1: docs/spec.md に LINE の入口を足す**

置き換え `docs/spec.md`:

```markdown
配役ツール: Web 版の `/village` で、インサイダーゲームの役職とお題を参加者それぞれのスマホに配る。LINE Bot と同じ村の中核を使い、同じ文言で答える（下記「配役ツール（Web）」）。
```

↓

```markdown
配役ツール: Web 版の `/village` で、インサイダーゲームの役職とお題を参加者それぞれのスマホに配る。LINE Bot と同じ村の中核を使い、同じ文言で答える（下記「配役ツール（Web）」）。

LINE Bot: LINE の 1 対 1 のトークで同じ配役を行う。Web 版と同じプロセスの同じ村の中核を使うので、LINE で作った村に Web から入れる（下記「LINE の入口」）。
```

置き換え `docs/spec.md`:

```markdown
| `join` | `number` | 10000 以上は特殊村、それ以外は通常村に入る（オーナーには配布状況） |
```

↓

```markdown
| `join` | `number` | 10000 以上は特殊村、それ以外は通常村に入る（オーナーには配布状況。ランダム村のオーナーは参加者なので役職） |
```

追記 `docs/spec.md`（末尾。空行を 1 行挟む）:

```markdown
## LINE の入口

LINE Bot の webhook を Web 版のプロセスで受ける。村の中核は配役ツール（Web）と同じものを使うので、LINE で作った村に Web から入れ、Web で作った特殊村に LINE から入れる。`LINE_CHANNEL_SECRET` と `LINE_CHANNEL_TOKEN` を設定したときだけ `/line/callback` を受け付ける。外部仕様は [村の外部仕様](village.md)。

### webhook

- `POST /line/callback` は本文を bytes のまま読み、`X-Line-Signature` を本文の HMAC-SHA256（チャネルシークレット、Base64）と定数時間で比べてから JSON として読む。署名が合わない・本文が読めないときは 400。
- イベントごとに村の中核を 1 回呼ぶ。利用者は `line:<LINE ユーザー ID>` で識別する。

| イベント | 動作 |
| --- | --- |
| テキスト | ユーザー ID がなければ、状態を変えずに 1 対 1 のトークを促す。あればテキストの解釈 |
| ポストバック | ポストバックの解釈（0〜9 のお題候補はユーザー ID がなくても答える） |
| スタンプ | 製作者の連絡先（ご意見フォームとホームページ） |
| それ以外・返信先のないイベント | 返信しない |

- 対象の村がないときは、村の作成を促す確認テンプレートを返す。
- 返信は待たない。webhook は 200 を先に返し、返信 API（`POST /v2/bot/message/reply`、タイムアウト 10 秒）への送信は別のタスクで行う。送信の失敗は WARNING に残すだけで再試行しない。停止するときは送りかけの返信を待つ。
- イベントの本文・LINE ユーザー ID・入力の文はログに出さない。記録するのはイベントの種別と処理の結果まで。

### LINE のメッセージ

返事モデルを LineBot（Java）と同じ JSON に描く。

- ボタンは、画像とタイトルの有無でボタンテンプレートのサムネイルと見出しを付け外しする。`imageSize` は常に `contain`。値のない項目は送らない。代替文は返事の `alt_text`、なければ本文。
- 本文がボタンテンプレートに収まらない（画像かタイトルがあれば 60、なければ 160。UTF-16 の符号単位で数える）ときは `overflow` を描く。
- 画像は元画像とプレビューに同じ URL を使う。LINE は https で公開された画像しか表示できないので、LINE を使うときは `PUBLIC_BASE_URL` に https の公開 URL が要る。
- `@特殊` の案内先は `PUBLIC_BASE_URL` の `/village/special`、スタンプ応答のホームページは `PUBLIC_BASE_URL`。

### 検証

- **Java との突き合わせ**: `tests/test_line_golden.py` が、Java の LineBot の `/callapi` から採った JSON（`tests/golden/line_callapi.json`）と、同じ入力を Python に通した JSON を比べる。村番号・画像の URL・お題候補の語・overflow の席番号・特殊村フォームの URL を伏せ、配役で変わる応答は順不同で比べる。ポストバックとスタンプは `/callapi` に入口がないので、Java の webhook のコードから起こした期待値でテストする。
- **切替前の検証の道具**: `deploy/verify/line_api_stub.py` は返信 API のスタブで、届いた返信を表示する（`LINE_API_BASE_URL` をここへ向ける）。`deploy/verify/post_callback.py` は署名付きの webhook を送り、応答コードと所要時間を出す。
```

- [ ] **Step 2: docs/village.md の実装の対応に LINE を足す**

置き換え `docs/village.md`:

```markdown
| 返事モデル | `village/reply.py` |
```

↓

```markdown
| 返事モデル | `village/reply.py` |
| LINE の入口（webhook・署名・返信 API） | `line/webhook.py`、`line/signature.py`、`line/client.py` |
| LINE のメッセージの形 | `line/render.py` |
| スタンプ応答 | `line/sticker.py` |
```

- [ ] **Step 3: README と .env.example に LINE を足す**

置き換え `README.md`:

```markdown
| `PUBLIC_BASE_URL` | | — | Web 版の公開 URL（例 `https://game.example.com`）。配役ツールの役職画像と特殊村フォームの URL に使う。未設定ならサイト内のパス |
```

↓

```markdown
| `PUBLIC_BASE_URL` | | — | Web 版の公開 URL（例 `https://game.example.com`）。配役ツールの役職画像と特殊村フォームの URL に使う。未設定ならサイト内のパス |
| `LINE_CHANNEL_SECRET` | | — | LINE Bot のチャネルシークレット。`LINE_CHANNEL_TOKEN` と両方設定すると `/line/callback` で webhook を受ける（`PUBLIC_BASE_URL` に https の公開 URL が要る） |
| `LINE_CHANNEL_TOKEN` | | — | LINE Bot のチャネルアクセストークン（長期） |
| `LINE_API_BASE_URL` | | `https://api.line.me` | LINE の返信 API の送り先。切替前の検証でスタブへ向けるときだけ変える |
```

置き換え `README.md`:

````markdown
役職画像は神・GM・村人・インサイダー各5枚を同梱し、表示するたびに同じ役職の5枚から等確率で選びます。画像URLにはバージョンを付け、画像を更新した際に旧画像のキャッシュが使われないようにします。
````

↓

````markdown
役職画像は神・GM・村人・インサイダー各5枚を同梱し、表示するたびに同じ役職の5枚から等確率で選びます。画像URLにはバージョンを付け、画像を更新した際に旧画像のキャッシュが使われないようにします。

### LINE Bot

Web 版のプロセスが LINE Bot の webhook も受けます。`LINE_CHANNEL_SECRET`・`LINE_CHANNEL_TOKEN` と、https の `PUBLIC_BASE_URL` を設定すると `/line/callback` が有効になります。LINE で作った村に Web から入れます（逆も同じ）。

1. LINE Developers のチャネルで、Webhook URL を `https://<公開 URL>/line/callback` にし、Webhook の利用をオンにする（応答メッセージはオフ）
2. コンソールの「検証」で成功を確かめる

LINE へ送らずに確かめるときは、返信 API のスタブを起動し、Web 版を `LINE_API_BASE_URL=http://127.0.0.1:18080` を足して起動してから、署名付きの webhook を送ります。返信の中身はスタブの端末に出ます。

```bash
uv run python deploy/verify/line_api_stub.py 18080
```

```bash
LINE_CHANNEL_SECRET=<Web 版と同じ値> uv run python deploy/verify/post_callback.py http://127.0.0.1:8080/line/callback text U0000 お題
```

LINE の返信が Java の LineBot と同じかは `tests/test_line_golden.py` が確かめます。`tests/line_golden.py` の手順を変えたら、Java の LineBot を手元で動かして（`<LineBot>` は LineBot のリポジトリ）採り直します。

```bash
LINE_BOT_CHANNEL_TOKEN=golden LINE_BOT_CHANNEL_SECRET=golden java -jar <LineBot>/insider-game-bot/build/libs/insider-game-bot-2.7.0-SNAPSHOT.jar --server.port=18080
```

```bash
uv run python -m tests.line_golden http://127.0.0.1:18080/callapi
```
````

追記 `.env.example`（末尾。空行を挟まずに続ける）:

```
# 任意（LINE Bot）: チャネルシークレットとチャネルアクセストークン。両方設定すると /line/callback で webhook を受ける（PUBLIC_BASE_URL に https の公開 URL が要る）
LINE_CHANNEL_SECRET=
LINE_CHANNEL_TOKEN=
# 任意（LINE Bot）: 返信 API の送り先。切替前の検証で deploy/verify/line_api_stub.py へ向けるときだけ設定する
LINE_API_BASE_URL=
```

- [ ] **Step 4: 記述とコードの一致を確かめる**

Run: `grep -n "line/callback\|LINE_CHANNEL\|LINE_API_BASE_URL\|line_golden\|deploy/verify" docs/spec.md docs/village.md README.md .env.example`
Expected: パスが `src/insider_bot/line/webhook.py` の `CALLBACK_PATH` に、環境変数名が `src/insider_bot/config.py` に、ファイル名が実在のファイルに一致する

Run: `uv run pytest -q && node --test tests/js/*.test.mjs`
Expected: どちらも失敗なし

- [ ] **Step 5: コミット**

```bash
git add docs/spec.md docs/village.md README.md .env.example
git commit -m "docs: LINE の入口（webhook・メッセージの形・検証）を設計書と README に足す"
```

---

## 完了の確認

- `uv run pytest -q`（553 passed 前後）と `node --test tests/js/*.test.mjs` がすべて PASS
- `tests/golden/line_callapi.json` が Java の LineBot から採ったもので、`test_python_answers_line_exactly_like_the_java_linebot` が通る
- Task 5 の Step 5 の手元での通し確認（スタブに 3 件の返信、署名を壊すと 400）をした
- `docs/spec.md` の「LINE の入口」が `line/` のコードと食い違っていない
- `git log --oneline` に Task ごとのコミットが並んでいる
- 本番への切替（Webhook URL の付け替え）はまだしない（M5 の仕事）。OCI への配備・Caddy・systemd は M4
