// トーク画面の履歴。この端末の localStorage にだけ残し、サーバーには送らない。
// 発言は 3 種類: 自分（me: 送った文字）、ボット（bot: 返事の列、または村に入る QR のカード）、知らせ（system）
import { parseVillageInput } from "./villageurl.js";

export const LOG_KEY = "village:talk";
// LINE のように遡れれば十分で、localStorage の容量を食わない件数
export const MAX_ENTRIES = 200;

export function emptyLog() {
  return { entries: [], nextId: 1, converted: {} };
}

const isNumber = (value) => Number.isInteger(value) && value > 0;

function validEntry(entry) {
  if (entry === null || typeof entry !== "object" || !isNumber(entry.id) || !Number.isFinite(entry.at)) return false;
  if (entry.from === "me" || entry.from === "system") return typeof entry.text === "string";
  if (entry.from === "bot") return Array.isArray(entry.replies) || isNumber(entry.invite);
  return false;
}

/** 保存済みの履歴。読めない・壊れているときは空から始める（形の違う発言だけを捨てる）。 */
export function loadLog(storage) {
  let saved;
  try {
    saved = JSON.parse(storage?.getItem(LOG_KEY) ?? "null");
  } catch {
    return emptyLog();
  }
  if (saved === null || typeof saved !== "object" || !Array.isArray(saved.entries)) return emptyLog();
  const entries = saved.entries.filter(validEntry).slice(-MAX_ENTRIES);
  const converted = {};
  for (const [number, special] of Object.entries(saved.converted ?? {})) {
    if (isNumber(Number(number)) && isNumber(special)) converted[number] = special;
  }
  const nextId = Math.max(isNumber(saved.nextId) ? saved.nextId : 1, ...entries.map((entry) => entry.id + 1));
  return { entries, nextId, converted };
}

/** 履歴を保存する。保存できない環境（プライベートブラウズなど）では false を返し、画面はそのまま動く。 */
export function saveLog(storage, log) {
  try {
    storage.setItem(LOG_KEY, JSON.stringify(log));
    return true;
  } catch {
    return false;
  }
}

/** 発言を足した新しい履歴と、番号と時刻を付けた発言を返す。配布状況は最新の 1 つだけが status を持つ。 */
export function appendEntry(log, fields, now) {
  const entry = { id: log.nextId, at: now, ...fields };
  let entries = log.entries;
  if (entry.status !== undefined) {
    entries = entries.map((old) => {
      if (old.status === undefined) return old;
      const { status, ...rest } = old;
      return rest;
    });
  }
  entries = [...entries, entry].slice(-MAX_ENTRIES);
  return { log: { ...log, entries, nextId: log.nextId + 1 }, entry };
}

export function updateEntry(log, id, patch) {
  return { ...log, entries: log.entries.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry)) };
}

/** 自動で書き換える配布状況の発言。なければ null。 */
export function statusEntry(log) {
  return log.entries.findLast((entry) => entry.status !== undefined) ?? null;
}

/** ワーワーズにした村と、作った特殊村の番号を覚える（再読み込みしても新しい番号を案内するため）。 */
export function markConverted(log, number, special) {
  return { ...log, converted: { ...log.converted, [number]: special } };
}

/** 同じ番号の村が新しく作られたら（番号は再起動などで使い回される）、昔のワーワーズの記録を忘れる。 */
export function forgetConverted(log, number) {
  if (log.converted[number] === undefined) return log;
  const { [number]: _, ...converted } = log.converted;
  return { ...log, converted };
}

/** /v/<村番号> から開いたとき、その番号を送るか。最後に送ったのが同じ番号なら、再読み込みとみなして送らない。 */
export function shouldAutoJoin(log, number) {
  const last = log.entries.findLast((entry) => entry.from === "me");
  return last === undefined || parseVillageInput(last.text) !== number;
}

/**
 * 送った文字への返事が、自分の村の配布状況なら村番号を返す。
 * オーナーが自分の村番号を送ると配布状況が返る。人数が決まる前と、自分の役職が返るランダム村は除く。
 */
export function statusNumber(text, village) {
  if (village === null || village === undefined) return null;
  if (village.mode === "random" || village.size === 0) return null;
  return parseVillageInput(text) === village.number ? village.number : null;
}
