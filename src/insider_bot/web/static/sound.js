// ゲーム開始の音声、返事の声、正解・ギブアップの声を鳴らす。
// ブラウザは操作のないページに音を出させないので、タップやキー操作のたびに AudioContext を動かしておき、
// サーバーから合図が届いたらそれで鳴らす。鳴らせなくてもゲームは遊べるので、失敗は黙って捨てる
const UNLOCK_EVENTS = ["pointerdown", "pointerup", "touchend", "keydown"];
// iPhone の Safari は裏にある間ページを止め、その間に届いた合図を戻ったときにまとめて渡す。
// 戻ってからこの時間内に届いた合図は、とっくに始まったゲームのものとみなして鳴らさない
const RETURN_GRACE_MS = 3000;
// 合図から鳴らせるまでにこれより長くかかったら、吹き出しとずれるので鳴らさない
const MAX_LAG_MS = 2000;

function createAudioContext() {
  const Context = globalThis.AudioContext ?? globalThis.webkitAudioContext;
  return Context ? new Context() : null;
}

async function fetchAudio(src) {
  const response = await fetch(src);
  if (!response.ok) throw new Error(`${src}: ${response.status}`);
  return response.arrayBuffer();
}

export class SoundPlayer {
  constructor({
    createContext = createAudioContext,
    load = fetchAudio,
    now = () => performance.now(),
  } = {}) {
    this.createContext = createContext;
    this.load = load;
    this.now = now;
    this.context = null;
    this.buffers = new Map();
    this.page = null;
    this.shownAt = -Infinity;
    this.sources = new Set();
    this.enabled = true;
  }

  /** 音のオン／オフ。オフにしたら鳴りかけの音も止める（次の合図まで待たせない）。 */
  setEnabled(on) {
    this.enabled = on;
    if (!on) this.stop();
  }

  /** 操作のたびに動かし直す。iPhone は音声認識や着信のあと AudioContext を止めるため。 */
  unlockOn(target) {
    const unlock = () => this.unlock();
    for (const type of UNLOCK_EVENTS)
      target.addEventListener(type, unlock, { capture: true, passive: true });
  }

  unlock() {
    try {
      this.context ??= this.createContext();
      const context = this.context;
      if (!context || context.state === "running") return;
      context.resume().catch(() => {});
      // 古い iPhone は、操作の中で一度音を出さないと再生を許さない
      const silence = context.createBufferSource();
      silence.buffer = context.createBuffer(1, 1, 22050);
      silence.connect(context.destination);
      silence.start();
    } catch {
      // 音を出せないブラウザでも遊べる
    }
  }

  /** 画面を見ていない間と、裏から戻った直後に届いた合図は鳴らさない。離れたら鳴りかけの音も止める。 */
  watchVisibility(page) {
    this.page = page;
    page.addEventListener("visibilitychange", () => {
      if (page.visibilityState === "hidden") this.stop();
      else this.shownAt = this.now();
    });
  }

  watching() {
    if (this.page?.visibilityState === "hidden") return false;
    return this.now() - this.shownAt >= RETURN_GRACE_MS;
  }

  async play(src) {
    const context = this.context;
    if (!this.enabled || !context || !this.watching()) return;
    const signaledAt = this.now();
    try {
      // 操作がないと resume は終わらないので待たない。待つと次に触ったときに遅れて鳴ってしまう
      if (context.state !== "running") context.resume().catch(() => {});
      const buffer = await this.buffer(src);
      if (context.state !== "running") return;
      // 読み込みを待つ間に裏へ回った・時間がたったなら、もう開始の時ではない
      if (!this.watching() || this.now() - signaledAt > MAX_LAG_MS) return;
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      source.onended = () => this.sources.delete(source);
      this.sources.add(source);
      source.start();
    } catch {
      // 読み込めない・再生できないときは鳴らさない
    }
  }

  // 裏に回るとき止めておかないと、iPhone は音を止めたまま持ち越し、戻ったときに続きを鳴らす
  stop() {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // すでに終わっている
      }
    }
    this.sources.clear();
  }

  buffer(src) {
    let pending = this.buffers.get(src);
    if (!pending) {
      pending = this.load(src).then((data) =>
        this.context.decodeAudioData(data),
      );
      // 失敗した読み込みは覚えず、次の合図で読み直す
      pending.catch(() => this.buffers.delete(src));
      this.buffers.set(src, pending);
    }
    return pending;
  }
}
