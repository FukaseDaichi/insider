// 読み取った QR の文字列が、このサイトのルーム URL かを判定する
export const ROOM_CODE_PATTERN = /^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{6}$/;

/** このサイト（origin）の /r/<ルーム番号> ならルーム番号を、それ以外は null を返す。 */
export function parseRoomCode(text, origin) {
  let url;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  // 読み取った見知らぬ URL へは移動しない
  if (url.origin !== origin) return null;
  const match = /^\/r\/([^/]+)\/?$/.exec(url.pathname);
  if (!match || !ROOM_CODE_PATTERN.test(match[1])) return null;
  return match[1];
}
