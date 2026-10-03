// 配役ツールの村番号。ページのパス・QR の URL・入力欄から読み取る
export const MIN_VILLAGE_NUMBER = 1000;
export const MAX_VILLAGE_NUMBER = 99998;

function toNumber(digits) {
  const number = Number(digits);
  return number >= MIN_VILLAGE_NUMBER && number <= MAX_VILLAGE_NUMBER ? number : null;
}

/** パスが /v/<村番号> なら村番号を、それ以外は null を返す。 */
export function villageFromPath(pathname) {
  const match = /^\/v\/(\d{4,5})\/?$/.exec(pathname);
  return match ? toNumber(match[1]) : null;
}

/** このサイト（origin）の /v/<村番号> の URL なら村番号を、それ以外は null を返す。 */
export function parseVillageUrl(text, origin) {
  let url;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  // 読み取った見知らぬ URL へは移動しない
  if (url.origin !== origin) return null;
  return villageFromPath(url.pathname);
}

/** 入力欄の村番号。全角数字と前後の空白は許し、4〜5 桁の数字だけを受け付ける。 */
export function parseVillageInput(text) {
  const normalized = text.normalize("NFKC").trim();
  return /^\d{4,5}$/.test(normalized) ? toNumber(normalized) : null;
}

/** 村に入るための URL。 */
export function villageUrl(number, origin) {
  return `${origin}/v/${number}`;
}
