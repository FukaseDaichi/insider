import assert from "node:assert/strict";
import { test } from "node:test";

import { mergeResults } from "../../src/insider_bot/web/static/speech.js";

// SpeechRecognitionResult の代わり: 候補の配列に isFinal を付けたもの
const result = (transcript, isFinal) => Object.assign([{ transcript }], { isFinal });

test("未確定の結果だけなら、未確定の文字として持つ", () => {
  assert.deepEqual(mergeResults("", [result("くだもの", false)], 0), { finals: "", interim: "くだもの" });
});

test("確定した後に届いた未確定の末尾を捨てない", () => {
  const first = mergeResults("", [result("赤い", true)], 0);
  const second = mergeResults(first.finals, [result("赤い", true), result("果物ですか", false)], 1);
  assert.deepEqual(second, { finals: "赤い", interim: "果物ですか" });
});

test("一度確定した結果を二重に数えない", () => {
  const first = mergeResults("", [result("赤い", true)], 0);
  const second = mergeResults(first.finals, [result("赤い", true), result("果物ですか", true)], 1);
  assert.deepEqual(second, { finals: "赤い果物ですか", interim: "" });
});

test("聞き直した後は、それまでの確定分に新しい結果を足す", () => {
  assert.deepEqual(mergeResults("赤い", [result("丸い", true)], 0), { finals: "赤い丸い", interim: "" });
});
