import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatRemaining,
  idleStatus,
  initialSelection,
  resultView,
  selectable,
  setupProblem,
  startMessage,
  voteTargets,
} from "../../src/insider_bot/web/static/insider.js";

const PLAYERS = [
  { id: 1, name: "たろう", online: true },
  { id: 2, name: "はなこ", online: true },
  { id: 3, name: "じろう", online: false },
  { id: 4, name: "さぶろう", online: true },
];

test("自分で決めるときは自分を選べない", () => {
  assert.deepEqual(
    selectable(PLAYERS, 1, "self").map((p) => p.id),
    [2, 3, 4],
  );
  assert.deepEqual(
    selectable(PLAYERS, 1, "random").map((p) => p.id),
    [1, 2, 3, 4],
  );
});

test("最初は接続中の人を選んでおく", () => {
  assert.deepEqual([...initialSelection(PLAYERS, 1, "random")], [1, 2, 4]);
  assert.deepEqual([...initialSelection(PLAYERS, 1, "self")], [2, 4]);
});

test("設定の検査", () => {
  const ok = { selected: new Set([1, 2, 4]), topicMode: "random", topic: "", minutes: null };
  assert.equal(setupProblem(ok), null);
  assert.equal(setupProblem({ ...ok, selected: new Set([1, 2]) }), "参加者を3人以上選んでください");
  assert.equal(setupProblem({ ...ok, topicMode: "self", topic: "  " }), "お題を入力してください");
  assert.equal(setupProblem({ ...ok, topicMode: "self", topic: "あ".repeat(51) }), "お題は50文字までです");
  assert.equal(setupProblem({ ...ok, minutes: 31 }), "制限時間は1〜30分で選んでください");
});

test("始めるメッセージ。お題は自分で決めるときだけ送る", () => {
  assert.deepEqual(startMessage({ selected: new Set([2, 4, 3]), topicMode: "self", topic: " もも ", minutes: 5 }), {
    type: "insider_start",
    participants: [2, 4, 3],
    topic_mode: "self",
    topic: "もも",
    minutes: 5,
  });
  assert.equal(startMessage({ selected: new Set([1, 2, 3]), topicMode: "random", topic: "もも", minutes: null }).topic, null);
});

test("残り時間", () => {
  assert.equal(formatRemaining(300), "5:00");
  assert.equal(formatRemaining(61.4), "1:02");
  assert.equal(formatRemaining(0), "0:00");
  assert.equal(formatRemaining(-3), "0:00");
});

test("投票の相手は自分以外の参加者", () => {
  const insider = { participants: [1, 2, 3] };
  assert.deepEqual(voteTargets(insider, PLAYERS, 2), [
    { id: 1, name: "たろう" },
    { id: 3, name: "じろう" },
  ]);
});

test("結果の表示", () => {
  const view = resultView({
    ending: "voted",
    topic: "すいか",
    insider: "たろう",
    insider_id: 1,
    guesser: "はなこ",
    winner: "villagers",
    votes: [
      { id: 1, name: "たろう", count: 2 },
      { id: 2, name: "はなこ", count: 1 },
    ],
  });
  assert.equal(view.headline, "村人の勝ち！");
  assert.equal(view.title, "インサイダーは たろう");
  assert.deepEqual(view.rows, [
    { name: "たろう", count: 2, insider: true },
    { name: "はなこ", count: 1, insider: false },
  ]);
  assert.equal(resultView({ ending: "time_up", topic: "すいか", insider: "たろう", winner: "none", votes: [] }).headline, "時間切れ　全員の負け…");
  assert.equal(resultView({ ending: "giveup", topic: null, insider: "たろう", winner: "none", votes: [] }).topic, null);
});

test("ゲームのない間の上のバー。お題待ちと投票中はそれを出す", () => {
  assert.equal(idleStatus(null), null);
  assert.equal(idleStatus({ phase: "done" }), null);
  assert.equal(idleStatus({ phase: "choosing" }), "インサイダーがお題を考えています…");
  assert.equal(idleStatus({ phase: "voting" }), "投票中 — インサイダーは誰？");
});
