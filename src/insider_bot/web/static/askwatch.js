// 送った質問がサーバーに届いたかを見張る。
// 半開きの接続（スマホの回線切り替え直後など）では WebSocket.send() が失敗を知らせずに捨てるため、
// 送った後にサーバーから何も届かなければ、届いていない可能性があると知らせる
export const ASK_ACK_TIMEOUT_MS = 5000;

export class AskWatch {
  constructor(onLost) {
    this.onLost = onLost;
    this.pending = [];
  }

  sent(text) {
    const item = { text, timer: null };
    item.timer = setTimeout(() => {
      this.pending = this.pending.filter((other) => other !== item);
      this.onLost(text);
    }, ASK_ACK_TIMEOUT_MS);
    this.pending.push(item);
  }

  /** サーバーから何か届いた。送った後に届いたので、接続は生きていて質問も届いている。 */
  received() {
    for (const item of this.pending) clearTimeout(item.timer);
    this.pending = [];
  }

  /** 接続が切れた。届いたか分からない質問を、時間切れを待たずに知らせる。 */
  lost() {
    const pending = this.pending;
    this.pending = [];
    for (const item of pending) {
      clearTimeout(item.timer);
      this.onLost(item.text);
    }
  }
}
