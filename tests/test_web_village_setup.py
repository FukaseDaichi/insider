from insider_bot.village.reply import Text
from insider_bot.web.village_setup import build_village


def test_build_village_uses_the_bundled_dictionary_and_root_relative_images():
    village = build_village("")
    assert village.service.pick_topic(2) is not None
    assert village.service.illust.default_url("GM") == "/static/roles/GM.png?v=20261004"
    assert village.commands.handle("web:someone", "@特殊") == [Text("/village/special")]


def test_build_village_uses_the_public_base_url():
    village = build_village("https://game.example.com")
    assert village.service.illust.default_url("GM") == "https://game.example.com/static/roles/GM.png?v=20261004"
    assert village.commands.handle("web:someone", "@特殊") == [Text("https://game.example.com/village/special")]
