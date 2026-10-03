// 特殊村フォーム: 1 行 1 通。末尾の空行は数えず、途中の空行は空のメッセージ（「メッセージは特にありません。」）になる。
// 文字数は LINE と同じく UTF-16 の符号単位（String の length）で数える
export const MAX_MESSAGES = 100;
export const MAX_MESSAGE_LENGTH = 5000;

export function parseMessages(text) {
  const lines = text.split(/\r\n|\r|\n/);
  while (lines.length > 0 && lines.at(-1).trim() === "") lines.pop();
  return lines;
}

/** 送れない理由。送れるなら null。 */
export function messagesProblem(messages) {
  if (messages.length === 0) return "メッセージを 1 行以上入力してください";
  if (messages.length > MAX_MESSAGES) return `メッセージは ${MAX_MESSAGES} 通までです（いま ${messages.length} 通）`;
  const tooLong = messages.findIndex((message) => message.length > MAX_MESSAGE_LENGTH);
  if (tooLong >= 0) return `${tooLong + 1} 行目が ${MAX_MESSAGE_LENGTH} 文字を超えています`;
  return null;
}
