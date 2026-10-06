import assert from "node:assert/strict";
import { test } from "node:test";

import { readResults } from "../../src/insider_bot/web/static/speech.js";

// SpeechRecognitionResult の代わり: 候補の配列に isFinal を付けたもの
const result = (transcript, isFinal) =>
  Object.assign([{ transcript }], { isFinal });

test("未確定の結果だけなら、その文字を持つ", () => {
  assert.equal(readResults([result("くだもの", false)]), "くだもの");
});

test("確定した結果と、その後の未確定の末尾をつなぐ", () => {
  assert.equal(
    readResults([result("赤い", true), result("果物ですか", false)]),
    "赤い果物ですか",
  );
});

test("確定した結果が続けば、順につなぐ", () => {
  assert.equal(
    readResults([result("赤い", true), result("果物ですか", true)]),
    "赤い果物ですか",
  );
});

// Android の Chrome は continuous だと、新しい結果を区切りではなく「聞き始めからの文全体」として
// 一覧に足していく（確定扱いのことが多い）。全部つなぐと「何月何月何月何日か何月何日か…」になっていた
test("前までの文で始まる結果は累積の途中経過なので、足さずに置き換える", () => {
  const results = [
    result("何月", true),
    result("何月", true),
    result("何月何日か", true),
    result("何月何日か", true),
    result("何月何日か", false),
  ];
  assert.equal(readResults(results), "何月何日か");
});

test("累積の文が空白をはさんで伸びても、置き換える", () => {
  const results = [
    result("誕生日", true),
    result("誕生日", true),
    result("誕生日 関係ありますか？", false),
  ];
  assert.equal(readResults(results), "誕生日 関係ありますか？");
});

test("前までの文の先頭だけの結果は古い途中経過なので、捨てる", () => {
  const results = [result("何月何日か", true), result("何月", false)];
  assert.equal(readResults(results), "何月何日か");
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
