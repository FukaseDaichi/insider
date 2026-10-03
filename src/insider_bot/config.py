"""環境変数から設定を読み込む。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigError(Exception):
    """設定が不足・不正。"""


@dataclass(frozen=True)
class Config:
    discord_token: str
    typesafe_api_key: str
    guild_id: int | None
    correct_threshold: float
    jev_timeout_seconds: float


@dataclass(frozen=True)
class WebConfig:
    typesafe_api_key: str
    correct_threshold: float
    jev_timeout_seconds: float
    host: str
    port: int
    # 役職画像と特殊村フォームの URL を組み立てる公開 URL（末尾の / なし）。空ならサイト内の絶対パス
    public_base_url: str = ""
    # 役職画像の外部カタログ（Google Apps Script のデプロイ URL）。None なら取りに行かない
    illustration_catalog_url: str | None = None


def _get(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _get(env, name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} は数値で指定してください（現在: {raw!r}）") from None


def _require(env: Mapping[str, str], names: tuple[str, ...]) -> None:
    missing = [name for name in names if not _get(env, name)]
    if missing:
        raise ConfigError(f"必須の環境変数が未設定です: {', '.join(missing)}（.env を確認してください）")


def _judge_settings(env: Mapping[str, str]) -> tuple[float, float]:
    """Discord 版と Web 版で共通の、正解のしきい値と Jev のタイムアウト。"""
    threshold = _float(env, "CORRECT_THRESHOLD", 0.8)
    if not 0.0 <= threshold <= 1.0:
        raise ConfigError(f"CORRECT_THRESHOLD は 0〜1 で指定してください（現在: {threshold}）")

    timeout = _float(env, "JEV_TIMEOUT_SECONDS", 10.0)
    if timeout <= 0:
        raise ConfigError(f"JEV_TIMEOUT_SECONDS は 0 より大きい値にしてください（現在: {timeout}）")
    return threshold, timeout


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    _require(env, ("DISCORD_TOKEN", "TYPESAFE_API_KEY"))

    guild_raw = _get(env, "DISCORD_GUILD_ID")
    try:
        guild_id = int(guild_raw) if guild_raw else None
    except ValueError:
        raise ConfigError(f"DISCORD_GUILD_ID は数字で指定してください（現在: {guild_raw!r}）") from None

    threshold, timeout = _judge_settings(env)
    return Config(
        discord_token=_get(env, "DISCORD_TOKEN"),
        typesafe_api_key=_get(env, "TYPESAFE_API_KEY"),
        guild_id=guild_id,
        correct_threshold=threshold,
        jev_timeout_seconds=timeout,
    )


def _public_base_url(env: Mapping[str, str]) -> str:
    raw = _get(env, "PUBLIC_BASE_URL")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    # 画面と画像はサイトの根から配るので、パスやクエリを持つ URL は受け付けない
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ConfigError(f"PUBLIC_BASE_URL は https://example.com のようにパスなしの URL で指定してください（現在: {raw!r}）")
    return raw.rstrip("/")


def _catalog_url(env: Mapping[str, str]) -> str | None:
    raw = _get(env, "ILLUSTRATION_CATALOG_URL")
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(f"ILLUSTRATION_CATALOG_URL は https:// で始まる URL で指定してください（現在: {raw!r}）")
    return raw


def load_web_config(env: Mapping[str, str] | None = None) -> WebConfig:
    env = os.environ if env is None else env
    _require(env, ("TYPESAFE_API_KEY",))
    threshold, timeout = _judge_settings(env)

    port_raw = _get(env, "WEB_PORT")
    try:
        port = int(port_raw) if port_raw else 8080
    except ValueError:
        raise ConfigError(f"WEB_PORT は数字で指定してください（現在: {port_raw!r}）") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"WEB_PORT は 1〜65535 で指定してください（現在: {port}）")

    return WebConfig(
        typesafe_api_key=_get(env, "TYPESAFE_API_KEY"),
        correct_threshold=threshold,
        jev_timeout_seconds=timeout,
        host=_get(env, "WEB_HOST") or "127.0.0.1",
        port=port,
        public_base_url=_public_base_url(env),
        illustration_catalog_url=_catalog_url(env),
    )
