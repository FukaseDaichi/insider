import random

import pytest

from insider_bot.village.model import GOD_MODE_PENDING, Role, Village
from tests.fakes import FixedRandom


def village_of(size: int, insider_at: int) -> Village:
    village = Village("owner")
    assert village.configure(size, FixedRandom(insider_at - 1))
    return village


def join_all(village: Village, *user_ids: str) -> None:
    for user_id in user_ids:
        assert village.join(user_id) is not None, f"参加できなかった: {user_id}"
    assert village.member_count() == len(user_ids) + (1 if village.random_mode else 0)


# --- 配役 ---


def test_normal_village_assigns_insider_by_join_order():
    village = village_of(3, insider_at=2)
    join_all(village, "first", "second", "third")
    assert village.role_of("first") is Role.VILLAGER
    assert village.role_of("second") is Role.INSIDER
    assert village.role_of("third") is Role.VILLAGER


def test_join_is_capacity_bound_and_idempotent():
    village = village_of(1, insider_at=1)
    assert village.join("first") is not None
    assert village.join("first") is not None
    assert village.join("second") is None
    assert village.role_of("first") is Role.INSIDER
    assert village.member_count() == 1


def test_god_mode_assigns_game_master_at_its_own_seat():
    village = Village("owner")
    village.mark_god_mode()
    assert village.is_god_mode_awaiting_size()
    # インサイダーは1番目、GM は3番目
    assert village.configure(3, FixedRandom(0, 2))
    assert not village.is_god_mode_awaiting_size()
    assert village.has_game_master()
    join_all(village, "first", "second", "third")
    assert village.role_of("first") is Role.INSIDER
    assert village.role_of("second") is Role.VILLAGER
    assert village.role_of("third") is Role.GAME_MASTER


def test_god_mode_never_puts_the_game_master_on_the_insider_seat():
    village = Village("owner")
    village.mark_god_mode()
    # GM の席がインサイダーと衝突したら引き直す
    village.configure(3, FixedRandom(1, 1, 1, 0))
    assert village.insider_seat == 2
    assert village.gm_seat == 1


def test_normal_village_has_no_game_master():
    village = village_of(3, insider_at=1)
    assert not village.has_game_master()
    assert village.gm_seat == 0


def test_random_mode_seats_the_owner_first():
    village = Village("owner")
    village.mark_god_mode()
    village.random_mode = True
    # インサイダーは1番目、GM は2番目
    assert village.configure(3, FixedRandom(0, 1))
    assert village.member_count() == 1
    assert village.role_of("owner") is Role.INSIDER
    assert village.join("second") is not None
    assert village.join("third") is not None
    assert village.member_count() == 3
    assert village.role_of("second") is Role.GAME_MASTER
    assert village.role_of("third") is Role.VILLAGER


def test_exactly_one_insider_whatever_the_draw():
    for seed in range(50):
        village = Village("owner")
        village.configure(6, random.Random(seed))
        users = [f"u{i}" for i in range(1, 7)]
        join_all(village, *users)
        insiders = [u for u in users if village.role_of(u) is Role.INSIDER]
        assert len(insiders) == 1, f"seed={seed}"


# --- 逆村 ---


def test_reverse_village_inverts_insider_and_villagers():
    village = village_of(3, insider_at=2)
    assert village.apply_reverse()
    join_all(village, "first", "second", "third")
    assert village.role_of("first") is Role.INSIDER
    assert village.role_of("second") is Role.VILLAGER
    assert village.role_of("third") is Role.INSIDER


def test_reverse_village_keeps_the_game_master():
    village = Village("owner")
    village.mark_god_mode()
    village.configure(3, FixedRandom(0, 2))
    assert village.apply_reverse()
    join_all(village, "first", "second", "third")
    assert village.role_of("first") is Role.VILLAGER
    assert village.role_of("second") is Role.INSIDER
    assert village.role_of("third") is Role.GAME_MASTER


def test_reverse_village_is_rejected_once_someone_joined():
    village = village_of(3, insider_at=2)
    assert village.join("first") is not None
    assert not village.apply_reverse()
    assert not village.reverse
    assert village.role_of("first") is Role.VILLAGER


# --- 一度きりの設定 ---


def test_configure_is_one_shot():
    village = village_of(3, insider_at=2)
    assert not village.configure(5, FixedRandom(0))
    assert village.size == 3
    assert village.insider_seat == 2


def test_set_topic_is_one_shot():
    village = Village("owner")
    assert village.set_topic("すいか")
    assert not village.set_topic("めろん")
    assert village.topic == "すいか"


# --- 参照 ---


def test_seat_number_and_role_of_unknown_user():
    village = village_of(2, insider_at=1)
    assert village.role_of("nobody") is None
    assert village.seat_number_of("nobody") == 0
    village.join("a")
    village.join("b")
    assert village.seat_number_of("a") == 1
    assert village.seat_number_of("b") == 2


def test_join_before_configure_is_full():
    # 人数未設定の村は定員 0。Java と同じく「村がいっぱいです。」側に落ちる
    village = Village("owner")
    assert village.join("a") is None


def test_role_labels_and_illust_keys():
    assert Role.INSIDER.label == "インサイダー"
    assert Role.VILLAGER.label == "村人"
    assert Role.GAME_MASTER.label == "ＧＭ"
    assert Role.INSIDER.illust_key == "INSIDER"
    assert Role.VILLAGER.illust_key == "VILLAGERS"
    assert Role.GAME_MASTER.illust_key == "GM"


def test_god_mode_pending_is_not_a_seat():
    assert GOD_MODE_PENDING == 999


# --- 特殊村 ---

from insider_bot.village.model import SpecialVillage  # noqa: E402


def test_special_village_hands_out_messages_in_join_order():
    village = SpecialVillage(["1人目", "2人目", "3人目"])
    assert village.capacity() == 3
    assert village.join("a")
    assert village.join("b")
    assert village.message_for("a") == "1人目"
    assert village.message_for("b") == "2人目"
    assert village.seat_number_of("a") == 1
    assert village.seat_number_of("b") == 2
    assert village.member_count() == 2


def test_special_village_join_is_idempotent_and_capacity_bound():
    village = SpecialVillage(["only"])
    assert village.join("a")
    assert village.join("a")
    assert not village.join("b")
    assert village.member_count() == 1


def test_special_village_blank_messages_get_the_placeholder():
    village = SpecialVillage([None, "", "本文"])
    for user in ("a", "b", "c"):
        assert village.join(user)
    assert village.message_for("a") == "メッセージは特にありません。"
    assert village.message_for("b") == "メッセージは特にありません。"
    assert village.message_for("c") == "本文"


def test_special_village_message_for_unknown_user_is_none():
    village = SpecialVillage(["x"])
    assert village.message_for("nobody") is None
    assert village.seat_number_of("nobody") == 0


def test_special_village_copies_the_messages():
    source = ["a", "b"]
    village = SpecialVillage(source)
    source.append("c")
    assert village.capacity() == 2
