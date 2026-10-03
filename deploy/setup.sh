#!/usr/bin/env bash
# サーバー（Ubuntu 24.04）の初期設定。clone したリポジトリで通常ユーザーとして実行する: bash deploy/setup.sh
# 何度実行してもよい。.env が未記入ならひな形を作って止まるので、記入してからもう一度実行する。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$(id -un)"
UV="$HOME/.local/bin/uv"
# Discord ボットと Web 版。どちらも同じ .env を読む
SERVICES=(insider-bot insider-web)

if [ "$(id -u)" -eq 0 ]; then
  echo "root ではなく通常ユーザーで実行してください（必要な箇所は中で sudo します）" >&2
  exit 1
fi

echo "== スワップ（1GB）"
# e2-micro はメモリが 1GB しかないため
if [ ! -f /swapfile ]; then
  sudo fallocate -l 1G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
fi
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
  sudo swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null

echo "== uv"
if [ ! -x "$UV" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "== 依存パッケージ"
(cd "$APP_DIR" && "$UV" sync --frozen --no-dev)

echo "== systemd"
for service in "${SERVICES[@]}"; do
  sed -e "s|__USER__|$APP_USER|g" -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__UV__|$UV|g" \
    "$APP_DIR/deploy/$service.service" | sudo tee "/etc/systemd/system/$service.service" >/dev/null
done
sudo systemctl daemon-reload

echo "== .env"
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "$APP_DIR/.env.example" "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"
if ! grep -Eq '^DISCORD_TOKEN=[^[:space:]]' "$ENV_FILE" || ! grep -Eq '^TYPESAFE_API_KEY=[^[:space:]]' "$ENV_FILE"; then
  echo
  echo "DISCORD_TOKEN と TYPESAFE_API_KEY を記入してから、もう一度実行してください:"
  echo "  nano $ENV_FILE"
  echo "  bash $APP_DIR/deploy/setup.sh"
  exit 0
fi

echo "== 起動"
sudo systemctl enable "${SERVICES[@]}"
sudo systemctl restart "${SERVICES[@]}"
sleep 5
sudo systemctl status "${SERVICES[@]}" --no-pager || true
echo
echo "ログを見る: journalctl -u insider-bot -f ／ journalctl -u insider-web -f"
