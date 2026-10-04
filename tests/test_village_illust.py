import hashlib
import struct

import pytest

from insider_bot.village.illust import ROLE_VARIANTS, Illustrations
from insider_bot.web.server import STATIC_DIR
from tests.fakes import FirstRandom, FixedRandom

BASE = "https://game.example.com"


@pytest.mark.parametrize("role", ["INSIDER", "VILLAGERS", "GM", "GOD"])
def test_default_urls_use_a_new_version_to_avoid_the_old_cached_images(role):
    assert Illustrations(BASE).default_url(role) == f"{BASE}/static/roles/{role}.png?v=20261004"


def test_invitation_image_is_preserved():
    illust = Illustrations(BASE)
    assert illust.invitation_image_url == f"{BASE}/static/roles/966mpnqz.png"
    assert hashlib.sha256((STATIC_DIR / "roles/966mpnqz.png").read_bytes()).hexdigest() == (
        "5a5d6c30ff6253c90e509a78153a1a4172a50a182c0c2d62513d5553837231bb"
    )


def test_trailing_slash_in_base_url_is_tolerated():
    assert Illustrations(BASE + "/").default_url("GM") == f"{BASE}/static/roles/GM.png?v=20261004"


@pytest.mark.parametrize("role", ["INSIDER", "VILLAGERS", "GM", "GOD"])
def test_all_five_regenerated_images_can_be_selected_without_an_external_catalog(role):
    illust = Illustrations("", FixedRandom(0, 1, 2, 3, 4))
    assert [illust.url_for(role) for _ in range(5)] == [
        f"/static/roles/{role}.png?v=20261004",
        f"/static/roles/{role}_1_02.png?v=20261004",
        f"/static/roles/{role}_1_03.png?v=20261004",
        f"/static/roles/{role}_1_04.png?v=20261004",
        f"/static/roles/{role}_1_05.png?v=20261004",
    ]


def test_each_variant_has_one_of_five_equal_draw_slots():
    class RecordingRandom(FirstRandom):
        bounds = []

        def randrange(self, n):
            self.bounds.append(n)
            return 0

    rng = RecordingRandom()
    illust = Illustrations(BASE, rng)
    for role in ("INSIDER", "VILLAGERS", "GM", "GOD"):
        assert illust.url_for(role) == illust.default_url(role)
    assert rng.bounds == [5, 5, 5, 5]


@pytest.mark.parametrize("method", ["default_url", "url_for"])
def test_unknown_role_key_is_rejected(method):
    with pytest.raises(KeyError):
        getattr(Illustrations(BASE), method)("NOPE")


def test_all_20_bundled_role_images_are_distinct_square_pngs_under_one_megabyte():
    images = [STATIC_DIR / "roles" / filename for files in ROLE_VARIANTS.values() for filename in files]
    assert len(images) == len(set(images)) == 20
    hashes = set()
    for path in images:
        data = path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", path
        assert struct.unpack(">II", data[16:24]) == (1024, 1024), path
        assert len(data) <= 1_000_000, path
        hashes.add(hashlib.sha256(data).hexdigest())
    assert len(hashes) == 20
