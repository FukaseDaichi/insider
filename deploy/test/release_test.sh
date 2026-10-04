#!/usr/bin/env bash
# deploy/insider-release.sh の振る舞いを、systemctl・curl・uv を偽物に差し替えて確かめる。
# 本番は Linux (flock / sha256sum)。CI の build job で必ず走らせる。sha256sum が無ければ shasum に切り替え、
# flock が無ければ (Mac) 排他なしで動く。
#
# tar の中の BEHAVIOR ファイルが「振る舞い」を表す:
#   GOOD     起動して 200 ok を返し、bot も active
#   BROKEN   Web も bot も起動しない (curl が失敗し、bot は起動の直後に落ちて自動再起動を繰り返す)
#   HALFUP   本文は ok だが HTTP 503 (ステータスを見ていないと健康と誤判定する)。bot は正常
#   NOSTART  systemctl restart 自体が失敗する
#   FLAKY    本文も HTTP 200 も正常だが curl 自体が失敗する (終了コードを見ていないと健康と誤判定する)
#   NOSYNC   uv sync が失敗する (current を変えずに終わる)
#   NOIMPORT 展開後の python が import に失敗する (current を変えずに終わる)
#   BOTDOWN  Web は 200 ok だが insider-bot が起動の直後に落ち、自動再起動を繰り返す (NRestarts が 0 でない)
#   BOTLATE  Web は 200 ok で bot も最初の確認では NRestarts が 0 だが、BOT_SETTLE の後の再確認で 1
#            (起動の数秒後に落ち、以後は自動再起動を繰り返す)
# 世代の外にある状態 ($INSIDER_HOME 直下) も偽物が見る:
#   stopped-<unit>    systemctl stop が作り、restart が消す。ある間は is-active が失敗し、Web の curl も失敗する
#   env-broken        ある間はどの世代でも curl が失敗し、bot も起動の直後に落ちる (/etc/insider.env の誤りを模す)
#   bot-broken        ある間はどの世代でも bot だけが起動の直後に落ちる (DISCORD_TOKEN の誤りや失効を模す)
#   slow-fail         ある間は起動しない世代の curl が 0.5 秒遅れて失敗する (出力側が閉じる時間を作る)
#   nrestarts-<unit>  NRestarts の値 (無ければ 0)
#   crashloop-<unit>  ある間、そのユニットは落ちて自動再起動を待っている (下の偽 systemctl を参照)
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
# 本物の systemd (Ubuntu 24.04 の 255) のうち、更新スクリプトの判定に効く振る舞いを真似る。
# NRestarts (自動再起動の回数) は手動の restart で 0 に戻る。ただし、落ちて自動再起動を待っている間 (auto-restart) に
# 来た restart では 0 に戻らない (実測)。reset-failed と stop は 0 に戻す。
# ここでは落ち続けているユニットへの restart は必ずその待ちの間に来ることにする (本物ではたいていそうなる)
behavior="$(cat "$INSIDER_HOME/current/BEHAVIOR" 2>/dev/null || true)"
unit="${*: -1}"
count_file="$INSIDER_HOME/nrestarts-$unit"
crashloop="$INSIDER_HOME/crashloop-$unit"
nrestarts() { cat "$count_file" 2>/dev/null || echo 0; }
case "$1" in
  reset-failed)
    echo "$1 $unit" >> "$INSIDER_HOME/systemctl.log"
    echo 0 > "$count_file"
    rm -f "$crashloop"
    exit 0 ;;
  restart)
    echo "$1 $unit" >> "$INSIDER_HOME/systemctl.log"
    [[ "$behavior" == NOSTART ]] && exit 1
    rm -f "$INSIDER_HOME/stopped-$unit" "$INSIDER_HOME/show-count"
    [[ -e "$crashloop" ]] || echo 0 > "$count_file"
    rm -f "$crashloop"
    if [[ "$unit" == insider-bot ]]; then
      if [[ -e "$INSIDER_HOME/env-broken" || -e "$INSIDER_HOME/bot-broken" || "$behavior" == BROKEN || "$behavior" == BOTDOWN ]]; then
        # 起動の直後に落ち、自動再起動を繰り返す
        echo $(( $(nrestarts) + 1 )) > "$count_file"
        : > "$crashloop"
      elif [[ "$behavior" == BOTLATE ]]; then
        # 起動の数秒後に落ち (数が増えるのは下の show の 2 回目)、以後は自動再起動を繰り返す
        : > "$crashloop"
      fi
    fi
    exit 0 ;;
  stop)
    echo "$1 $unit" >> "$INSIDER_HOME/systemctl.log"
    : > "$INSIDER_HOME/stopped-$unit"
    echo 0 > "$count_file"
    rm -f "$crashloop"
    exit 0 ;;
  is-active)
    if [[ -e "$INSIDER_HOME/stopped-$unit" ]]; then state=inactive rc=3; else state=active rc=0; fi
    [[ "$2" == --quiet ]] || echo "$state"
    exit "$rc" ;;
  show)
    # show -p NRestarts --value <unit>
    if [[ "$unit" == insider-bot && "$behavior" == BOTLATE ]]; then
      # restart の後の最初の 1 回はそのままの数、2 回目からは 1 回落ちて自動再起動した後の数
      case "$(cat "$INSIDER_HOME/show-count" 2>/dev/null)" in
        '') echo first > "$INSIDER_HOME/show-count" ;;
        first) echo crashed > "$INSIDER_HOME/show-count"; echo $(( $(nrestarts) + 1 )) > "$count_file" ;;
      esac
    fi
    nrestarts
    exit 0 ;;
esac
FAKE
cat > "$fake_bin/curl" <<'FAKE'
#!/usr/bin/env bash
# 本物と同じく -o <file> に本文を書き、-w の代わりに HTTP ステータスを標準出力へ出す (繋がらなければ 000)
out=/dev/null
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) shift 2 ;;
    *) shift ;;
  esac
done
# 世代の外の状態: Web が止まっている間と、/etc/insider.env が誤っている間は、どの世代でも繋がらない
if [[ -e "$INSIDER_HOME/stopped-insider-web" || -e "$INSIDER_HOME/env-broken" ]]; then printf 000; exit 7; fi
behavior="$(cat "$INSIDER_HOME/current/BEHAVIOR" 2>/dev/null || true)"
case "$behavior" in
  GOOD|BOTDOWN|BOTLATE) printf ok > "$out"; printf 200; exit 0 ;;
  HALFUP)       printf ok > "$out"; printf 503; exit 0 ;;
  FLAKY)        printf ok > "$out"; printf 200; exit 7 ;;
  *)            [[ -e "$INSIDER_HOME/slow-fail" ]] && sleep 0.5; printf 000; exit 7 ;;
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
echo "$*" >> "$INSIDER_HOME/python-args.log"
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
botlate="$(rep40 8)"   # Web は上がり、bot も最初の確認は通るが、BOT_SETTLE の後に自動再起動している

released() { echo "$INSIDER_HOME/releases/$1"; }
current() { readlink "$INSIDER_HOME/current" 2>/dev/null || echo none; }
previous() { readlink "$INSIDER_HOME/previous" 2>/dev/null || echo none; }
# restart と stop の並び。更新スクリプトは restart の直前に必ず reset-failed するので、その行はここでは除き、
# systemctl_log_all と restarts_without_reset で別に確かめる
systemctl_log() { grep -v '^reset-failed ' "$INSIDER_HOME/systemctl.log" 2>/dev/null | tr '\n' ';' || true; }
systemctl_log_all() { cat "$INSIDER_HOME/systemctl.log" 2>/dev/null | tr '\n' ';' || true; }
# 直前の行が同じユニットの reset-failed でない restart の数
restarts_without_reset() {
  { cat "$INSIDER_HOME/systemctl.log" 2>/dev/null || true; } |
    awk '/^restart / { if (prev != "reset-failed " $2) n++ } { prev = $0 } END { print n + 0 }'
}
logged() { grep -qF -- "$1" "$INSIDER_HOME/out.log" && echo yes || echo no; }
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
assert_eq "restart の直前に、同じユニットを reset-failed する (自動再起動の待ちの最中でも NRestarts を 0 に戻す)" \
  "reset-failed insider-web;restart insider-web;reset-failed insider-bot;restart insider-bot;" "$(systemctl_log_all)"
assert_eq "起動する 2 つのエントリ (python -m insider_bot と python -m insider_bot.web) を import で確かめる" \
  "-c import insider_bot.__main__, insider_bot.web.__main__" "$(cat "$INSIDER_HOME/python-args.log")"

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
assert_eq "どの確認で落ちたかをログに 1 行で出す (HTTP ステータス・curl の終了コード・本文・bot の状態・NRestarts)" yes \
  "$(logged "not healthy within 0s: web http=503 curl=0 body=ok; bot active NRestarts=0")"

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
assert_eq "ログに bot の NRestarts が出る" yes "$(logged "not healthy within 0s: web http=200 curl=0 body=ok; bot active NRestarts=1")"

echo "# Web が上がり bot も最初の確認は通っても、BOT_SETTLE の後に自動再起動していれば戻す"
add_release "$botlate" BOTLATE
run_release "$botlate"
assert_eq "job は失敗する (最初の確認だけで健康と見なさない)" 1 "$status"
assert_eq "current が bbb に戻る" "$(released "$bbb")" "$(current)"
assert_eq "BOT_SETTLE の後の再確認で落ちたことがログに出る" yes \
  "$(logged "not healthy 0s after passing: web http=200 curl=0 body=ok; bot active NRestarts=1")"
assert_eq "戻した世代で健康になり、何も止めない" 0 "$(systemctl_log | tr ';' '\n' | grep -c '^stop ' || true)"

echo "# uv sync の失敗は current も previous も変えず、再起動もしない"
# previous が current と違う状態 (aaa → bbb) から始める。失敗する前に current を previous へ昇格させる実装を見逃さないため
fresh_home
add_release "$aaa" GOOD
run_release "$aaa"
add_release "$bbb" GOOD
run_release "$bbb"
before_log="$(systemctl_log)"
before_previous="$(previous)"
assert_eq "前提: previous が aaa、current が bbb" "$(released "$aaa") $(released "$bbb")" "$before_previous $(current)"
add_release "$nosync" NOSYNC
run_release "$nosync"
assert_eq "job は失敗する" 1 "$status"
assert_eq "current は bbb のまま" "$(released "$bbb")" "$(current)"
assert_eq "previous も変わらない (aaa のまま)" "$(released "$aaa")" "$(previous)"
assert_eq "restart は呼ばれない" "$before_log" "$(systemctl_log)"
assert_eq "失敗した世代は releases に残らない" no "$(exists "$(released "$nosync")")"
assert_eq "展開中のディレクトリも残らない" 0 "$(staging_count)"
assert_eq "incoming は片付く" 0 "$(incoming_count)"

echo "# 展開後に import できない世代は current も previous も変えず、再起動もしない"
before_log="$(systemctl_log)"
before_previous="$(previous)"
assert_eq "前提: previous が aaa、current が bbb" "$(released "$aaa") $(released "$bbb")" "$before_previous $(current)"
add_release "$noimport" NOIMPORT
run_release "$noimport"
assert_eq "job は失敗する" 1 "$status"
assert_eq "current は bbb のまま" "$(released "$bbb")" "$(current)"
assert_eq "previous も変わらない (aaa のまま)" "$(released "$aaa")" "$(previous)"
assert_eq "restart は呼ばれない" "$before_log" "$(systemctl_log)"
assert_eq "失敗した世代は releases に残らない" no "$(exists "$(released "$noimport")")"

echo "# 戻し先が無く、Web も bot も通らなければ両方を止める"
fresh_home
add_release "$ddd" BROKEN
run_release "$ddd"
assert_eq "job は失敗する" 1 "$status"
assert_eq "restart の後に両方を stop する" "restart insider-web;restart insider-bot;stop insider-web;stop insider-bot;" "$(systemctl_log)"
assert_eq "止めたユニットと残したユニットをログに出す" yes "$(logged "no healthy release; stopped: insider-web insider-bot; kept running: none")"

echo "# 戻し先が無く bot だけが通らなければ、bot だけを止めて Web と LINE は動かしたままにする"
fresh_home
add_release "$botdown" BOTDOWN
run_release "$botdown"
assert_eq "job は失敗する" 1 "$status"
assert_eq "restart の後に bot だけを stop する" "restart insider-web;restart insider-bot;stop insider-bot;" "$(systemctl_log)"
assert_eq "Web は動いたまま (is-active)" active "$(systemctl is-active insider-web)"
assert_eq "ログに bot を止めて Web を残したと出る" yes "$(logged "no healthy release; stopped: insider-bot; kept running: insider-web")"

echo "# 戻し先が無く Web だけが通らなければ、Web だけを止めて bot は動かしたままにする"
fresh_home
add_release "$halfup" HALFUP
run_release "$halfup"
assert_eq "job は失敗する" 1 "$status"
assert_eq "restart の後に Web だけを stop する" "restart insider-web;restart insider-bot;stop insider-web;" "$(systemctl_log)"
assert_eq "bot は動いたまま (is-active)" active "$(systemctl is-active insider-bot)"
assert_eq "ログに Web を止めて bot を残したと出る" yes "$(logged "no healthy release; stopped: insider-web; kept running: insider-bot")"

echo "# 戻しても bot だけが通らなければ (Discord 側の障害など)、bot だけを止めて Web と LINE は動かしたままにする"
fresh_home
add_release "$aaa" GOOD
run_release "$aaa"
touch "$INSIDER_HOME/bot-broken"   # どの世代の bot も起動しない
add_release "$bbb" GOOD
run_release "$bbb"
assert_eq "job は失敗する" 1 "$status"
assert_eq "ログに戻しも通らなかったと出る" yes "$(logged "rollback did not become healthy either")"
assert_eq "current は戻した aaa" "$(released "$aaa")" "$(current)"
assert_eq "aaa、bbb、戻しの restart の後に、bot だけを stop する" \
  "restart insider-web;restart insider-bot;restart insider-web;restart insider-bot;restart insider-web;restart insider-bot;stop insider-bot;" "$(systemctl_log)"
assert_eq "Web は動いたまま (is-active)" active "$(systemctl is-active insider-web)"

echo "# 落ち続ける bot の世代から戻すとき、直前の世代の bot を健康と判定できる (NRestarts を引き継がない)"
# 落ちて自動再起動を待っている bot へ restart しても、systemd 255 は NRestarts を 0 に戻さない。
# reset-failed をしないと、正常な bbb の bot まで「自動再起動した」と見えて戻しが失敗し、全部を止めてしまう
fresh_home
add_release "$aaa" GOOD
run_release "$aaa"
add_release "$bbb" GOOD
run_release "$bbb"
add_release "$botdown" BOTDOWN
run_release "$botdown"
assert_eq "job は失敗する (戻せても配備した commit は動いていない)" 1 "$status"
assert_eq "current が bbb に戻る" "$(released "$bbb")" "$(current)"
assert_eq "ログに rolled back と出る" yes "$(logged "rolled back; production is running $(released "$bbb")")"
assert_eq "stop は呼ばない" 0 "$(systemctl_log | tr ';' '\n' | grep -c '^stop ' || true)"
assert_eq "戻した後の bot は active" active "$(systemctl is-active insider-bot)"
assert_eq "戻した後の bot の NRestarts は 0" 0 "$(systemctl show -p NRestarts --value insider-bot)"
assert_eq "どの restart の直前にも、同じユニットの reset-failed がある" 0 "$(restarts_without_reset)"

echo "# 稼働中の bot が落ち続けている間に env を直し、同じ commit を再実行すると、再起動して成功する"
fresh_home
add_release "$aaa" GOOD
run_release "$aaa"
touch "$INSIDER_HOME/bot-broken"   # 稼働中に DISCORD_TOKEN が失効した。Restart=always で落ちては上がり直す
systemctl restart insider-bot      # 失効の後の最初の起動 (落ちて自動再起動を待つ状態になる)
assert_eq "前提: bot の NRestarts が 0 でない" 1 "$(systemctl show -p NRestarts --value insider-bot)"
rm -f "$INSIDER_HOME/bot-broken"   # 運用者が /etc/insider.env を直して、GitHub の job を re-run する
add_release "$aaa" GOOD
run_release "$aaa"
assert_eq "成功する" 0 "$status"
assert_eq "bot の NRestarts は 0" 0 "$(systemctl show -p NRestarts --value insider-bot)"
assert_eq "ログに healthy と出る" yes "$(logged "healthy: $aaa")"

echo "# 同じ commit の再実行が通らないときも、通らないユニットだけを止める"
fresh_home
touch "$INSIDER_HOME/bot-broken"   # DISCORD_TOKEN の誤り。bot だけが、どの世代でも起動の直後に落ちる
add_release "$aaa" GOOD
run_release "$aaa"
assert_eq "bot が起動しないので失敗する" 1 "$status"
assert_eq "戻し先が無いので bot だけを stop する" "restart insider-web;restart insider-bot;stop insider-bot;" "$(systemctl_log)"
add_release "$aaa" GOOD
run_release "$aaa"
assert_eq "env がまだ誤っていれば、再実行も失敗する" 1 "$status"
assert_eq "再起動を試みてから、bot だけをもう一度 stop する (Web は止めない)" \
  "restart insider-web;restart insider-bot;stop insider-bot;restart insider-web;restart insider-bot;stop insider-bot;" "$(systemctl_log)"
assert_eq "Web は動いたまま (is-active)" active "$(systemctl is-active insider-web)"

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

echo "# ロックは root 所有のスクリプト自身で取り、insider の領域にファイルを作らない (シンボリックリンクで root に切り詰めさせない)"
fresh_home
victim="$(mktemp)"
printf keep > "$victim"
ln -s "$victim" "$INSIDER_HOME/release.lock"   # insider が /opt/insider に置ける罠。昔の release.lock を狙う
add_release "$aaa" GOOD
run_release "$aaa"
assert_eq "成功する" 0 "$status"
assert_eq "リンク先のファイルは切り詰められない" keep "$(cat "$victim")"
rm -f "$victim"
fresh_home
add_release "$aaa" GOOD
run_release "$aaa"
assert_eq "release.lock を作らない" no "$(exists "$INSIDER_HOME/release.lock")"

echo "# 停止で終わった配備と同じ commit を再実行したら、稼働中とは見なさず再起動して確かめる"
fresh_home
touch "$INSIDER_HOME/env-broken"   # /etc/insider.env の誤りを模す。世代の外にあるので、どの世代も起動しない
add_release "$aaa" GOOD
run_release "$aaa"
assert_eq "起動しないので失敗する" 1 "$status"
assert_eq "戻し先が無いので両方を stop する" "restart insider-web;restart insider-bot;stop insider-web;stop insider-bot;" "$(systemctl_log)"
assert_eq "current は aaa のまま" "$(released "$aaa")" "$(current)"
before_uv="$(uv_log)"
add_release "$aaa" GOOD
run_release "$aaa"
assert_eq "env がまだ誤っていれば、再実行も失敗する (成功にしない)" 1 "$status"
assert_eq "再起動を試みてから、もう一度両方を stop する" \
  "restart insider-web;restart insider-bot;stop insider-web;stop insider-bot;restart insider-web;restart insider-bot;stop insider-web;stop insider-bot;" "$(systemctl_log)"
rm -f "$INSIDER_HOME/env-broken"   # 運用者が env を直して、GitHub の job を re-run する
before_log="$(systemctl_log)"
add_release "$aaa" GOOD
run_release "$aaa"
assert_eq "直したあとの再実行は成功する" 0 "$status"
assert_eq "両方を再起動する" "${before_log}restart insider-web;restart insider-bot;" "$(systemctl_log)"
assert_eq "current は aaa のまま" "$(released "$aaa")" "$(current)"
assert_eq "previous は作られない" none "$(previous)"
assert_eq "uv sync を呼ばない" "$before_uv" "$(uv_log)"
assert_eq "incoming は片付く" 0 "$(incoming_count)"
assert_eq "ログに already running と出ない" no "$(grep -q 'already running' "$INSIDER_HOME/out.log" && echo yes || echo no)"
assert_eq "ログに healthy と出る" yes "$(grep -q "healthy: $aaa" "$INSIDER_HOME/out.log" && echo yes || echo no)"

echo "# 昇格の後に ssh が切れても、戻しまで完走する (出力先が閉じても途中で死なない)"
fresh_home
add_release "$aaa" GOOD
run_release "$aaa"
add_release "$bbb" GOOD
run_release "$bbb"
add_release "$ccc" BROKEN
touch "$INSIDER_HOME/slow-fail"   # 昇格のログを読んだ側が閉じる時間を作る
set +e
"$script" "$ccc" 2>&1 | { while IFS= read -r line; do [[ "$line" == *"restart insider-web"* ]] && break; done; }
script_status="${PIPESTATUS[0]}"
set -e
assert_eq "出力先が閉じても、失敗として 1 で終わる" 1 "$script_status"
assert_eq "current が bbb に戻る" "$(released "$bbb")" "$(current)"
assert_eq "戻しの restart まで完走する (aaa, bbb, ccc, 戻しの 4 回 × 2 ユニット)" \
  8 "$(systemctl_log | tr ';' '\n' | grep -c '^restart ')"
assert_eq "stop は呼ばない" 0 "$(systemctl_log | tr ';' '\n' | grep -c '^stop ' || true)"

if [[ "$failures" -ne 0 ]]; then
  echo "$failures failure(s)"
  exit 1
fi
echo "all passed"
