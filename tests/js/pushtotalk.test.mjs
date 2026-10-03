import assert from "node:assert/strict";
import { test } from "node:test";

// speech.js は読み込むときに SpeechRecognition を探すので、偽物を置いてから読み込む
class FakeRecognition {
  static last = null;
  constructor() {
    FakeRecognition.last = this;
  }
  start() {}
  stop() {}
  abort() {}
}
globalThis.SpeechRecognition = FakeRecognition;
globalThis.document = { hidden: false, addEventListener() {} };
globalThis.window = { addEventListener() {} };
const { PushToTalk } = await import(
  "../../src/insider_bot/web/static/speech.js"
);

// SpeechRecognitionResult の代わり: 候補の配列に isFinal を付けたもの
const result = (transcript, isFinal) =>
  Object.assign([{ transcript }], { isFinal });

function setup(t) {
  const button = {
    dataset: {},
    textContent: "",
    classList: { toggle() {} },
    setAttribute() {},
    addEventListener() {},
  };
  const calls = { unavailable: [], status: [], text: [] };
  const ptt = new PushToTalk(button, {
    onTranscript() {},
    onText: (text) => calls.text.push(text),
    onStatus: (message) => calls.status.push(message),
    onUnavailable: (message, reason) =>
      calls.unavailable.push({ message, reason }),
  });
  // 押しっぱなしの打ち切り（20 秒）のタイマーを残さない
  t?.after(() => ptt.cancel());
  return { ptt, calls };
}

// iPhone の Safari は「音声認識」の許可がオフだと service-not-allowed の error だけを出し、end を出さない（実機で確認）
test("end が来なくても、音声認識が使えないとわかった時点で文字入力に切り替える", () => {
  const { ptt, calls } = setup();
  ptt.press();
  FakeRecognition.last.onerror({ error: "service-not-allowed" });
  assert.equal(calls.unavailable.length, 1);
  // 画面が設定のしかたへの案内を出せるように、原因も渡す
  assert.equal(calls.unavailable[0].reason, "service-not-allowed");
  assert.match(calls.unavailable[0].message, /Safari/);
  assert.equal(ptt.state, "idle");
  ptt.release();
  assert.deepEqual(calls.status, []);
});

test("error の後に end も届くブラウザでも、案内は 1 回だけ", () => {
  const { ptt, calls } = setup();
  ptt.press();
  const recognition = FakeRecognition.last;
  recognition.onerror({ error: "not-allowed" });
  recognition.onend?.();
  assert.equal(calls.unavailable.length, 1);
  assert.deepEqual(calls.status, []);
});

test("無音で終わったときは、聞き取った分を残して聞き直す", (t) => {
  const { ptt } = setup(t);
  ptt.press();
  const first = FakeRecognition.last;
  first.onstart();
  first.onresult({ results: [result("赤い", false)], resultIndex: 0 });
  first.onend();
  const second = FakeRecognition.last;
  assert.notEqual(second, first);
  assert.equal(ptt.text(), "赤い");
  // Chrome は無音が続くと no-speech の後に end を出す。これも聞き直す
  second.onerror({ error: "no-speech" });
  second.onend();
  assert.notEqual(FakeRecognition.last, second);
  assert.equal(ptt.state, "listening");
});

// 聞き直してもすぐ同じエラーで終わるので、押している間（最大 20 秒）開始と失敗を繰り返していた
test("分類できないエラーで終わったら、聞き直さずに止めて知らせる", (t) => {
  const { ptt, calls } = setup(t);
  ptt.press();
  const first = FakeRecognition.last;
  first.onstart();
  first.onerror({ error: "aborted" });
  first.onend();
  assert.equal(FakeRecognition.last, first);
  assert.equal(ptt.state, "idle");
  assert.equal(calls.status.length, 1);
  assert.match(calls.status[0], /もう一度押して/);
  assert.deepEqual(calls.text, []);
});
