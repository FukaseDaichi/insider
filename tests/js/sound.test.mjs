import assert from "node:assert/strict";
import { test } from "node:test";

import { SoundPlayer } from "../../src/insider_bot/web/static/sound.js";

const SILENCE = "無音";
const START = "/static/sounds/start-1.m4a";

class FakeContext {
  // firesStateChange: 動き出したときに statechange を出すか（出さない版のブラウザもある）
  constructor({ resumable = true, firesStateChange = true } = {}) {
    this.state = "suspended";
    this.resumable = resumable;
    this.firesStateChange = firesStateChange;
    this.resumeCalls = 0;
    this.started = [];
    this.stopped = [];
    this.destination = {};
  }

  resume() {
    this.resumeCalls += 1;
    if (this.resumable) {
      this.state = "running";
      if (this.firesStateChange) this.onstatechange?.();
    }
    return Promise.resolve();
  }

  // ブラウザが自分で状態を変えたとき（iPhone の電話や音声認識で止まる・戻る）
  setState(state) {
    this.state = state;
    this.onstatechange?.();
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
  const changes = [];
  player.onChange = (ready) => changes.push(ready);
  const played = () => context.started.filter((buffer) => buffer !== SILENCE);
  return { player, target, context, loads, played, page, clock, changes };
}

// 指を離したときに届く一連のイベント。iPhone では pointerup と touchend が操作に数えられる
function tap(target) {
  for (const type of ["pointerdown", "pointerup", "touchend"])
    target.dispatchEvent(new Event(type));
}

// resume の Promise の続きを走らせる
const settle = () => new Promise((resolve) => setImmediate(resolve));

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

test("音をオフにしていれば、鳴らさず読み込みもしない", async () => {
  const { player, target, loads, played, clock } = setup();
  clock.now = 10_000;
  target.dispatchEvent(new Event("pointerdown"));
  player.setEnabled(false);
  await player.play(START);
  assert.deepEqual(loads, []);
  assert.deepEqual(played(), []);
  assert.equal(player.enabled, false);
});

test("音をオンに戻せば、また鳴る", async () => {
  const { player, target, played, clock } = setup();
  clock.now = 10_000;
  target.dispatchEvent(new Event("pointerdown"));
  player.setEnabled(false);
  player.setEnabled(true);
  await player.play(START);
  assert.deepEqual(played(), [{ decoded: `中身:${START}` }]);
});

test("オフにした瞬間に、鳴りかけの音も止める", async () => {
  const { player, target, context, clock } = setup();
  clock.now = 10_000;
  target.dispatchEvent(new Event("pointerdown"));
  await player.play(START);
  player.setEnabled(false);
  assert.deepEqual(context.stopped, [{ decoded: `中身:${START}` }]);
});

test("部屋を開いた時点で準備しても、タップするまでは鳴らせる状態にならない", () => {
  const { player, target } = setup();
  player.prepare();
  assert.equal(player.ready, false);
  tap(target);
  assert.equal(player.ready, true);
});

test("タップで鳴らせるようになったら、そのことを 1 回だけ知らせる", async () => {
  const { player, target, changes } = setup();
  player.prepare();
  tap(target);
  await settle();
  assert.deepEqual(changes, [true]);
});

test("statechange を出さないブラウザでも、タップで鳴らせるようになったら知らせる", async () => {
  const context = new FakeContext({ firesStateChange: false });
  const { player, target, changes } = setup({ context });
  player.prepare();
  tap(target);
  await settle();
  assert.deepEqual(changes, [true]);
});

test("スクロールのように音を動かせない操作では、鳴らせないまま何も知らせない", async () => {
  const context = new FakeContext({ resumable: false });
  const { player, target, changes } = setup({ context });
  player.prepare();
  target.dispatchEvent(new Event("pointerdown"));
  await settle();
  assert.equal(player.ready, false);
  assert.deepEqual(changes, []);
});

test("iPhone が電話などで音を止めたら知らせ、戻ったらまた知らせる", async () => {
  const { player, target, context, changes } = setup();
  player.prepare();
  tap(target);
  await settle();
  context.setState("interrupted");
  assert.equal(player.ready, false);
  context.setState("running");
  assert.equal(player.ready, true);
  assert.deepEqual(changes, [true, false, true]);
});

test("AudioContext のないブラウザでは、準備しても鳴らせる状態にならない", () => {
  const player = new SoundPlayer({
    createContext: () => null,
    load: () => Promise.resolve("中身"),
  });
  player.prepare();
  assert.equal(player.ready, false);
});

test("声をオンにしたのにブラウザが音を止めている間だけ、止められていると答える", () => {
  const { player, target } = setup();
  player.prepare();
  assert.equal(player.blocked, true);
  player.setEnabled(false);
  assert.equal(player.blocked, false, "オフにしているなら止められていても困らない");
  player.setEnabled(true);
  tap(target);
  assert.equal(player.blocked, false);
});

test("AudioContext のないブラウザでは、止められているとは答えない（タップしても直らないため）", () => {
  const player = new SoundPlayer({
    createContext: () => null,
    load: () => Promise.resolve("中身"),
  });
  player.prepare();
  assert.equal(player.blocked, false);
});
