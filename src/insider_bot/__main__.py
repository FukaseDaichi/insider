"""起動: uv run --env-file .env python -m insider_bot"""

from __future__ import annotations

import asyncio
import sys

import discord
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

from insider_bot.bot import OdaiBot
from insider_bot.config import Config, ConfigError, load_config
from insider_bot.game import GameManager
from insider_bot.judge import JevJudge
from insider_bot.service import GameService


async def run(config: Config) -> None:
    client = AsyncTypeSafeClient(
        api_key=config.typesafe_api_key,
        retry=RetryPolicy(max_retries=1, timeout=config.jev_timeout_seconds),
    )
    try:
        judge = JevJudge(client, config.correct_threshold, config.jev_timeout_seconds)
        service = GameService(GameManager(), judge)
        bot = OdaiBot(service, config.guild_id)
        async with bot:
            await bot.start(config.discord_token)
    finally:
        await client.aclose()


def main() -> None:
    discord.utils.setup_logging()
    try:
        config = load_config()
    except ConfigError as error:
        print(f"設定エラー: {error}", file=sys.stderr)
        sys.exit(1)
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
