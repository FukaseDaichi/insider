#!/usr/bin/env bash
# 本番の VM（A1）を空きが出るまで繰り返し作る: bash scripts/oci-launch-a1.sh（Ctrl+C で止まる）
# Always Free の A1 は「Out of host capacity」で作れないことが多く、人が押し直すより機械に繰り返させる。
# 作れたら公開 IP を表示して終わる。すでに同名の VM が動いていれば何も作らずに終わる。
# 前提: OCI CLI（uv tool install oci-cli）と ~/.oci/config（API キー）。VCN と公開サブネットはコンソールで作っておく。
# 値は deploy/human-steps.md 2-1 の表と同じ。変えるときは環境変数で上書きする（例 INTERVAL=60）。
set -euo pipefail

# oci-cli が Python 3.13 で出す SyntaxWarning と、config の権限の注意を抑える
export PYTHONWARNINGS=ignore OCI_CLI_SUPPRESS_FILE_PERMISSIONS_WARNING=True

OCI="$(command -v oci || true)"
[ -n "$OCI" ] || OCI="$HOME/.local/bin/oci"
if [ ! -x "$OCI" ]; then
  echo "oci CLI がありません。uv tool install oci-cli で入れてください" >&2
  exit 1
fi
if [ ! -f "$HOME/.oci/config" ]; then
  echo "~/.oci/config がありません。deploy/human-steps.md の 2-1 を見て API キーを設定してください" >&2
  exit 1
fi

NAME="${NAME:-insider}"
SHAPE="VM.Standard.A1.Flex"
OCPUS="${OCPUS:-2}"
MEMORY_GB="${MEMORY_GB:-12}"
BOOT_GB="${BOOT_GB:-50}"
SSH_PUB="${SSH_PUB:-$HOME/.ssh/id_ed25519.pub}"
INTERVAL="${INTERVAL:-120}"   # 空きなしのときに次を試すまでの秒数。短くしすぎると 429 で待たされる
LOG="${LOG:-$HOME/.oci/launch-a1.log}"

if [ ! -f "$SSH_PUB" ]; then
  echo "公開鍵 $SSH_PUB がありません（deploy/human-steps.md 1-3）" >&2
  exit 1
fi

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

# 既定はテナンシ（root コンパートメント）。別のコンパートメントなら COMPARTMENT_OCID で指定する
TENANCY="$(sed -n 's/^tenancy *= *//p' "$HOME/.oci/config" | head -n 1)"
COMPARTMENT="${COMPARTMENT_OCID:-$TENANCY}"
if [ -z "$COMPARTMENT" ]; then
  echo "~/.oci/config に tenancy がありません" >&2
  exit 1
fi

echo "== 既存の VM を確認"
existing="$("$OCI" compute instance list -c "$COMPARTMENT" --display-name "$NAME" \
  --query 'data[?"lifecycle-state"!=`TERMINATED` && "lifecycle-state"!=`TERMINATING`].id' --raw-output 2>/dev/null \
  | jq -r '.[]?' || true)"
if [ -n "$existing" ]; then
  echo "$NAME という VM がすでにあります。作りません:" >&2
  echo "$existing" >&2
  exit 1
fi

echo "== 値を集める"
AD="${AD:-$("$OCI" iam availability-domain list -c "$COMPARTMENT" --query 'data[0].name' --raw-output)}"
IMAGE="${IMAGE_OCID:-$("$OCI" compute image list -c "$COMPARTMENT" \
  --operating-system 'Canonical Ubuntu' --operating-system-version '24.04' --shape "$SHAPE" \
  --sort-by TIMECREATED --sort-order DESC --query 'data[0].id' --raw-output)}"
if [ -z "${SUBNET_OCID:-}" ]; then
  subnets="$("$OCI" network subnet list -c "$COMPARTMENT" --lifecycle-state AVAILABLE \
    --query 'data[?"prohibit-public-ip-on-vnic"==`false`].[id,"display-name"]' --raw-output | jq -r '.[] | @tsv')"
  if [ "$(printf '%s\n' "$subnets" | grep -c .)" -ne 1 ]; then
    echo "公開サブネットが 1 つに決まりません。SUBNET_OCID で指定してください:" >&2
    printf '%s\n' "$subnets" >&2
    exit 1
  fi
  SUBNET_OCID="${subnets%%	*}"
fi
printf '  AD      %s\n  image   %s\n  subnet  %s\n  shape   %s %s OCPU %s GB, boot %s GB\n' \
  "$AD" "$IMAGE" "$SUBNET_OCID" "$SHAPE" "$OCPUS" "$MEMORY_GB" "$BOOT_GB"

# 回している間は Mac をスリープさせない（play.sh と同じ）
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -is -w $$ &
fi

echo "== 作成を試す（Ctrl+C で止まる。記録は ${LOG}）"
n=0
while :; do
  n=$((n + 1))
  if out="$("$OCI" compute instance launch -c "$COMPARTMENT" --availability-domain "$AD" \
      --display-name "$NAME" --shape "$SHAPE" \
      --shape-config "{\"ocpus\": $OCPUS, \"memoryInGBs\": $MEMORY_GB}" \
      --image-id "$IMAGE" --subnet-id "$SUBNET_OCID" --assign-public-ip true \
      --boot-volume-size-in-gbs "$BOOT_GB" --ssh-authorized-keys-file "$SSH_PUB" \
      --query 'data.id' --raw-output 2>&1)"; then
    INSTANCE="$out"
    log "作成できました（$n 回目）: $INSTANCE"
    break
  fi
  # 理由は API の message の 1 行だけ記録する（全文は長い）
  reason="$(grep -oE "'message': '[^']*'|\"message\": \"[^\"]*\"" <<<"$out" | head -n 1 | sed -E "s/^.message.: //" || true)"
  if grep -qi 'out of host capacity\|out of capacity' <<<"$out"; then
    log "$n 回目: 空きなし。${INTERVAL} 秒後に再試行 ${reason}"
    sleep "$INTERVAL"
  elif grep -qi 'TooManyRequests\|status 429' <<<"$out"; then
    log "$n 回目: 429（叩きすぎ）。$((INTERVAL * 3)) 秒待つ ${reason}"
    sleep $((INTERVAL * 3))
  else
    log "$n 回目: 空きなし以外のエラーで止まります"
    printf '%s\n' "$out" >&2
    exit 1
  fi
done

echo "== 起動を待つ"
"$OCI" compute instance get --instance-id "$INSTANCE" --wait-for-state RUNNING --max-wait-seconds 600 >/dev/null
IP="$("$OCI" compute instance list-vnics --instance-id "$INSTANCE" --query 'data[0]."public-ip"' --raw-output)"
log "起動しました。公開 IP: $IP"
echo
echo "次: deploy/human-steps.md の記録表に公開 IP を書き、2-2（80/443 を開ける）と Phase 3（A レコード）へ"
