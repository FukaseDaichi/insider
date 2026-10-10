// 画面全体: トップページ、名前の入力、ルーム画面（WebSocket の接続と再接続）
import { parseAnswer } from "./answer.js";
import { AskWatch } from "./askwatch.js";
import { fireCrackers } from "./confetti.js";
import { HOST_NAME, hostLines } from "./host.js";
import { InsiderView } from "./insiderview.js";
import { placeChrome, watchCompact } from "./layout.js";
import { isWeak, numberQuestions, questionNote, resultOf } from "./log.js";
import { renderQr, Scanner } from "./qr.js";
import { ROOM_CODE_PATTERN } from "./roomurl.js";
import { SoundPlayer } from "./sound.js";
import { PushToTalk, speechSupported } from "./speech.js";

const $ = (id) => document.getElementById(id);
const NAME_KEY = "odai:name";
const tokenKey = (code) => `odai:token:${code}`;
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 10000];
const NOTICE_MS = 5000;
// 正解のクラッカーは、テロップが着地するころに鳴らす（style.css の .celebrate-telop の animation）
const CRACKER_DELAY_MS = 650;
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
// 音のオン／オフは端末ごとの好みなので、名前と同じく localStorage に覚える
const SOUND_KEY = "odai:sound";
// GM の声をオンにしたとき、聞こえるかをその場で確かめる短い声（返事の「はい」）
const SAMPLE_SOUND = "/static/sounds/yes-90.m4a";
// ブラウザが音を止めたままこれだけ続いたら「タップすると聞こえます」の帯を出す。
// 1 秒ごとの見直しで 2 回続けて止まっていたら出す長さ。読み込み直後や押して話すの途中でちらつかせない
const SOUND_HINT_DELAY_MS = 900;
// 音が動き出してから帯を消すまでの間。同じタップの click が届く前に帯が消えると、
// 指の下に詰まってきた別のボタンが押されてしまう
const SOUND_HINT_SETTLE_MS = 400;
sounds.unlockOn(document);
sounds.watchVisibility(document);

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

// 推理ノートの 1 行: 番号（renumber が埋める）、質問文、質問者
function renderQuestion(author, question) {
  const num = document.createElement("span");
  num.className = "num";
  num.setAttribute("aria-hidden", "true");
  const body = document.createElement("div");
  body.className = "q-body";
  const text = document.createElement("p");
  text.className = "q-text";
  text.textContent = question;
  const by = document.createElement("span");
  by.className = "author";
  by.textContent = author ?? "";
  body.append(text, by);
  return [num, body];
}

// 右端の判定: はい／いいえのチップと、確信度の数字と短いバー
function renderVerdict(answer) {
  const box = document.createElement("div");
  box.className = "verdict-box";
  const chip = document.createElement("strong");
  chip.className = answer.positive ? "verdict yes" : "verdict no";
  if (isWeak(answer.yes)) chip.classList.add("weak");
  chip.textContent = answer.positive ? "はい" : "いいえ";
  const sure = answer.positive ? answer.yes : answer.no;
  const pct = document.createElement("span");
  pct.className = "pct";
  pct.textContent = `${sure}%`;
  const meter = document.createElement("meter");
  meter.min = 0;
  meter.max = 100;
  meter.value = sure;
  meter.setAttribute("aria-label", `${answer.positive ? "はい" : "いいえ"}の確信度`);
  meter.textContent = `${sure}%`;
  pct.append(meter);
  box.append(chip, pct);
  return box;
}

// 判定中・取り消しは、判定の場所に小さな札を置く
function renderNote(note) {
  const box = document.createElement("div");
  box.className = "verdict-box";
  const chip = document.createElement("span");
  chip.className = "verdict note";
  chip.textContent = note;
  box.append(chip);
  return box;
}

// 正解は、GM がバラエティ番組のテロップで発表する。
// 後ろで集中線が回り、「正解！！」のテロップが横から飛び込み、お題の帯と内訳が続く
function renderCelebration(result) {
  const lines = document.createElement("span");
  lines.className = "celebrate-lines";
  lines.setAttribute("aria-hidden", "true");

  const avatar = document.createElement("figure");
  avatar.className = "celebrate-avatar";
  avatar.setAttribute("aria-hidden", "true");
  const face = document.createElement("span");
  face.className = "celebrate-face";
  const img = document.createElement("img");
  img.src = "/static/host-correct.png";
  img.alt = "";
  img.width = 160;
  img.height = 160;
  face.append(img);
  avatar.append(face);

  const body = document.createElement("div");
  body.className = "celebrate-body";
  // テロップは 1 文字ずつ跳ねるよう、何文字目かを CSS に渡す
  const telop = document.createElement("strong");
  telop.className = "celebrate-telop";
  [..."正解！！"].forEach((char, index) => {
    const span = document.createElement("span");
    span.style.setProperty("--i", String(index));
    span.textContent = char;
    telop.append(span);
  });
  const band = document.createElement("p");
  band.className = "celebrate-band";
  band.textContent = `お題は「${result.topic}」`;
  body.append(telop, band);
  if (result.meta) {
    // 内訳は「正解者」「質問数」「経過時間」の項目ごとに折り返す（「1」と「秒」の間で切れないように）
    const meta = document.createElement("p");
    meta.className = "celebrate-meta";
    for (const part of result.meta.split(/　(?=質問数: |経過時間: )/u)) {
      const span = document.createElement("span");
      span.textContent = part;
      meta.append(span);
    }
    body.append(meta);
  }
  return [lines, avatar, body];
}

// ギブアップは、お題の公開が主役の大きなカード
function renderResult(result) {
  const label = document.createElement("span");
  label.className = "result-label";
  label.textContent = "🏳️ ギブアップ";
  const title = document.createElement("strong");
  title.className = "result-title";
  title.textContent = result.title;
  const parts = [label, title];
  if (result.meta) {
    const meta = document.createElement("span");
    meta.className = "result-meta";
    meta.textContent = result.meta;
    parts.push(meta);
  }
  return parts;
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
    this.soundBlockedSince = null;
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
    this.insider = new InsiderView({
      send: (message) => this.send(message),
      notice: (text) => this.notice(text),
    });
  }

  start() {
    showPage("room");
    $("room-code").textContent = this.code;
    $("menu-code").textContent = this.code;
    document.title = `ルーム ${this.code} — INSIDER`;
    this.bindControls();
    this.insider.bind();
    this.bindMenu();
    this.bindLog();
    if (!speechSupported) {
      $("speech-help").textContent = NO_SPEECH_HELP;
      $("speech-help").hidden = false;
      $("mode-toggle").hidden = true;
    }
    this.setTextMode(this.textMode);
    $("offline").textContent = "接続中…";
    this.setConnected(false);
    // 部屋を開いた時点で音を用意しておき、タップ前で止まっている間は帯で知らせる
    sounds.prepare();
    sounds.onChange = () =>
      setTimeout(() => this.renderSoundHint(), SOUND_HINT_SETTLE_MS);
    document.addEventListener("visibilitychange", () =>
      this.renderSoundHint(),
    );
    setInterval(() => {
      this.renderStatus();
      // 状態の変化を知らせない版のブラウザもあるので、時計と一緒に見直す
      this.renderSoundHint();
    }, 1000);
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
        // 判定中の質問が正解に変わった、その場かぎりの合図。snapshot（再接続・途中参加）では鳴らさない
        if (!message.entry.pending && resultOf(message.entry.text)?.kind === "correct")
          setTimeout(() => fireCrackers(), CRACKER_DELAY_MS);
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

  renderRoom(room) {
    const { players, game, you } = room;
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
    const canAsk = this.insider.render(room);
    const busy = Boolean(game) || Boolean(room.insider && room.insider.phase !== "done");
    $("start-panel").hidden = busy;
    // 出題者も質問者に紛れて遊ぶので、全員に同じ操作を出す。インサイダーゲームでは見るだけの人に出さない
    $("asker-panel").hidden = !game || !canAsk;
    if (game) this.closeStartForm();
    if (!game) this.talk?.cancel("ゲームが終わったため取り消しました");
    this.renderStatus();
  }

  renderStatus() {
    if (!this.game) {
      $("game-status").textContent =
        this.insider.idleLabel() ?? "準備中 — 仲間を招いて、お題をひとつ。";
      return;
    }
    const elapsed = Math.max(
      0,
      Math.floor(performance.now() / 1000 - this.startedAt),
    );
    // インサイダーゲームに制限時間があるときは、経過の代わりに残りを出す
    const remaining = this.insider.remainingLabel();
    $("game-status").replaceChildren(
      ...[
        ["質問", `${this.game.questions} 回`],
        remaining === null ? ["経過", formatElapsed(elapsed)] : ["残り", remaining],
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
    this.renumber();
    this.seenAll();
  }

  // 会話欄は「推理ノート」: 1 問 1 行で、左に番号、中央に質問文と質問者、右端に判定。
  // 行の種類（question / host / result / system）は renumber で番号を振るときにも使う
  upsertEntry(entry) {
    const log = $("log");
    $("empty-room").hidden = true;
    const atBottom = this.atBottom();
    let item = this.items.get(entry.id);
    const fresh = !item;
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
    // インサイダーゲームの結果は、文字の読み解きではなく記録の中身で描く
    if (entry.kind === "insider_result" && entry.data) {
      item.className = "entry result insider-result";
      item.dataset.kind = "result";
      item.replaceChildren(...InsiderView.resultNodes(entry.data));
      this.renumber();
      if (atBottom) log.scrollTop = log.scrollHeight;
      return;
    }
    const answer = !entry.pending && parseAnswer(entry.text);
    const note = !answer && questionNote(entry.text);
    // 正解・ギブアップは、言い当てた人やギブアップした人が質問者として付く
    const result = !entry.pending && resultOf(entry.text);
    const host = !entry.author && !entry.pending && hostLines(entry.text);
    if (answer || note) {
      item.className = "entry question";
      item.dataset.kind = "question";
      if (entry.author === this.name) item.classList.add("mine");
      if (note?.cancelled) item.classList.add("cancelled");
      if (entry.pending) item.classList.add("pending");
      item.replaceChildren(
        ...renderQuestion(entry.author, answer ? answer.question : note.question),
        answer ? renderVerdict(answer) : renderNote(note.note),
      );
    } else if (host) {
      item.className = "entry host";
      item.dataset.kind = "host";
      item.replaceChildren(...renderHost(host));
    } else if (result?.kind === "correct") {
      item.className = "entry celebrate";
      item.dataset.kind = "result";
      item.replaceChildren(...renderCelebration(result));
    } else if (result) {
      item.className = "entry result giveup";
      item.dataset.kind = "result";
      item.replaceChildren(...renderResult(result));
    } else {
      item.className = entry.author ? "entry plain" : "entry system";
      item.dataset.kind = "system";
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
    }
    // 判定中→回答の更新でも番号の札を作り直しているので、毎回振り直す（300 件まで）
    this.renumber();
    if (atBottom) log.scrollTop = log.scrollHeight;
    // 上にスクロールして見返している間に届いた質問は、ピルで知らせる
    else if (fresh && item.dataset.kind === "question") this.unseen(1);
  }

  // 質問番号はゲームごとに 1 から。開始の案内で数え直す
  renumber() {
    const items = [...$("log").children];
    const numbers = numberQuestions(items.map((item) => item.dataset.kind));
    items.forEach((item, index) => {
      const n = numbers[index];
      const slot = item.querySelector(".num");
      if (slot) slot.textContent = n === null ? "" : String(n).padStart(2, "0");
    });
  }

  atBottom() {
    const log = $("log");
    return log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  }

  unseen(delta) {
    this.unseenCount = (this.unseenCount ?? 0) + delta;
    const pill = $("log-new");
    pill.hidden = this.unseenCount === 0;
    pill.textContent = `↓ 新しい質問 ${this.unseenCount} 件`;
  }

  seenAll() {
    this.unseenCount = 0;
    $("log-new").hidden = true;
  }

  bindLog() {
    const log = $("log");
    // 最下部を見ている間は、お題の表示や入力欄の切り替えで会話欄が縮んでも最下部に追従する。
    // 縮んだ直後は最下部にいなくても、上へスクロールしたときだけ追従をやめる
    this.following = true;
    this.lastScrollTop = 0;
    log.addEventListener("scroll", () => {
      const up = log.scrollTop < this.lastScrollTop - 1;
      this.lastScrollTop = log.scrollTop;
      if (up) this.following = false;
      else if (this.atBottom()) this.following = true;
      if (this.following) this.seenAll();
    });
    new ResizeObserver(() => {
      if (this.following) log.scrollTop = log.scrollHeight;
    }).observe(log);
    $("log-new").addEventListener("click", () => {
      log.scrollTop = log.scrollHeight;
      this.seenAll();
    });
  }

  // スマホでは招待ボタンと参加者一覧をハンバーガーメニューへ移し、広い画面では見出しに戻す
  bindMenu() {
    const moves = [
      { node: $("invite-open"), wide: $("room-actions"), narrow: $("menu-actions") },
      { node: $("sound-toggle"), wide: $("room-actions"), narrow: $("menu-actions") },
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
    this.setSound(load(SOUND_KEY) !== "off");
    $("sound-toggle").addEventListener("click", () => {
      const on = !sounds.enabled;
      this.setSound(on);
      // 保存済みの設定を戻すときではなく、自分でオンにしたときだけ鳴らす
      if (on) sounds.play(SAMPLE_SOUND);
    });
    // 帯を押したタップで音が動き出すので、聞こえるかをその場で確かめる声を鳴らす
    $("sound-hint").addEventListener("click", () => sounds.play(SAMPLE_SOUND));
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

  setSound(on) {
    sounds.setEnabled(on);
    $("sound-toggle").setAttribute("aria-checked", String(on));
    $("sound-state").textContent = on ? "オン" : "オフ";
    save(SOUND_KEY, on ? "on" : "off");
    this.renderSoundHint();
  }

  // GM の声がオンなのにブラウザが音を止めている間（タップ前・iPhone の電話や音声認識のあと）だけ帯を出す。
  // 押して話すの最中は出さない。話している途中に帯が出入りすると気が散る（止まったままなら離したあとに出る）
  renderSoundHint() {
    const blocked =
      sounds.blocked &&
      document.visibilityState === "visible" &&
      (this.talk?.state ?? "idle") === "idle";
    if (!blocked) this.soundBlockedSince = null;
    else this.soundBlockedSince ??= performance.now();
    $("sound-hint").hidden =
      !blocked ||
      performance.now() - this.soundBlockedSince < SOUND_HINT_DELAY_MS;
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
