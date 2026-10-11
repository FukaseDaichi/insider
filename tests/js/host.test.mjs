import assert from "node:assert/strict";
import { test } from "node:test";

import { HOST_POSES, hostEntry, hostImage, hostLines } from "../../src/insider_bot/web/static/host.js";

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

test("kind が host の記録は、data の絵（pose）とセリフ（lines）で吹き出しにする", () => {
  assert.deepEqual(
    hostEntry({ text: "🕵️ インサイダーがお題を考えています…", kind: "host", data: { pose: "secret", lines: ["役職を配ったよ。", "しーっ。"] } }),
    { pose: "secret", lines: ["役職を配ったよ。", "しーっ。"], start: false },
  );
});

test("🎮 の開始の案内は、既定の絵の吹き出しにし、質問番号を数え直す印をつける", () => {
  assert.deepEqual(hostEntry({ text: "🎮 お題が設定されました！\n質問どうぞ。", author: null }), {
    pose: "start",
    lines: ["お題が設定されました！", "質問どうぞ。"],
    start: true,
  });
});

test("質問者のいる発言・判定中・data のない host・それ以外の記録は吹き出しにしない", () => {
  for (const entry of [
    { text: "🎮 開始", author: "たろう" },
    { text: "🎮 開始", author: null, pending: true },
    { text: "🕵️ …", kind: "host" },
    { text: "🕵️ …", kind: "insider_result", data: { winner: "insider" } },
    { text: "果物ですか？", author: "たろう" },
  ]) {
    assert.equal(hostEntry(entry), null, JSON.stringify(entry));
  }
});

test("絵は pose ごとに決まり、知らない pose は既定の絵にする", () => {
  assert.equal(hostImage("start"), "/static/host.png");
  assert.notEqual(hostImage("secret"), undefined);
  assert.equal(hostImage("unknown"), "/static/host.png");
  assert.equal(hostImage(undefined), "/static/host.png");
});

test("どの pose の絵も static に置いてある", async () => {
  const { existsSync } = await import("node:fs");
  const { fileURLToPath } = await import("node:url");
  const staticDir = fileURLToPath(new URL("../../src/insider_bot/web/static/", import.meta.url));
  for (const pose of HOST_POSES) {
    const src = hostImage(pose);
    assert.ok(src.startsWith("/static/"), src);
    assert.ok(existsSync(staticDir + src.slice("/static/".length)), `${pose}: ${src}`);
  }
});
