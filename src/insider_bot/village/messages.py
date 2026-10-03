"""返事の組み立て。状態から返事モデルへの純粋関数で、文言は Java の LineBot と一字一句同じ。

LINE のボタンテンプレートの文字数制限（画像つき 60、画像なし 160）で Java が Text に落としていた分岐は、
Buttons.overflow として表す。収まるかどうかの判断は LINE の入口が行い、Web は常に本体を描く。
"""

from __future__ import annotations

from insider_bot.village import texts
from insider_bot.village.illust import Illustrations
from insider_bot.village.model import Role, SpecialVillage, Village
from insider_bot.village.reply import Buttons, Confirm, Image, MessageAction, PostbackAction, Reply, Text
from insider_bot.village.words import ADVANCED_RANK, BEGINNER_RANK, EXPERT_RANK


def _shown(topic: str | None) -> str:
    """Java の文字列連結と同じく、未設定のお題は「null」と書く。"""
    return "null" if topic is None else topic


def _status_text(village: Village | SpecialVillage, user_id: str) -> str:
    return f"あなたは{village.seat_number_of(user_id)}番目の参加者です。\n　入室状況：{village.member_count()}/{village.capacity() if isinstance(village, SpecialVillage) else village.size}人"


def status_reply(village: Village | SpecialVillage, user_id: str) -> list[Reply]:
    return [Text(_status_text(village, user_id))]


def role_reply(village: Village, user_id: str, illust: Illustrations) -> list[Reply]:
    role = village.role_of(user_id)
    if role is None:
        return [Text(texts.DEFAULT_MESSAGE)]
    status = Text(_status_text(village, user_id))
    check = (PostbackAction("入室状況確認", str(village.number)),)
    if role is Role.INSIDER:
        text = f"あなたの役職は{texts.INSIDER_ROLE}です。お題は『{_shown(village.topic)}』です。"
        return [Buttons(text, check, image=illust.url_for("INSIDER"), overflow=(Text(text), status))]
    if role is Role.VILLAGER:
        text = f"あなたの役職は{texts.VILLAGER_ROLE}です。"
        return [Buttons(text, check, image=illust.url_for("VILLAGERS"))]
    text = (
        f"役職は{texts.GAME_MASTER_ROLE}です。\n"
        f"{village.member_count()}/{village.size}人にお題を配りました。お題は『{_shown(village.topic)}』です。"
    )
    # 画像つき（60 文字）→ 画像なし（160 文字）→ Text＋入室状況 の 3 段
    return [Buttons(text, check, image=illust.url_for("GM"), overflow=(Buttons(text, check, overflow=(Text(text), status)),))]


def owner_reply(village: Village) -> list[Reply]:
    text = f"{village.number}村：{village.member_count()}/{village.size}人にお題を配りました。お題は『{_shown(village.topic)}』です。"
    return [Buttons(text, (MessageAction("再確認", str(village.number)),), overflow=(Text(text),))]


def special_role_reply(village: SpecialVillage, user_id: str) -> list[Reply] | None:
    text = village.message_for(user_id)
    if text is None:
        return None
    status = Text(_status_text(village, user_id))
    return [Buttons(text, (PostbackAction("入室状況確認", str(village.number)),), overflow=(Text(text), status))]


def default_reply() -> list[Reply]:
    """対象の村がないときの、村の作成を促す応答。"""
    return [
        Confirm(
            texts.DEFAULT_CONFIRM_TEXT,
            (MessageAction("GM", "お題"), MessageAction("神", "神")),
            alt_text=texts.DEFAULT_MESSAGE,
        )
    ]


def created_reply(number: int) -> list[Reply]:
    text = f"{number}村 を新しく作成しました。{texts.OWNER_ODAI_MESSAGE}"
    return [Buttons(text + "\nお題の自動取得もできます。", (PostbackAction("お題の自動取得", "0"),), alt_text=text)]


def random_created_reply(number: int) -> list[Reply]:
    return [Text(f"{number}村 を新しく作成しました。{texts.RANDOM_NUMSET_MESSAGE}")]


def size_set_reply(village: Village, god_mode: bool, illust: Illustrations) -> list[Reply]:
    number = str(village.number)
    text = f"人数を『{village.size}人』に設定しました。\n皆さんに村番号を伝えてください。"
    return [
        Buttons(
            text,
            (MessageAction("確認", number),),
            image=illust.url_for("GOD" if god_mode else "GM"),
            title=f"{number}村",
            alt_text=text + "配布状況の確認は村番号を入力してください。",
        )
    ]


def random_size_set_reply(village: Village, size: int, illust: Illustrations) -> list[Reply]:
    """ランダム村はオーナーも参加者なので、案内と一緒に自分の役職を返す。"""
    return [Text(f"{village.number}村：人数を『{size}人』に設定しました。\n皆さんに村番号を伝えてください。")] + role_reply(
        village, village.owner_id, illust
    )


def topic_set_reply(village: Village) -> list[Reply]:
    hint = texts.GOD_NUMSET_MESSAGE if village.is_god_mode_awaiting_size() else texts.OWNER_NUMSET_MESSAGE
    return [Text(f"{village.number}村 のお題を『{village.topic}』に設定しました。\n{hint}")]


def reverse_set_reply(village: Village) -> list[Reply]:
    return [Text(f"{village.number}村 を『逆村』に設定しました。\nお題を知らない村人が1人となります。")]


def werewords_created_reply(topic: str, number: int, god_mode: bool) -> list[Reply]:
    text = f"お題を『{topic}』として新たにワーワーズの『{number}』村を作成しました。"
    if god_mode:
        return [Text(text + f"参加者へ『{number}』を伝えてください。")]
    return [
        Text(
            text + f"参加者へ『{number}』を伝え、あなたも入室してください。\n"
            "\n■注意\nあなたはGMです。入室時に表示された役職が欠けた役職となります。"
        )
    ]


def candidate_reply(topic: str | None) -> list[Reply]:
    """お題候補と引き直しのボタン。辞書が壊れていると Java の文字列連結と同じく「null」が出る。

    Java は確定ボタンの text にも null をそのまま渡していた。返事モデルの型を str に保つため、ここでは表示と
    同じ「null」を入れる。同梱の辞書は tests/test_village_words.py で読めることを確かめているので、通常は通らない。
    """
    shown = _shown(topic)
    text = f"お題は「{shown}」です。確定しますか？"
    return [
        Buttons(
            text,
            (
                MessageAction("確定", shown),
                PostbackAction("初心者", str(BEGINNER_RANK)),
                PostbackAction("上級者", str(ADVANCED_RANK)),
                PostbackAction("変態", str(EXPERT_RANK)),
            ),
            alt_text=text,
        )
    ]


def invitation_reply(illust: Illustrations) -> list[Reply]:
    return [Image(illust.invitation_image_url), Text(texts.OFFICIAL_ACCOUNT_URL), Text(texts.OFFICIAL_ACCOUNT_ID_MESSAGE)]


def special_form_reply(url: str) -> list[Reply]:
    return [Text(url)]


def size_error_reply() -> list[Reply]:
    return [Text(texts.ERR_NUMSET_MESSAGE)]


def full_reply() -> list[Reply]:
    return [Text(texts.VILLAGE_FULL)]


def random_numset_reply() -> list[Reply]:
    return [Text(texts.RANDOM_NUMSET_MESSAGE)]
