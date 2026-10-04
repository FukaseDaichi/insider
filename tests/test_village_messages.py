from insider_bot.village import messages, texts
from insider_bot.village.illust import Illustrations
from insider_bot.village.model import SpecialVillage, Village
from insider_bot.village.reply import Buttons, Confirm, Image, MessageAction, PostbackAction, Text
from tests.fakes import FirstRandom, FixedRandom

BASE = "https://game.example.com"
ILLUST = Illustrations(BASE, FirstRandom())


def village_with(size: int, insider_at: int, topic: str = "すいか", number: int = 1234, god_at: int | None = None) -> Village:
    village = Village("owner")
    village.number = number
    village.set_topic(topic)
    if god_at is not None:
        village.mark_god_mode()
        assert village.configure(size, FixedRandom(insider_at - 1, god_at - 1))
    else:
        assert village.configure(size, FixedRandom(insider_at - 1))
    return village


# --- 役職 ---


def test_insider_reply_has_image_button_and_text_overflow():
    village = village_with(2, insider_at=1)
    village.join("user")
    reply = messages.role_reply(village, "user", ILLUST)
    text = "あなたの役職はインサイダーです。お題は『すいか』です。"
    assert reply == [
        Buttons(
            text,
            (PostbackAction("入室状況確認", "1234"),),
            image=f"{BASE}/static/roles/INSIDER.png?v=20261004",
            overflow=(Text(text), Text("あなたは1番目の参加者です。\n　入室状況：1/2人")),
        )
    ]


def test_villager_reply_has_image_button_without_overflow():
    village = village_with(2, insider_at=2)
    village.join("user")
    reply = messages.role_reply(village, "user", ILLUST)
    assert reply == [
        Buttons("あなたの役職は村人です。", (PostbackAction("入室状況確認", "1234"),), image=f"{BASE}/static/roles/VILLAGERS.png?v=20261004")
    ]


def test_game_master_reply_has_three_tiers():
    village = village_with(3, insider_at=1, god_at=2)
    village.join("a")
    village.join("gm")
    text = "役職はＧＭです。\n2/3人にお題を配りました。お題は『すいか』です。"
    status = Text("あなたは2番目の参加者です。\n　入室状況：2/3人")
    assert messages.role_reply(village, "gm", ILLUST) == [
        Buttons(
            text,
            (PostbackAction("入室状況確認", "1234"),),
            image=f"{BASE}/static/roles/GM.png?v=20261004",
            overflow=(Buttons(text, (PostbackAction("入室状況確認", "1234"),), overflow=(Text(text), status)),),
        )
    ]


def test_role_reply_for_a_stranger_is_the_default_text():
    village = village_with(2, insider_at=1)
    assert messages.role_reply(village, "nobody", ILLUST) == [Text(texts.DEFAULT_MESSAGE)]


def test_unset_topic_is_shown_as_null_like_java():
    # お題を決めずに人数を設定した村。Java の文字列連結と同じく『null』と出る（Python の f 文字列なら『None』）
    village = Village("owner")
    village.number = 1234
    assert village.configure(2, FixedRandom(0))
    village.join("user")
    assert messages.role_reply(village, "user", ILLUST)[0].text == "あなたの役職はインサイダーです。お題は『null』です。"
    assert messages.owner_reply(village)[0].text == "1234村：1/2人にお題を配りました。お題は『null』です。"
    god = Village("owner")
    god.number = 1234
    god.mark_god_mode()
    assert god.configure(2, FixedRandom(0, 1))
    god.join("a")
    god.join("gm")
    assert messages.role_reply(god, "gm", ILLUST)[0].text == "役職はＧＭです。\n2/2人にお題を配りました。お題は『null』です。"


def test_topic_with_comma_and_newline_is_kept_verbatim():
    village = village_with(1, insider_at=1, topic="りんご,みかん\nぶどう")
    village.join("user")
    assert messages.role_reply(village, "user", ILLUST)[0].text == "あなたの役職はインサイダーです。お題は『りんご,みかん\nぶどう』です。"


# --- 配布状況 ---


def test_status_reply_counts_from_one_and_zero_for_strangers():
    village = village_with(3, insider_at=1)
    village.join("a")
    village.join("b")
    assert messages.status_reply(village, "b") == [Text("あなたは2番目の参加者です。\n　入室状況：2/3人")]
    assert messages.status_reply(village, "nobody") == [Text("あなたは0番目の参加者です。\n　入室状況：2/3人")]


def test_owner_reply_is_a_button_with_text_overflow():
    village = village_with(2, insider_at=1)
    village.join("a")
    text = "1234村：1/2人にお題を配りました。お題は『すいか』です。"
    assert messages.owner_reply(village) == [Buttons(text, (MessageAction("再確認", "1234"),), overflow=(Text(text),))]


# --- 特殊村 ---


def test_special_role_reply_is_a_button_with_text_and_status_overflow():
    village = SpecialVillage(["あなたの役職は村人です", "x"])
    village.number = 12345
    village.join("user")
    assert messages.special_role_reply(village, "user") == [
        Buttons(
            "あなたの役職は村人です",
            (PostbackAction("入室状況確認", "12345"),),
            overflow=(Text("あなたの役職は村人です"), Text("あなたは1番目の参加者です。\n　入室状況：1/2人")),
        )
    ]


def test_special_role_reply_for_blank_message_and_stranger():
    village = SpecialVillage([None])
    village.number = 12345
    assert messages.special_role_reply(village, "nobody") is None
    village.join("user")
    assert messages.special_role_reply(village, "user")[0].text == "メッセージは特にありません。"


def test_special_status_reply():
    village = SpecialVillage(["a", "b", "c"])
    village.join("x")
    assert messages.status_reply(village, "x") == [Text("あなたは1番目の参加者です。\n　入室状況：1/3人")]


# --- 案内 ---


def test_default_reply_is_a_confirm_with_two_choices():
    assert messages.default_reply() == [
        Confirm("村の作成をしますか？", (MessageAction("GM", "お題"), MessageAction("神", "神")), alt_text=texts.DEFAULT_MESSAGE)
    ]


def test_created_reply():
    text = "1234村 を新しく作成しました。お題を入力してください。"
    assert messages.created_reply(1234) == [
        Buttons(text + "\nお題の自動取得もできます。", (PostbackAction("お題の自動取得", "0"),), alt_text=text)
    ]


def test_random_created_reply():
    assert messages.random_created_reply(1234) == [Text("1234村 を新しく作成しました。人数を設定してください。役職もお題もランダムに配ります。")]


def test_size_set_reply_uses_god_or_gm_image():
    village = village_with(3, insider_at=1)
    text = "人数を『3人』に設定しました。\n皆さんに村番号を伝えてください。"
    assert messages.size_set_reply(village, god_mode=False, illust=ILLUST) == [
        Buttons(
            text,
            (MessageAction("確認", "1234"),),
            image=f"{BASE}/static/roles/GM.png?v=20261004",
            title="1234村",
            alt_text=text + "配布状況の確認は村番号を入力してください。",
        )
    ]
    assert messages.size_set_reply(village, god_mode=True, illust=ILLUST)[0].image == f"{BASE}/static/roles/GOD.png?v=20261004"


def test_random_size_set_reply_includes_the_owners_role():
    village = Village("owner")
    village.number = 1234
    village.set_topic("すいか")
    village.mark_god_mode()
    village.random_mode = True
    # インサイダーは3番目、GM は1番目 → オーナーは GM
    village.configure(4, FixedRandom(2, 0))
    reply = messages.random_size_set_reply(village, 4, ILLUST)
    assert reply[0] == Text("1234村：人数を『4人』に設定しました。\n皆さんに村番号を伝えてください。")
    assert reply[1:] == messages.role_reply(village, "owner", ILLUST)


def test_topic_set_reply_depends_on_god_mode():
    village = Village("owner")
    village.number = 1234
    village.set_topic("すいか")
    assert messages.topic_set_reply(village) == [Text("1234村 のお題を『すいか』に設定しました。\n" + texts.OWNER_NUMSET_MESSAGE)]
    village.mark_god_mode()
    assert messages.topic_set_reply(village) == [Text("1234村 のお題を『すいか』に設定しました。\n" + texts.GOD_NUMSET_MESSAGE)]


def test_reverse_set_reply():
    village = village_with(3, insider_at=1)
    assert messages.reverse_set_reply(village) == [Text("1234村 を『逆村』に設定しました。\nお題を知らない村人が1人となります。")]


def test_werewords_created_reply():
    assert messages.werewords_created_reply("すいか", 12345, god_mode=True) == [
        Text("お題を『すいか』として新たにワーワーズの『12345』村を作成しました。参加者へ『12345』を伝えてください。")
    ]
    assert messages.werewords_created_reply("すいか", 12345, god_mode=False) == [
        Text(
            "お題を『すいか』として新たにワーワーズの『12345』村を作成しました。参加者へ『12345』を伝え、あなたも入室してください。\n"
            "\n■注意\nあなたはGMです。入室時に表示された役職が欠けた役職となります。"
        )
    ]


def test_candidate_reply_offers_confirm_and_three_difficulties():
    text = "お題は「すいか」です。確定しますか？"
    assert messages.candidate_reply("すいか") == [
        Buttons(
            text,
            (
                MessageAction("確定", "すいか"),
                PostbackAction("初心者", "2"),
                PostbackAction("上級者", "3"),
                PostbackAction("変態", "4"),
            ),
            alt_text=text,
        )
    ]


def test_candidate_reply_with_a_broken_dictionary_shows_null_like_java():
    assert messages.candidate_reply(None)[0].text == "お題は「null」です。確定しますか？"
    assert messages.candidate_reply(None)[0].actions[0] == MessageAction("確定", "null")


def test_invitation_reply():
    url = f"{BASE}/static/roles/966mpnqz.png"
    assert messages.invitation_reply(ILLUST) == [Image(url), Text("https://line.me/R/ti/p/%40966mpnqz"), Text("お友達ID\n@966mpnqz")]


def test_simple_text_replies():
    assert messages.special_form_reply("https://x/village/special") == [Text("https://x/village/special")]
    assert messages.size_error_reply() == [Text(texts.ERR_NUMSET_MESSAGE)]
    assert messages.full_reply() == [Text("村がいっぱいです。")]
    assert messages.random_numset_reply() == [Text(texts.RANDOM_NUMSET_MESSAGE)]


def test_guide_reply_is_the_default_message_text():
    assert messages.guide_reply() == [
        Text("お題を配りたい方は「お題」または「神」を、\nお題及び役職を確認したい場合は村番号（数字4桁）を入力してください。")
    ]
