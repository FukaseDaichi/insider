// 会話欄「推理ノート」の純粋な解析。サーバーの本文はそのまま保持し、表示に必要な形だけを取り出す。
// 回答の解析は answer.js、ゲーム開始の案内は host.js にあり、ここはそれ以外の見分けと質問番号を受け持つ。

// 判定を待つ質問「❓ 質問\n… 判定中」と、ゲームが終わって取り消された質問「❓ 質問\n— ゲームが終わったため取り消しました」。
// 質問文に改行があっても、最後の行だけを状態として読む
const QUESTION_NOTE = /^❓ ([\s\S]+)\n(… 判定中|— ゲームが終わったため取り消しました)$/;

export function questionNote(text) {
  const match = QUESTION_NOTE.exec(text);
  if (!match) return null;
  const cancelled = match[2].startsWith("—");
  return {
    question: match[1],
    note: cancelled ? "取り消し" : "判定中…",
    cancelled,
  };
}

// 正解は GM がテロップでお題を発表するカードにするので、お題と内訳（最後の行）を取り出す。
// お題に「」や改行が入っても切れないよう、お題は最後の「」でした」までとみなす
const CORRECT = /^🎉 正解です！お題は「([\s\S]*)」でした\n(.*)$/u;
// ギブアップは、お題の公開が主役の大きなカード。1 行目を見出し、残りを内訳として分け、先頭の絵文字は出さない
const GIVEUP_PREFIX = "🏳️ ";

export function resultOf(text) {
  const correct = CORRECT.exec(text);
  if (correct) return { kind: "correct", topic: correct[1], meta: correct[2].trim() };
  if (!text.startsWith(GIVEUP_PREFIX)) return null;
  const [title, ...rest] = text.slice(GIVEUP_PREFIX.length).split("\n");
  const meta = rest.map((line) => line.trim()).filter(Boolean);
  return { kind: "giveup", title: title.trim(), meta: meta.length ? meta.join("　") : null };
}

// 質問番号はゲームごとに 1 から。開始の案内（host）で数え直し、質問（question）だけに付ける
export function numberQuestions(kinds) {
  let n = 0;
  return kinds.map((kind) => {
    if (kind === "host") {
      n = 0;
      return null;
    }
    if (kind !== "question") return null;
    n += 1;
    return n;
  });
}

// はい・いいえのどちらも 65% 未満なら「微妙な判定」。チップを薄くして伝える
const WEAK_BELOW = 65;

export function isWeak(yes) {
  return Math.max(yes, 100 - yes) < WEAK_BELOW;
}
