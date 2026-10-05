#!/usr/bin/env bash
# 遊ぶときに Mac で起動する: bash scripts/play.sh（Ctrl+C ですべて止まる）
# Discord ボットと Web 版を起動し、Web 版を Tailscale Funnel で https://<マシン名>.<tailnet名>.ts.net として公開する。
# どれか 1 つが止まったら全部止める。動いている間は Mac をスリープさせない（ノートの蓋を閉じると止まる）。
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo ".env がありません。cp .env.example .env で作り、DISCORD_TOKEN と TYPESAFE_API_KEY を記入してください" >&2
  exit 1
fi

# 本番の VM が動いている間は起動しない。Discord ボットが 2 か所で動くと質問に 2 回返信するため。
# VM では Web とボットが一緒に動くので、本番の /healthz が ok なら本番のボットも動いていると見なす。
# 届かないときは起動を続ける（本番が止まっているときに Mac で遊べるように）
PRODUCTION_URL="$(sed -n 's/^PRODUCTION_URL=//p' .env | tail -n 1)"
PRODUCTION_URL="${PRODUCTION_URL%/}"
if [ -n "$PRODUCTION_URL" ] && [ "$(curl -fs --max-time 5 "$PRODUCTION_URL/healthz" 2>/dev/null || true)" = ok ]; then
  echo "本番の VM（${PRODUCTION_URL}）で動いているので起動しません。Discord ボットが 2 か所で動くと質問に 2 回返信します" >&2
  echo "遊ぶときは本番の ${PRODUCTION_URL} を使ってください。どうしても Mac で動かすなら、先に VM で sudo systemctl stop insider-bot insider-web を実行します（LINE も止まります）" >&2
  exit 1
fi

# Mac のアプリ版はアプリの中の本体を直接使う。PATH に入る tailscale は本体を exec せずに子として起動する
# スクリプトで、止めても本体が残って公開が終わらないため
TAILSCALE=/Applications/Tailscale.app/Contents/MacOS/Tailscale
if [ ! -x "$TAILSCALE" ]; then
  TAILSCALE="$(command -v tailscale || true)"
fi
if [ -z "$TAILSCALE" ]; then
  echo "Tailscale が見つかりません。https://tailscale.com/download/mac から入れて、ログインしてください" >&2
  exit 1
fi

# Web 版と同じく .env の WEB_PORT（既定 8080）を公開する
PORT="$(sed -n 's/^WEB_PORT=//p' .env | tail -n 1)"
PORT="${PORT:-8080}"
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ポート $PORT はすでに使われています。前に起動したものが残っていないか確かめてください" >&2
  exit 1
fi

# 前回の公開の設定が残っていると「listener already exists for port 443」で公開できない。
# tailscale serve・funnel が 1 つも動いていないのに残る前面の公開は古いので消す（--bg の常時公開があれば消さない）
if ! pgrep -qif 'tailscale (serve|funnel)' \
  && "$TAILSCALE" serve status --json 2>/dev/null \
    | jq -e '(.Foreground // {}) != {} and del(.Foreground) == {}' >/dev/null 2>&1; then
  echo "== 前回の公開の設定が残っていたので消します"
  "$TAILSCALE" serve reset
fi

bot_pid="" web_pid="" funnel_pid=""
stop_all() {
  trap - EXIT
  echo
  echo "== 停止"
  # uv run は TERM を子のプロセスに伝える。funnel は止まると公開も終わる
  for pid in $funnel_pid $web_pid $bot_pid; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  for pid in $funnel_pid $web_pid $bot_pid; do
    wait "$pid" 2>/dev/null || true
  done
}
trap stop_all EXIT
trap 'exit 130' INT TERM

caffeinate -is -w $$ &

echo "== Discord ボット"
uv run --env-file .env python -m insider_bot &
bot_pid=$!

echo "== Web 版"
uv run --env-file .env python -m insider_bot.web &
web_pid=$!

# 待ち受けが始まってから公開する（初回は依存のインストールで時間がかかる）
ready=""
for _ in $(seq 60); do
  if curl -fs -o /dev/null "http://127.0.0.1:$PORT/"; then
    ready=1
    break
  fi
  kill -0 "$web_pid" 2>/dev/null || break
  sleep 1
done
if [ -z "$ready" ]; then
  echo "Web 版が起動しませんでした。上のエラーを確かめてください" >&2
  exit 1
fi

echo "== 公開（表示される https://….ts.net を仲間に共有する）"
"$TAILSCALE" funnel "$PORT" &
funnel_pid=$!

while kill -0 "$bot_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null && kill -0 "$funnel_pid" 2>/dev/null; do
  sleep 1
done
echo "どれかが止まったので、すべて止めます" >&2
exit 1
