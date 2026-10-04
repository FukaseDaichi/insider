#!/usr/bin/env bash
# 使い方: insider-release.sh <commit-sha>
#
# /opt/insider/incoming/<commit-sha>/ に転送された insider.tar.gz を検証し、
# /opt/insider/releases/<commit-sha>/ へ展開して uv sync し、current へ昇格して
# insider-web と insider-bot を再起動し、ヘルスチェックが通るまで待つ。
# 通らなければ直前の世代へ戻す (戻せても終了コードは 1。push した commit は動いていないため)。
# 戻し先がない、または戻しても通らなければ、自分の確認が通らないユニットだけを止める (壊れた状態で Restart=always が
# 空回りするのを止める)。通るほうは動かしたままにする (Discord の障害で bot だけが落ちても Web と LINE を止めない)。
#
# root で呼ばれるが、ファイルの操作 (検証・展開・uv sync・削除・リンク) はすべて insider ユーザーとして行い、
# root がするのは systemctl だけ。insider が書ける tar を root で展開しない (権限の境界を保つ)。
# 展開と uv sync は releases/.staging-<sha>/ で済ませてから releases/<sha>/ へ mv する。uv sync の失敗で
# current を壊さないため。稼働中の世代と同じ SHA が届いたら、展開も昇格もせずに健康を確かめる。健康なら何もせず成功、
# そうでなければその世代のまま再起動して確かめる (稼働中の世代のファイルと previous は触らない)。
# プロジェクトは --no-editable で入れる。編集可能インストールは .pth に展開中の絶対パスを書くので、mv の後に import できなくなる。
# ssh が途中で切れても (GitHub Actions の runner が消えても) VM 上で完走する。HUP と PIPE を無視し、log の書き込みの失敗も無視する。
# 昇格した後に死ぬと、壊れた世代が Restart=always で動いたまま、戻しも停止もされない。
# 同時に 2 本走らないように flock で排他する。ロックは root 所有のこのスクリプト自身を読み取りで開いて取る。
# insider が書ける /opt/insider の中に root がファイルを作ると、insider がシンボリックリンクを置いて root に任意のファイルを切り詰めさせられる。
# 本番は Linux。sha256sum が無ければ shasum に切り替え、flock が無ければ (Mac) 排他なしで動く (テスト用)。
set -euo pipefail

# ssh が切れたときの SIGHUP と、閉じた出力へ書いたときの SIGPIPE で死なない (無視は子プロセスにも引き継がれる)
trap '' HUP PIPE

HOME_DIR="${INSIDER_HOME:-/opt/insider}"
APP_USER="${INSIDER_APP_USER:-insider}"
UV="${INSIDER_UV:-$HOME_DIR/.local/bin/uv}"
HEALTH_URL="${INSIDER_HEALTH_URL:-http://127.0.0.1:8080/healthz}"
HEALTH_TIMEOUT="${INSIDER_HEALTH_TIMEOUT:-60}"  # 秒。restart からこの時間まで待つ
HEALTH_INTERVAL="${INSIDER_HEALTH_INTERVAL:-2}" # 秒。確認の間隔
BOT_SETTLE="${INSIDER_BOT_SETTLE:-10}"          # 秒。Web が上がった後、bot が落ちずにいることを見る時間
KEEP_RELEASES="${INSIDER_KEEP_RELEASES:-5}"
WEB_SERVICE=insider-web
BOT_SERVICE=insider-bot
ARCHIVE=insider.tar.gz

INCOMING="$HOME_DIR/incoming"
RELEASES="$HOME_DIR/releases"
CURRENT="$HOME_DIR/current"
PREVIOUS="$HOME_DIR/previous"

# 出力先 (ssh) が閉じていると echo の書き込みが失敗する。set -e で死なないように握りつぶす
log() { echo "[release] $*" 2>/dev/null || true; }

sha="${1:?usage: $0 <commit-sha>}"
# sudoers は引数を制限できないので、受け取る形をここで固定する。GITHUB_SHA は常に 40 桁の小文字 hex。
# 確かめずに使うと ../../../etc のような引数で incoming_dir が任意のディレクトリを指し、rm -rf がそこへ効く
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { log "invalid revision: $sha"; exit 2; }

incoming_dir="$INCOMING/$sha"
release_dir="$RELEASES/$sha"
staging_dir="$RELEASES/.staging-$sha"

if command -v sha256sum >/dev/null 2>&1; then
  CHECKSUM=(sha256sum -c --quiet)
else
  CHECKSUM=(shasum -a 256 -c --quiet)
fi

# アプリのユーザーとして実行する。root で呼ばれたら sudo -u、本人なら直接 (テスト)
run_as_app() {
  if [[ "$(id -un)" == "$APP_USER" ]]; then
    "$@"
  else
    sudo -u "$APP_USER" -H "$@"
  fi
}

# 直前の確認で見た値。どの確認で落ちたかをログに出すのに使う (log_health)
web_status='' web_rc='' web_body='' bot_state='' bot_nrestarts=''

# 契約: Web は HTTP 200 かつ本文が ok (本文だけでなく HTTP ステータスと curl の成否も見る)
check_web() {
  local body_file
  body_file="$(mktemp)"
  web_status="$(curl -s --max-time 2 -o "$body_file" -w '%{http_code}' "$HEALTH_URL")" && web_rc=0 || web_rc=$?
  if [[ "$(cat "$body_file")" == ok ]]; then web_body=ok; else web_body=not-ok; fi
  rm -f "$body_file"
  (( web_rc == 0 )) && [[ "$web_status" == 200 && "$web_body" == ok ]]
}

# 契約: bot は active で、この restart の後に一度も自動再起動していない (NRestarts は restart_and_check で 0 に戻す)。
# is-active だけだと、落ちて RestartSec 後に上がり直した瞬間を健康と見てしまう
check_bot() {
  local rc
  bot_state="$(systemctl is-active "$BOT_SERVICE")" && rc=0 || rc=$?
  bot_nrestarts="$(systemctl show -p NRestarts --value "$BOT_SERVICE")" || bot_nrestarts='?'
  (( rc == 0 )) && [[ "$bot_nrestarts" == 0 ]]
}

# 片方が通らなくても両方を見る (どちらで落ちたかをログに出すため)
check_health() {
  local rc=0
  check_web || rc=1
  check_bot || rc=1
  return "$rc"
}

# 直前の check_health で見た値を 1 行で残す。job のログだけで、どの確認で落ちたかがわかるように (秘密は含まない)
log_health() {
  log "$1: web http=$web_status curl=$web_rc body=$web_body; bot $bot_state NRestarts=$bot_nrestarts"
}

# restart から HEALTH_TIMEOUT 秒以内に check_health が通るまで、HEALTH_INTERVAL 秒間隔で待つ
healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT))
  while :; do
    if check_health; then
      return 0
    fi
    if (( SECONDS >= deadline )); then
      return 1
    fi
    sleep "$HEALTH_INTERVAL"
  done
}

# restart の直前に reset-failed する。落ちて自動再起動を待っている間 (auto-restart) に来た restart は NRestarts を
# 0 に戻さない (systemd 255 で実測)。そのままだと、落ち続ける bot の世代から戻したとき、正常な直前の世代の bot まで
# 自動再起動したように見えて戻しが失敗する。reset-failed は待ちの最中でも 0 に戻す。
# systemctl restart 自体の失敗も、ヘルスチェック失敗と同じに扱う。
# 通った後も BOT_SETTLE 秒待ってもう一度見る (Discord のログイン失敗は起動の数秒後に落ちるため)
restart_and_check() {
  local service
  for service in "$WEB_SERVICE" "$BOT_SERVICE"; do
    systemctl reset-failed "$service" || true
    if ! systemctl restart "$service"; then
      log "systemctl restart $service failed"
      return 1
    fi
  done
  if ! healthy; then
    log_health "not healthy within ${HEALTH_TIMEOUT}s"
    return 1
  fi
  sleep "$BOT_SETTLE"
  if ! check_health; then
    log_health "not healthy ${BOT_SETTLE}s after passing"
    return 1
  fi
}

# 最後の失敗 (戻し先がない・戻しても通らない・同じ世代の再起動が通らない) で、自分の確認が通らないユニットだけを止める
# (壊れた状態で Restart=always が空回りするのを止める)。通るほうは動かしたままにする。2 プロセスに分けたのは
# 片方の不具合をもう片方に及ぼさないためで、Discord の障害やトークンの失効で bot だけが落ちているときに Web と LINE まで止めない
stop_failing_units() {
  local stopped=() kept=()
  if check_web; then
    kept+=("$WEB_SERVICE")
  else
    systemctl stop "$WEB_SERVICE" || true
    stopped+=("$WEB_SERVICE")
  fi
  if check_bot; then
    kept+=("$BOT_SERVICE")
  else
    systemctl stop "$BOT_SERVICE" || true
    stopped+=("$BOT_SERVICE")
  fi
  log "no healthy release; stopped: ${stopped[*]:-none}; kept running: ${kept[*]:-none}"
}

# link <世代の絶対パス> <リンク先> : 一時名で作って rename(2) するので、リンクの差し替えは原子的。
# mv は差し替え先がディレクトリへのシンボリックリンクだとその中へ移してしまう (GNU mv の -T は macOS にない) ので、
# python3 (Ubuntu にも Mac にも入っている) で rename を直接呼ぶ
link() {
  run_as_app ln -sfn "$1" "$2.tmp"
  run_as_app python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$2.tmp" "$2"
}

# 直近 KEEP_RELEASES 世代を残して古い世代を削る。current / previous が指す世代は世代数に関わらず残す。
# このスクリプトが作る世代は必ず 40 桁 hex なので、先にそれだけを選んでから新しい順に数える
# (それ以外のエントリを数に入れると、有効な世代が余計に消える)
prune() {
  local keep=() old dir k
  [[ -L "$CURRENT" ]] && keep+=("$(readlink "$CURRENT")")
  [[ -L "$PREVIOUS" ]] && keep+=("$(readlink "$PREVIOUS")")
  { ls -1t "$RELEASES" | grep -E '^[0-9a-f]{40}$' || true; } | tail -n "+$((KEEP_RELEASES + 1))" | while read -r old; do
    dir="$RELEASES/$old"
    for k in "${keep[@]}"; do
      [[ "$k" == "$dir" ]] && continue 2
    done
    log "prune $dir"
    run_as_app rm -rf "$dir"
  done
}

# root 所有のこのスクリプト自身を読み取りで開いてロックする (flock は読み取り専用の fd にも掛かる)。
# ロック用のファイルを /opt/insider の中に作らない: そこは insider が書けるので、シンボリックリンクで root に任意のファイルを切り詰めさせられる
exec 9<"$0"
if command -v flock >/dev/null 2>&1; then
  flock 9
fi

log "verify $sha"
if ! (cd "$incoming_dir" && run_as_app "${CHECKSUM[@]}" "$ARCHIVE.sha256"); then
  log "checksum verification failed for $sha"
  run_as_app rm -rf "$incoming_dir"
  prune
  exit 1
fi

# 稼働中の世代と同じ commit (同じ commit の workflow を re-run したとき)。稼働中の世代は触らない。
# ただし current が指していても動いているとは限らない (前の配備が停止で終わった後がそう。env を直して re-run する)。
# 健康なら何もせず成功。そうでなければ同じ世代を再起動して確かめ、それでも通らなければ通らないユニットだけを止めて失敗する
if [[ -L "$CURRENT" && -e "$CURRENT" && "$(readlink "$CURRENT")" == "$release_dir" ]]; then
  run_as_app rm -rf "$incoming_dir"
  if check_health; then
    log "already running $sha; nothing to do"
    prune
    exit 0
  fi
  log "$sha is current but not healthy; restarting"
  if restart_and_check; then
    log "healthy: $sha"
    prune
    exit 0
  fi
  log "health check failed for $sha"
  stop_failing_units
  prune
  exit 1
fi

# 展開と依存の取得は .staging-<sha> で済ませる。失敗しても current は変わらない
log "extract $sha"
run_as_app rm -rf "$staging_dir"
run_as_app mkdir -p "$staging_dir"
run_as_app tar -xzf "$incoming_dir/$ARCHIVE" -C "$staging_dir"
run_as_app cp "$incoming_dir/$ARCHIVE.sha256" "$staging_dir/"
run_as_app rm -rf "$incoming_dir"

log "uv sync $sha"
if ! (cd "$staging_dir" && run_as_app "$UV" sync --locked --no-dev --no-editable); then
  log "uv sync failed for $sha"
  run_as_app rm -rf "$staging_dir"
  prune
  exit 1
fi

# release_dir が残っていれば、前に失敗した配備か previous の世代。current ではない (上で確かめた)
run_as_app rm -rf "$release_dir"
run_as_app mv "$staging_dir" "$release_dir"

# 移動した後の場所で、起動する 2 つのエントリ (python -m insider_bot と python -m insider_bot.web) が import できることを見る。
# 編集可能インストールの .pth の問題や、wheel に入らなかったサブパッケージを、再起動の前に捕まえる。
# どちらの __main__ も main() は if __name__ == "__main__" の中なので、import しても起動はしない
if ! run_as_app "$release_dir/.venv/bin/python" -c 'import insider_bot.__main__, insider_bot.web.__main__'; then
  log "import check failed for $sha"
  run_as_app rm -rf "$release_dir"
  prune
  exit 1
fi

# current のリンク先が実在しないときは previous を動かさない。壊れた current を previous へ昇格させると、
# 次に配備が失敗したときの戻し先が壊れた世代になり、戻せたはずの旧版を失う
if [[ -L "$CURRENT" && -e "$CURRENT" ]]; then
  link "$(readlink "$CURRENT")" "$PREVIOUS"
fi
link "$release_dir" "$CURRENT"
log "restart $WEB_SERVICE and $BOT_SERVICE with $sha"

if restart_and_check; then
  log "healthy: $sha"
  prune
  exit 0
fi

log "health check failed for $sha"
if [[ -L "$PREVIOUS" ]]; then
  previous_dir="$(readlink "$PREVIOUS")"
  log "rolling back to $previous_dir"
  link "$previous_dir" "$CURRENT"
  if restart_and_check; then
    log "rolled back; production is running $previous_dir"
    prune
    exit 1 # 戻せても job は失敗にする (push した commit は動いていない)
  fi
  log "rollback did not become healthy either"
fi

stop_failing_units
prune
exit 1
