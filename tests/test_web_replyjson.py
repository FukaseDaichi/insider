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
