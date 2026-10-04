"""起動: uv run --env-file .env python -m insider_bot.web"""

from __future__ import annotations

import logging
import sys

from aiohttp import web

from insider_bot.config import ConfigError, WebConfig, load_web_config
from insider_bot.game import GameManager
from insider_bot.judge import JevJudge, create_jev_client
from insider_bot.service import GameService
from insider_bot.web.hub import RoomHub
from insider_bot.web.rooms import RoomRegistry
from insider_bot.web.server import create_app
from insider_bot.web.village_setup import build_village


async def make_app(config: WebConfig) -> web.Application:
    client = create_jev_client(config.typesafe_api_key, config.jev_timeout_seconds)
    manager = GameManager()
    service = GameService(manager, JevJudge(client, config.correct_threshold, config.jev_timeout_seconds))
    registry = RoomRegistry(on_remove=lambda room: manager.end(room.room_id))
    village = build_village(config.public_base_url)
    app = create_app(RoomHub(registry, service, manager), village=village)

    async def close_client(_app: web.Application) -> None:
        await client.aclose()

    app.on_cleanup.append(close_client)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_web_config()
    except ConfigError as error:
        print(f"設定エラー: {error}", file=sys.stderr)
        sys.exit(1)
    web.run_app(make_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
