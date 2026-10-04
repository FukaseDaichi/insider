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
