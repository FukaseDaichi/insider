import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isWeak,
  numberQuestions,
  questionNote,
  resultOf,
} from "../../src/insider_bot/web/static/log.js";

test("判定中の質問は、質問文と状態を取り出す", () => {
  assert.deepEqual(questionNote("❓ 果物ですか？\n… 判定中"), {
    question: "果物ですか？",
    note: "判定中…",
    cancelled: false,
  });
});

test("ゲームが終わって取り消された質問は、取り消しとして取り出す", () => {
  assert.deepEqual(
    questionNote("❓ りんごですか？\n— ゲームが終わったため取り消しました"),
    { question: "りんごですか？", note: "取り消し", cancelled: true },
  );
});

test("質問文に改行があっても、最後の行だけを状態として読む", () => {
  assert.deepEqual(questionNote("❓ 赤い\nですか？\n… 判定中"), {
    question: "赤い\nですか？",
    note: "判定中…",
    cancelled: false,
  });
});

test("回答や通知は、判定中の質問ではない", () => {
  for (const text of [
    "❓ 果物ですか？\n✅ はい　　はい 93% ███████████░ いいえ 7%",
    "お題『りんご』を登録しました",
    "❓ 果物ですか？",
    "",
  ]) {
    assert.equal(questionNote(text), null, text);
  }
});

test("正解は、見出しと内訳に分ける", () => {
  assert.deepEqual(
    resultOf(
      "🎉 正解です！お題は「りんご」でした\n正解者: ふかせ　質問数: 9　経過時間: 4分12秒",
    ),
    {
      kind: "correct",
      title: "正解です！お題は「りんご」でした",
      meta: "正解者: ふかせ　質問数: 9　経過時間: 4分12秒",
    },
  );
});

test("ギブアップは、内訳なしの見出しだけ", () => {
  assert.deepEqual(
    resultOf("🏳️ ギブアップ！お題は『りんご』でした（質問数: 3）"),
    {
      kind: "giveup",
      title: "ギブアップ！お題は『りんご』でした（質問数: 3）",
      meta: null,
    },
  );
});

test("正解でもギブアップでもない発言は結果ではない", () => {
  for (const text of ["果物ですか？", "🎮 お題が設定されました！", "⚠️ 判定できませんでした。もう一度どうぞ", ""]) {
    assert.equal(resultOf(text), null, text);
  }
});

test("質問番号はゲームの開始ごとに 01 から数え直し、質問以外には付けない", () => {
  assert.deepEqual(
    numberQuestions([
      "system",
      "host",
      "question",
      "question",
      "system",
      "question",
      "result",
      "host",
      "question",
    ]),
    [null, null, 1, 2, null, 3, null, null, 1],
  );
});

test("履歴の先頭が切れて開始の案内がなくても、質問は 1 から数える", () => {
  assert.deepEqual(numberQuestions(["question", "question"]), [1, 2]);
});

test("弱い判定は、はい・いいえのどちらも 65% 未満のとき", () => {
  assert.equal(isWeak(64), true);
  assert.equal(isWeak(36), true);
  assert.equal(isWeak(50), true);
  assert.equal(isWeak(65), false);
  assert.equal(isWeak(35), false);
  assert.equal(isWeak(93), false);
});
