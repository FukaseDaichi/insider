// サービスの本文は保持し、既知の回答形式だけを表示用に構造化する。
// 通知・正解・エラーや将来の未知の形式は、本文をそのまま表示する。
export function parseAnswer(text) {
  const match =
    /^❓ ([\s\S]+)\n(✅ はい|❌ いいえ)　　はい (\d{1,3})% [█░]{12} いいえ (\d{1,3})%$/.exec(
      text,
    );
  if (!match) return null;
  const yes = Number(match[3]);
  const no = Number(match[4]);
  if (yes + no !== 100 || yes > 100 || no > 100) return null;
  return { question: match[1], positive: yes >= 50, yes, no };
}
