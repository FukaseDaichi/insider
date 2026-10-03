// 配役ツールで自分を表すトークン。知っている人がその参加者として振る舞えるので、URL やログに出さない
export const TOKEN_KEY = "village:token";
const TOKEN_BYTES = 16;
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{16,64}$/;

/** 乱数のバイト列を、= のない base64url にする。 */
export function newToken(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

/** 保存済みのトークン。なければ作って保存する。保存できない環境では、その場かぎりのトークンになる。 */
export function villageToken(storage, cryptoObject) {
  let saved = null;
  try {
    saved = storage?.getItem(TOKEN_KEY) ?? null;
  } catch {
    // プライベートブラウズなどで読めない
  }
  if (saved !== null && TOKEN_PATTERN.test(saved)) return saved;
  const token = newToken(cryptoObject.getRandomValues(new Uint8Array(TOKEN_BYTES)));
  try {
    storage?.setItem(TOKEN_KEY, token);
  } catch {
    // 保存できなくても、このページを開いている間は同じトークンで動く
  }
  return token;
}
