// ゲーム開始の案内は、案内役キャラクター「GM」の吹き出しとして描く。
export const HOST_NAME = "GM";

const START_PREFIX = "🎮 ゲーム開始！";

// 開始の案内なら吹き出しに出す行の配列を、それ以外なら null を返す。
// 先頭の 🎮 はサーバーの文面に残して見分けに使い、吹き出しには出さない
export function hostLines(text) {
  if (!text.startsWith(START_PREFIX)) return null;
  return text
    .replace(/^🎮\s*/u, "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}
