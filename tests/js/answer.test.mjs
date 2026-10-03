import assert from "node:assert/strict";
import { test } from "node:test";
import { parseAnswer } from "../../src/insider_bot/web/static/answer.js";

test("はい・いいえの割合を失わずに表示用へ変換する", () => {
  assert.deepEqual(
    parseAnswer("❓ 果物ですか？\n✅ はい　　はい 82% ██████████░░ いいえ 18%"),
    { question: "果物ですか？", positive: true, yes: 82, no: 18 },
  );
  assert.deepEqual(
    parseAnswer(
      "❓ 動物ですか？\n❌ いいえ　　はい 0% ░░░░░░░░░░░░ いいえ 100%",
    ),
    { question: "動物ですか？", positive: false, yes: 0, no: 100 },
  );
});
test("改行やHTMLに見える質問も文字列のまま保つ", () => {
  assert.equal(
    parseAnswer(
      "❓ <img src=x>\n果物？\n✅ はい　　はい 100% ████████████ いいえ 0%",
    ).question,
    "<img src=x>\n果物？",
  );
});
test("正解・判定中・未知の形式・不正な割合は本文表示に戻す", () => {
  for (const text of [
    "🎉 正解です！お題は「りんご」でした",
    "❓ 果物？\n… 判定中",
    "新しい形式",
    "❓ 果物？\n✅ はい　　はい 110% ████████████ いいえ 0%",
    "❓ 果物？\n✅ はい　　はい 82% ██████████░░ いいえ 20%",
  ])
    assert.equal(parseAnswer(text), null);
});
