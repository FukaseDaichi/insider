import random

from insider_bot.village.model import SpecialVillage, Village
from insider_bot.village.registry import (
    MAX_SPECIAL_NUMBER,
    MAX_VILLAGE_NUMBER,
    MIN_SPECIAL_NUMBER,
    MIN_VILLAGE_NUMBER,
    SpecialVillageRegistry,
    VillageRegistry,
)
from tests.fakes import FixedRandom


def test_assigns_unique_four_digit_numbers():
    registry = VillageRegistry(random.Random(1))
    numbers = {registry.add(Village("owner")) for _ in range(50)}
    assert len(numbers) == 50
    assert all(MIN_VILLAGE_NUMBER <= n <= MAX_VILLAGE_NUMBER for n in numbers)


def test_add_writes_the_number_into_the_village():
    registry = VillageRegistry(random.Random(1))
    village = Village("owner")
    number = registry.add(village)
    assert village.number == number
    assert registry.get(number) is village


def test_evicts_the_oldest_village_beyond_the_limit():
    registry = VillageRegistry(random.Random(1), max_count=50)
    oldest = registry.add(Village("owner"))
    second = registry.add(Village("owner"))
    for _ in range(49):
        registry.add(Village("owner"))
    assert registry.get(oldest) is None
    assert registry.get(second) is not None


def test_find_latest_owned_returns_the_newest_match():
    registry = VillageRegistry(random.Random(1))
    registry.add(Village("other"))
    older = registry.add(Village("owner"))
    newer = registry.add(Village("owner"))
    assert registry.find_latest_owned("owner", lambda v: True).number == newer
    assert registry.find_latest_owned("owner", lambda v: v.number != newer).number == older
    assert registry.find_latest_owned("owner", lambda v: False) is None


def test_find_latest_owned_ignores_other_owners():
    registry = VillageRegistry(random.Random(1))
    registry.add(Village("other"))
    assert registry.find_latest_owned("owner", lambda v: True) is None


def test_number_draw_skips_taken_numbers_and_sweeps_when_unlucky():
    # 抽選は MIN〜MAX-1。100 回外れたら MIN から順に空きを探す（MAX は総当たりでしか出ない）
    registry = VillageRegistry(FixedRandom(*([0] * 101)))
    first = registry.add(Village("owner"))
    assert first == MIN_VILLAGE_NUMBER
    second = registry.add(Village("owner"))
    assert second == MIN_VILLAGE_NUMBER + 1


def test_special_registry_assigns_five_digit_numbers_and_evicts():
    registry = SpecialVillageRegistry(random.Random(1), max_count=30)
    first = registry.add(SpecialVillage(["a"]))
    assert MIN_SPECIAL_NUMBER <= first <= MAX_SPECIAL_NUMBER
    for _ in range(30):
        registry.add(SpecialVillage(["a"]))
    assert registry.get(first) is None


def test_special_registry_get_unknown_is_none():
    registry = SpecialVillageRegistry(random.Random(1))
    assert registry.get(12345) is None
