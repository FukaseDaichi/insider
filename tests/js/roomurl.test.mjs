import assert from "node:assert/strict";
import { test } from "node:test";

import { parseRoomCode } from "../../src/insider_bot/web/static/roomurl.js";

const ORIGIN = "https://insider-bot.example.ts.net";

test("同じオリジンのルーム URL からルーム番号を取り出す", () => {
  assert.equal(parseRoomCode(`${ORIGIN}/r/K7Q2MX`, ORIGIN), "K7Q2MX");
});

test("末尾の / とクエリ・ハッシュは無視する", () => {
  assert.equal(parseRoomCode(`${ORIGIN}/r/K7Q2MX/`, ORIGIN), "K7Q2MX");
  assert.equal(parseRoomCode(`${ORIGIN}/r/K7Q2MX?invite=1#x`, ORIGIN), "K7Q2MX");
});

test("別のオリジンは拒む", () => {
  assert.equal(parseRoomCode("https://evil.example/r/K7Q2MX", ORIGIN), null);
  assert.equal(parseRoomCode("http://insider-bot.example.ts.net/r/K7Q2MX", ORIGIN), null);
});

test("ルーム以外のパスは拒む", () => {
  for (const path of ["/r/K7Q2MX/ws", "/x/K7Q2MX", "/r/", "/", "/r/K7Q2MX/extra"]) {
    assert.equal(parseRoomCode(`${ORIGIN}${path}`, ORIGIN), null, path);
  }
});

test("ルーム番号の文字種や長さが違うものは拒む", () => {
  for (const code of ["k7q2mx", "K7Q2M0", "K7Q2MI", "K7Q2M", "K7Q2MXA"]) {
    assert.equal(parseRoomCode(`${ORIGIN}/r/${code}`, ORIGIN), null, code);
  }
});

test("URL でない文字列は拒む", () => {
  for (const text of ["K7Q2MX", "", "javascript:alert(1)", "りんご"]) {
    assert.equal(parseRoomCode(text, ORIGIN), null, text);
  }
});
