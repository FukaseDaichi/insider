import assert from "node:assert/strict";
import { test } from "node:test";

import {
  dialogsToClose,
  formatRemaining,
  idleStatus,
  initialSelection,
  nameLabels,
  resultView,
  selectable,
  setupProblem,
  startMessage,
  voteSummary,
  voteTargets,
  voteWaiting,
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
  assert.equal(view.headline, "村人の勝ち！！");
  assert.equal(view.title, "インサイダーは たろう");
  assert.deepEqual(view.rows, [
    { name: "たろう", count: 2, insider: true },
    { name: "はなこ", count: 1, insider: false },
  ]);
  assert.equal(resultView({ ending: "time_up", topic: "すいか", insider: "たろう", winner: "none", votes: [] }).headline, "全員の負け…");
  assert.equal(resultView({ ending: "giveup", topic: null, insider: "たろう", winner: "none", votes: [] }).topic, null);
});

test("ゲームのない間の上のバー。お題待ちと投票中はそれを出す", () => {
  assert.equal(idleStatus(null), null);
  assert.equal(idleStatus({ phase: "done" }), null);
  assert.equal(idleStatus({ phase: "choosing" }), "インサイダーがお題を考えています…");
  assert.equal(idleStatus({ phase: "voting" }), "投票中 — インサイダーは誰？");
});

test("畳んだ帯には、進み具合と自分の票を 1 行で出す", () => {
  const insider = { participants: [1, 2, 3], voted: [2], you: { vote: null } };
  assert.equal(voteSummary(insider, PLAYERS), "投票中 1 / 3 人 ・ あなたの票：まだ");
  assert.equal(
    voteSummary({ participants: [1, 2, 3], voted: [1, 2], you: { vote: 1 } }, PLAYERS),
    "投票中 2 / 3 人 ・ あなたの票：たろう",
  );
});

test("開いた中には、まだ入れていない人の名前を出す", () => {
  assert.equal(voteWaiting({ participants: [1, 2, 3], voted: [2] }, PLAYERS), "まだ：たろう・じろう");
  assert.equal(voteWaiting({ participants: [1, 2, 3], voted: [1, 2, 3] }, PLAYERS), "全員が投票しました。開票できます");
});

const TWINS = [
  { id: 1, name: "たろう", online: true },
  { id: 2, name: "はなこ", online: true },
  { id: 5, name: "たろう", online: true },
];

test("同じ名前の人には、入った順に番号を添えて見分ける", () => {
  assert.deepEqual([...nameLabels(TWINS)], [
    [1, "たろう（1）"],
    [2, "はなこ"],
    [5, "たろう（2）"],
  ]);
  assert.deepEqual(
    voteTargets({ participants: [1, 2, 5] }, TWINS, 2).map((t) => t.name),
    ["たろう（1）", "たろう（2）"],
  );
  assert.equal(voteWaiting({ participants: [1, 2, 5], voted: [2] }, TWINS), "まだ：たろう（1）・たろう（2）");
  assert.equal(
    voteSummary({ participants: [1, 2, 5], voted: [2], you: { vote: 5 } }, TWINS),
    "投票中 1 / 3 人 ・ あなたの票：たろう（2）",
  );
  const view = resultView(
    {
      ending: "voted",
      topic: "すいか",
      insider: "たろう",
      insider_id: 5,
      winner: "insider",
      votes: [
        { id: 1, name: "たろう", count: 1 },
        { id: 5, name: "たろう", count: 1 },
      ],
    },
    TWINS,
  );
  assert.equal(view.title, "インサイダーは たろう（2）");
  assert.deepEqual(view.rows.map((row) => row.name), ["たろう（1）", "たろう（2）"]);
});

test("状態が変わったら、もう意味のないダイアログを閉じる", () => {
  const asking = { phase: "asking", participants: [1, 2, 3], you: { role: "villager" } };
  const voting = { ...asking, phase: "voting" };
  const done = { ...asking, phase: "done" };
  assert.deepEqual(dialogsToClose(asking, asking), ["insider-cancel-dialog", "close-vote-dialog"]);
  assert.deepEqual(dialogsToClose(voting, voting), ["insider-cancel-dialog"]);
  assert.deepEqual(dialogsToClose(voting, done), ["insider-cancel-dialog", "close-vote-dialog"]);
  // 次のゲームが始まった（回がなくなった・新しい回になった）ら、前の役職のカードも閉じる
  assert.deepEqual(dialogsToClose(done, null), ["role-dialog", "insider-cancel-dialog", "close-vote-dialog"]);
  assert.deepEqual(dialogsToClose(done, { ...asking, phase: "choosing" }), ["role-dialog", "close-vote-dialog"]);
});

test("結果のカードの見た目は勝った側で決まり、負けのときは終わり方のラベルを添える", () => {
  const base = { topic: "すいか", insider: "たろう", insider_id: 1, votes: [] };
  assert.equal(resultView({ ...base, ending: "voted", winner: "villagers" }).look, "villagers");
  assert.equal(resultView({ ...base, ending: "voted", winner: "villagers" }).label, null);
  assert.equal(resultView({ ...base, ending: "voted", winner: "insider" }).look, "insider");
  assert.equal(resultView({ ...base, ending: "time_up", winner: "none" }).look, "lose");
  assert.equal(resultView({ ...base, ending: "time_up", winner: "none" }).label, "時間切れ");
  assert.equal(resultView({ ...base, ending: "giveup", winner: "none" }).label, "ギブアップ");
  assert.equal(resultView({ ...base, ending: "giveup", winner: "none" }).headline, "全員の負け…");
  // 勝ったときの見出しはテロップにするので、1 文字ずつ跳ねられるよう「！！」で終える
  assert.equal(resultView({ ...base, ending: "voted", winner: "villagers" }).headline, "村人の勝ち！！");
  assert.equal(resultView({ ...base, ending: "voted", winner: "insider" }).headline, "インサイダーの勝ち！！");
  // スマホで語の途中で折り返さないよう、テロップは語ごとに分けて持つ
  assert.deepEqual(resultView({ ...base, ending: "voted", winner: "insider" }).telop, ["インサイダーの", "勝ち！！"]);
  assert.equal(resultView({ ...base, ending: "giveup", winner: "none" }).telop, null);
  // インサイダーの名前は札でいったん隠してから明かすので、文と名前を分けて持つ
  assert.deepEqual(resultView({ ...base, ending: "voted", winner: "insider" }, PLAYERS).reveal, { lead: "インサイダーは", name: "たろう" });
});
