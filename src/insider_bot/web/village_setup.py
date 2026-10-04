"""Web と LINE の入口で共有する村の中核をプロセスに 1 つ組み立てる。"""

from __future__ import annotations

from insider_bot.village.commands import CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.service import VillageService
from insider_bot.village.words import load_dictionary
from insider_bot.web.village_api import VillageApp

SPECIAL_FORM_PATH = "/village/special"


def build_village(public_base_url: str) -> VillageApp:
    """辞書を 1 度だけ読み、画像とフォームの URL は公開 URL から組み立てる。

    公開 URL が空なら、サイト内の絶対パス（/static/roles/…、/village/special）になる。
    """
    illust = Illustrations(public_base_url)
    service = VillageService(VillageRegistry(), SpecialVillageRegistry(), load_dictionary(), illust)
    return VillageApp(service, CommandHandler(service, public_base_url.rstrip("/") + SPECIAL_FORM_PATH))
