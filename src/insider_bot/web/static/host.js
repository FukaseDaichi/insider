// 案内役キャラクター「GM」の吹き出し。開始の案内（🎮）と、インサイダーゲームの節目（kind: host）を描く
export const HOST_NAME = "GM";

// Web 版でサーバーが 🎮 で始める通知はゲーム開始だけ
const START_PREFIX = "🎮 ";

// 場面（pose）ごとの GM の絵。どれも host.png と同じ子で、表情と小物だけ違う（生成のプロンプトは assets/host-poses-prompt.md）
const DEFAULT_IMAGE = "/static/host.png";
const HOST_IMAGES = {
  start: DEFAULT_IMAGE, // ウインクでピース
  secret: "/static/host-secret.png", // 口に指「しーっ」（配役直後のお題待ち）
  hurry: "/static/host-hurry.png", // 時計を抱えて慌てる（残り 1 分・時間切れ）
  detective: "/static/host-detective.png", // 探偵帽と虫眼鏡（お題が当たって投票へ）
  giveup: "/static/host-giveup.png", // 白旗で苦笑（ギブアップ）
  "villagers-win": "/static/host-villagers-win.png", // 村人のコスプレで両手を上げる
  "insider-win": "/static/host-insider-win.png", // インサイダーのコスプレで口に指
};
export const HOST_POSES = Object.keys(HOST_IMAGES);

export function hostImage(pose) {
  return HOST_IMAGES[pose] ?? DEFAULT_IMAGE;
}

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

/**
 * 記録が GM の吹き出しなら { pose, lines, start } を、それ以外なら null を返す。
 * start は開始の案内で、質問番号を数え直す区切りになる（節目の吹き出しでは数え直さない）
 */
export function hostEntry(entry) {
  if (entry.author || entry.pending) return null;
  if (entry.kind === "host") {
    if (!entry.data?.lines) return null;
    return { pose: entry.data.pose, lines: entry.data.lines, start: false };
  }
  if (entry.kind) return null;
  const lines = hostLines(entry.text);
  return lines ? { pose: "start", lines, start: true } : null;
}
