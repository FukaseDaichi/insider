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
