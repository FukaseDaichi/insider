// 押して話す: ボタン（PC はスペースキー）を押している間だけ Web Speech API で聞き取り、離したら送る
const Recognition =
  globalThis.SpeechRecognition ?? globalThis.webkitSpeechRecognition;
export const speechSupported = Boolean(Recognition);

const MAX_HOLD_MS = 20000;
const STOP_WAIT_MS = 2000;
const CANCELLED = "取り消しました";
const LABELS = {
  idle: "押して話す",
  starting: "準備中…",
  listening: "聞いています…",
  outside: "離すと取り消し",
  stopping: "送信中…",
};
const MIC_DENIED =
  "マイクが許可されていません。ブラウザの設定から許可するか、文字で質問してください";
// 聞き直しても直らないエラー。文字入力に切り替える
const UNAVAILABLE_ERRORS = {
  "not-allowed": MIC_DENIED,
  "service-not-allowed": MIC_DENIED,
  "audio-capture": "マイクが見つかりません",
  "language-not-supported": "このブラウザは日本語の音声認識に対応していません",
};

/**
 * result イベントの内容を、それまでに確定した文字に合わせる。
 * 確定分は resultIndex 以降の新しいものだけを足し（二重に数えない）、未確定の部分はその時点のものに置き換える。
 * stop() は全区間の確定を保証しないので、呼び出し側は「確定分＋未確定の末尾」を送る。
 */
export function mergeResults(finals, results, resultIndex) {
  let added = "";
  for (let i = resultIndex; i < results.length; i++) {
    if (results[i].isFinal) added += results[i][0].transcript;
  }
  let interim = "";
  for (let i = 0; i < results.length; i++) {
    if (!results[i].isFinal) interim += results[i][0].transcript;
  }
  return { finals: finals + added, interim };
}

export class PushToTalk {
  constructor(button, handlers) {
    this.button = button;
    this.handlers = handlers;
    this.state = "idle";
    this.outside = false;
    this.pointerId = null;
    this.keyHeld = false;
    this.everStarted = false;
    this.recognition = null;
    this.finals = "";
    this.interim = "";
    this.error = null;
    this.holdTimer = null;
    this.stopTimer = null;
    this.enabled = true;
    this.bindPointer();
    this.bindKeyboard();
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this.cancel(CANCELLED);
    });
    this.render();
  }

  // 接続が切れている間は新しく押し始めさせない。押している途中で切れた分は、送るときに呼び出し側が扱う
  // （ボタン自体を disabled にすると、押している途中の pointerup が届かないブラウザがある）
  get enabled() {
    return this._enabled;
  }

  set enabled(value) {
    this._enabled = value;
    this.button.classList.toggle("off", !value);
    this.button.setAttribute("aria-disabled", String(!value));
  }

  text() {
    return (this.finals + this.interim).trim();
  }

  press() {
    if (this.state !== "idle") return;
    this.finals = "";
    this.interim = "";
    this.error = null;
    this.outside = false;
    this.state = "starting";
    this.render();
    this.holdTimer = setTimeout(() => {
      // 押しっぱなしの打ち切り。この後に来る pointerup / keyup は無視する
      this.pointerId = null;
      this.keyHeld = false;
      this.release();
    }, MAX_HOLD_MS);
    this.listen();
  }

  listen() {
    const recognition = new Recognition();
    recognition.lang = "ja-JP";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onstart = () => {
      this.everStarted = true;
      if (this.state === "starting") {
        this.state = "listening";
        this.render();
      }
    };
    recognition.onresult = (event) => {
      ({ finals: this.finals, interim: this.interim } = mergeResults(
        this.finals,
        event.results,
        event.resultIndex,
      ));
      this.handlers.onTranscript(this.text());
    };
    recognition.onerror = (event) => {
      this.error = event.error;
    };
    recognition.onend = () => this.ended();
    this.recognition = recognition;
    try {
      recognition.start();
    } catch {
      this.finish(null, "音声認識を開始できませんでした");
    }
  }

  ended() {
    const error = this.error;
    this.error = null;
    if (this.state === "stopping") {
      this.finish(this.text());
      return;
    }
    if (this.state !== "starting" && this.state !== "listening") return;
    if (error in UNAVAILABLE_ERRORS) {
      this.finish(null);
      this.handlers.onUnavailable(UNAVAILABLE_ERRORS[error]);
      return;
    }
    if (error === "network") {
      this.finish(null, "音声認識サーバーに接続できませんでした");
      return;
    }
    // 押している間に勝手に終わった（Android などで無音が続くと起きる）。聞き取った分を残して聞き直す
    this.finals += this.interim;
    this.interim = "";
    this.listen();
  }

  release() {
    clearTimeout(this.holdTimer);
    if (this.state === "starting") {
      // 初回はマイクの許可を求める間に指を離しがち
      this.finish(
        null,
        this.everStarted
          ? "長押ししてから話してください"
          : "マイクの使用を許可したら、もう一度押して話してください",
      );
      return;
    }
    if (this.state !== "listening") return;
    this.state = "stopping";
    this.render();
    this.recognition.stop();
    this.stopTimer = setTimeout(() => {
      if (this.state === "stopping") this.finish(this.text());
    }, STOP_WAIT_MS);
  }

  cancel(message) {
    if (this.state === "idle") return;
    this.finish(null, message);
  }

  /** text が null なら何も送らない。空文字なら「聞き取れませんでした」。 */
  finish(text, message) {
    clearTimeout(this.holdTimer);
    clearTimeout(this.stopTimer);
    const recognition = this.recognition;
    this.recognition = null;
    if (recognition) {
      recognition.onstart =
        recognition.onresult =
        recognition.onerror =
        recognition.onend =
          null;
      try {
        recognition.abort();
      } catch {
        // すでに終わっている
      }
    }
    this.state = "idle";
    this.outside = false;
    this.pointerId = null;
    this.keyHeld = false;
    this.render();
    this.handlers.onTranscript("");
    if (message) {
      this.handlers.onStatus(message);
      return;
    }
    if (text === null) return;
    if (!text) {
      this.handlers.onStatus("聞き取れませんでした");
      return;
    }
    this.handlers.onText(text);
  }

  render() {
    const state =
      this.state === "listening" && this.outside ? "outside" : this.state;
    this.button.dataset.state = state;
    this.button.textContent = LABELS[state];
  }

  isInside(event) {
    const rect = this.button.getBoundingClientRect();
    return (
      event.clientX >= rect.left &&
      event.clientX <= rect.right &&
      event.clientY >= rect.top &&
      event.clientY <= rect.bottom
    );
  }

  bindPointer() {
    const button = this.button;
    button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !this.enabled || this.state !== "idle") return;
      event.preventDefault();
      button.setPointerCapture(event.pointerId);
      this.pointerId = event.pointerId;
      this.press();
    });
    // 指を捕まえている間は pointerleave がボタン基準で届かないので、座標とボタンの矩形を比べる
    button.addEventListener("pointermove", (event) => {
      if (event.pointerId !== this.pointerId) return;
      const outside = !this.isInside(event);
      if (outside !== this.outside) {
        this.outside = outside;
        this.render();
      }
    });
    button.addEventListener("pointerup", (event) => {
      if (event.pointerId !== this.pointerId) return;
      this.pointerId = null;
      if (this.isInside(event)) this.release();
      else this.cancel(CANCELLED);
    });
    // pointerup の後の lostpointercapture は pointerId を消してあるので無視される
    const lost = (event) => {
      if (event.pointerId !== this.pointerId) return;
      this.pointerId = null;
      this.cancel(CANCELLED);
    };
    button.addEventListener("pointercancel", lost);
    button.addEventListener("lostpointercapture", lost);
    button.addEventListener("contextmenu", (event) => event.preventDefault());
  }

  bindKeyboard() {
    window.addEventListener("keydown", (event) => {
      if (event.code === "Escape" && this.keyHeld) {
        this.keyHeld = false;
        this.cancel(CANCELLED);
        return;
      }
      if (event.code !== "Space" || event.repeat || !this.keyboardUsable(event))
        return;
      event.preventDefault();
      if (this.state !== "idle") return;
      this.keyHeld = true;
      this.press();
    });
    window.addEventListener("keyup", (event) => {
      if (event.code !== "Space" || !this.keyHeld) return;
      event.preventDefault();
      this.keyHeld = false;
      this.release();
    });
  }

  keyboardUsable(event) {
    const target = event.target;
    if (
      target instanceof HTMLElement &&
      (target.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
    ) {
      return false;
    }
    if (
      target instanceof HTMLElement &&
      target !== this.button &&
      target.closest("button, a, summary")
    )
      return false;
    if (document.querySelector("dialog[open]")) return false;
    return this.enabled && this.button.offsetParent !== null;
  }
}
