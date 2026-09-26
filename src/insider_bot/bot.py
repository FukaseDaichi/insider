"""discord.py アダプター。判断はすべて GameService に任せ、ここは送受信だけを行う。"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.utils import escape_markdown

from insider_bot.service import GameService, Outcome

log = logging.getLogger(__name__)


def _name(user: discord.abc.User) -> str:
    return escape_markdown(user.display_name)


async def _respond(interaction: discord.Interaction, outcome: Outcome) -> None:
    """defer 済みのスラッシュコマンドに結果を返す。公開通知はチャンネルへ別途投稿する。"""
    if outcome.public and interaction.channel is not None:
        await interaction.channel.send(outcome.public)
    await interaction.followup.send(outcome.private or "完了しました", ephemeral=True)


def build_odai_group(service: GameService) -> app_commands.Group:
    group = app_commands.Group(name="odai", description="お題当てゲーム", guild_only=True)

    @group.command(name="set", description="お題を登録してゲームを開始します（お題は自分にしか見えません）")
    @app_commands.rename(topic="お題", hint="補足")
    @app_commands.describe(topic="当ててもらうお題（50文字まで）", hint="お題の補足説明（任意・300文字まで）")
    async def set_topic(
        interaction: discord.Interaction,
        topic: app_commands.Range[str, 1, 50],
        hint: Optional[app_commands.Range[str, 1, 300]] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        outcome = await service.start(
            interaction.channel_id, interaction.user.id, _name(interaction.user), topic, hint or ""
        )
        await _respond(interaction, outcome)

    @group.command(name="status", description="進行中のゲームの状況を表示します")
    async def status(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _respond(interaction, await service.status(interaction.channel_id))

    @group.command(name="giveup", description="お題を公開してゲームを終了します")
    async def giveup(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _respond(interaction, await service.giveup(interaction.channel_id))

    return group


class OdaiBot(discord.Client):
    def __init__(self, service: GameService, guild_id: int | None) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        # 質問文を引用して返すので、@everyone 等で誰にも通知が飛ばないようにする
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.service = service
        self.guild_id = guild_id
        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(build_odai_group(service))

    async def setup_hook(self) -> None:
        if self.guild_id is not None:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("スラッシュコマンドをサーバー %s に同期しました（%d 件）", self.guild_id, len(synced))
        else:
            synced = await self.tree.sync()
            log.info("スラッシュコマンドをグローバル同期しました（%d 件、反映まで時間がかかる場合があります）", len(synced))

    async def on_ready(self) -> None:
        log.info("ログインしました: %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        outcome = await self.service.handle_question(
            message.channel.id, message.author.id, _name(message.author), message.content
        )
        if outcome.public is None:
            return
        try:
            await message.channel.send(
                outcome.public, reference=message.to_reference(fail_if_not_exists=False)
            )
        except discord.HTTPException:
            # 判定・質問数・終了処理はやり直さない
            log.exception("返信の送信に失敗しました（channel=%s）", message.channel.id)
