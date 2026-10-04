import assert from "node:assert/strict";
import { test } from "node:test";

import { readResults } from "../../src/insider_bot/web/static/speech.js";

// SpeechRecognitionResult の代わり: 候補の配列に isFinal を付けたもの
const result = (transcript, isFinal) =>
  Object.assign([{ transcript }], { isFinal });

test("未確定の結果だけなら、未確定の文字として持つ", () => {
  assert.deepEqual(readResults([result("くだもの", false)]), {
    finals: "",
    interim: "くだもの",
  });
});

test("確定した結果と、その後の未確定の末尾を分けて持つ", () => {
  assert.deepEqual(
    readResults([result("赤い", true), result("果物ですか", false)]),
    { finals: "赤い", interim: "果物ですか" },
  );
});

test("確定した結果が続けば、順につなぐ", () => {
  assert.deepEqual(
    readResults([result("赤い", true), result("果物ですか", true)]),
    { finals: "赤い果物ですか", interim: "" },
  );
});

test("音声ショートカットは他のボタン・入力・ダイアログの操作を奪わない", async () => {
  const { PushToTalk } = await import(
    "../../src/insider_bot/web/static/speech.js"
  );
  const originalElement = globalThis.HTMLElement;
  const originalDocument = globalThis.document;
  class Element {
    constructor(tagName) {
      this.tagName = tagName;
      this.offsetParent = {};
    }
    closest() {
      return ["BUTTON", "A", "SUMMARY"].includes(this.tagName) ? this : null;
    }
  }
  globalThis.HTMLElement = Element;
  let dialogOpen = false;
  globalThis.document = { querySelector: () => (dialogOpen ? {} : null) };
  const button = new Element("BUTTON");
  const context = { button, enabled: true };
  const usable = (target) =>
    PushToTalk.prototype.keyboardUsable.call(context, { target });
  try {
    assert.equal(usable(button), true);
    for (const tag of ["BUTTON", "A", "SUMMARY", "INPUT", "TEXTAREA", "SELECT"])
      assert.equal(usable(new Element(tag)), false);
    const child = new Element("SPAN");
    child.closest = () => new Element("BUTTON");
    assert.equal(usable(child), false);
    dialogOpen = true;
    assert.equal(usable(button), false);
    dialogOpen = false;
    context.enabled = false;
    assert.equal(usable(button), false);
  } finally {
    if (originalElement === undefined) delete globalThis.HTMLElement;
    else globalThis.HTMLElement = originalElement;
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});
