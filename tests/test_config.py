import pytest

from insider_bot.config import Config, ConfigError, load_config

REQUIRED = {"DISCORD_TOKEN": "discord-token", "TYPESAFE_API_KEY": "ts-key"}


def test_defaults():
    assert load_config(REQUIRED) == Config(
        discord_token="discord-token",
        typesafe_api_key="ts-key",
        guild_id=None,
        correct_threshold=0.8,
        jev_timeout_seconds=10.0,
    )


def test_optional_values():
    config = load_config(
        REQUIRED | {"DISCORD_GUILD_ID": "123", "CORRECT_THRESHOLD": "0.9", "JEV_TIMEOUT_SECONDS": "5"}
    )
    assert (config.guild_id, config.correct_threshold, config.jev_timeout_seconds) == (123, 0.9, 5.0)


def test_blank_optional_values_use_defaults():
    config = load_config(REQUIRED | {"DISCORD_GUILD_ID": "", "CORRECT_THRESHOLD": " "})
    assert (config.guild_id, config.correct_threshold) == (None, 0.8)


def test_missing_required_lists_all_names():
    with pytest.raises(ConfigError) as error:
        load_config({"DISCORD_TOKEN": " "})
    assert "DISCORD_TOKEN" in str(error.value)
    assert "TYPESAFE_API_KEY" in str(error.value)


@pytest.mark.parametrize(
    "extra",
    [
        {"DISCORD_GUILD_ID": "abc"},
        {"CORRECT_THRESHOLD": "high"},
        {"CORRECT_THRESHOLD": "1.5"},
        {"JEV_TIMEOUT_SECONDS": "0"},
    ],
)
def test_invalid_values(extra):
    with pytest.raises(ConfigError):
        load_config(REQUIRED | extra)
