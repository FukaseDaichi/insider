// 画面全体: トップページ、名前の入力、ルーム画面（WebSocket の接続と再接続）
import { AskWatch } from "./askwatch.js";
import { renderQr, Scanner } from "./qr.js";
import { ROOM_CODE_PATTERN } from "./roomurl.js";
import { PushToTalk, speechSupported } from "./speech.js";

const $ = (id) => document.getElementById(id);
const NAME_KEY = "odai:name";
const tokenKey = (code) => `odai:token:${code}`;
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 10000];
const NOTICE_MS = 5000;
const LOG_LIMIT = 300;
const CLOSE_MESSAGES = {
  4400: "ルームに入れませんでした。名前を確かめて、もう一度どうぞ",
  4404: "ルームが見つかりません（サーバーが再起動した可能性があります）",
  4409: "このルームは満員です",
};
const NO_SPEECH_HELP =
  "音声入力は Chrome / Edge / Safari で使えます（iPhone は Siri を有効にしてください）。このブラウザでは文字で質問してください";

function load(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // 保存できなくても、このタブの中では遊べる
  }
}

function showPage(id) {
  for (const page of document.querySelectorAll(".page")) page.hidden = page.id !== id;
}

function showFatal(message) {
  $("fatal-message").textContent = message;
  showPage("fatal");
}

function formatElapsed(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hours ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

function initHome() {
  showPage("home");
  $("home-name").value = load(NAME_KEY) ?? "";
  $("home-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = $("home-name").value.trim();
    if (!name) return;
    save(NAME_KEY, name);
    $("home-message").textContent = "";
    let response = null;
    try {
      response = await fetch("/api/rooms", { method: "POST" });
    } catch {
      // 下でまとめて案内する
    }
    if (!response?.ok) {
      $("home-message").textContent = "今はルームを作れません。しばらくしてからどうぞ";
      return;
    }
    const { code } = await response.json();
    location.href = `/r/${code}?invite=1`;
  });
  const scanner = new Scanner($("scanner"), $("scanner-video"), $("scanner-message"), (code) => {
    location.href = `/r/${code}`;
  });
  $("scan-open").addEventListener("click", () => scanner.open());
  $("scanner-close").addEventListener("click", () => scanner.close());
}

function initRoom(code) {
  const openInvite = new URLSearchParams(location.search).has("invite");
  if (openInvite) history.replaceState(null, "", `/r/${code}`);
  const enter = (name) => {
    const page = new RoomPage(code, name);
    page.start();
    if (openInvite) page.openInvite();
  };
  const stored = load(NAME_KEY);
  if (stored) {
    enter(stored);
    return;
  }
  showPage("name-page");
  $("name-room-code").textContent = code;
  $("name-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const name = $("name-input").value.trim();
    if (!name) return;
    save(NAME_KEY, name);
    enter(name);
  });
}

class RoomPage {
  constructor(code, name) {
    this.code = code;
    this.name = name;
    this.token = load(tokenKey(code));
    this.ws = null;
    this.connected = false;
    this.retry = 0;
    this.game = null;
    this.isSetter = false;
    this.startedAt = 0;
    this.items = new Map();
    this.noticeTimer = null;
    this.askWatch = new AskWatch((text) => this.askLost(text));
    this.textMode = !speechSupported;
    this.talk = speechSupported
      ? new PushToTalk($("talk"), {
          onTranscript: (text) => {
            $("transcript").textContent = text;
          },
          onText: (text) => this.ask(text),
          onStatus: (text) => this.notice(text),
          onUnavailable: (text) => {
            this.notice(text);
            this.setTextMode(true);
          },
        })
      : null;
  }

  start() {
    showPage("room");
    $("room-code").textContent = this.code;
    this.bindControls();
    if (!speechSupported) {
      $("speech-help").textContent = NO_SPEECH_HELP;
      $("speech-help").hidden = false;
      $("mode-toggle").hidden = true;
    }
    this.setTextMode(this.textMode);
    $("offline").textContent = "接続中…";
    this.setConnected(false);
    setInterval(() => this.renderStatus(), 1000);
    this.connect();
  }

  connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/r/${this.code}/ws`);
    this.ws = ws;
    ws.addEventListener("open", () => {
      ws.send(JSON.stringify({ type: "join", name: this.name, token: this.token }));
    });
    ws.addEventListener("message", (event) => this.receive(JSON.parse(event.data)));
    ws.addEventListener("close", (event) => {
      // reconnectNow で見切った古い接続の close は無視する
      if (this.ws === ws) this.closed(event.code);
    });
  }

  receive(message) {
    this.askWatch.received();
    switch (message.type) {
      case "welcome":
        this.token = message.token;
        save(tokenKey(this.code), message.token);
        break;
      case "snapshot":
        this.retry = 0;
        this.setConnected(true);
        this.renderLog(message.log);
        this.renderRoom(message.room);
        break;
      case "room":
        this.renderRoom(message);
        break;
      case "entry":
        this.upsertEntry(message.entry);
        break;
      case "notice":
        this.notice(message.text);
        break;
    }
  }

  closed(code) {
    this.ws = null;
    this.setConnected(false);
    this.askWatch.lost();
    if (code in CLOSE_MESSAGES) {
      showFatal(CLOSE_MESSAGES[code]);
      return;
    }
    $("offline").textContent = "再接続中…";
    const delay = RETRY_DELAYS_MS[Math.min(this.retry, RETRY_DELAYS_MS.length - 1)];
    this.retry += 1;
    setTimeout(() => this.connect(), delay);
  }

  send(message) {
    if (!this.connected) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  ask(text) {
    if (this.send({ type: "ask", text, game_id: this.game?.id ?? null })) {
      this.askWatch.sent(text);
      return;
    }
    this.notice("接続が切れているため送れませんでした");
    this.setTextMode(true);
    $("text-input").value = text;
  }

  askLost(text) {
    this.notice("質問が届いていない可能性があります。通信を確かめて、もう一度どうぞ");
    this.setTextMode(true);
    $("text-input").value = text;
    this.reconnectNow();
  }

  // 送った質問に何の応答もない。接続が半開きになっているとみなして、close を待たずに張り直す
  reconnectNow() {
    const ws = this.ws;
    if (!ws) return;
    this.ws = null;
    ws.close();
    this.closed(1006);
  }

  setConnected(connected) {
    this.connected = connected;
    $("offline").hidden = connected;
    for (const control of $("controls").querySelectorAll("button:not(#talk), input, textarea")) {
      control.disabled = !connected;
    }
    // 押して話すボタンは disabled にせず、新しく押し始められないようにするだけ（speech.js の enabled）
    if (this.talk) this.talk.enabled = connected;
  }

  renderRoom({ players, game, you }) {
    this.game = game;
    this.isSetter = you.is_setter;
    // 経過時間はサーバーが送った時点の秒数から画面側で進める
    this.startedAt = game ? performance.now() / 1000 - game.elapsed : 0;
    $("players").replaceChildren(
      ...players.map((player) => {
        const item = document.createElement("span");
        item.className = player.online ? "player online" : "player";
        item.textContent = player.name;
        return item;
      }),
    );
    const secret = $("secret");
    secret.hidden = !you.is_setter;
    secret.textContent = you.is_setter ? `🤫 お題「${you.topic}」${you.hint ? `　補足: ${you.hint}` : ""}` : "";
    $("start-panel").hidden = Boolean(game);
    $("setter-panel").hidden = !game || !you.is_setter;
    $("asker-panel").hidden = !game || you.is_setter;
    if (game) this.closeStartForm();
    if (!game || you.is_setter) this.talk?.cancel("ゲームが終わったため取り消しました");
    this.renderStatus();
  }

  renderStatus() {
    if (!this.game) {
      $("game-status").textContent = "ゲームは始まっていません。誰かが「お題を出す」から始めます";
      return;
    }
    const elapsed = Math.max(0, Math.floor(performance.now() / 1000 - this.startedAt));
    const setter = this.isSetter ? "あなた" : this.game.setter;
    $("game-status").textContent = `出題者 ${setter}・質問 ${this.game.questions}・${formatElapsed(elapsed)}`;
  }

  renderLog(entries) {
    this.items.clear();
    $("log").replaceChildren();
    for (const entry of entries) this.upsertEntry(entry);
  }

  upsertEntry(entry) {
    const log = $("log");
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
    let item = this.items.get(entry.id);
    if (!item) {
      item = document.createElement("li");
      item.dataset.id = String(entry.id);
      this.items.set(entry.id, item);
      log.append(item);
      while (log.children.length > LOG_LIMIT) {
        const oldest = log.firstElementChild;
        this.items.delete(Number(oldest.dataset.id));
        oldest.remove();
      }
    }
    item.className = entry.pending ? "entry pending" : "entry";
    const parts = [];
    if (entry.author) {
      const author = document.createElement("span");
      author.className = "author";
      author.textContent = entry.author;
      parts.push(author);
    }
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = entry.text;
    parts.push(text);
    item.replaceChildren(...parts);
    if (atBottom) log.scrollTop = log.scrollHeight;
  }

  bindControls() {
    $("invite-open").addEventListener("click", () => this.openInvite());
    $("invite-close").addEventListener("click", () => $("invite").close());
    $("invite-copy").addEventListener("click", () => this.copyInvite());
    $("start-open").addEventListener("click", () => {
      $("start-open").hidden = true;
      $("start-form").hidden = false;
      $("topic").focus();
    });
    $("start-cancel").addEventListener("click", () => this.closeStartForm());
    $("start-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const topic = $("topic").value.trim();
      if (!topic) return;
      if (!this.send({ type: "start", topic, hint: $("hint").value.trim() })) return;
      $("topic").value = "";
      $("hint").value = "";
      this.closeStartForm();
    });
    const giveup = () => {
      if (confirm("ギブアップしてお題を公開しますか？")) this.send({ type: "giveup" });
    };
    $("setter-giveup").addEventListener("click", giveup);
    $("asker-giveup").addEventListener("click", giveup);
    $("mode-toggle").addEventListener("click", () => this.setTextMode(!this.textMode));
    $("text-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const text = $("text-input").value.trim();
      if (!text) return;
      $("text-input").value = "";
      this.ask(text);
    });
  }

  closeStartForm() {
    $("start-form").hidden = true;
    $("start-open").hidden = false;
  }

  setTextMode(on) {
    this.textMode = on || !speechSupported;
    $("voice").hidden = this.textMode;
    $("text-form").hidden = !this.textMode;
    $("mode-toggle").textContent = this.textMode ? "🎙 声で質問" : "⌨ 文字で質問";
    if (this.textMode) this.talk?.cancel();
  }

  async openInvite() {
    const url = `${location.origin}/r/${this.code}`;
    $("invite-code").textContent = this.code;
    $("invite-url").textContent = url;
    $("invite-message").textContent = "";
    if (!$("invite").open) $("invite").showModal();
    try {
      await renderQr($("invite-qr"), url);
    } catch {
      $("invite-message").textContent = "QR コードを表示できませんでした。URL を共有してください";
    }
  }

  async copyInvite() {
    try {
      await navigator.clipboard.writeText(`${location.origin}/r/${this.code}`);
      $("invite-message").textContent = "コピーしました";
    } catch {
      $("invite-message").textContent = "コピーできませんでした。URL を長押ししてコピーしてください";
    }
  }

  notice(text) {
    $("notice").textContent = text;
    clearTimeout(this.noticeTimer);
    this.noticeTimer = setTimeout(() => {
      $("notice").textContent = "";
    }, NOTICE_MS);
  }
}

const match = /^\/r\/([^/]+)\/?$/.exec(location.pathname);
if (!match) {
  initHome();
} else {
  const code = match[1].toUpperCase();
  if (!ROOM_CODE_PATTERN.test(code)) showFatal("ルームが見つかりません（URL を確かめてください）");
  else if (code !== match[1]) location.replace(`/r/${code}${location.search}`);
  else initRoom(code);
}
