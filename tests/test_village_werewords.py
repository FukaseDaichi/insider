import random

from insider_bot.village.werewords import MIN_WEREWORDS_SIZE, role_name, werewords_messages
from tests.fakes import FixedRandom


def test_god_mode_distributes_one_message_per_participant():
    messages = werewords_messages(True, 5, "すいか", random.Random(0))
    assert len(messages) == 5
    assert messages[0].startswith("あなたの役職はＧＭです。")
    assert "が欠けています。" in messages[0]


def test_without_god_mode_an_extra_villager_message_is_added():
    messages = werewords_messages(False, 5, "すいか", random.Random(0))
    assert len(messages) == 6
    assert messages[0] == "あなたの役職は村人です"


def test_every_message_is_assigned():
    for message in werewords_messages(True, 4, "すいか", random.Random(0)):
        assert message


def test_the_missing_role_is_the_first_after_shuffle():
    # shuffle しない乱数なら並びは [占師, インサイダー, 村人, 村人, 村人]。先頭の占師が欠け
    messages = werewords_messages(True, 5, "すいか", FixedRandom())
    assert messages[0] == "あなたの役職はＧＭです。お題は「すいか」です。\n役職は「占師」が欠けています。"
    assert messages[1] == "あなたの役職はインサイダーです。お題は「すいか」です。"
    assert messages[2:] == ["あなたの役職は村人です"] * 3


def test_without_god_mode_all_roles_are_distributed_including_the_missing_one():
    messages = werewords_messages(False, 3, "すいか", FixedRandom())
    assert messages == [
        "あなたの役職は村人です",
        "あなたの役職は占師です。お題は「すいか」です。",
        "あなたの役職はインサイダーです。お題は「すいか」です。",
        "あなたの役職は村人です",
    ]


def test_the_missing_role_is_named_rather_than_described():
    assert role_name(3) == "村人"
    saw_missing_villager = False
    for seed in range(100):
        gm = werewords_messages(True, 5, "すいか", random.Random(seed))[0]
        assert gm.count("あなたの役職は") == 1, gm
        if "役職は「村人」が欠けています。" in gm:
            saw_missing_villager = True
    assert saw_missing_villager


def test_minimum_size_is_three():
    assert MIN_WEREWORDS_SIZE == 3
