import assert from "node:assert/strict";
import { test } from "node:test";

import { ASK_ACK_TIMEOUT_MS, AskWatch } from "../../src/insider_bot/web/static/askwatch.js";

test("送った後に何も届かなければ、時間切れで届いていない質問として知らせる", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const lost = [];
  const watch = new AskWatch((text) => lost.push(text));
  watch.sent("果物ですか");
  t.mock.timers.tick(ASK_ACK_TIMEOUT_MS - 1);
  assert.deepEqual(lost, []);
  t.mock.timers.tick(1);
  assert.deepEqual(lost, ["果物ですか"]);
});

test("送った後にサーバーから何か届けば、知らせない", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const lost = [];
  const watch = new AskWatch((text) => lost.push(text));
  watch.sent("果物ですか");
  watch.received();
  t.mock.timers.tick(ASK_ACK_TIMEOUT_MS * 2);
  assert.deepEqual(lost, []);
});

test("接続が切れたら、時間切れを待たずに待っている質問をすべて知らせる", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const lost = [];
  const watch = new AskWatch((text) => lost.push(text));
  watch.sent("果物ですか");
  watch.sent("赤いですか");
  watch.lost();
  assert.deepEqual(lost, ["果物ですか", "赤いですか"]);
  t.mock.timers.tick(ASK_ACK_TIMEOUT_MS * 2);
  assert.equal(lost.length, 2);
});
