import assert from "node:assert/strict";
import { test } from "node:test";

import { messagesProblem, parseMessages } from "../../src/insider_bot/web/static/specialform.js";

test("1 行 1 通。CRLF と CR も区切りにする", () => {
  assert.deepEqual(parseMessages("a\r\nb\nc\rd"), ["a", "b", "c", "d"]);
});

test("末尾の空行は数えず、途中の空行は空のメッセージにする", () => {
  assert.deepEqual(parseMessages("a\n\nb\n\n \n"), ["a", "", "b"]);
  assert.deepEqual(parseMessages("\na"), ["", "a"]);
});

test("空白だけの行も、途中にあればそのまま送る", () => {
  assert.deepEqual(parseMessages("a\n \nb"), ["a", " ", "b"]);
});

test("何も書いていなければ 0 通", () => {
  assert.deepEqual(parseMessages(""), []);
  assert.deepEqual(parseMessages("\n \n"), []);
});

test("送れない理由を返し、送れるなら null", () => {
  assert.equal(messagesProblem([]), "メッセージを 1 行以上入力してください");
  assert.equal(messagesProblem(Array(101).fill("a")), "メッセージは 100 通までです（いま 101 通）");
  assert.equal(messagesProblem(["a", "😀".repeat(2500) + "a"]), "2 行目が 5000 文字を超えています");
  assert.equal(messagesProblem(Array(100).fill("😀".repeat(2500))), null);
});
