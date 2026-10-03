import assert from "node:assert/strict";
import { test } from "node:test";

import { placeChrome, watchCompact } from "../../src/insider_bot/web/static/layout.js";

// DOM の append と同じく「別の親から外して末尾に付ける」だけの最小の親
function slot(name) {
  return {
    name,
    children: [],
    append(node) {
      node.parent?.children.splice(node.parent.children.indexOf(node), 1);
      this.children.push(node);
      node.parent = this;
    },
  };
}

test("狭い画面では固定情報をメニュー側へ移し、広い画面では元の場所へ戻す", () => {
  const header = slot("header");
  const menu = slot("menu");
  const players = { parent: null };
  header.append(players);
  const moves = [{ node: players, wide: header, narrow: menu }];

  placeChrome(true, moves);
  assert.deepEqual(menu.children, [players]);
  assert.deepEqual(header.children, []);

  placeChrome(false, moves);
  assert.deepEqual(header.children, [players]);
  assert.deepEqual(menu.children, []);
});

test("同じ向きに二度並べ直しても要素は増えず、並び順も保つ", () => {
  const header = slot("header");
  const menu = slot("menu");
  const invite = { parent: null };
  const players = { parent: null };
  header.append(invite);
  header.append(players);
  const moves = [
    { node: invite, wide: header, narrow: menu },
    { node: players, wide: header, narrow: menu },
  ];

  placeChrome(true, moves);
  placeChrome(true, moves);
  assert.deepEqual(menu.children, [invite, players]);
  assert.deepEqual(header.children, []);
});

test("画面幅の見張りは最初の状態をすぐ知らせ、その後の変化も知らせる", () => {
  const listeners = [];
  const media = {
    matches: true,
    addEventListener: (type, fn) => listeners.push([type, fn]),
  };
  const seen = [];
  watchCompact(media, (compact) => seen.push(compact));
  assert.deepEqual(seen, [true]);

  for (const [type, fn] of listeners) if (type === "change") fn({ matches: false });
  assert.deepEqual(seen, [true, false]);
});
