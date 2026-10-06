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
  // iPhone の Safari は、「設定」の「音声認識」で Safari がオフだとこうなる（マイクの許可とは別）
  "service-not-allowed":
    "音声認識が許可されていません。下の「設定のしかた」を見て、Safari の音声認識をオンにしてください。文字でも質問できます",
  "audio-capture": "マイクが見つかりません",
  "language-not-supported": "このブラウザは日本語の音声認識に対応していません",
};

/**
 * result イベントの結果の一覧を、ここまでに聞き取った 1 本の文字にする。
 * 一覧には聞き始めからの結果がすべて入っているので、毎回はじめから読み直す。
 * resultIndex（どこから新しいか）は、スマホのブラウザによって 0 のまま進まないので使わない。
 * PC の Chrome や Safari は区切りごとに別の文を並べるが、Android の Chrome は continuous だと
 * 「聞き始めからの文全体」を途中経過のたびに足していく（確定扱いのことが多い）。
 * そこで、前までの文で始まる項目は累積の途中経過として置き換え、前までの文の先頭だけの項目は
 * 古い途中経過として捨て、それ以外を新しい区切りとして足す。確定か未確定かは見ない。
 * stop() は全区間の確定を保証しないので、未確定の末尾も含めて送る。
 */
export function readResults(results) {
  let text = "";
  for (let i = 0; i < results.length; i++) {
    const piece = results[i][0].transcript;
    if (piece.startsWith(text)) text = piece;
    else if (!text.startsWith(piece)) text += piece;
  }
  return text;
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
    // earlier は聞き直す前までに聞き取った分。current は今の聞き取りの分
    this.earlier = "";
    this.current = "";
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
    return (this.earlier + this.current).trim();
  }

  press() {
    if (this.state !== "idle") return;
    this.earlier = "";
    this.current = "";
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
      this.current = readResults(event.results);
      this.handlers.onTranscript(this.text());
    };
    recognition.onerror = (event) => {
      this.error = event.error;
      // iPhone の Safari は、使えないときの error の後に end を出さないので待たずに終える
      if (event.error in UNAVAILABLE_ERRORS || event.error === "network")
        this.ended();
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
      this.handlers.onUnavailable(UNAVAILABLE_ERRORS[error], error);
      return;
    }
    if (error === "network") {
      this.finish(null, "音声認識サーバーに接続できませんでした");
      return;
    }
    // ほかのエラー（aborted や分類していないもの）は聞き直してもすぐ同じく終わり、押している間ずっと繰り返すので止める
    if (error && error !== "no-speech") {
      this.finish(null, "音声認識が止まりました。もう一度押して話してください");
      return;
    }
    // 押している間に勝手に終わった（Android などで無音が続くと起きる）。聞き取った分を残して聞き直す
    this.earlier += this.current;
    this.current = "";
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
