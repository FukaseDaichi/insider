import assert from "node:assert/strict";
import { test } from "node:test";

import { isWerewordsCommand, quickReplies } from "../../src/insider_bot/web/static/quickreply.js";

const READY = { number: 4821, mode: "normal", has_topic: true, size: 5, member_count: 0, reverse: false };
const kinds = (chips) => chips.map((chip) => chip.kind);

test("村がない・人数が決まっていないときは出さない", () => {
  assert.deepEqual(quickReplies(null, {}), []);
  assert.deepEqual(quickReplies({ ...READY, size: 0 }, {}), []);
});

test("人を呼べる村では QR、まだ誰もいなければ逆村とワーワーズも出す", () => {
  const chips = quickReplies(READY, {});
  assert.deepEqual(kinds(chips), ["invite", "reverse", "werewords"]);
  assert.deepEqual(chips[0], { kind: "invite", label: "QR を見せる", number: 4821 });
  assert.deepEqual(chips[1], { kind: "reverse", label: "逆村にする", text: "@逆村" });
  assert.deepEqual(chips[2], { kind: "werewords", label: "ワーワーズにする", text: "@わーわーず" });
});

test("誰か入った村では QR だけ", () => {
  assert.deepEqual(kinds(quickReplies({ ...READY, member_count: 1 }, {})), ["invite"]);
});

test("逆村にした村とランダム村には逆村を出さない", () => {
  assert.deepEqual(kinds(quickReplies({ ...READY, reverse: true }, {})), ["invite", "werewords"]);
  assert.deepEqual(kinds(quickReplies({ ...READY, mode: "random" }, {})), ["invite", "werewords"]);
});

test("ワーワーズは 3 人以上でお題があるときだけ", () => {
  assert.deepEqual(kinds(quickReplies({ ...READY, size: 2 }, {})), ["invite", "reverse"]);
  assert.deepEqual(kinds(quickReplies({ ...READY, has_topic: false }, {})), ["invite", "reverse"]);
});

test("ワーワーズにした後は、新しい村の QR と、GM でなければ入るボタンだけ", () => {
  const converted = { 4821: 50123 };
  assert.deepEqual(quickReplies(READY, converted), [
    { kind: "invite", label: "QR を見せる", number: 50123 },
    { kind: "send", label: "ワーワーズの村に入る", text: "50123" },
  ]);
  assert.deepEqual(kinds(quickReplies({ ...READY, mode: "god" }, converted)), ["invite"]);
});

test("ワーワーズのコマンドは LINE と同じく、前後の半角の空白を除いて全角・半角の @ で判定する", () => {
  assert.equal(isWerewordsCommand("@わーわーず"), true);
  assert.equal(isWerewordsCommand(" ＠わーわーず\n"), true);
  // 全角スペースは除かない（お題になる）
  assert.equal(isWerewordsCommand("　@わーわーず"), false);
  assert.equal(isWerewordsCommand("@逆村"), false);
});
