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
