import assert from "node:assert/strict";
import { test } from "node:test";

import {
  appendEntry,
  emptyLog,
  forgetConverted,
  LOG_KEY,
  loadLog,
  markConverted,
  MAX_ENTRIES,
  saveLog,
  shouldAutoJoin,
  statusEntry,
  statusNumber,
  updateEntry,
} from "../../src/insider_bot/web/static/talklog.js";

class MemoryStorage {
  constructor(entries = {}) {
    this.map = new Map(Object.entries(entries));
  }

  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }

  setItem(key, value) {
    this.map.set(key, value);
  }

  removeItem(key) {
    this.map.delete(key);
  }
}

class BrokenStorage {
  getItem() {
    throw new Error("blocked");
  }

  setItem() {
    throw new Error("blocked");
  }
}

const TEXT = [{ type: "text", text: "こんにちは" }];

test("足した発言には番号と時刻が付き、元の履歴は変えない", () => {
  const log = emptyLog();
  const { log: next, entry } = appendEntry(log, { from: "me", text: "お題" }, 1000);
  assert.deepEqual(entry, { id: 1, at: 1000, from: "me", text: "お題" });
  assert.deepEqual(next.entries, [entry]);
  assert.equal(next.nextId, 2);
  assert.deepEqual(log.entries, []);
});

test("履歴は新しいほうから決まった件数だけ残す", () => {
  let log = emptyLog();
  for (let i = 0; i < MAX_ENTRIES + 5; i++) log = appendEntry(log, { from: "me", text: String(i) }, i).log;
  assert.equal(log.entries.length, MAX_ENTRIES);
  assert.equal(log.entries[0].text, "5");
  assert.equal(log.entries.at(-1).text, String(MAX_ENTRIES + 4));
});

test("配布状況として書き換えるのは、いちばん新しい 1 つだけ", () => {
  let log = emptyLog();
  log = appendEntry(log, { from: "bot", replies: TEXT, status: 4821 }, 1).log;
  assert.equal(statusEntry(log).status, 4821);
  log = appendEntry(log, { from: "bot", replies: TEXT, status: 4821 }, 2).log;
  assert.deepEqual(
    log.entries.map((entry) => entry.status),
    [undefined, 4821],
  );
  assert.equal(statusEntry(log).id, 2);
  log = appendEntry(log, { from: "bot", replies: TEXT }, 3).log;
  // 後に別の返事が来ても、最新の配布状況は書き換え続ける
  assert.equal(statusEntry(log).id, 2);
});

test("配布状況がなければ null", () => {
  assert.equal(statusEntry(emptyLog()), null);
});

test("番号で選んだ発言だけを書き換える", () => {
  let log = emptyLog();
  log = appendEntry(log, { from: "me", text: "a" }, 1).log;
  log = appendEntry(log, { from: "me", text: "b" }, 2).log;
  const next = updateEntry(log, 2, { failed: true });
  assert.equal(next.entries[1].failed, true);
  assert.equal(next.entries[0].failed, undefined);
  assert.equal(log.entries[1].failed, undefined);
});

test("保存して読み直すと同じ履歴になる", () => {
  const storage = new MemoryStorage();
  let log = appendEntry(emptyLog(), { from: "bot", replies: TEXT }, 5).log;
  log = markConverted(log, 4821, 50123);
  assert.equal(saveLog(storage, log), true);
  assert.deepEqual(loadLog(storage), log);
});

test("読めない・壊れた・形の違う履歴は空から始める", () => {
  assert.deepEqual(loadLog(new BrokenStorage()), emptyLog());
  assert.deepEqual(loadLog(null), emptyLog());
  assert.deepEqual(loadLog(new MemoryStorage({ [LOG_KEY]: "{" })), emptyLog());
  assert.deepEqual(loadLog(new MemoryStorage({ [LOG_KEY]: "[]" })), emptyLog());
  assert.deepEqual(loadLog(new MemoryStorage({ [LOG_KEY]: '{"entries":3}' })), emptyLog());
  assert.equal(saveLog(new BrokenStorage(), emptyLog()), false);
});

test("形の違う発言だけを捨て、番号は残った発言より先から振る", () => {
  const saved = {
    entries: [
      { id: 1, at: 1, from: "me", text: "お題" },
      { id: 2, at: 2, from: "bot", replies: "x" },
      { id: 3, at: 3, from: "stranger", text: "?" },
      { id: 4, at: 4, from: "bot", replies: TEXT },
      { id: 9, at: 5, from: "bot", invite: 4821 },
      { id: 10, at: 6, from: "bot", invite: "4821" },
      { id: 11, at: 7, from: "system", text: "通信に失敗しました" },
      null,
    ],
    nextId: 1,
    converted: { 4821: 50123, x: "y" },
  };
  const log = loadLog(new MemoryStorage({ [LOG_KEY]: JSON.stringify(saved) }));
  assert.deepEqual(
    log.entries.map((entry) => entry.id),
    [1, 4, 9, 11],
  );
  assert.equal(log.nextId, 12);
  assert.deepEqual(log.converted, { 4821: 50123 });
});

test("ワーワーズにした村を覚え、同じ番号の村が新しく作られたら忘れる", () => {
  const log = markConverted(markConverted(emptyLog(), 4821, 50123), 6000, 70000);
  assert.deepEqual(log.converted, { 4821: 50123, 6000: 70000 });
  assert.deepEqual(forgetConverted(log, 4821).converted, { 6000: 70000 });
  assert.equal(forgetConverted(log, 1234), log);
});

test("URL から入るとき、最後に送ったのが同じ番号なら送り直さない", () => {
  let log = emptyLog();
  assert.equal(shouldAutoJoin(log, 4821), true);
  log = appendEntry(log, { from: "me", text: "4821" }, 1).log;
  log = appendEntry(log, { from: "bot", replies: TEXT }, 2).log;
  assert.equal(shouldAutoJoin(log, 4821), false);
  assert.equal(shouldAutoJoin(log, 5000), true);
  log = appendEntry(log, { from: "me", text: "お題" }, 3).log;
  assert.equal(shouldAutoJoin(log, 4821), true);
});

test("自分の村の番号を送ったときだけ、返事を配布状況として扱う", () => {
  const village = { number: 4821, mode: "normal", has_topic: true, size: 5, member_count: 0, reverse: false };
  assert.equal(statusNumber("4821", village), 4821);
  assert.equal(statusNumber(" ４８２１ ", village), 4821);
  assert.equal(statusNumber("4822", village), null);
  assert.equal(statusNumber("お題", village), null);
  assert.equal(statusNumber("4821", null), null);
  // 人数が決まる前は配布状況にならない
  assert.equal(statusNumber("4821", { ...village, size: 0 }), null);
  // ランダム村のオーナーには自分の役職が返る
  assert.equal(statusNumber("4821", { ...village, mode: "random" }), null);
});
