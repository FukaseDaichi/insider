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
