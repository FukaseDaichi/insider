import random

from insider_bot.village import messages
from insider_bot.village.commands import MAX_SIZE_INPUT, CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.reply import Image, MessageAction, PostbackAction, Text
from insider_bot.village.service import VillageService
from insider_bot.village.words import UNSPECIFIED_RANK, parse_dictionary
from tests.fakes import FirstRandom, FixedRandom

OWNER = "line:owner"
MEMBER = "line:member"
FORM_URL = "https://game.example.com/village/special"
DICTIONARY = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])


def make(*draws: int):
    villages = VillageRegistry(random.Random(1))
    specials = SpecialVillageRegistry(random.Random(2))
    rng = FixedRandom(*draws) if draws else random.Random(3)
    service = VillageService(villages, specials, DICTIONARY, Illustrations("https://game.example.com", FirstRandom()), rng)
    return CommandHandler(service, FORM_URL), service, villages, specials


def latest(villages, owner=OWNER):
    return villages.find_latest_owned(owner, lambda v: True)


# --- 村の作成 ---


def test_village_creation_commands():
    handler, _, villages, _ = make()
    assert handler.handle(OWNER, "お題") == messages.created_reply(latest(villages).number)
    assert handler.handle(OWNER, "題") == messages.created_reply(latest(villages).number)
    assert handler.handle("line:god", "神") == messages.created_reply(latest(villages, "line:god").number)
    assert latest(villages, "line:god").is_god_mode_awaiting_size()
    assert handler.handle("line:rnd", "ランダム") == messages.random_created_reply(latest(villages, "line:rnd").number)


# --- 数値の解釈 ---


def test_numbers_up_to_100_are_sizes_and_101_onwards_are_village_numbers():
    handler, _, villages, _ = make(0, 0)
    assert MAX_SIZE_INPUT == 100
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, "1") == messages.size_error_reply()
    assert handler.handle(OWNER, "0") == messages.size_error_reply()
    assert handler.handle(OWNER, "-5") == messages.size_error_reply()
    assert handler.handle(OWNER, "100")[0].text.startswith("人数を『100人』に設定しました。")
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, "101") is None  # 該当なしの村番号
    assert handler.handle(OWNER, "999") is None
    assert latest(villages).size == 0


def test_surrounding_whitespace_is_ignored_for_numbers():
    handler, _, villages, _ = make(0)
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, " 3 ")[0].text.startswith("人数を『3人』に設定しました。")


def test_fullwidth_digits_are_numbers_like_java():
    # Java の Integer.parseInt は全角数字を読む
    handler, _, villages, _ = make(0)
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, "３")[0].text.startswith("人数を『3人』に設定しました。")
    assert latest(villages).size == 3


def test_fullwidth_village_numbers_join_too():
    handler, _, villages, _ = make(0)
    handler.handle(OWNER, "お題")
    handler.handle(OWNER, "すいか")
    handler.handle(OWNER, "2")
    number = str(latest(villages).number).translate(str.maketrans("0123456789", "０１２３４５６７８９"))
    assert handler.handle(MEMBER, number)[0].text.startswith("あなたの役職は")


def test_ideographic_spaces_are_not_trimmed():
    # Java の trim() は全角スペースを除かないので、数値にもコマンドにもならずお題になる
    handler, _, villages, _ = make()
    handler.handle(OWNER, "お題")
    first = latest(villages)
    assert handler.handle(OWNER, "　3　") == messages.topic_set_reply(first)
    assert first.topic == "　3　"
    handler.handle(OWNER, "お題")
    second = latest(villages)
    assert handler.handle(OWNER, "　神　") == messages.topic_set_reply(second)
    assert latest(villages) is second  # 神モードの村は作られていない
    assert second.topic == "　神　"


def test_commands_are_matched_after_java_trim():
    # Java の trim() は U+0020 以下の文字（空白・タブ・改行）を除いてからコマンド表と照らす
    handler, _, villages, _ = make()
    assert handler.handle(OWNER, " お題 ") == messages.created_reply(latest(villages).number)
    assert latest(villages).topic is None  # お題として読まれていない
    expected = [
        Image("https://game.example.com/static/roles/966mpnqz.png"),
        Text("https://line.me/R/ti/p/%40966mpnqz"),
        Text("お友達ID\n@966mpnqz"),
    ]
    assert handler.handle(OWNER, "\t@配布\n") == expected


def test_numbers_java_cannot_read_are_topics():
    # Integer.parseInt は「_」と int の範囲外を読めない。Java ではお題になる
    for text in ("1_0", "2147483648", "-2147483649", "99999999999"):
        handler, _, villages, _ = make()
        handler.handle(OWNER, "お題")
        assert handler.handle(OWNER, text) == messages.topic_set_reply(latest(villages)), text
        assert latest(villages).topic == text


def test_supplementary_plane_digits_are_topics():
    # Java の Integer.parseInt は UTF-16 の 1 文字ずつ読むので、BMP 外の数字はサロゲートペアになり読めない
    handler, _, villages, _ = make()
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, "\U0001D7D1") == messages.topic_set_reply(latest(villages))
    assert latest(villages).topic == "\U0001D7D1"


def test_five_digit_numbers_join_special_villages():
    handler, service, _, specials = make()
    number = service.create_special_village(["a", "b"])
    reply = handler.handle(MEMBER, str(number))
    assert reply == messages.special_role_reply(specials.get(number), MEMBER)
    assert handler.handle(MEMBER, "99999") is None


def test_four_digit_numbers_join_villages_until_full():
    handler, _, villages, _ = make(0)
    handler.handle(OWNER, "お題")
    handler.handle(OWNER, "すいか")
    handler.handle(OWNER, "2")
    number = str(latest(villages).number)
    assert handler.handle(MEMBER, number)[0].text.startswith("あなたの役職は")
    assert handler.handle(MEMBER, number) == handler.handle(MEMBER, number)
    assert handler.handle("line:second", number)[0].text.startswith("あなたの役職は")
    assert handler.handle("line:third", number) == messages.full_reply()
    assert handler.handle(OWNER, number) == messages.owner_reply(latest(villages))


# --- お題 ---


def test_free_text_becomes_the_topic_with_whitespace_kept():
    handler, _, villages, _ = make()
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, " すいか ") == messages.topic_set_reply(latest(villages))
    assert latest(villages).topic == " すいか "


def test_unknown_text_without_a_village_is_none():
    handler, _, _, _ = make()
    assert handler.handle(OWNER, "知らない文字列") is None


def test_an_at_command_that_is_not_defined_is_a_topic():
    handler, _, villages, _ = make()
    handler.handle(OWNER, "お題")
    handler.handle(OWNER, "@あ")
    assert latest(villages).topic == "@あ"


# --- @ コマンド ---


def test_reverse_and_werewords_commands_accept_both_at_signs():
    handler, _, villages, specials = make(0, 0)
    handler.handle(OWNER, "お題")
    handler.handle(OWNER, "すいか")
    handler.handle(OWNER, "3")
    assert handler.handle(OWNER, "＠逆村") == messages.reverse_set_reply(latest(villages))
    reply = handler.handle(OWNER, "@わーわーず")
    assert reply is not None and "ワーワーズ" in reply[0].text
    handler.handle(OWNER, "お題")
    assert handler.handle(OWNER, "@逆村") is not None
    assert handler.handle(OWNER, "＠わーわーず") is None  # 人数もお題もない


def test_distribution_command_replies_with_the_invitation():
    handler, service, _, _ = make()
    expected = [
        Image("https://game.example.com/static/roles/966mpnqz.png"),
        Text("https://line.me/R/ti/p/%40966mpnqz"),
        Text("お友達ID\n@966mpnqz"),
    ]
    assert handler.handle(OWNER, "@配布") == expected
    assert handler.handle(OWNER, "＠配布") == expected


def test_special_command_replies_with_the_form_url():
    handler, _, _, _ = make()
    assert handler.handle(OWNER, "@特殊") == [Text(FORM_URL)]
    assert handler.handle(OWNER, "＠特殊") == [Text(FORM_URL)]


def test_lookup_command_offers_a_candidate_from_the_unspecified_range():
    handler, _, _, _ = make(3)
    reply = handler.handle(OWNER, "@取得")
    assert reply == messages.candidate_reply("d")
    assert reply[0].actions[0] == MessageAction("確定", "d")
    assert reply[0].actions[1:] == (PostbackAction("初心者", "2"), PostbackAction("上級者", "3"), PostbackAction("変態", "4"))


def test_topic_candidate_uses_the_given_rank():
    handler, _, _, _ = make(0, 0, 0, 0)
    assert handler.topic_candidate(2) == messages.candidate_reply("a")
    assert handler.topic_candidate(3) == messages.candidate_reply("c")
    assert handler.topic_candidate(4) == messages.candidate_reply("e")
    assert handler.topic_candidate(UNSPECIFIED_RANK) == messages.candidate_reply("a")


# --- 経路一致 ---

SCRIPT = ["お題", "すいか", "3", "<現在の村>", "@逆村", "＠わーわーず", "@特殊", "@配布", "101", "9999", " 3 ", "知らない文字列", "３", "　3　"]


def run_through_text(handler, villages):
    answers = []
    for text in SCRIPT:
        if text == "<現在の村>":
            text = str(latest(villages).number)
        answers.append(handler.handle(OWNER, text))
    return answers


def run_through_service(service, villages):
    def number():
        return latest(villages).number

    return [
        service.create_village(OWNER, False),
        service.set_topic(OWNER, "すいか"),
        service.set_size(OWNER, 3),
        service.join_village(OWNER, number()),
        service.set_reverse(OWNER),
        service.convert_to_werewords(OWNER),
        messages.special_form_reply(FORM_URL),
        messages.invitation_reply(service.illust),
        service.join_village(OWNER, 101),
        service.join_village(OWNER, 9999),
        service.set_size(OWNER, 3),
        service.set_topic(OWNER, "知らない文字列"),
        service.set_size(OWNER, 3),
        service.set_topic(OWNER, "　3　"),
    ]


def normalize(reply):
    """村番号は実行ごとに採番されるので 4 桁以上の数字を伏せる。人数や入室状況は 3 桁以下なので残る。"""
    import re

    return None if reply is None else re.sub(r"\d{4,}", "<村番号>", repr(reply))


def test_text_commands_and_structured_operations_answer_the_same_script_the_same_way():
    handler, _, villages_a, _ = make(0, 0)
    through_text = run_through_text(handler, villages_a)
    _, service, villages_b, _ = make(0, 0)
    through_service = run_through_service(service, villages_b)
    assert len(through_text) == len(SCRIPT)
    for text, a, b in zip(SCRIPT, through_text, through_service):
        assert normalize(a) == normalize(b), f"入力『{text}』への応答が経路で異なる"


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
