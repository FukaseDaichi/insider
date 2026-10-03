// 画面全体: トップページ、名前の入力、ルーム画面（WebSocket の接続と再接続）
import { parseAnswer } from "./answer.js";
import { AskWatch } from "./askwatch.js";
import { HOST_NAME, hostLines } from "./host.js";
import { placeChrome, watchCompact } from "./layout.js";
import { renderQr, Scanner } from "./qr.js";
import { ROOM_CODE_PATTERN } from "./roomurl.js";
import { SoundPlayer } from "./sound.js";
import { PushToTalk, speechSupported } from "./speech.js";

const $ = (id) => document.getElementById(id);
const NAME_KEY = "odai:name";
const tokenKey = (code) => `odai:token:${code}`;
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 10000];
const NOTICE_MS = 5000;
const LOG_LIMIT = 300;
// この幅以下では、参加者などの固定情報を上部のメニューにしまって会話を広く見せる
const COMPACT_LAYOUT = "(max-width: 900px)";
const CLOSE_MESSAGES = {
  4400: "ルームに入れませんでした。名前を確かめて、もう一度どうぞ",
  4404: "ルームが見つかりません（サーバーが再起動した可能性があります）",
  4409: "このルームは満員です",
};
const NO_SPEECH_HELP =
  "音声入力は Chrome / Edge / Safari で使えます（iPhone は LINE などのアプリの中ではなく Safari で開いてください）。このブラウザでは文字で質問してください";

// トップページでの「入る」などの操作も音の許可に数えるため、ページを開いた時点から見張る
const sounds = new SoundPlayer();
sounds.unlockOn(document);

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
  for (const page of document.querySelectorAll(".page"))
    page.hidden = page.id !== id;
  document.body.dataset.page = id;
}

function showFatal(message) {
  $("fatal-message").textContent = message;
  showPage("fatal");
}

// 案内役「GM」のアバターと吹き出し。行は順番に現れるよう、何行目かを CSS に渡す
function renderHost(lines) {
  // カードの背景に散る小さな飾り（読み上げない）
  const deco = document.createElement("span");
  deco.className = "host-deco";
  deco.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 6; i++) deco.append(document.createElement("i"));

  const avatar = document.createElement("figure");
  avatar.className = "host-avatar";
  avatar.setAttribute("aria-hidden", "true");
  const face = document.createElement("span");
  face.className = "host-face";
  const img = document.createElement("img");
  img.src = "/static/host.png";
  img.alt = "";
  img.width = 160;
  img.height = 160;
  face.append(img);
  avatar.append(face);
  // 登場時に周りへ散る光の粒と、頭の横の勢い線
  for (let i = 0; i < 6; i++) {
    const dot = document.createElement("i");
    dot.className = "host-dot";
    dot.style.setProperty("--n", String(i));
    avatar.append(dot);
  }
  const marks = document.createElement("i");
  marks.className = "host-marks";
  avatar.append(marks);

  // 影は clip-path で切られてしまうので、形を切る枠とその影を付ける外側を分ける
  const bubble = document.createElement("div");
  bubble.className = "host-bubble";
  const frame = document.createElement("div");
  frame.className = "host-bubble-frame";
  const inner = document.createElement("div");
  inner.className = "host-bubble-inner";
  const name = document.createElement("span");
  name.className = "host-name";
  name.textContent = HOST_NAME;
  inner.append(name);
  lines.forEach((line, index) => {
    const p = document.createElement("p");
    p.className = index === 0 ? "host-line lead" : "host-line";
    p.style.setProperty("--i", String(index));
    p.textContent = line;
    inner.append(p);
  });
  const shine = document.createElement("span");
  shine.className = "host-shine";
  shine.setAttribute("aria-hidden", "true");
  frame.append(inner, shine);
  const spark = document.createElement("span");
  spark.className = "host-spark";
  spark.setAttribute("aria-hidden", "true");
  spark.textContent = "✦";
  bubble.append(frame, spark);
  return [deco, avatar, bubble];
}

function formatElapsed(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hours
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${minutes}:${pad(seconds)}`;
}

function initHome() {
  showPage("home");
  $("home-name").value = load(NAME_KEY) ?? "";
  $("home-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = $("home-name").value.trim();
    if (!name) return;
    const button = $("create-room");
    if (button.disabled) return;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.querySelector("span").textContent = "ルームを準備中…";
    save(NAME_KEY, name);
    $("home-message").textContent = "";
    let response = null;
    try {
      response = await fetch("/api/rooms", { method: "POST" });
    } catch {
      // 下でまとめて案内する
    }
    if (!response?.ok) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.querySelector("span").textContent = "ルームを作る";
      $("home-message").textContent =
        "今はルームを作れません。しばらくしてからどうぞ";
      return;
    }
    const { code } = await response.json();
    location.href = `/r/${code}?invite=1`;
  });
  const scanner = new Scanner(
    $("scanner"),
    $("scanner-video"),
    $("scanner-message"),
    (code) => {
      location.href = `/r/${code}`;
    },
  );
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
          onUnavailable: (text, reason) => {
            this.notice(text);
            this.setTextMode(true);
            // iPhone で Safari の音声認識がオフのとき。設定のしかたを常に見える場所に出す
            $("voice-help").hidden = reason !== "service-not-allowed";
          },
        })
      : null;
  }

  start() {
    showPage("room");
    $("room-code").textContent = this.code;
    $("menu-code").textContent = this.code;
    document.title = `ルーム ${this.code} — INSIDER`;
    this.bindControls();
    this.bindMenu();
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
      ws.send(
        JSON.stringify({ type: "join", name: this.name, token: this.token }),
      );
    });
    ws.addEventListener("message", (event) =>
      this.receive(JSON.parse(event.data)),
    );
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
      case "sound":
        sounds.play(message.src);
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
    const delay =
      RETRY_DELAYS_MS[Math.min(this.retry, RETRY_DELAYS_MS.length - 1)];
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
    this.notice(
      "質問が届いていない可能性があります。通信を確かめて、もう一度どうぞ",
    );
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
    for (const control of $("controls").querySelectorAll(
      "button:not(#talk), input, textarea",
    )) {
      control.disabled = !connected;
    }
    // 押して話すボタンは disabled にせず、新しく押し始められないようにするだけ（speech.js の enabled）
    if (this.talk) this.talk.enabled = connected;
    $("giveup-confirm").disabled = !connected;
  }

  renderRoom({ players, game, you }) {
    if (this.game?.id !== game?.id && $("giveup-dialog").open)
      $("giveup-dialog").close();
    this.game = game;
    // 経過時間はサーバーが送った時点の秒数から画面側で進める
    this.startedAt = game ? performance.now() / 1000 - game.elapsed : 0;
    $("menu-count").textContent = String(
      players.filter((player) => player.online).length,
    );
    $("players").replaceChildren(
      ...players.map((player) => {
        const item = document.createElement("span");
        item.className = player.online ? "player online" : "player";
        item.textContent = player.name;
        item.title = `${player.name}：${player.online ? "接続中" : "オフライン"}`;
        return item;
      }),
    );
    const secret = $("secret");
    secret.hidden = !you.is_setter;
    secret.textContent = you.is_setter
      ? `あなただけのお題：${you.topic}${you.hint ? `　／ 補足：${you.hint}` : ""}`
      : "";
    $("start-panel").hidden = Boolean(game);
    // 出題者も質問者に紛れて遊ぶので、全員に同じ操作を出す
    $("asker-panel").hidden = !game;
    if (game) this.closeStartForm();
    if (!game) this.talk?.cancel("ゲームが終わったため取り消しました");
    this.renderStatus();
  }

  renderStatus() {
    if (!this.game) {
      $("game-status").textContent = "準備中 — 仲間を招いて、お題をひとつ。";
      return;
    }
    const elapsed = Math.max(
      0,
      Math.floor(performance.now() / 1000 - this.startedAt),
    );
    $("game-status").replaceChildren(
      ...[
        ["質問", `${this.game.questions} 回`],
        ["経過", formatElapsed(elapsed)],
      ].map(([label, value]) => {
        const stat = document.createElement("span");
        stat.append(label);
        const strong = document.createElement("span");
        strong.className = "status-value";
        strong.textContent = value;
        stat.append(strong);
        return stat;
      }),
    );
  }

  renderLog(entries) {
    this.items.clear();
    $("log").replaceChildren();
    $("empty-room").hidden = entries.length > 0;
    for (const entry of entries) this.upsertEntry(entry);
  }

  upsertEntry(entry) {
    const log = $("log");
    $("empty-room").hidden = true;
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
    item.className = entry.pending
      ? "entry pending"
      : entry.author
        ? "entry"
        : "entry system";
    const parts = [];
    if (entry.author) {
      const author = document.createElement("span");
      author.className = "author";
      author.textContent = entry.author;
      parts.push(author);
    }
    const answer = !entry.pending && parseAnswer(entry.text);
    if (answer) {
      item.classList.add("answer-entry");
      const question = document.createElement("p");
      question.className = "answer-question";
      question.textContent = answer.question;
      const result = document.createElement("div");
      result.className = "answer-result";
      const verdict = document.createElement("strong");
      verdict.className = answer.positive ? "verdict yes" : "verdict no";
      verdict.textContent = answer.positive ? "はい" : "いいえ";
      const scale = document.createElement("div");
      scale.className = "answer-scale";
      const labels = document.createElement("div");
      labels.className = "answer-labels";
      for (const label of [`はい ${answer.yes}%`, `いいえ ${answer.no}%`]) {
        const part = document.createElement("span");
        part.textContent = label;
        labels.append(part);
      }
      const meter = document.createElement("meter");
      meter.min = 0;
      meter.max = 100;
      meter.value = answer.yes;
      meter.setAttribute("aria-label", "はいの割合");
      meter.textContent = `${answer.yes}%`;
      scale.append(labels, meter);
      result.append(verdict, scale);
      parts.push(question, result);
    } else if (!entry.author && !entry.pending && hostLines(entry.text)) {
      item.classList.add("host");
      parts.push(...renderHost(hostLines(entry.text)));
    } else {
      const text = document.createElement("span");
      text.className = "text";
      text.textContent = entry.text;
      parts.push(text);
      if (entry.text.startsWith("🎉 正解です！"))
        item.classList.add("celebration");
    }
    item.replaceChildren(...parts);
    if (atBottom) log.scrollTop = log.scrollHeight;
  }

  // スマホでは招待ボタンと参加者一覧をハンバーガーメニューへ移し、広い画面では見出しに戻す
  bindMenu() {
    const moves = [
      { node: $("invite-open"), wide: $("room-actions"), narrow: $("menu-actions") },
      { node: $("players-row"), wide: $("players-slot"), narrow: $("menu-players") },
    ];
    watchCompact(matchMedia(COMPACT_LAYOUT), (compact) => {
      placeChrome(compact, moves);
      if (!compact && $("room-menu").open) $("room-menu").close();
    });
    $("menu-open").addEventListener("click", () => $("room-menu").showModal());
    $("menu-close").addEventListener("click", () => $("room-menu").close());
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
    $("start-cancel").addEventListener("click", () => {
      this.closeStartForm();
      $("start-open").focus();
    });
    $("start-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const topic = $("topic").value.trim();
      if (!topic) return;
      if (!this.send({ type: "start", topic, hint: $("hint").value.trim() }))
        return;
      $("topic").value = "";
      $("hint").value = "";
      this.closeStartForm();
    });
    const giveup = () => {
      this.giveupGameId = this.game?.id;
      $("giveup-dialog").showModal();
    };
    $("giveup-cancel").addEventListener("click", () =>
      $("giveup-dialog").close(),
    );
    $("giveup-confirm").addEventListener("click", () => {
      if (this.game && this.game.id === this.giveupGameId)
        this.send({ type: "giveup" });
      $("giveup-dialog").close();
    });
    $("asker-giveup").addEventListener("click", giveup);
    $("mode-toggle").addEventListener("click", () => {
      this.setTextMode(!this.textMode);
      $(this.textMode ? "text-input" : "talk").focus();
    });
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
    $("mode-toggle").textContent = this.textMode
      ? "声で質問に切り替え"
      : "文字で質問に切り替え";
    if (this.textMode) this.talk?.cancel();
  }

  async openInvite() {
    if ($("room-menu").open) $("room-menu").close();
    const url = `${location.origin}/r/${this.code}`;
    $("invite-code").textContent = this.code;
    $("invite-url").textContent = url;
    $("invite-message").textContent = "";
    if (!$("invite").open) $("invite").showModal();
    try {
      await renderQr($("invite-qr"), url);
    } catch {
      $("invite-message").textContent =
        "QR コードを表示できませんでした。URL を共有してください";
    }
  }

  async copyInvite() {
    try {
      await navigator.clipboard.writeText(`${location.origin}/r/${this.code}`);
      $("invite-message").textContent = "コピーしました";
    } catch {
      $("invite-message").textContent =
        "コピーできませんでした。URL を長押ししてコピーしてください";
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

// 共通のガイドは、ホーム・参加・ゲーム中のどこからでも参照できる。
for (const button of document.querySelectorAll("[data-rules-open]")) {
  button.addEventListener("click", () => $("rules").showModal());
}
$("rules-close").addEventListener("click", () => $("rules").close());

const match = /^\/r\/([^/]+)\/?$/.exec(location.pathname);
if (!match) {
  initHome();
} else {
  const code = match[1].toUpperCase();
  if (!ROOM_CODE_PATTERN.test(code))
    showFatal("ルームが見つかりません（URL を確かめてください）");
  else if (code !== match[1]) location.replace(`/r/${code}${location.search}`);
  else initRoom(code);
}
