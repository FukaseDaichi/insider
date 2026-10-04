import assert from "node:assert/strict";
import { test } from "node:test";

import { SoundPlayer } from "../../src/insider_bot/web/static/sound.js";

const SILENCE = "無音";
const START = "/static/sounds/start-1.m4a";

class FakeContext {
  constructor({ resumable = true } = {}) {
    this.state = "suspended";
    this.resumable = resumable;
    this.resumeCalls = 0;
    this.started = [];
    this.stopped = [];
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
    const { started, stopped } = this;
    return {
      buffer: null,
      onended: null,
      connect() {},
      start() {
        started.push(this.buffer);
      },
      stop() {
        stopped.push(this.buffer);
      },
    };
  }
}

// document の代わり。visibilityState を変えて visibilitychange を出す
class FakePage extends EventTarget {
  visibilityState = "visible";

  show(state) {
    this.visibilityState = state;
    this.dispatchEvent(new Event("visibilitychange"));
  }
}

function setup({
  context = new FakeContext(),
  load,
  page = new FakePage(),
  clock = { now: 0 },
} = {}) {
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
    now: () => clock.now,
  });
  player.unlockOn(target);
  player.watchVisibility(page);
  const played = () => context.started.filter((buffer) => buffer !== SILENCE);
  return { player, target, context, loads, played, page, clock };
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

test("画面を見ていない間に届いた合図は鳴らさない", async () => {
  const { player, target, page, played } = setup();
  target.dispatchEvent(new Event("pointerdown"));
  page.show("hidden");
  await player.play(START);
  assert.deepEqual(played(), []);
});

test("画面に戻った直後の合図は、裏にいる間にたまっていたものとみなして鳴らさない", async () => {
  // iPhone の Safari は裏にある間ページを止め、その間に届いた合図を戻ったときにまとめて渡す
  const { player, target, page, clock, played } = setup();
  target.dispatchEvent(new Event("pointerdown"));
  page.show("hidden");
  clock.now += 60_000;
  page.show("visible");
  clock.now += 500;
  await player.play(START);
  assert.deepEqual(played(), []);
});

test("画面に戻ってしばらくたってからの合図は鳴らす", async () => {
  const { player, target, page, clock, played } = setup();
  target.dispatchEvent(new Event("pointerdown"));
  page.show("hidden");
  clock.now += 60_000;
  page.show("visible");
  clock.now += 5000;
  await player.play(START);
  assert.equal(played().length, 1);
});

test("読み込みに時間がかかり、合図から遅れて鳴りそうなら鳴らさない", async () => {
  const clock = { now: 0 };
  const { player, target, played } = setup({
    clock,
    load: (src) => {
      clock.now += 5000;
      return Promise.resolve(`中身:${src}`);
    },
  });
  target.dispatchEvent(new Event("pointerdown"));
  await player.play(START);
  assert.deepEqual(played(), []);
});

test("読み込みを待つ間に裏へ回ったら、すぐ戻ってきても鳴らさない", async () => {
  const page = new FakePage();
  const { player, target, played } = setup({
    page,
    load: (src) => {
      page.show("hidden");
      page.show("visible");
      return Promise.resolve(`中身:${src}`);
    },
  });
  target.dispatchEvent(new Event("pointerdown"));
  await player.play(START);
  assert.deepEqual(played(), []);
});

test("画面を離れたら鳴っている音を止め、戻ったときに続きが鳴らないようにする", async () => {
  const { player, target, page, context, played } = setup();
  target.dispatchEvent(new Event("pointerdown"));
  await player.play(START);
  assert.equal(played().length, 1);
  page.show("hidden");
  assert.deepEqual(context.stopped, played());
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
