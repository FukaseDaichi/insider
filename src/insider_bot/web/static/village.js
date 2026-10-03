// 配役ツールの画面。サーバーの返事モデルを reply.js で描き、返事のボタンは LINE と同じ意味で送り返す。
// 画面は /village（入口）、/village/new（村を作る）、/village/special（特殊村）、/v/<村番号>（村に入る）の 4 つ
import { renderQr, Scanner } from "./qr.js";
import { renderReplies } from "./reply.js";
import { messagesProblem, parseMessages } from "./specialform.js";
import { parseVillageInput, parseVillageUrl, villageFromPath, villageUrl } from "./villageurl.js";
import { villageToken } from "./villagetoken.js";

const $ = (id) => document.getElementById(id);
// 配布状況の自動更新の間隔。1 秒を争わないので数秒で足りる
const STATUS_REFRESH_MS = 5000;
const NETWORK_ERROR = "通信に失敗しました。少し待ってからもう一度どうぞ";

function localStorageOrNull() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

const token = villageToken(localStorageOrNull(), crypto);

function showPage(id) {
  for (const page of document.querySelectorAll(".page")) page.hidden = page.id !== id;
}

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

// 返事のボタン。LINE でその文字列を送った・ポストバックが届いたのと同じ解釈をサーバーがする
function actionCall(action) {
  return action.kind === "text"
    ? call("text", { text: action.value })
    : call("postback", { data: action.value });
}

let busy = false;

// 利用者の操作を 1 つずつ送る。連打で村が 2 つできないよう、応答を待つ間の操作は捨てる
async function run(message, task) {
  if (busy) return null;
  busy = true;
  message.textContent = "";
  try {
    return await task();
  } catch {
    message.textContent = NETWORK_ERROR;
    return null;
  } finally {
    busy = false;
  }
}

// 村に入る URL を、QR・文字・コピーのボタンで見せる
function showInvite(number, { canvas, url, copy, message }) {
  const link = villageUrl(number, location.origin);
  url.textContent = link;
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(link);
      message.textContent = "URL をコピーしました";
    } catch {
      message.textContent = "コピーできませんでした。URL を長押ししてコピーしてください";
    }
  };
  canvas.hidden = false;
  renderQr(canvas, link).catch(() => {
    canvas.hidden = true;
  });
}

function initHome(notice = "") {
  showPage("village-home");
  $("home-message").textContent = notice;
  $("join-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const number = parseVillageInput($("join-number").value);
    if (number === null) {
      $("home-message").textContent = "村番号は 4〜5 桁の数字で入力してください";
      return;
    }
    location.href = `/v/${number}`;
  });
  const scanner = new Scanner(
    $("scanner"),
    $("scanner-video"),
    $("scanner-message"),
    (number) => {
      location.href = `/v/${number}`;
    },
    (text) => parseVillageUrl(text, location.origin),
  );
  $("scan-open").addEventListener("click", () => scanner.open());
  $("scanner-close").addEventListener("click", () => scanner.close());
}

function initCard(number) {
  showPage("village-card");
  $("card-number").textContent = String(number);
  const message = $("card-message");

  async function onAction(action) {
    const body = await run(message, () => actionCall(action));
    if (body !== null) renderReplies($("card-status"), body.replies, onAction);
  }

  // 参加済みなら同じ役職が返るので、何度押しても席は増えない
  async function join() {
    const body = await run(message, () => call("join", { number }));
    if (body === null) return;
    renderReplies($("card-replies"), body.replies, onAction);
    $("card-status").replaceChildren();
  }

  $("card-reload").addEventListener("click", join);
  join();
}

function initNew() {
  showPage("village-new");
  const message = $("new-message");
  const steps = ["step-kind", "step-topic", "step-size", "step-status"];
  let village = null;
  // 「新しい村を作る」を押したあとは、作りかけの村があっても種類から聞く
  let startingOver = false;
  let invited = null;
  let timer = null;

  function stepOf(owned) {
    if (owned === null || startingOver) return "step-kind";
    if (!owned.has_topic) return "step-topic";
    if (owned.size === 0) return "step-size";
    return "step-status";
  }

  function updateOwnerButtons(owned) {
    // 中核も同じ条件で断るが、押しても案内文しか返らないボタンは出さない
    $("reverse-button").hidden = owned.member_count > 0 || owned.mode === "random" || owned.reverse;
    $("werewords-button").hidden = owned.member_count > 0 || owned.size < 3 || !owned.has_topic;
  }

  // オーナーが自分の村番号で入ると配布状況が返る。画面が隠れている間は取りに行かない
  async function refreshStatus() {
    if (village === null || document.visibilityState !== "visible") return;
    const number = village.number;
    let body;
    try {
      body = await call("join", { number });
    } catch {
      return; // 次の更新で取り直す
    }
    if (village === null || village.number !== number) return;
    renderReplies($("status-replies"), body.replies, onStatusAction);
    if (body.village?.number === number) {
      village = body.village;
      updateOwnerButtons(village);
    }
  }

  // 配布状況のボタン（通常村の「再確認」、ランダム村のオーナーの「入室状況確認」）。結果は配布状況の欄に描く
  async function onStatusAction(action) {
    const body = await run(message, () => actionCall(action));
    if (body === null) return;
    renderReplies($("status-replies"), body.replies, onStatusAction);
    if (village !== null && body.village?.number === village.number) {
      village = body.village;
      updateOwnerButtons(village);
    }
  }

  function startStatus() {
    $("status-number").textContent = String(village.number);
    if (invited !== village.number) {
      invited = village.number;
      $("status-replies").replaceChildren();
      showInvite(village.number, { canvas: $("status-qr"), url: $("status-url"), copy: $("status-copy"), message });
    }
    updateOwnerButtons(village);
    if (timer === null) {
      refreshStatus();
      timer = setInterval(refreshStatus, STATUS_REFRESH_MS);
    }
  }

  function stopStatus() {
    clearInterval(timer);
    timer = null;
  }

  function show(owned) {
    village = owned;
    const step = stepOf(owned);
    for (const id of steps) $(id).hidden = id !== step;
    if (step === "step-status") startStatus();
    else stopStatus();
  }

  // 返事を描き、最新の村の要約から次に聞くことを決める
  function apply(body) {
    if (body === null) return;
    renderReplies($("new-replies"), body.replies, onAction);
    show(body.village);
  }

  async function onAction(action) {
    apply(await run(message, () => actionCall(action)));
  }

  for (const button of document.querySelectorAll("[data-kind]")) {
    button.addEventListener("click", async () => {
      const body = await run(message, () => call("create", { kind: button.dataset.kind }));
      if (body === null) return;
      startingOver = false;
      apply(body);
    });
  }

  $("step-topic").addEventListener("submit", async (event) => {
    event.preventDefault();
    const topic = $("topic-input").value;
    if (topic === "") return;
    const body = await run(message, () => call("topic", { topic }));
    if (body?.found) $("topic-input").value = "";
    apply(body);
  });

  $("step-size").addEventListener("submit", async (event) => {
    event.preventDefault();
    const size = Number.parseInt($("size-input").value, 10);
    if (!Number.isInteger(size) || size > 100) {
      message.textContent = "人数は 100 人までの数字で入力してください";
      return;
    }
    apply(await run(message, () => call("size", { size })));
  });

  $("reverse-button").addEventListener("click", async () => apply(await run(message, () => call("reverse"))));
  $("werewords-button").addEventListener("click", async () => apply(await run(message, () => call("werewords"))));
  $("restart-button").addEventListener("click", () => {
    startingOver = true;
    $("new-replies").replaceChildren();
    show(village);
  });
  document.addEventListener("visibilitychange", () => {
    if (timer !== null) refreshStatus();
  });

  // 再読み込みや別のタブでは、作りかけの村の続きから表示する
  run(message, () => call("mine")).then((body) => show(body === null ? null : body.village));
}

function initSpecial() {
  showPage("village-special");
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
    submit.disabled = true;
    const body = await run(message, () => post("/api/village/special", { messages }));
    submit.disabled = false;
    if (body === null) return;
    $("special-form").hidden = true;
    $("special-result").hidden = false;
    $("special-number").textContent = String(body.number);
    showInvite(body.number, { canvas: $("special-qr"), url: $("special-url"), copy: $("special-copy"), message });
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
if (path === "/village/new") initNew();
else if (path === "/village/special") initSpecial();
else if (path.startsWith("/v/")) {
  const number = villageFromPath(path);
  if (number === null) initHome("村番号が正しくありません（URL を確かめてください）");
  else initCard(number);
} else initHome();
