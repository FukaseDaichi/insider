"""起動: uv run --env-file .env python -m insider_bot.web"""

from __future__ import annotations

import logging
import sys

from aiohttp import web

from insider_bot.config import ConfigError, WebConfig, load_web_config
from insider_bot.game import GameManager
from insider_bot.judge import JevJudge, create_jev_client
from insider_bot.line.client import LineReplyClient
from insider_bot.line.webhook import CALLBACK_PATH, LineWebhook, add_line_routes
from insider_bot.service import GameService
from insider_bot.web.hub import RoomHub
from insider_bot.web.rooms import RoomRegistry
from insider_bot.web.server import create_app
from insider_bot.web.village_setup import build_village

log = logging.getLogger(__name__)


async def make_app(config: WebConfig) -> web.Application:
    client = create_jev_client(config.typesafe_api_key, config.jev_timeout_seconds)
    manager = GameManager()
    service = GameService(manager, JevJudge(client, config.correct_threshold, config.jev_timeout_seconds))
    registry = RoomRegistry(on_remove=lambda room: manager.end(room.room_id))
    village = build_village(config.public_base_url)
    app = create_app(RoomHub(registry, service, manager), village=village)
    if config.line is not None:
        # LINE も Web と同じ中核を使うので、LINE で作った村に Web から入れる
        sender = LineReplyClient(config.line.channel_token, config.line.api_base_url)
        webhook = LineWebhook(
            config.line.channel_secret, village.commands, village.service.illust, sender, config.public_base_url
        )
        add_line_routes(app, webhook)
        log.info("LINE の webhook を %s で受け付けます（返信先 %s）", CALLBACK_PATH, config.line.api_base_url)

        async def close_line(_app: web.Application) -> None:
            # 止める途中に実行中のハンドラーが始めた返信は、on_shutdown の待ちのあとに送りかける。閉じる前にもう一度待つ
            await webhook.drain()
            await sender.aclose()

        app.on_cleanup.append(close_line)

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
