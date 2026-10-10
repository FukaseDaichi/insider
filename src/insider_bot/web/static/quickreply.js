// 入力欄の上に出すクイックリプライ。オーナーの最新の村の要約から、いま押して意味のあるものだけを出す。
// 中核も同じ条件で断るが、押しても案内文しか返らないボタンは出さない

const WEREWORDS_COMMANDS = ["@わーわーず", "＠わーわーず"];

/** ワーワーズにするコマンドか。LINE と同じく前後の U+0020 以下の文字だけを除く（全角スペースは除かない）。 */
export function isWerewordsCommand(text) {
  return WEREWORDS_COMMANDS.includes(text.replace(/^[\u0000-\u0020]+|[\u0000-\u0020]+$/g, ""));
}

/**
 * village はサーバーが毎回添える最新の村の要約、converted はワーワーズにした村 → 作った特殊村の番号。
 * 返すボタンの kind は invite（QR のカードを出す）・reverse / werewords / send（text を送る）。
 */
export function quickReplies(village, converted) {
  if (village === null || village === undefined || village.size === 0) return [];
  const special = converted[village.number];
  if (special !== undefined) {
    const chips = [{ kind: "invite", label: "QR を見せる", number: special }];
    // 神モードでない村では、オーナーも特殊村に入って役職を受け取る
    if (village.mode !== "god") chips.push({ kind: "send", label: "ワーワーズの村に入る", text: String(special) });
    return chips;
  }
  const chips = [{ kind: "invite", label: "QR を見せる", number: village.number }];
  const empty = village.member_count === 0;
  if (empty && village.mode !== "random" && !village.reverse) chips.push({ kind: "reverse", label: "逆村にする", text: "@逆村" });
  if (empty && village.size >= 3 && village.has_topic) {
    chips.push({ kind: "werewords", label: "ワーワーズにする", text: "@わーわーず" });
  }
  return chips;
}
