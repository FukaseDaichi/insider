import assert from "node:assert/strict";
import { test } from "node:test";

import { newToken, TOKEN_KEY, villageToken } from "../../src/insider_bot/web/static/villagetoken.js";

const TOKEN = /^[A-Za-z0-9_-]{22}$/;
const fixedCrypto = { getRandomValues: (array) => array.fill(7) };

class MemoryStorage {
  constructor(entries = {}) {
    this.map = new Map(Object.entries(entries));
  }

  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }

  setItem(key, value) {
    this.map.set(key, value);
  }
}

class BrokenStorage {
  getItem() {
    throw new Error("blocked");
  }

  setItem() {
    throw new Error("blocked");
  }
}

test("16 バイトの乱数を、= のない base64url の 22 文字にする", () => {
  assert.equal(newToken(new Uint8Array(16)), "A".repeat(22));
  // + と / は URL で意味を持つので - と _ にする
  assert.equal(newToken(new Uint8Array([0xfb, 0xff, 0xbf])), "-_-_");
});

test("保存済みのトークンを使い続ける", () => {
  const storage = new MemoryStorage({ [TOKEN_KEY]: "saved-token-0123456789" });
  assert.equal(villageToken(storage, fixedCrypto), "saved-token-0123456789");
});

test("なければ作って保存する", () => {
  const storage = new MemoryStorage();
  const token = villageToken(storage, fixedCrypto);
  assert.match(token, TOKEN);
  assert.equal(storage.getItem(TOKEN_KEY), token);
});

test("形の壊れた保存値は作り直す", () => {
  const storage = new MemoryStorage({ [TOKEN_KEY]: "bad token" });
  const token = villageToken(storage, fixedCrypto);
  assert.match(token, TOKEN);
  assert.equal(storage.getItem(TOKEN_KEY), token);
});

test("保存できない環境や storage がない環境でも、その場のトークンで動く", () => {
  assert.match(villageToken(new BrokenStorage(), fixedCrypto), TOKEN);
  assert.match(villageToken(null, fixedCrypto), TOKEN);
});
