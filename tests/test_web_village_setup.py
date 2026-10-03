import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from insider_bot.village.reply import Text
from insider_bot.web.village_setup import build_village, catalog_refresh


def test_build_village_uses_the_bundled_dictionary_and_root_relative_images():
    village = build_village("", None)
    assert village.service.pick_topic(2) is not None
    assert village.service.illust.default_url("GM") == "/static/roles/GM.png"
    assert village.commands.handle("web:someone", "@特殊") == [Text("/village/special")]


def test_build_village_uses_the_public_base_url():
    village = build_village("https://game.example.com", None)
    assert village.service.illust.default_url("GM") == "https://game.example.com/static/roles/GM.png"
    assert village.commands.handle("web:someone", "@特殊") == [Text("https://game.example.com/village/special")]


class RecordingIllust:
    def __init__(self):
        self.clients = []

    async def refresh(self, client):
        self.clients.append(client)


class FakeClient:
    closed = False

    async def aclose(self):
        self.closed = True


async def test_the_catalog_is_refreshed_at_start_and_periodically_and_the_client_is_closed():
    illust = RecordingIllust()
    client = FakeClient()
    app = web.Application()
    app.cleanup_ctx.append(catalog_refresh(illust, interval=0.01, client_factory=lambda: client))
    async with TestClient(TestServer(app)):
        async with asyncio.timeout(2):
            while len(illust.clients) < 3:
                await asyncio.sleep(0.01)
    assert illust.clients[0] is client
    assert client.closed
