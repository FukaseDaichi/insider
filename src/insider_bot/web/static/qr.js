// 招待パネルの QR 表示と、サイト内の QR 読み取り
import { parseRoomCode } from "./roomurl.js";

const QRCODE_SRC = "/static/vendor/qrcode-generator-1.4.4.js";
const JSQR_SRC = "/static/vendor/jsQR-1.4.0.js";
const QR_SCALE = 8;
const QR_MARGIN = 4;
const SCAN_INTERVAL_MS = 100;
const SCAN_MAX_WIDTH = 640;
const CAMERA_HELP = "スマホ標準のカメラでも読み取れます";

const loading = new Map();

// 使うときだけ読み込む（外向き通信を抑えるため。jsQR は大きい）
function loadScript(src) {
  if (!loading.has(src)) {
    loading.set(
      src,
      new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = src;
        script.onload = () => resolve();
        script.onerror = () => {
          loading.delete(src);
          reject(new Error(`${src} を読み込めませんでした`));
        };
        document.head.append(script);
      }),
    );
  }
  return loading.get(src);
}

/** text の QR をキャンバスに描く。innerHTML を使わないよう、モジュールを 1 つずつ塗る。 */
export async function renderQr(canvas, text) {
  await loadScript(QRCODE_SRC);
  const qr = window.qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const count = qr.getModuleCount();
  const size = (count + QR_MARGIN * 2) * QR_SCALE;
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  context.fillStyle = "#fff";
  context.fillRect(0, 0, size, size);
  context.fillStyle = "#000";
  for (let row = 0; row < count; row++) {
    for (let col = 0; col < count; col++) {
      if (qr.isDark(row, col)) {
        context.fillRect((col + QR_MARGIN) * QR_SCALE, (row + QR_MARGIN) * QR_SCALE, QR_SCALE, QR_SCALE);
      }
    }
  }
}

export class Scanner {
  constructor(dialog, video, message, onRoom) {
    this.dialog = dialog;
    this.video = video;
    this.message = message;
    this.onRoom = onRoom;
    this.stream = null;
    this.timer = null;
    this.canvas = document.createElement("canvas");
    this.context = this.canvas.getContext("2d", { willReadFrequently: true });
    dialog.addEventListener("close", () => this.stop());
  }

  async open() {
    this.dialog.showModal();
    this.say("カメラを起動しています…");
    try {
      await loadScript(JSQR_SRC);
    } catch {
      this.say(`読み取りの準備に失敗しました。${CAMERA_HELP}`);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      this.say(`このブラウザではカメラを使えません。${CAMERA_HELP}`);
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
    } catch {
      this.say(`カメラを使えませんでした。${CAMERA_HELP}`);
      return;
    }
    if (!this.dialog.open) {
      // 起動を待つ間に閉じられた
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    this.stream = stream;
    this.video.srcObject = stream;
    try {
      await this.video.play();
    } catch {
      // 自動再生が止められても、映像のフレームは読める
    }
    this.say("QR コードを枠に合わせてください");
    this.timer = setInterval(() => this.scan(), SCAN_INTERVAL_MS);
  }

  scan() {
    const { videoWidth: width, videoHeight: height } = this.video;
    if (!width || !height) return;
    const scale = Math.min(1, SCAN_MAX_WIDTH / width);
    this.canvas.width = Math.round(width * scale);
    this.canvas.height = Math.round(height * scale);
    this.context.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);
    const image = this.context.getImageData(0, 0, this.canvas.width, this.canvas.height);
    const found = window.jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" });
    if (!found) return;
    const code = parseRoomCode(found.data, location.origin);
    if (!code) {
      this.say("このゲームの QR コードではありません");
      return;
    }
    this.close();
    this.onRoom(code);
  }

  say(text) {
    this.message.textContent = text;
  }

  close() {
    if (this.dialog.open) this.dialog.close();
    else this.stop();
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.video.srcObject = null;
  }
}
