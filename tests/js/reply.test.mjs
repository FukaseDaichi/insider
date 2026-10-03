import assert from "node:assert/strict";
import { test } from "node:test";

import { actionView, replyView, safeUrl } from "../../src/insider_bot/web/static/reply.js";

const ORIGIN = "https://game.example.com";

test("自サイトの絶対パスと https の URL だけを使う", () => {
  assert.equal(safeUrl("/static/roles/GM.png", ORIGIN), `${ORIGIN}/static/roles/GM.png`);
  assert.equal(safeUrl("https://lh3.googleusercontent.com/x", ORIGIN), "https://lh3.googleusercontent.com/x");
  for (const url of ["javascript:alert(1)", "data:image/png;base64,AAAA", "http://evil.example/x.png", "", null, undefined, 3]) {
    assert.equal(safeUrl(url, ORIGIN), null, String(url));
  }
});

test("手元の http で動かしていても、自サイトの画像は使う", () => {
  assert.equal(safeUrl("/static/roles/GM.png", "http://localhost:8080"), "http://localhost:8080/static/roles/GM.png");
});

test("文字と画像", () => {
  assert.deepEqual(replyView({ type: "text", text: "本文\n2 行目" }, ORIGIN), { kind: "text", text: "本文\n2 行目" });
  assert.deepEqual(replyView({ type: "image", url: "/static/roles/966mpnqz.png" }, ORIGIN), {
    kind: "image",
    src: `${ORIGIN}/static/roles/966mpnqz.png`,
  });
});

test("ボタンはカードにし、押したときの動作を種類ごとに決める", () => {
  const reply = {
    type: "buttons",
    text: "お題は「すいか」です。確定しますか？",
    image: null,
    title: null,
    actions: [
      { type: "message", label: "確定", text: "すいか" },
      { type: "postback", label: "初心者", data: "2" },
      { type: "uri", label: "ご意見", uri: "https://forms.example/x" },
    ],
  };
  assert.deepEqual(replyView(reply, ORIGIN), {
    kind: "card",
    title: null,
    text: "お題は「すいか」です。確定しますか？",
    image: null,
    actions: [
      { label: "確定", kind: "text", value: "すいか" },
      { label: "初心者", kind: "postback", value: "2" },
      { label: "ご意見", kind: "link", value: "https://forms.example/x" },
    ],
  });
});

test("画像と見出しのあるボタン（人数設定の返事）", () => {
  const view = replyView(
    { type: "buttons", text: "人数を『3人』に設定しました。", image: "/static/roles/GM.png", title: "1234村", actions: [] },
    ORIGIN,
  );
  assert.equal(view.image, `${ORIGIN}/static/roles/GM.png`);
  assert.equal(view.title, "1234村");
});

test("確認テンプレートもカードにする", () => {
  const view = replyView(
    { type: "confirm", text: "村の作成をしますか？", actions: [{ type: "message", label: "GM", text: "お題" }] },
    ORIGIN,
  );
  assert.equal(view.kind, "card");
  assert.deepEqual(view.actions, [{ label: "GM", kind: "text", value: "お題" }]);
});

test("知らない形・使えない URL の画像やリンクは描かない", () => {
  assert.equal(replyView({ type: "video" }, ORIGIN), null);
  assert.equal(replyView(null, ORIGIN), null);
  assert.equal(replyView({ type: "image", url: "javascript:alert(1)" }, ORIGIN), null);
  assert.equal(actionView({ type: "uri", label: "x", uri: "javascript:alert(1)" }, ORIGIN), null);
  assert.equal(actionView({ type: "camera", label: "x" }, ORIGIN), null);
  const view = replyView(
    { type: "buttons", text: "本文", image: "http://evil.example/x.png", title: null, actions: [{ type: "camera" }] },
    ORIGIN,
  );
  assert.equal(view.image, null);
  assert.deepEqual(view.actions, []);
});
