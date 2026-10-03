"""村の中核をプロセスに 1 つだけ組み立て、役職画像のカタログを取り直し続ける。

Web と LINE の入口は同じ VillageApp を共有する。村のレジストリはメモリにしかないので、
「LINE で作った村に Web から入る」には同じプロセスの同じ中核を使うしかない。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx2
from aiohttp import web

from insider_bot.village.commands import CommandHandler
from insider_bot.village.illust import Illustrations
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.service import VillageService
from insider_bot.village.words import load_dictionary
from insider_bot.web.village_api import VillageApp

# 外部カタログを取り直す間隔
CATALOG_REFRESH_SECONDS = 300.0
SPECIAL_FORM_PATH = "/village/special"


def build_village(public_base_url: str, catalog_url: str | None) -> VillageApp:
    """辞書を 1 度だけ読み、画像とフォームの URL は公開 URL から組み立てる。

    公開 URL が空なら、サイト内の絶対パス（/static/roles/…、/village/special）になる。Web だけならこれで足りる。
    """
    illust = Illustrations(public_base_url, catalog_url=catalog_url)
    service = VillageService(VillageRegistry(), SpecialVillageRegistry(), load_dictionary(), illust)
    return VillageApp(service, CommandHandler(service, public_base_url.rstrip("/") + SPECIAL_FORM_PATH))


def catalog_refresh(
    illust: Any,
    interval: float = CATALOG_REFRESH_SECONDS,
    client_factory: Callable[[], Any] = httpx2.AsyncClient,
) -> Callable[[web.Application], AsyncIterator[None]]:
    """起動直後と以降 interval 秒ごとにカタログを取り直す、aiohttp の cleanup_ctx。

    取り直しの失敗は Illustrations.refresh が WARNING にして前回分を使い続けるので、ここでは扱わない。
    """

    async def run(app: web.Application) -> AsyncIterator[None]:
        client = client_factory()
        task = asyncio.create_task(_refresh_forever(illust, client, interval))
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await client.aclose()

    return run


async def _refresh_forever(illust: Any, client: Any, interval: float) -> None:
    while True:
        await illust.refresh(client)
        await asyncio.sleep(interval)
