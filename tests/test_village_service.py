import random

from insider_bot.village import messages
from insider_bot.village.illust import Illustrations
from insider_bot.village.model import Role
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.service import OwnedVillage, VillageService
from insider_bot.village.words import BEGINNER_RANK, parse_dictionary
from tests.fakes import FixedRandom

OWNER = "line:owner"
BASE = "https://game.example.com"
DICTIONARY = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])


def make(*draws: int):
    """配役の乱数だけを固定し、採番は本物の乱数に任せる（Java と同じ分担）。"""
    villages = VillageRegistry(random.Random(1))
    specials = SpecialVillageRegistry(random.Random(2))
    rng = FixedRandom(*draws) if draws else random.Random(3)
    illust = Illustrations(BASE, FixedRandom(0))
    return VillageService(villages, specials, DICTIONARY, illust, rng), villages, specials, illust


def latest(villages, owner=OWNER):
    return villages.find_latest_owned(owner, lambda v: True)


def join_all(village, *users):
    for user in users:
        assert village.join(user) is not None, user


# --- 作成 ---


def test_create_village_registers_and_replies():
    service, villages, _, _ = make()
    reply = service.create_village(OWNER, god_mode=False)
    village = latest(villages)
    assert 1000 <= village.number <= 9999
    assert reply == messages.created_reply(village.number)
    assert not village.has_game_master()


def test_create_god_village_awaits_size():
    service, villages, _, _ = make()
    service.create_village(OWNER, god_mode=True)
    assert latest(villages).is_god_mode_awaiting_size()


def test_create_random_village_picks_a_topic_and_marks_god_mode():
    service, villages, _, _ = make(0)
    reply = service.create_random_village(OWNER)
    village = latest(villages)
    assert village.random_mode
    assert village.is_god_mode_awaiting_size()
    assert village.topic == "a"  # 初心者の 1 行目
    assert reply == messages.random_created_reply(village.number)


# --- 人数 ---


def test_insider_seat_follows_the_draw():
    service, villages, _, illust = make(2)
    service.create_village(OWNER, False)
    village = latest(villages)
    village.set_topic("すいか")
    reply = service.set_size(OWNER, 5)
    assert village.insider_seat == 3
    assert village.size == 5
    assert reply == messages.size_set_reply(village, god_mode=False, illust=illust)
    join_all(village, "u1", "u2", "u3", "u4", "u5")
    assert village.role_of("u3") is Role.INSIDER
    assert village.role_of("u1") is Role.VILLAGER


def test_god_mode_draws_a_game_master_distinct_from_the_insider():
    service, villages, _, illust = make(1, 1, 3)
    service.create_village(OWNER, True)
    reply = service.set_size(OWNER, 5)
    village = latest(villages)
    assert (village.insider_seat, village.gm_seat) == (2, 4)
    assert reply[0].image == illust.default_url("GOD")


def test_size_below_two_is_rejected_with_guidance_and_leaves_the_village_unset():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    assert service.set_size(OWNER, 1) == messages.size_error_reply()
    assert service.set_size(OWNER, 0) == messages.size_error_reply()
    assert service.set_size(OWNER, -3) == messages.size_error_reply()
    assert latest(villages).size == 0


def test_second_size_setting_is_rejected_instead_of_reshuffling():
    service, villages, _, _ = make(2, 0)
    service.create_village(OWNER, False)
    assert service.set_size(OWNER, 5) is not None
    assert service.set_size(OWNER, 9) is None
    village = latest(villages)
    assert (village.size, village.insider_seat) == (5, 3)


def test_size_without_a_village_is_none():
    service, _, _, _ = make()
    assert service.set_size(OWNER, 3) is None


def test_random_village_size_seats_the_owner_and_replies_with_their_role():
    service, villages, _, illust = make(0, 2, 0)  # お題の抽選、インサイダー 3 番目、GM 1 番目
    service.create_random_village(OWNER)
    reply = service.set_size(OWNER, 4)
    village = latest(villages)
    assert village.role_of(OWNER) is Role.GAME_MASTER
    assert reply == messages.random_size_set_reply(village, 4, illust)
    join_all(village, "u2", "u3", "u4")
    assert village.role_of("u3") is Role.INSIDER


# --- お題 ---


def test_topic_is_set_only_once():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    village = latest(villages)
    assert service.set_topic(OWNER, "すいか") == messages.topic_set_reply(village)
    assert service.set_topic(OWNER, "めろん") is None
    assert village.topic == "すいか"


def test_topic_keeps_surrounding_whitespace_and_commas():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    service.set_topic(OWNER, " りんご,みかん ")
    assert latest(villages).topic == " りんご,みかん "


def test_topic_goes_to_the_latest_village_without_a_topic():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    first = latest(villages)
    service.set_topic(OWNER, "一つ目")
    service.create_village(OWNER, False)
    second = latest(villages)
    service.set_topic(OWNER, "二つ目")
    assert (first.topic, second.topic) == ("一つ目", "二つ目")


# --- 逆村 ---


def test_reverse_is_confirmed_before_anyone_joins():
    service, villages, _, _ = make(1)
    service.create_village(OWNER, False)
    service.set_size(OWNER, 3)
    village = latest(villages)
    assert service.set_reverse(OWNER) == messages.reverse_set_reply(village)
    assert village.reverse


def test_reverse_is_rejected_once_participants_joined():
    service, villages, _, _ = make(1)
    service.create_village(OWNER, False)
    service.set_size(OWNER, 3)
    village = latest(villages)
    join_all(village, "u1")
    assert service.set_reverse(OWNER) is None
    assert not village.reverse


def test_random_village_is_not_turned_into_a_reverse_village():
    service, villages, _, _ = make(0)
    service.create_random_village(OWNER)
    assert service.set_reverse(OWNER) is None


def test_reverse_without_a_village_is_none():
    service, _, _, _ = make()
    assert service.set_reverse(OWNER) is None


# --- 参加 ---


def test_participants_join_until_full_and_rejoining_is_idempotent():
    service, villages, _, illust = make(0)
    service.create_village(OWNER, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 2)
    number = latest(villages).number
    first = service.join_village("line:m1", number)
    assert first == messages.role_reply(latest(villages), "line:m1", illust)
    assert service.join_village("line:m1", number) == first
    assert service.join_village("line:m2", number)[0].text.startswith("あなたの役職は")
    assert service.join_village("line:m3", number) == messages.full_reply()


def test_joining_before_the_size_is_set_is_full():
    service, villages, _, _ = make()
    service.create_village(OWNER, False)
    assert service.join_village("line:m1", latest(villages).number) == messages.full_reply()


def test_owner_sees_the_distribution_status():
    service, villages, _, _ = make(0)
    service.create_village(OWNER, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 2)
    village = latest(villages)
    service.join_village("line:m1", village.number)
    assert service.join_village(OWNER, village.number) == messages.owner_reply(village)
    assert village.member_count() == 1  # オーナーは着席しない


def test_random_village_owner_sees_their_own_role_or_is_asked_for_the_size():
    service, villages, _, illust = make(0, 1, 2)
    service.create_random_village(OWNER)
    village = latest(villages)
    assert service.join_village(OWNER, village.number) == messages.random_numset_reply()
    service.set_size(OWNER, 3)
    assert village.role_of(OWNER) is Role.VILLAGER
    assert service.join_village(OWNER, village.number) == messages.role_reply(village, OWNER, illust)


def test_unknown_village_number_is_none():
    service, _, _, _ = make()
    assert service.join_village("line:m1", 1234) is None
    assert service.village_status("line:m1", 1234) is None


def test_village_status():
    service, villages, _, _ = make(0)
    service.create_village(OWNER, False)
    service.set_size(OWNER, 3)
    village = latest(villages)
    service.join_village("line:m1", village.number)
    assert service.village_status("line:m1", village.number) == messages.status_reply(village, "line:m1")


# --- 特殊村 ---


def test_create_special_village_shuffles_a_copy_and_registers_it():
    service, _, specials, _ = make()
    source = ["1人目", "2人目", "3人目"]
    number = service.create_special_village(source)
    assert source == ["1人目", "2人目", "3人目"]
    village = specials.get(number)
    assert 10000 <= number <= 99998
    assert sorted(village.messages) == sorted(source)


def test_special_village_join_and_status():
    service, _, specials, _ = make()
    number = service.create_special_village(["only", None])
    village = specials.get(number)
    reply = service.join_special_village("line:a", number)
    assert reply == messages.special_role_reply(village, "line:a")
    assert service.join_special_village("line:a", number) == reply
    assert service.join_special_village("line:b", number) is not None
    assert service.join_special_village("line:c", number) == messages.full_reply()
    assert service.special_village_status("line:a", number) == messages.status_reply(village, "line:a")
    assert service.join_special_village("line:a", 99999) is None
    assert service.special_village_status("line:a", 99999) is None


# --- Werewords ---


def test_werewords_from_a_god_village_distributes_size_messages():
    service, villages, specials, _ = make(0, 1)
    service.create_village(OWNER, True)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 3)
    original = latest(villages)
    reply = service.convert_to_werewords(OWNER)
    number = int(reply[0].text.split("『")[2].split("』")[0])
    assert reply == messages.werewords_created_reply("すいか", number, god_mode=True)
    assert specials.get(number).capacity() == 3
    assert sum(1 for m in specials.get(number).messages if m.startswith("あなたの役職はGMです。")) == 1
    # 元の村は残る
    assert villages.get(original.number) is original


def test_werewords_from_a_normal_village_adds_one_message_for_the_owner():
    service, villages, specials, _ = make(0)
    service.create_village(OWNER, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 3)
    reply = service.convert_to_werewords(OWNER)
    number = int(reply[0].text.split("『")[2].split("』")[0])
    assert reply == messages.werewords_created_reply("すいか", number, god_mode=False)
    assert specials.get(number).capacity() == 4


def test_werewords_needs_three_participants_and_a_topic_on_the_latest_empty_village():
    service, _, _, _ = make(0, 0)
    service.create_village(OWNER, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 2)
    assert service.convert_to_werewords(OWNER) is None
    service.create_village(OWNER, False)
    service.set_size(OWNER, 3)
    assert service.convert_to_werewords(OWNER) is None  # お題がない。古い村へは遡らない
    assert service.convert_to_werewords("line:nobody") is None


def test_werewords_does_not_fall_back_to_an_older_eligible_village():
    service, villages, _, _ = make(0, 0)
    # Create village A (older, eligible): size 3, topic set, no members
    service.create_village(OWNER, False)
    village_a = latest(villages)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 3)

    # Create village B (newer, initially ineligible): size 3 but no topic
    service.create_village(OWNER, False)
    village_b = latest(villages)
    service.set_size(OWNER, 3)

    # B is newest but lacks topic, should not fall back to A
    assert service.convert_to_werewords(OWNER) is None

    # Set B's topic, now B is eligible and should be used
    service.set_topic(OWNER, "めろん")
    reply = service.convert_to_werewords(OWNER)
    assert reply is not None


# --- 辞書 ---


def test_pick_topic_delegates_to_the_dictionary():
    service, _, _, _ = make(0)
    assert service.pick_topic(BEGINNER_RANK) == "a"


# --- オーナーから見た村 ---


def test_latest_owned_follows_the_setup_of_the_newest_village():
    service, villages, _, _ = make(0)
    assert service.latest_owned(OWNER) is None
    service.create_village(OWNER, god_mode=False)
    number = latest(villages).number
    assert service.latest_owned(OWNER) == OwnedVillage(number, "normal", False, 0, 0, False)
    service.set_topic(OWNER, "すいか")
    service.set_size(OWNER, 2)
    service.join_village("line:m1", number)
    assert service.latest_owned(OWNER) == OwnedVillage(number, "normal", True, 2, 1, False)


def test_latest_owned_reports_the_mode_and_reverse():
    service, _, _, _ = make(0)
    service.create_village(OWNER, god_mode=True)
    assert service.latest_owned(OWNER).mode == "god"
    service.create_village(OWNER, god_mode=False)
    service.set_reverse(OWNER)
    assert service.latest_owned(OWNER).reverse
    service.create_random_village(OWNER)
    owned = service.latest_owned(OWNER)
    assert (owned.mode, owned.has_topic) == ("random", True)
    assert service.latest_owned("line:other") is None
