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

function setup() {
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
