import assert from "node:assert/strict";
import { test } from "node:test";

import { hostLines } from "../../src/insider_bot/web/static/host.js";

test("ゲーム開始の案内は、先頭の絵文字を外して改行ごとに吹き出しの行として取り出す", () => {
  assert.deepEqual(hostLines("🎮 お題が設定されました！\n質問どうぞ。"), [
    "お題が設定されました！",
    "質問どうぞ。",
  ]);
});

test("改行のない古い開始メッセージも、絵文字を外した 1 行の案内として扱う", () => {
  assert.deepEqual(
    hostLines("🎮 ゲーム開始！お題が出されました。「🎙 押して話す」で質問をどうぞ"),
    ["ゲーム開始！お題が出されました。「🎙 押して話す」で質問をどうぞ"],
  );
});

test("質問や正解など、開始以外の発言は案内ではない", () => {
  for (const text of ["果物ですか？", "🎉 正解です！お題は「りんご」でした", "", "ゲーム開始！"]) {
    assert.equal(hostLines(text), null, text);
  }
});
