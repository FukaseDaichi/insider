import assert from "node:assert/strict";
import { test } from "node:test";

import {
  parseVillageInput,
  parseVillageUrl,
  villageFromPath,
  villageUrl,
} from "../../src/insider_bot/web/static/villageurl.js";

const ORIGIN = "https://game.example.com";

test("パスの /v/<村番号> から村番号を取り出す", () => {
  assert.equal(villageFromPath("/v/1234"), 1234);
  assert.equal(villageFromPath("/v/12345/"), 12345);
  assert.equal(villageFromPath("/v/99998"), 99998);
});

test("村番号の範囲や形が違うパスは拒む", () => {
  for (const path of ["/v/0999", "/v/999", "/v/99999", "/v/123456", "/v/12a4", "/v/1234/x", "/v/", "/village", "/r/1234"]) {
    assert.equal(villageFromPath(path), null, path);
  }
});

test("同じオリジンの村の URL から村番号を取り出す（クエリとハッシュは無視）", () => {
  assert.equal(parseVillageUrl(`${ORIGIN}/v/1234`, ORIGIN), 1234);
  assert.equal(parseVillageUrl(`${ORIGIN}/v/12345?x=1#y`, ORIGIN), 12345);
});

test("別のオリジンや URL でない文字列は拒む", () => {
  for (const text of ["https://evil.example/v/1234", "http://game.example.com/v/1234", "1234", "", "javascript:alert(1)"]) {
    assert.equal(parseVillageUrl(text, ORIGIN), null, text);
  }
});

test("入力欄は全角数字と前後の空白（全角スペースを含む）を許す", () => {
  assert.equal(parseVillageInput("1234"), 1234);
  assert.equal(parseVillageInput("１２３４"), 1234);
  assert.equal(parseVillageInput(" 1234 "), 1234);
  assert.equal(parseVillageInput("　１２３４５　"), 12345);
});

test("入力欄の 4〜5 桁でない数字や範囲外は拒む", () => {
  for (const text of ["", "123", "123456", "12-34", "abcd", "99999", "0999", "1 234"]) {
    assert.equal(parseVillageInput(text), null, text);
  }
});

test("参加用の URL", () => {
  assert.equal(villageUrl(1234, ORIGIN), `${ORIGIN}/v/1234`);
});
