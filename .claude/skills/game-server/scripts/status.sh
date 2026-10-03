#!/usr/bin/env bash
# ゲームサーバー（scripts/play.sh）の状態を表示する: 動いているか、待ち受けポート、公開 URL、外から届くか
set -u

cd "$(dirname "$0")/../../../.."

TAILSCALE="$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)"
PORT="$(sed -n 's/^WEB_PORT=//p' .env 2>/dev/null | tail -n 1)"
PORT="${PORT:-8080}"

pid="$(pgrep -f 'scripts/play.sh' | head -n 1)"
if [ -n "$pid" ]; then
  echo "状態: 動作中（play.sh PID ${pid}）"
else
  echo "状態: 停止中"
fi

listener="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR == 2 { print $1 " (PID " $2 ")" }')"
echo "ポート ${PORT}: ${listener:-空き}"

host="$("$TAILSCALE" status --json --peers=false 2>/dev/null | sed -n 's/.*"DNSName": "\(.*\)\.",*$/\1/p' | head -n 1)"
if [ -z "$host" ]; then
  echo "公開 URL: 不明（Tailscale に未ログインか、入っていない）"
  exit 0
fi
echo "公開 URL: https://$host/"

# 自分の Mac からは MagicDNS で Tailscale の中を通ってしまうので、公開 DNS で引いた入口に向けて確かめる
if [ -n "$pid" ]; then
  ip="$(dig +short A "$host" @1.1.1.1 | tail -n 1)"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 --resolve "$host:443:$ip" "https://$host/")"
  echo "外からの応答: ${code}（200 なら遊べる。000 は初回の証明書の準備中のことがある）"
fi
