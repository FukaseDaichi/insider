#!/usr/bin/env bash
# deploy/insider-release.sh の振る舞いを、systemctl・curl・uv を偽物に差し替えて確かめる。
# 本番は Linux (flock / sha256sum)。CI の build job で必ず走らせる。Mac では shasum に切り替わり、排他なしで動く。
#
# tar の中の BEHAVIOR ファイルが「振る舞い」を表す:
#   GOOD     起動して 200 ok を返し、bot も active
#   BROKEN   起動しない (curl が失敗する)
#   HALFUP   本文は ok だが HTTP 503 (ステータスを見ていないと健康と誤判定する)
#   NOSTART  systemctl restart 自体が失敗する
#   FLAKY    本文も HTTP 200 も正常だが curl 自体が失敗する (終了コードを見ていないと健康と誤判定する)
#   NOSYNC   uv sync が失敗する (current を変えずに終わる)
#   NOIMPORT 展開後の python が import に失敗する (current を変えずに終わる)
#   BOTDOWN  Web は 200 ok だが insider-bot が自動再起動している (NRestarts が 0 でない)
set -euo pipefail

script="$(cd "$(dirname "$0")/.." && pwd)/insider-release.sh"
failures=0

if command -v sha256sum >/dev/null 2>&1; then
  sha256() { sha256sum "$@"; }
else
  sha256() { shasum -a 256 "$@"; }
fi

fake_bin="$(mktemp -d)"
cat > "$fake_bin/systemctl" <<'FAKE'
#!/usr/bin/env bash
behavior="$(cat "$INSIDER_HOME/current/BEHAVIOR" 2>/dev/null || true)"
case "$1" in
  restart|stop)
    echo "$1 $2" >> "$INSIDER_HOME/systemctl.log"
    [[ "$1" == restart && "$behavior" == NOSTART ]] && exit 1
    exit 0 ;;
  is-active)
    exit 0 ;;
  show)
    # show -p NRestarts --value <unit>
    [[ "$behavior" == BOTDOWN ]] && echo 1 || echo 0
    exit 0 ;;
esac
FAKE
cat > "$fake_bin/curl" <<'FAKE'
#!/usr/bin/env bash
# 本物と同じく -o <file> に本文を書き、-w の代わりに HTTP ステータスを標準出力へ出す
out=/dev/null
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) shift 2 ;;
    *) shift ;;
  esac
done
behavior="$(cat "$INSIDER_HOME/current/BEHAVIOR" 2>/dev/null || true)"
case "$behavior" in
  GOOD|BOTDOWN) printf ok > "$out"; printf 200; exit 0 ;;
  HALFUP)       printf ok > "$out"; printf 503; exit 0 ;;
  FLAKY)        printf ok > "$out"; printf 200; exit 7 ;;
  *)            exit 7 ;;
esac
FAKE
cat > "$fake_bin/uv" <<'FAKE'
#!/usr/bin/env bash
# 更新スクリプトは展開先に cd してから uv sync を呼ぶ。そこに .venv を作る。
# .venv/bin/python は偽物で、BEHAVIOR が NOIMPORT のときだけ import に失敗したことにする
echo "$PWD" >> "$INSIDER_HOME/uv.log"
echo "$*" >> "$INSIDER_HOME/uv-args.log"
[[ "$(cat BEHAVIOR 2>/dev/null)" == NOSYNC ]] && exit 1
mkdir -p .venv/bin
cat > .venv/bin/python <<'PY'
#!/usr/bin/env bash
[[ "$(cat "$(dirname "$0")/../../BEHAVIOR" 2>/dev/null)" == NOIMPORT ]] && exit 1
exit 0
PY
chmod +x .venv/bin/python
FAKE
chmod +x "$fake_bin/systemctl" "$fake_bin/curl" "$fake_bin/uv"
export PATH="$fake_bin:$PATH"
export INSIDER_UV="$fake_bin/uv"
export INSIDER_HEALTH_TIMEOUT=0 INSIDER_HEALTH_INTERVAL=0 INSIDER_BOT_SETTLE=0
# sudo を使わずに自分自身として動かす
INSIDER_APP_USER="$(id -un)"
export INSIDER_APP_USER

fresh_home() {
  INSIDER_HOME="$(mktemp -d)"
  export INSIDER_HOME
  mkdir -p "$INSIDER_HOME/releases" "$INSIDER_HOME/incoming"
}

# add_release <sha> <振る舞い> : CI が転送した状態 (incoming/<sha>/ に tar と正しい sha256) を作る
add_release() {
  local dir="$INSIDER_HOME/incoming/$1" src
  src="$(mktemp -d)"
  printf '%s' "$2" > "$src/BEHAVIOR"
  mkdir -p "$src/src" && : > "$src/pyproject.toml"
  mkdir -p "$dir"
  tar -czf "$dir/insider.tar.gz" -C "$src" .
  (cd "$dir" && sha256 insider.tar.gz > insider.tar.gz.sha256)
  rm -rf "$src"
  sleep 0.01 # ls -t で世代順を区別できるように mtime をずらす
}

# run_release <sha> : 終了コードを $status に入れる
run_release() {
  set +e
  "$script" "$1" > "$INSIDER_HOME/out.log" 2>&1
  status=$?
  set -e
}

assert_eq() {
  if [[ "$2" == "$3" ]]; then
    echo "ok   - $1"
  else
    echo "FAIL - $1: expected [$2] got [$3]"
    failures=$((failures + 1))
  fi
}

rep40() { printf '%040d' 0 | tr 0 "$1"; }
seq_sha() { printf '%040d' "$1"; }

aaa="$(rep40 a)"       # 初回配備
bbb="$(rep40 b)"       # 2 回目の配備 (以降の戻し先)
ccc="$(rep40 c)"       # 起動しない
ddd="$(rep40 d)"       # 戻し先が無い状態の壊れた世代
eee="$(rep40 e)"       # チェックサム不一致
halfup="$(rep40 f)"    # 本文は ok だが HTTP 503
nostart="$(rep40 1)"   # systemctl restart 自体が失敗する
nosync="$(rep40 5)"    # uv sync が失敗する
noimport="$(rep40 7)"  # 展開後に import できない
botdown="$(rep40 6)"   # Web は上がるが bot が自動再起動している
exc="$(rep40 2)"       # 保持数を超えても current / previous が残ることの検証
brk="$(rep40 3)"       # current のリンク先が失われた後の配備
flaky="$(rep40 4)"     # 本文も 200 も正常だが curl 自体が失敗する

released() { echo "$INSIDER_HOME/releases/$1"; }
current() { readlink "$INSIDER_HOME/current" 2>/dev/null || echo none; }
previous() { readlink "$INSIDER_HOME/previous" 2>/dev/null || echo none; }
systemctl_log() { cat "$INSIDER_HOME/systemctl.log" 2>/dev/null | tr '\n' ';' || true; }
uv_log() { cat "$INSIDER_HOME/uv.log" 2>/dev/null | tr '\n' ';' || true; }
incoming_count() { ls -1 "$INSIDER_HOME/incoming" | wc -l | tr -d ' '; }
release_count() { ls -1 "$INSIDER_HOME/releases" | grep -cE '^[0-9a-f]{40}$' || true; }
staging_count() { ls -1a "$INSIDER_HOME/releases" | grep -c '^\.staging' || true; }
exists() { [[ -e "$1" ]] && echo yes || echo no; }

echo "# 40 桁 hex 以外の revision は何もせずに拒否する"
for bad in ../../../etc aaa "$(printf '%040d' 0 | tr 0 A)"; do
  fresh_home
  run_release "$bad"
  assert_eq "終了コードは 2 [$bad]" 2 "$status"
  assert_eq "releases に何も作らない [$bad]" "" "$(ls -1 "$INSIDER_HOME/releases")"
  assert_eq "systemctl を呼ばない [$bad]" "" "$(systemctl_log)"
done

echo "# 初回配備"
fresh_home
add_release "$aaa" GOOD
run_release "$aaa"
assert_eq "初回は成功する" 0 "$status"
assert_eq "current が releases 配下の新しい世代を指す" "$(released "$aaa")" "$(current)"
assert_eq "previous は無い" none "$(previous)"
assert_eq "incoming は空になる" 0 "$(incoming_count)"
assert_eq "展開先に .venv ができている" yes "$(exists "$(released "$aaa")/.venv/bin/python")"
assert_eq "uv sync は展開中のディレクトリで 1 回" "$INSIDER_HOME/releases/.staging-$aaa;" "$(uv_log)"
assert_eq "uv sync は --locked --no-dev --no-editable" "sync --locked --no-dev --no-editable" "$(cat "$INSIDER_HOME/uv-args.log")"
assert_eq "展開中のディレクトリは残らない" 0 "$(staging_count)"
assert_eq "web と bot を 1 回ずつ再起動する" "restart insider-web;restart insider-bot;" "$(systemctl_log)"

echo "# 2 回目の配備"
add_release "$bbb" GOOD
run_release "$bbb"
assert_eq "成功する" 0 "$status"
assert_eq "current が bbb" "$(released "$bbb")" "$(current)"
assert_eq "previous が aaa" "$(released "$aaa")" "$(previous)"

echo "# 稼働中の世代と同じ commit の再実行は何もせず成功する (稼働中の世代を触らない)"
before_uv="$(uv_log)"; before_log="$(systemctl_log)"
add_release "$bbb" GOOD
run_release "$bbb"
assert_eq "成功する" 0 "$status"
assert_eq "current は bbb のまま" "$(released "$bbb")" "$(current)"
assert_eq "previous は aaa のまま (bbb 自身にならない)" "$(released "$aaa")" "$(previous)"
assert_eq "uv sync を呼ばない" "$before_uv" "$(uv_log)"
assert_eq "再起動しない" "$before_log" "$(systemctl_log)"
assert_eq "incoming は片付く" 0 "$(incoming_count)"
assert_eq "ログに already running と出る" yes "$(grep -q 'already running' "$INSIDER_HOME/out.log" && echo yes || echo no)"

echo "# 起動しない世代は直前へ戻す"
add_release "$ccc" BROKEN
run_release "$ccc"
assert_eq "job は失敗する" 1 "$status"
assert_eq "current が bbb に戻る" "$(released "$bbb")" "$(current)"
assert_eq "restart は aaa, bbb, ccc, 戻しの 4 回 × 2 ユニット。stop はしない" \
  8 "$(systemctl_log | tr ';' '\n' | grep -c '^restart ')"
assert_eq "stop は呼ばない" 0 "$(systemctl_log | tr ';' '\n' | grep -c '^stop ' || true)"

echo "# 本文が ok でも HTTP 200 でなければ失敗として戻す"
add_release "$halfup" HALFUP
run_release "$halfup"
assert_eq "job は失敗する" 1 "$status"
assert_eq "current が bbb に戻る" "$(released "$bbb")" "$(current)"

echo "# systemctl restart 自体の失敗も戻す"
add_release "$nostart" NOSTART
run_release "$nostart"
assert_eq "job は失敗する" 1 "$status"
assert_eq "current が bbb に戻る" "$(released "$bbb")" "$(current)"

echo "# Web が 200 ok でも insider-bot が自動再起動していれば戻す"
add_release "$botdown" BOTDOWN
run_release "$botdown"
assert_eq "job は失敗する" 1 "$status"
assert_eq "current が bbb に戻る" "$(released "$bbb")" "$(current)"

echo "# uv sync の失敗は current も previous も変えず、再起動もしない"
before_log="$(systemctl_log)"
before_previous="$(previous)"  # 直前の戻しで previous も bbb を指している (戻しは previous を動かさない)
add_release "$nosync" NOSYNC
run_release "$nosync"
assert_eq "job は失敗する" 1 "$status"
assert_eq "current は bbb のまま" "$(released "$bbb")" "$(current)"
assert_eq "previous も変わらない" "$before_previous" "$(previous)"
assert_eq "restart は呼ばれない" "$before_log" "$(systemctl_log)"
assert_eq "失敗した世代は releases に残らない" no "$(exists "$(released "$nosync")")"
assert_eq "展開中のディレクトリも残らない" 0 "$(staging_count)"
assert_eq "incoming は片付く" 0 "$(incoming_count)"

echo "# 展開後に import できない世代は current も previous も変えず、再起動もしない"
before_log="$(systemctl_log)"
before_previous="$(previous)"
add_release "$noimport" NOIMPORT
run_release "$noimport"
assert_eq "job は失敗する" 1 "$status"
assert_eq "current は bbb のまま" "$(released "$bbb")" "$(current)"
assert_eq "previous も変わらない" "$before_previous" "$(previous)"
assert_eq "restart は呼ばれない" "$before_log" "$(systemctl_log)"
assert_eq "失敗した世代は releases に残らない" no "$(exists "$(released "$noimport")")"

echo "# 戻し先が無ければ停止する"
fresh_home
add_release "$ddd" BROKEN
run_release "$ddd"
assert_eq "job は失敗する" 1 "$status"
assert_eq "restart の後に両方を stop する" "restart insider-web;restart insider-bot;stop insider-web;stop insider-bot;" "$(systemctl_log)"

echo "# チェックサム不一致は何もしない"
fresh_home
add_release "$eee" GOOD
printf '%064d  insider.tar.gz\n' 0 > "$INSIDER_HOME/incoming/$eee/insider.tar.gz.sha256"
run_release "$eee"
assert_eq "失敗する" 1 "$status"
assert_eq "current は作られない" none "$(current)"
assert_eq "releases に展開されない" "" "$(ls -1 "$INSIDER_HOME/releases")"
assert_eq "restart しない" "" "$(systemctl_log)"
assert_eq "incoming は片付く" 0 "$(incoming_count)"

echo "# 直近 5 世代だけ残す (current / previous は例外)"
fresh_home
for n in 1 2 3 4 5 6 7; do
  add_release "$(seq_sha "$n")" GOOD
  run_release "$(seq_sha "$n")"
done
assert_eq "7 回目も成功" 0 "$status"
assert_eq "残るのは 5 世代" 5 "$(release_count)"
assert_eq "current の r7 が残る" "$(released "$(seq_sha 7)")" "$(current)"
assert_eq "previous の r6 が残る" "$(released "$(seq_sha 6)")" "$(previous)"
assert_eq "最古の r1 は消える" no "$(exists "$(released "$(seq_sha 1)")")"

echo "# current / previous が指す世代は、保持数を超えても残る"
export INSIDER_KEEP_RELEASES=1
add_release "$exc" GOOD
printf '%064d  insider.tar.gz\n' 0 > "$INSIDER_HOME/incoming/$exc/insider.tar.gz.sha256"
run_release "$exc"
unset INSIDER_KEEP_RELEASES
assert_eq "チェックサム不一致なので失敗する" 1 "$status"
assert_eq "保持数 1 でも current の r7 と previous の r6 の 2 世代が残る" 2 "$(release_count)"
assert_eq "current のリンク先が実在する" yes "$(exists "$INSIDER_HOME/current")"
assert_eq "previous のリンク先が実在する" yes "$(exists "$INSIDER_HOME/previous")"

echo "# prune はこのスクリプトが作っていないエントリを消さず、数にも入れない"
fresh_home
for n in 1 2 3; do
  add_release "$(seq_sha "$n")" GOOD
  run_release "$(seq_sha "$n")"
done
mkdir -p "$INSIDER_HOME/releases/not-a-sha"   # 世代の途中に新しい不明なエントリ
for n in 4 5 6 7; do
  add_release "$(seq_sha "$n")" GOOD
  run_release "$(seq_sha "$n")"
done
assert_eq "7 回目も成功" 0 "$status"
assert_eq "40 桁 hex でないエントリは消さない" yes "$(exists "$INSIDER_HOME/releases/not-a-sha")"
assert_eq "不明なエントリを数に入れず、SHA の世代が 5 つ残る" 5 "$(release_count)"
assert_eq "最古の r1 は消える" no "$(exists "$(released "$(seq_sha 1)")")"
assert_eq "r3 は残る (不明なエントリのぶん余計に消えない)" yes "$(exists "$(released "$(seq_sha 3)")")"

echo "# current のリンク先が失われているときは previous を上書きしない"
fresh_home
add_release "$aaa" GOOD
run_release "$aaa"
add_release "$bbb" GOOD
run_release "$bbb"
assert_eq "この時点の previous は aaa" "$(released "$aaa")" "$(previous)"
rm -rf "$(released "$bbb")"
add_release "$brk" GOOD
run_release "$brk"
assert_eq "成功する" 0 "$status"
assert_eq "previous は aaa のまま (リンク先を失った bbb を昇格させない)" "$(released "$aaa")" "$(previous)"
assert_eq "previous のリンク先が実在する" yes "$(exists "$INSIDER_HOME/previous")"

echo "# 本文も HTTP 200 も正常でも curl 自体が失敗したら健康と見なさない"
fresh_home
add_release "$aaa" GOOD
run_release "$aaa"
add_release "$flaky" FLAKY
run_release "$flaky"
assert_eq "job は失敗する" 1 "$status"
assert_eq "current が aaa に戻る" "$(released "$aaa")" "$(current)"

if [[ "$failures" -ne 0 ]]; then
  echo "$failures failure(s)"
  exit 1
fi
echo "all passed"
