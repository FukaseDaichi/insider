import assert from "node:assert/strict";
import { test } from "node:test";

import { SoundPlayer } from "../../src/insider_bot/web/static/sound.js";

const SILENCE = "無音";

class FakeContext {
  constructor({ resumable = true } = {}) {
    this.state = "suspended";
    this.resumable = resumable;
    this.resumeCalls = 0;
    this.started = [];
    this.destination = {};
  }

  resume() {
    this.resumeCalls += 1;
    if (this.resumable) this.state = "running";
    return Promise.resolve();
  }

  decodeAudioData(data) {
    return Promise.resolve({ decoded: data });
  }

  createBuffer() {
    return SILENCE;
  }

  createBufferSource() {
    const started = this.started;
    return {
      buffer: null,
      connect() {},
      start() {
        started.push(this.buffer);
      },
    };
  }
}

function setup({ context = new FakeContext(), load } = {}) {
  const target = new EventTarget();
  const loads = [];
  const player = new SoundPlayer({
    createContext: () => context,
    load:
      load ??
      ((src) => {
        loads.push(src);
        return Promise.resolve(`中身:${src}`);
      }),
  });
  player.unlockOn(target);
  const played = () => context.started.filter((buffer) => buffer !== SILENCE);
  return { player, target, context, loads, played };
}

test("画面を一度も操作していなければ、鳴らさず読み込みもしない", async () => {
  const { player, loads, played } = setup();
  await player.play("/static/sounds/start-1.m4a");
  assert.deepEqual(loads, []);
  assert.deepEqual(played(), []);
});

test("操作のあとに合図が来たら、その音を鳴らす", async () => {
  const { player, target, played } = setup();
  target.dispatchEvent(new Event("pointerdown"));
  await player.play("/static/sounds/start-2.m4a");
  assert.deepEqual(played(), [{ decoded: "中身:/static/sounds/start-2.m4a" }]);
});

test("同じ音は読み込みを使い回す", async () => {
  const { player, target, loads, played } = setup();
  target.dispatchEvent(new Event("keydown"));
  await player.play("/static/sounds/start-1.m4a");
  await player.play("/static/sounds/start-1.m4a");
  assert.deepEqual(loads, ["/static/sounds/start-1.m4a"]);
  assert.equal(played().length, 2);
});

test("読み込みに失敗しても例外を出さず、次の合図では読み直す", async () => {
  let attempts = 0;
  const { player, target, played } = setup({
    load: (src) => {
      attempts += 1;
      return attempts === 1
        ? Promise.reject(new Error("offline"))
        : Promise.resolve(`中身:${src}`);
    },
  });
  target.dispatchEvent(new Event("pointerdown"));
  await player.play("/static/sounds/start-1.m4a");
  assert.deepEqual(played(), []);
  await player.play("/static/sounds/start-1.m4a");
  assert.equal(attempts, 2);
  assert.equal(played().length, 1);
});

test("音を出せない状態のままなら、あとから遅れて鳴らさない", async () => {
  const context = new FakeContext({ resumable: false });
  const { player, target, played } = setup({ context });
  target.dispatchEvent(new Event("pointerdown"));
  await player.play("/static/sounds/start-1.m4a");
  assert.ok(context.resumeCalls >= 2, "合図のときにも動かし直そうとする");
  assert.deepEqual(played(), []);
});

test("AudioContext のないブラウザでも例外を出さない", async () => {
  const target = new EventTarget();
  const player = new SoundPlayer({
    createContext: () => null,
    load: () => Promise.resolve("中身"),
  });
  player.unlockOn(target);
  target.dispatchEvent(new Event("pointerdown"));
  await player.play("/static/sounds/start-1.m4a");
});
