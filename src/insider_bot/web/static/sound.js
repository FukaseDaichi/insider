// ゲーム開始の音声を鳴らす。
// ブラウザは操作のないページに音を出させないので、タップやキー操作のたびに AudioContext を動かしておき、
// サーバーから合図が届いたらそれで鳴らす。鳴らせなくてもゲームは遊べるので、失敗は黙って捨てる
const UNLOCK_EVENTS = ["pointerdown", "pointerup", "touchend", "keydown"];

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
  constructor({ createContext = createAudioContext, load = fetchAudio } = {}) {
    this.createContext = createContext;
    this.load = load;
    this.context = null;
    this.buffers = new Map();
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

  async play(src) {
    const context = this.context;
    if (!context) return;
    try {
      // 操作がないと resume は終わらないので待たない。待つと次に触ったときに遅れて鳴ってしまう
      if (context.state !== "running") context.resume().catch(() => {});
      const buffer = await this.buffer(src);
      if (context.state !== "running") return;
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      source.start();
    } catch {
      // 読み込めない・再生できないときは鳴らさない
    }
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
