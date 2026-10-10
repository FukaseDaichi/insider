// 配役ツールの画面。LINE で配役ボットと話すのと同じトーク画面にする。
// 入力欄に打った文字は LINE で送ったのと同じ解釈を（/api/village/text）、返事のボタンは LINE と同じ意味で送り返す。
// 画面は /village（トーク）、/village/new（同じトーク）、/v/<村番号>（その番号を送ったトーク）、/village/special（特殊村）
import { renderQr, Scanner } from "./qr.js";
import { isWerewordsCommand, quickReplies } from "./quickreply.js";
import { replyNodes } from "./reply.js";
import { messagesProblem, parseMessages } from "./specialform.js";
import {
  appendEntry,
  emptyLog,
  forgetConverted,
  loadLog,
  LOG_KEY,
  markConverted,
  saveLog,
  shouldAutoJoin,
  statusEntry,
  statusNumber,
  updateEntry,
} from "./talklog.js";
import { parseVillageUrl, villageFromPath, villageUrl } from "./villageurl.js";
import { villageToken } from "./villagetoken.js";

const $ = (id) => document.getElementById(id);
// 配布状況の自動更新の間隔。1 秒を争わないので数秒で足りる
const STATUS_REFRESH_MS = 5000;
// これより古い配布状況は書き換えない（1 回の遊びはこれより短い。開いたままの画面が問い合わせ続けないため）
const STATUS_MAX_AGE_MS = 3 * 60 * 60 * 1000;
// これより下に近ければ、新しい発言で一番下までスクロールする
const STICK_TO_BOTTOM_PX = 80;
const NETWORK_ERROR = "通信に失敗しました。少し待ってからもう一度どうぞ";
const BOT_NAME = "インサイダー";
const AVATAR = "/static/mark.svg";
const GREETING =
  "インサイダーの配役ボットです。\n\n村を作るときは、下のメニューの「村を作る」か「神モード」を押してください。\n\n村に入るときは、教えてもらった村番号を送るか、「QR で入る」で読み取ってください。";
const HELP = [
  "【村を作る人】",
  "1. 「村を作る」（あなたが GM）か「神モード」（GM も参加者から選ぶ）を押す",
  "2. お題を送る（「お題の自動取得」も使えます）",
  "3. 参加する人数を数字で送る",
  "4. 「QR を見せる」で、参加する人に村番号と QR を見せる",
  "自分の村番号を送ると、何人入ったかとお題が見られます。",
  "",
  "【参加する人】",
  "教えてもらった村番号を送るか、「QR で入る」で読み取ると、役職とお題が届きます。何度送っても同じ役職が届きます。",
].join("\n");
const WEEKDAYS = "日月火水木金土";

function localStorageOrNull() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

const storage = localStorageOrNull();
const token = villageToken(storage, crypto);

async function post(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

function call(name, fields = {}) {
  return post(`/api/village/${name}`, { token, ...fields });
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showApp(id) {
  for (const app of document.querySelectorAll(".app")) app.hidden = app.id !== id;
  return $(id);
}

// iPhone はキーボードを開いても画面の高さを変えないので、見えている部分に画面を合わせる
function fitViewport(app) {
  const viewport = window.visualViewport;
  if (!viewport) return;
  const fit = () => {
    app.style.height = `${viewport.height}px`;
    app.style.top = `${viewport.offsetTop}px`;
  };
  viewport.addEventListener("resize", fit);
  viewport.addEventListener("scroll", fit);
  fit();
}

let toastTimer = null;

function toast(text) {
  const node = $("toast");
  node.textContent = text;
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 2500);
}

async function copyUrl(link) {
  try {
    await navigator.clipboard.writeText(link);
    toast("URL をコピーしました");
  } catch {
    toast("コピーできませんでした。URL を長押ししてコピーしてください");
  }
}

function dayKey(at) {
  const date = new Date(at);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function dayLabel(at) {
  const date = new Date(at);
  const today = new Date();
  if (dayKey(at) === dayKey(today)) return "今日";
  if (dayKey(at) === dayKey(today.getTime() - 24 * 60 * 60 * 1000)) return "昨日";
  return `${date.getMonth() + 1}/${date.getDate()}(${WEEKDAYS[date.getDay()]})`;
}

function timeLabel(at) {
  const date = new Date(at);
  return `${date.getHours()}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function initTalk(joinNumber, notice) {
  const app = showApp("talk");
  fitViewport(app);
  const list = $("talk-log");
  const scroller = $("talk-scroll");
  const input = $("composer-input");
  const sendButton = $("composer-send");
  const menu = $("rich-menu");
  const toggle = $("menu-toggle");
  let log = loadLog(storage);
  // サーバーが毎回添える、自分が作った最新の村の要約
  let village = null;
  let busy = false;
  let stuck = true;

  // --- 履歴と描画 ---

  function commit(next) {
    log = next;
    saveLog(storage, log);
  }

  function scrollToBottom() {
    scroller.scrollTop = scroller.scrollHeight;
  }

  // 利用者が自分でスクロールしたときだけ、一番下から離れたかを決め直す（こちらのスクロールや高さの変化では離れない）
  let touchedAt = 0;
  for (const type of ["wheel", "touchmove", "keydown"]) {
    scroller.addEventListener(type, () => {
      touchedAt = Date.now();
    }, { passive: true });
  }
  scroller.addEventListener("scroll", () => {
    const near = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < STICK_TO_BOTTOM_PX;
    if (near || Date.now() - touchedAt < 1000) stuck = near;
  });
  // 画像の読み込み・キーボード・メニューの開閉で高さが変わっても、一番下を見ていたら一番下に留める
  new ResizeObserver(() => {
    if (stuck) scrollToBottom();
  }).observe(list);
  new ResizeObserver(() => {
    if (stuck) scrollToBottom();
  }).observe(scroller);

  function meta(entry, read) {
    const node = element("span", "meta");
    if (read) node.append(element("span", "read", "既読"));
    const time = element("time", "", timeLabel(entry.at));
    time.dateTime = new Date(entry.at).toISOString();
    node.append(time);
    return node;
  }

  function inviteNode(number) {
    const link = villageUrl(number, location.origin);
    const card = element("div", "tpl");
    const body = element("div", "tpl-body");
    body.append(element("p", "tpl-title", "村番号"), element("p", "invite-number", String(number)));
    const canvas = element("canvas", "qr");
    canvas.setAttribute("aria-label", `村 ${number} に入る QR コード`);
    renderQr(canvas, link).catch(() => {
      canvas.hidden = true;
    });
    body.append(
      canvas,
      element("p", "tpl-text", "この QR を読み取るか、村番号を送ると村に入れます。"),
      element("p", "invite-url", link),
    );
    const actions = element("div", "tpl-actions");
    const copy = element("button", "tpl-action", "URL をコピー");
    copy.type = "button";
    copy.addEventListener("click", () => copyUrl(link));
    actions.append(copy);
    card.append(body, actions);
    return card;
  }

  function messageNode(entry) {
    if (entry.from === "system") return element("p", "notice", entry.text);
    if (entry.from === "me") {
      const node = element("div", "msg me");
      if (entry.failed) {
        const retry = element("button", "retry");
        retry.type = "button";
        retry.setAttribute("aria-label", "送れませんでした。もう一度送る");
        retry.addEventListener("click", () => resend(entry.id));
        node.append(retry);
      } else {
        node.append(meta(entry, entry.read));
      }
      node.append(element("p", "bubble", entry.text));
      return node;
    }
    const node = element("div", "msg bot");
    const avatar = element("img", "avatar");
    avatar.src = AVATAR;
    avatar.alt = "";
    const main = element("div", "msg-main");
    main.append(element("p", "name", BOT_NAME));
    const parts = entry.invite !== undefined ? [inviteNode(entry.invite)] : replyNodes(entry.replies, onAction);
    parts.forEach((part, index) => {
      const line = element("div", "line");
      line.append(part);
      if (index === parts.length - 1) line.append(meta(entry, false));
      main.append(line);
    });
    node.append(avatar, main);
    return node;
  }

  function entryNode(entry, previous) {
    const item = element("li", "entry");
    item.dataset.id = String(entry.id);
    if (previous === undefined || dayKey(previous.at) !== dayKey(entry.at)) item.append(element("p", "day", dayLabel(entry.at)));
    item.append(messageNode(entry));
    return item;
  }

  function renderAll() {
    list.replaceChildren(...log.entries.map((entry, index) => entryNode(entry, log.entries[index - 1])));
    scrollToBottom();
  }

  function add(fields) {
    const previous = log.entries.at(-1);
    const { log: next, entry } = appendEntry(log, fields, Date.now());
    commit(next);
    list.append(entryNode(entry, previous));
    // 件数の上限で消えた古い発言を画面からも消し、新しく先頭になった発言には日付を付け直す
    const kept = new Set(log.entries.map((kept) => String(kept.id)));
    const removed = [...list.children].filter((item) => !kept.has(item.dataset.id));
    if (removed.length > 0) {
      removed.forEach((item) => item.remove());
      list.firstElementChild?.replaceWith(entryNode(log.entries[0], undefined));
    }
    stuck = true;
    scrollToBottom();
    return entry;
  }

  function patch(id, fields) {
    commit(updateEntry(log, id, fields));
    const index = log.entries.findIndex((entry) => entry.id === id);
    const item = list.querySelector(`[data-id="${id}"]`);
    if (index >= 0 && item) item.replaceWith(entryNode(log.entries[index], log.entries[index - 1]));
  }

  // 別のタブ（QR から開いた /v/<村番号> など）が履歴を書き換えたら、読み直す（古い履歴で上書きしないため）
  window.addEventListener("storage", (event) => {
    if (event.key !== LOG_KEY) return;
    log = loadLog(storage);
    renderAll();
    renderChips();
  });

  // --- 送る ---

  function setVillage(summary) {
    village = summary ?? null;
    // 番号は再起動などで使い回されるので、同じ番号の村が新しく作られたら昔のワーワーズの記録を忘れる
    if (village !== null && village.size === 0 && log.converted[village.number] !== undefined) {
      commit(forgetConverted(log, village.number));
    }
    renderChips();
  }

  // 送るたびに増える。自動更新の応答が、後から送った操作の応答を古い村の要約で上書きしないため
  let generation = 0;

  // 1 回のやりとり。返事を待つ間は「…」を出し、ほかの操作は受け付けない（連打で村が 2 つできないよう）
  async function exchange(task, { me = null, text = null } = {}) {
    busy = true;
    generation += 1;
    $("typing").hidden = false;
    scrollToBottom();
    let body;
    try {
      body = await task();
    } catch (error) {
      console.error(error);
      if (me !== null) patch(me.id, { failed: true, read: false });
      else add({ from: "system", text: NETWORK_ERROR });
      return null;
    } finally {
      busy = false;
      $("typing").hidden = true;
    }
    if (me !== null) patch(me.id, { failed: false, read: true });
    const status = text === null ? null : statusNumber(text, body.village);
    add(status === null ? { from: "bot", replies: body.replies } : { from: "bot", replies: body.replies, status });
    setVillage(body.village);
    return body;
  }

  // 自分の発言をサーバーに届ける。ワーワーズにするコマンドだけは、作った特殊村の番号が応答に添えられる操作で呼ぶ
  async function deliver(me) {
    if (!isWerewordsCommand(me.text)) {
      exchange(() => call("text", { text: me.text }), { me, text: me.text });
      return;
    }
    const body = await exchange(() => call("werewords"), { me });
    // 中核は参加者のいない最新の村を変換する。最新の村に参加者がいれば古い村が変換されているので、
    // どの村かがわからず覚えない
    if (body?.special_number === undefined || body.village?.member_count !== 0) return;
    commit(markConverted(log, body.village.number, body.special_number));
    renderChips();
  }

  /** LINE で文字を送ったのと同じ。自分の吹き出しを出して送る。送れなかった（待ち中）なら false。 */
  function sendText(text) {
    if (busy) return false;
    deliver(add({ from: "me", text }));
    return true;
  }

  function resend(id) {
    const entry = log.entries.find((candidate) => candidate.id === id);
    if (busy || entry === undefined) return;
    deliver(entry);
  }

  // 返事のボタン。文字のボタンは LINE と同じく自分の吹き出しを出し、ポストバックは出さない
  function onAction(action) {
    if (action.kind === "text") sendText(action.value);
    else if (!busy) exchange(() => call("postback", { data: action.value }));
  }

  // --- クイックリプライ ---

  function renderChips() {
    const box = $("quick-replies");
    const chips = quickReplies(village, log.converted);
    box.replaceChildren(
      ...chips.map((chip) => {
        const button = element("button", "chip", chip.label);
        button.type = "button";
        button.addEventListener("click", () => onChip(chip));
        return button;
      }),
    );
    box.hidden = chips.length === 0;
  }

  // 村の要約を取り直す（何も変えない）。取れなければ null
  async function latestVillage() {
    try {
      return (await call("mine")).village;
    } catch {
      return null;
    }
  }

  async function onChip(chip) {
    if (chip.kind === "invite") {
      add({ from: "bot", invite: chip.number });
      return;
    }
    if (chip.kind === "reverse" || chip.kind === "werewords") {
      // 出したあとに参加者が入っていると、中核は参加者のいない古い村を探して切り替えてしまう。
      // 押す前に要約を取り直し、いまも出すべきボタンのときだけ送る
      if (busy) return;
      const latest = await latestVillage();
      if (latest === null) {
        toast(NETWORK_ERROR);
        return;
      }
      setVillage(latest);
      if (!quickReplies(latest, log.converted).some((current) => current.kind === chip.kind)) {
        toast("参加者が入ったので、もう切り替えられません");
        return;
      }
    }
    sendText(chip.text);
  }

  // --- 配布状況の自動更新 ---

  async function refreshStatus() {
    if (document.visibilityState !== "visible" || busy) return;
    const entry = statusEntry(log);
    if (entry === null || Date.now() - entry.at > STATUS_MAX_AGE_MS) return;
    if (log.converted[entry.status] !== undefined) return;
    const started = generation;
    // join は自分の村でなければ参加者として席を取ってしまう。先に、いまも自分の最新の村かを確かめる
    let latest;
    let body;
    try {
      latest = (await call("mine")).village;
      const mine = latest?.number === entry.status && latest.size > 0 && latest.mode !== "random";
      body = mine ? await call("join", { number: entry.status }) : null;
    } catch {
      return; // 次の更新で取り直す
    }
    const current = log.entries.find((candidate) => candidate.id === entry.id);
    if (current === undefined || current.status !== entry.status) return;
    // 自分の最新の村でなくなった（新しい村を作った・サーバーの再起動で村がなくなった）ら、更新をやめる
    if (body === null || body.found === false) {
      patch(entry.id, { status: undefined });
      return;
    }
    // 中身が同じなら描き直さない（読み上げの繰り返しとボタンのフォーカスの喪失を避ける）
    if (JSON.stringify(body.replies) !== JSON.stringify(current.replies)) patch(entry.id, { replies: body.replies });
    if (generation === started) setVillage(body.village);
  }

  setInterval(refreshStatus, STATUS_REFRESH_MS);
  document.addEventListener("visibilitychange", refreshStatus);

  // --- 入力欄とリッチメニュー ---

  function setMenu(open) {
    menu.dataset.open = String(open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "メニューを閉じる" : "メニューを開く");
  }

  function focusInput(numeric) {
    input.inputMode = numeric ? "numeric" : "text";
    input.placeholder = numeric ? "村番号（4〜5 桁）を入力" : "メッセージを入力";
    setMenu(false);
    input.focus();
  }

  const updateSend = () => {
    sendButton.disabled = input.value.trim() === "";
  };
  input.addEventListener("input", updateSend);
  input.addEventListener("focus", () => setMenu(false));
  input.addEventListener("blur", () => {
    input.inputMode = "text";
    input.placeholder = "メッセージを入力";
  });
  // 送信ボタンを押してもキーボードを閉じない（続けて打てるように）
  sendButton.addEventListener("pointerdown", (event) => event.preventDefault());

  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value;
    if (text.trim() === "" || !sendText(text)) return;
    input.value = "";
    updateSend();
  });

  toggle.addEventListener("click", () => {
    if (menu.dataset.open === "false") {
      input.blur();
      setMenu(true);
    } else {
      focusInput(false);
    }
  });

  const scanner = new Scanner(
    $("scanner"),
    $("scanner-video"),
    $("scanner-message"),
    (number) => {
      if (!sendText(String(number))) toast("もう一度読み取ってください");
    },
    (text) => parseVillageUrl(text, location.origin),
  );
  $("scanner-close").addEventListener("click", () => scanner.close());

  const menuActions = {
    normal: () => sendText("お題"),
    god: () => sendText("神"),
    join: () => focusInput(true),
    scan: () => scanner.open(),
    help: () => add({ from: "bot", replies: [{ type: "text", text: HELP }] }),
  };
  for (const tile of menu.querySelectorAll("[data-menu]")) {
    tile.addEventListener("click", () => menuActions[tile.dataset.menu]());
  }

  // --- その他（履歴の削除） ---

  const sheet = $("more-sheet");
  $("talk-more").addEventListener("click", () => sheet.showModal());
  $("more-close").addEventListener("click", () => sheet.close());
  sheet.addEventListener("click", (event) => {
    if (event.target === sheet) sheet.close();
  });
  $("clear-talk").addEventListener("click", () => {
    // ワーワーズにした村は覚えたままにする（クイックリプライが新しい番号を案内し続けるため）
    commit({ ...emptyLog(), converted: log.converted });
    renderAll();
    add({ from: "bot", replies: [{ type: "text", text: GREETING }] });
    sheet.close();
  });

  // --- 開いたとき ---

  setMenu(true);
  renderAll();
  if (log.entries.length === 0) add({ from: "bot", replies: [{ type: "text", text: GREETING }] });
  if (notice) add({ from: "system", text: notice });
  // 描き終えてからライブリージョンにする（開いたときに履歴の全体を読み上げないよう）
  setTimeout(() => {
    list.setAttribute("role", "log");
    list.setAttribute("aria-live", "polite");
  }, 0);
  // 再読み込みや別のタブでも、作りかけの村のクイックリプライを出す
  call("mine")
    .then((body) => {
      if (village === null) setVillage(body.village);
    })
    .catch(() => {});
  // 再読み込みで同じ番号を送り直さないよう、/v/<村番号> から開いたらアドレスはトークに戻す
  if (location.pathname.startsWith("/v/")) history.replaceState(null, "", "/village");
  if (joinNumber !== null && shouldAutoJoin(log, joinNumber)) sendText(String(joinNumber));
}

function initSpecial() {
  fitViewport(showApp("special"));
  const input = $("special-input");
  const message = $("special-message");
  const submit = $("special-submit");
  const count = () => {
    $("special-count").textContent = `${parseMessages(input.value).length} 通`;
  };
  input.addEventListener("input", count);
  count();

  $("special-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const messages = parseMessages(input.value);
    const problem = messagesProblem(messages);
    if (problem !== null) {
      message.textContent = problem;
      return;
    }
    message.textContent = "";
    submit.disabled = true;
    let body;
    try {
      body = await post("/api/village/special", { messages });
    } catch (error) {
      console.error(error);
      message.textContent = NETWORK_ERROR;
      return;
    } finally {
      submit.disabled = false;
    }
    const link = villageUrl(body.number, location.origin);
    $("special-form").hidden = true;
    $("special-result").hidden = false;
    $("special-number").textContent = String(body.number);
    $("special-url").textContent = link;
    $("special-copy").onclick = () => copyUrl(link);
    const canvas = $("special-qr");
    canvas.hidden = false;
    renderQr(canvas, link).catch(() => {
      canvas.hidden = true;
    });
  });

  $("special-again").addEventListener("click", () => {
    input.value = "";
    count();
    message.textContent = "";
    $("special-result").hidden = true;
    $("special-form").hidden = false;
  });
}

const path = location.pathname.replace(/\/$/, "") || "/";
if (path === "/village/special") initSpecial();
else if (path.startsWith("/v/")) {
  const number = villageFromPath(path);
  if (number === null) initTalk(null, "村番号が正しくありません（URL を確かめてください）");
  else initTalk(number, "");
} else initTalk(null, "");
