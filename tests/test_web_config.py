import pytest

from insider_bot.config import ConfigError, LineConfig, WebConfig, load_web_config


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


def test_web_village_urls_are_unset_by_default():
    config = load_web_config({"TYPESAFE_API_KEY": "ts-key"})
    assert config.public_base_url == ""


def test_web_village_urls():
    config = load_web_config(
        {
            "TYPESAFE_API_KEY": "ts-key",
            "PUBLIC_BASE_URL": "https://game.example.com/",
        }
    )
    assert config.public_base_url == "https://game.example.com"


@pytest.mark.parametrize(
    "value",
    ["game.example.com", "ftp://game.example.com", "https://", "https://game.example.com/sub", "https://game.example.com/?x=1"],
)
def test_web_public_base_url_must_be_an_origin(value):
    with pytest.raises(ConfigError, match="PUBLIC_BASE_URL"):
        load_web_config({"TYPESAFE_API_KEY": "ts-key", "PUBLIC_BASE_URL": value})


@pytest.mark.parametrize("value", ["https://script.google.com/macros/s/x/exec", "http://old.example.com", "obsolete"])
def test_obsolete_catalog_settings_are_ignored(value):
    assert load_web_config({"TYPESAFE_API_KEY": "ts-key", "ILLUSTRATION_CATALOG_URL": value}) == load_web_config(
        {"TYPESAFE_API_KEY": "ts-key"}
    )


LINE_ENV = {
    "TYPESAFE_API_KEY": "ts-key",
    "PUBLIC_BASE_URL": "https://game.example.com",
    "LINE_CHANNEL_SECRET": "secret",
    "LINE_CHANNEL_TOKEN": "token",
}


def test_line_is_off_unless_configured():
    assert load_web_config({"TYPESAFE_API_KEY": "ts-key"}).line is None


def test_line_settings():
    assert load_web_config(LINE_ENV).line == LineConfig("secret", "token", "https://api.line.me")
    stub = load_web_config({**LINE_ENV, "LINE_API_BASE_URL": "http://127.0.0.1:18080/"})
    assert stub.line.api_base_url == "http://127.0.0.1:18080"


@pytest.mark.parametrize("missing", ["LINE_CHANNEL_SECRET", "LINE_CHANNEL_TOKEN"])
def test_line_needs_both_the_secret_and_the_token(missing):
    with pytest.raises(ConfigError, match="LINE_CHANNEL_SECRET と LINE_CHANNEL_TOKEN"):
        load_web_config({name: value for name, value in LINE_ENV.items() if name != missing})


@pytest.mark.parametrize("public", ["", "http://game.example.com"])
def test_line_needs_an_https_public_base_url(public):
    with pytest.raises(ConfigError, match="PUBLIC_BASE_URL"):
        load_web_config({**LINE_ENV, "PUBLIC_BASE_URL": public})


@pytest.mark.parametrize("value", ["127.0.0.1:18080", "ftp://127.0.0.1", "http://127.0.0.1:18080/?x=1"])
def test_line_api_base_url_must_be_an_http_url(value):
    with pytest.raises(ConfigError, match="LINE_API_BASE_URL"):
        load_web_config({**LINE_ENV, "LINE_API_BASE_URL": value})


@pytest.mark.parametrize("name", ["PUBLIC_BASE_URL", "LINE_API_BASE_URL"])
def test_unreadable_urls_are_config_errors_naming_the_variable(name):
    # urlsplit は「https://[x」で ValueError を投げる。起動時にトレースバックではなく設定エラーとして伝える
    with pytest.raises(ConfigError, match=name):
        load_web_config({**LINE_ENV, name: "https://[x"})
