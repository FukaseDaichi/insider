import logging

import pytest

from insider_bot.village.illust import Illustrations, WeightedUrl, parse_catalog
from tests.fakes import FixedRandom

BASE = "https://game.example.com"


def entry(name, url):
    return {"name": name, "url": url}


def test_default_urls_are_served_from_our_own_static_dir():
    illust = Illustrations(BASE)
    assert illust.default_url("INSIDER") == f"{BASE}/static/roles/INSIDER.png"
    assert illust.default_url("VILLAGERS") == f"{BASE}/static/roles/VILLAGERS.png"
    assert illust.default_url("GM") == f"{BASE}/static/roles/GM.png"
    assert illust.default_url("GOD") == f"{BASE}/static/roles/GOD.png"
    assert illust.invitation_image_url == f"{BASE}/static/roles/966mpnqz.png"


def test_trailing_slash_in_base_url_is_tolerated():
    assert Illustrations(BASE + "/").default_url("GM") == f"{BASE}/static/roles/GM.png"


def test_falls_back_to_defaults_while_no_catalog_is_loaded():
    illust = Illustrations(BASE, FixedRandom(0))
    for key in ("INSIDER", "VILLAGERS", "GM", "GOD"):
        assert illust.url_for(key) == illust.default_url(key)


def test_entries_without_a_three_part_name_are_ignored():
    parsed = parse_catalog(
        [
            entry("INSIDER_2_a.png", "https://x/insider.png"),
            entry("VILLAGERS.png", "https://x/no-weight.png"),
            entry("GM_1_b_c.png", "https://x/too-many-parts.png"),
        ]
    )
    assert set(parsed) == {"INSIDER"}


def test_names_and_weights_are_read_like_java():
    # Java の String.split は末尾の空要素を落とし、Integer.parseInt は空白と int の範囲外を読まず、全角数字を読む
    parsed = parse_catalog(
        [
            entry("GM_1_a.png_", "https://x/trailing.png"),  # 末尾の空要素を落として 3 部
            entry("GM_1_", "https://x/two-parts.png"),  # 2 部
            entry("GM_1_a_b_", "https://x/four-parts.png"),  # 4 部
            entry("GM_ 1 _a.png", "https://x/spaced.png"),  # 重みに空白
            entry("GM_2147483648_a.png", "https://x/overflow.png"),  # int の範囲外
            entry("GM_２_b.png", "https://x/fullwidth.png"),  # 全角数字の重み
        ]
    )
    assert parsed == {"GM": (WeightedUrl("https://x/trailing.png", 1), WeightedUrl("https://x/fullwidth.png", 3))}


def test_an_unusable_entry_is_skipped_without_dropping_the_rest(caplog):
    with caplog.at_level(logging.WARNING, logger="insider_bot.village.illust"):
        parsed = parse_catalog(
            [
                entry("INSIDER_おおい_broken.png", "https://x/broken.png"),
                entry("GM_1_no-url.png", None),
                entry(None, "https://x/no-name.png"),
                {"url": "https://x/no-name-key.png"},
                entry("VILLAGERS_1_ok.png", "https://x/villagers.png"),
            ]
        )
    assert set(parsed) == {"VILLAGERS"}
    assert "4" in caplog.text  # 読み飛ばした件数


def test_weights_decide_how_many_draw_slots_a_file_gets():
    illust = Illustrations(BASE)
    illust.apply_catalog([entry("INSIDER_1_rare.png", "https://x/rare.png"), entry("INSIDER_3_common.png", "https://x/common.png")])
    draws = []
    for value in (0, 1, 3):
        illust._rng = FixedRandom(value)
        draws.append(illust.url_for("INSIDER"))
    assert draws == ["https://x/rare.png", "https://x/common.png", "https://x/common.png"]


def test_the_draw_bound_is_the_total_weight():
    class Recording(FixedRandom):
        bound = None

        def randrange(self, n):
            self.bound = n
            return 0

    rng = Recording()
    illust = Illustrations(BASE, rng)
    illust.apply_catalog([entry("INSIDER_1_rare.png", "https://x/rare.png"), entry("INSIDER_3_common.png", "https://x/common.png")])
    illust.url_for("INSIDER")
    assert rng.bound == 4


def test_files_without_a_positive_weight_are_never_drawn():
    illust = Illustrations(BASE, FixedRandom(0))
    illust.apply_catalog(
        [
            entry("INSIDER_0_zero.png", "https://x/zero.png"),
            entry("INSIDER_-2_negative.png", "https://x/negative.png"),
            entry("INSIDER_1_only.png", "https://x/only.png"),
        ]
    )
    assert illust.url_for("INSIDER") == "https://x/only.png"


def test_a_role_without_any_positive_weight_falls_back_to_the_default():
    illust = Illustrations(BASE, FixedRandom(0))
    illust.apply_catalog([entry("INSIDER_0_a.png", "https://x/a.png"), entry("INSIDER_0_b.png", "https://x/b.png")])
    assert illust.url_for("INSIDER") == illust.default_url("INSIDER")
    # 他の役職は候補がないので既定
    assert illust.url_for("GM") == illust.default_url("GM")


def test_unknown_role_key_is_rejected():
    with pytest.raises(KeyError):
        Illustrations(BASE).default_url("NOPE")


class FakeResponse:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


async def test_refresh_replaces_the_catalog():
    illust = Illustrations(BASE, FixedRandom(0), catalog_url="https://script.google.com/macros/s/x/exec")
    client = FakeClient(FakeResponse({"files": [entry("GM_1_a.png", "https://x/gm.png")]}))
    await illust.refresh(client)
    assert client.calls[0][0] == "https://script.google.com/macros/s/x/exec"
    assert client.calls[0][1]["follow_redirects"] is True
    assert illust.url_for("GM") == "https://x/gm.png"


async def test_refresh_keeps_the_previous_catalog_on_failure(caplog):
    illust = Illustrations(BASE, FixedRandom(0), catalog_url="https://script.google.com/macros/s/x/exec")
    await illust.refresh(FakeClient(FakeResponse({"files": [entry("GM_1_a.png", "https://x/gm.png")]})))
    with caplog.at_level(logging.WARNING, logger="insider_bot.village.illust"):
        await illust.refresh(FakeClient(error=RuntimeError("boom")))
        await illust.refresh(FakeClient(FakeResponse({"nope": 1})))
    assert illust.url_for("GM") == "https://x/gm.png"
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2


async def test_refresh_without_a_catalog_url_does_nothing():
    illust = Illustrations(BASE, FixedRandom(0))
    client = FakeClient()
    await illust.refresh(client)
    assert client.calls == []
