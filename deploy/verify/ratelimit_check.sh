#!/usr/bin/env bash
# 使い方: ratelimit_check.sh <base-url> <path> [回数]
#   例: bash deploy/verify/ratelimit_check.sh https://insider.example.com /api/village/special 40   # 作成系の枠 30 回/分
#       bash deploy/verify/ratelimit_check.sh https://insider.example.com /api/village/mine 310     # 全体の枠 300 回/分
# 指定回数だけ POST し（10 本並列）、HTTP ステータスごとの件数と所要時間を出す。本文は {} なので aiohttp は 400 を
# 返し、Caddy の枠を超えた分が 429 になる。所要時間が 60 秒を超えるとウィンドウをまたいで 429 が減るので、計測は無効。
# caddy-ratelimit はスライディングウィンドウなので、直前の操作の残りで数件ずれる。
set -euo pipefail

base="${1:?base-url}"
path="${2:?path (例 /api/village/special)}"
count="${3:-40}"

start=$SECONDS
seq "$count" | xargs -P 10 -I@ curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Content-Type: application/json' --data '{}' "$base$path" | sort | uniq -c
echo "elapsed: $((SECONDS - start))s（60 秒を超えていたら計り直す）"
