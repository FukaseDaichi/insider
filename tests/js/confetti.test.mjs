import assert from "node:assert/strict";
import { test } from "node:test";

import { burst, fireCrackers, step } from "../../src/insider_bot/web/static/confetti.js";

const middle = () => 0.5;

// 紙片が全部消えるまで 1 フレームずつ動かし、いちばん高く上がった位置を返す
function highest(particles, height) {
  let top = height;
  for (let frame = 0; particles.length && frame < 1000; frame++) {
    particles = step(particles, 1, height);
    for (const p of particles) top = Math.min(top, p.y);
  }
  assert.equal(particles.length, 0, "紙片が消えずに残った");
  return top;
}

test("左のクラッカーは左下の隅から右上へ飛ぶ", () => {
  const particles = burst("left", 400, 800, Math.random);
  assert.ok(particles.length > 0);
  for (const p of particles) {
    assert.equal(p.x, 0);
    assert.equal(p.y, 800);
    assert.ok(p.vx > 0, "右へ");
    assert.ok(p.vy < 0, "上へ");
  }
});

test("右のクラッカーは右下の隅から左上へ飛ぶ", () => {
  for (const p of burst("right", 400, 800, Math.random)) {
    assert.equal(p.x, 400);
    assert.equal(p.y, 800);
    assert.ok(p.vx < 0, "左へ");
    assert.ok(p.vy < 0, "上へ");
  }
});

test("どの高さの画面でも、高さの 6〜8 割まで上がってから落ちて消える", () => {
  for (const height of [500, 900]) {
    const rise = (height - highest(burst("left", 400, height, middle), height)) / height;
    assert.ok(rise > 0.6 && rise < 0.8, `高さ ${height}: ${rise}`);
  }
});

test("画面の下へ抜けた紙片と、寿命が尽きた紙片は消える", () => {
  const [below, old, alive] = burst("left", 400, 800, middle);
  below.y = 900;
  old.t = old.life;
  assert.deepEqual(step([below, old, alive], 1, 800), [alive]);
});

test("落ちる速さには上限がある", () => {
  const [p] = burst("left", 400, 600, middle);
  for (let frame = 0; frame < 200; frame++) step([p], 1, 10_000);
  const fallen = p.y;
  step([p], 1, 10_000);
  assert.ok(p.y - fallen < 5, `1 フレームで ${p.y - fallen}px`);
});

function fakePage({ hidden = false, reduced = false } = {}) {
  const appended = [];
  return {
    appended,
    doc: {
      visibilityState: hidden ? "hidden" : "visible",
      body: { append: (node) => appended.push(node) },
      createElement: () => ({ getContext: () => null }),
    },
    view: { matchMedia: () => ({ matches: reduced }) },
  };
}

test("画面が裏にあるときは出さない", () => {
  const page = fakePage({ hidden: true });
  assert.equal(fireCrackers(page), false);
  assert.deepEqual(page.appended, []);
});

test("視差効果を減らす設定では出さない", () => {
  const page = fakePage({ reduced: true });
  assert.equal(fireCrackers(page), false);
  assert.deepEqual(page.appended, []);
});
