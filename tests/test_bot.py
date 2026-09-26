from types import SimpleNamespace

import discord

from insider_bot.bot import _respond, is_player_message
from insider_bot.service import Outcome


class FakeChannel:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[str] = []

    async def send(self, content: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(content)


class FakeFollowup:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bool]] = []

    async def send(self, content: str, *, ephemeral: bool = False) -> None:
        self.sent.append((content, ephemeral))


def make_interaction(channel):
    return SimpleNamespace(channel=channel, channel_id=1, followup=FakeFollowup())


def forbidden() -> discord.Forbidden:
    return discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")


# --- _respond ---


async def test_respond_posts_public_and_private():
    channel = FakeChannel()
    interaction = make_interaction(channel)
    await _respond(interaction, Outcome(private="登録しました", public="🎮 ゲーム開始！"))
    assert channel.sent == ["🎮 ゲーム開始！"]
    assert interaction.followup.sent == [("登録しました", True)]


async def test_respond_public_only_sends_done_privately():
    channel = FakeChannel()
    interaction = make_interaction(channel)
    await _respond(interaction, Outcome(public="🏳️ ギブアップ！"))
    assert interaction.followup.sent == [("完了しました", True)]


async def test_respond_falls_back_to_private_when_channel_post_fails():
    interaction = make_interaction(FakeChannel(error=forbidden()))
    await _respond(interaction, Outcome(public="🏳️ ギブアップ！お題は『りんご』でした（質問数: 3）"))
    [(content, ephemeral)] = interaction.followup.sent
    assert ephemeral
    assert "チャンネルに投稿できませんでした" in content
    assert "お題は『りんご』でした" in content


async def test_respond_keeps_private_text_when_channel_post_fails():
    interaction = make_interaction(FakeChannel(error=forbidden()))
    await _respond(interaction, Outcome(private="お題『りんご』を登録しました", public="🎮 ゲーム開始！"))
    [(content, _)] = interaction.followup.sent
    assert content.startswith("お題『りんご』を登録しました")
    assert "チャンネルに投稿できませんでした" in content


async def test_respond_without_channel_shows_public_privately():
    interaction = make_interaction(None)
    await _respond(interaction, Outcome(public="🏳️ ギブアップ！"))
    [(content, _)] = interaction.followup.sent
    assert "🏳️ ギブアップ！" in content


# --- is_player_message ---


def message(bot: bool = False, type: discord.MessageType = discord.MessageType.default):
    return SimpleNamespace(author=SimpleNamespace(bot=bot), type=type)


def test_normal_and_reply_messages_are_player_messages():
    assert is_player_message(message())
    assert is_player_message(message(type=discord.MessageType.reply))


def test_bot_messages_are_not_player_messages():
    assert not is_player_message(message(bot=True))


def test_system_messages_are_not_player_messages():
    assert not is_player_message(message(type=discord.MessageType.thread_created))
    assert not is_player_message(message(type=discord.MessageType.pins_add))
