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
# 参加者への「入室状況：k/n人」の k は入った順。配役は抽選なので、Java と Python でインサイダーが
# 何番目に入ったかが変わり、k も変わる。席番号と同じ理由で伏せる（GM への入室状況は check=False で比べない）
_SEAT_COUNT = re.compile(r"入室状況：[0-9]+/")
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
        if _SEAT.search(value):
            value = _SEAT_COUNT.sub("入室状況：<SEAT>/", _SEAT.sub("あなたは<SEAT>番目", value))
        return _NUMBER.sub(self._number, value)

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
