import pytest

from insider_bot.config import ConfigError, WebConfig, load_web_config


def test_web_needs_only_typesafe_key():
    assert load_web_config({"TYPESAFE_API_KEY": "ts-key"}) == WebConfig(
        typesafe_api_key="ts-key",
        correct_threshold=0.8,
        jev_timeout_seconds=10.0,
        host="127.0.0.1",
        port=8080,
    )


def test_web_optional_values():
    config = load_web_config(
        {
            "TYPESAFE_API_KEY": "ts-key",
            "WEB_HOST": "0.0.0.0",
            "WEB_PORT": "9000",
            "CORRECT_THRESHOLD": "0.9",
            "JEV_TIMEOUT_SECONDS": "5",
        }
    )
    assert (config.host, config.port, config.correct_threshold, config.jev_timeout_seconds) == (
        "0.0.0.0",
        9000,
        0.9,
        5.0,
    )


def test_web_blank_optional_values_use_defaults():
    config = load_web_config({"TYPESAFE_API_KEY": "ts-key", "WEB_HOST": " ", "WEB_PORT": ""})
    assert (config.host, config.port) == ("127.0.0.1", 8080)


def test_web_missing_key():
    with pytest.raises(ConfigError) as error:
        load_web_config({"DISCORD_TOKEN": "discord-token"})
    assert "TYPESAFE_API_KEY" in str(error.value)
    assert "DISCORD_TOKEN" not in str(error.value)


@pytest.mark.parametrize(
    "extra",
    [
        {"WEB_PORT": "abc"},
        {"WEB_PORT": "0"},
        {"WEB_PORT": "70000"},
        {"CORRECT_THRESHOLD": "2"},
        {"JEV_TIMEOUT_SECONDS": "0"},
    ],
)
def test_web_invalid_values(extra):
    with pytest.raises(ConfigError):
        load_web_config({"TYPESAFE_API_KEY": "ts-key"} | extra)
