// ルームのインサイダーゲームの描画。判断は insider.js にあり、ここは DOM に描いてボタンを結ぶだけ
import {
  DEFAULT_MINUTES,
  dialogsToClose,
  formatRemaining,
  idleStatus,
  initialSelection,
  MAX_MINUTES,
  MIN_MINUTES,
  nameLabels,
  resultView,
  ROLE_LABELS,
  selectable,
  setupProblem,
  startMessage,
  voteSummary,
  voteTargets,
  voteWaiting,
} from "./insider.js";
import { hostImage } from "./host.js";

const $ = (id) => document.getElementById(id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// 名前ごとの大きなボタン。押すと選ぶ・外す（aria-pressed）。note は名前の後ろに小さく添える（「自分」など）
function pickButton(label, pressed, onClick, note) {
  const button = element("button", "pick");
  const text = element("span", "pick-label", label);
  if (note) text.append(element("small", "pick-note", note));
  button.append(text);
  button.type = "button";
  button.setAttribute("aria-pressed", String(pressed));
  button.addEventListener("click", onClick);
  return button;
}

export class InsiderView {
  constructor({ send, notice }) {
    this.send = send;
    this.notice = notice;
    this.room = null;
    this.selected = new Set();
    this.minutes = DEFAULT_MINUTES;
    this.deadline = null;
  }

  get deadlineAt() {
    return this.deadline;
  }

  topicMode() {
    return document.querySelector('input[name="topic-mode"]:checked').value;
  }

  bind() {
    $("insider-open").addEventListener("click", () => this.openSetup());
    $("insider-setup-cancel").addEventListener("click", () => $("insider-setup").close());
    for (const radio of document.querySelectorAll('input[name="topic-mode"]')) {
      radio.addEventListener("change", () => {
        $("insider-topic-field").hidden = this.topicMode() !== "self";
        // 自分で決めるときは自分を選べないので、選択から外す
        if (this.topicMode() === "self") this.selected.delete(this.room.you.id);
        this.renderPicker();
      });
    }
    $("insider-timer").addEventListener("change", () => {
      $("insider-minutes-row").hidden = !$("insider-timer").checked;
    });
    const step = (delta) => {
      this.minutes = Math.min(MAX_MINUTES, Math.max(MIN_MINUTES, this.minutes + delta));
      $("insider-minutes").textContent = String(this.minutes);
    };
    $("minutes-down").addEventListener("click", () => step(-1));
    $("minutes-up").addEventListener("click", () => step(1));
    $("insider-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const setup = {
        selected: this.selected,
        topicMode: this.topicMode(),
        topic: $("insider-topic").value,
        minutes: $("insider-timer").checked ? this.minutes : null,
      };
      const problem = setupProblem(setup);
      $("insider-problem").textContent = problem ?? "";
      if (problem !== null) return;
      if (!this.send(startMessage(setup))) {
        $("insider-problem").textContent = "接続が切れているため送れませんでした";
        return;
      }
      $("insider-topic").value = "";
      $("insider-setup").close();
    });
    $("role-open").addEventListener("click", () => $("role-dialog").showModal());
    $("vote-role").addEventListener("click", () => $("role-dialog").showModal());
    $("role-close").addEventListener("click", () => $("role-dialog").close());
    $("insider-topic-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const topic = $("insider-topic-input").value.trim();
      if (!topic) return;
      if (this.send({ type: "insider_topic", topic })) $("insider-topic-input").value = "";
    });
    $("vote-close").addEventListener("click", () => $("close-vote-dialog").showModal());
    $("close-vote-cancel").addEventListener("click", () => $("close-vote-dialog").close());
    $("close-vote-confirm").addEventListener("click", () => {
      this.send({ type: "close_vote" });
      $("close-vote-dialog").close();
    });
    // 1 回触れただけで回が終わらないよう、通常のギブアップと同じく確かめてから送る
    $("insider-cancel").addEventListener("click", () => $("insider-cancel-dialog").showModal());
    $("insider-cancel-back").addEventListener("click", () => $("insider-cancel-dialog").close());
    $("insider-cancel-confirm").addEventListener("click", () => {
      if (this.room?.insider?.phase === "choosing") this.send({ type: "giveup" });
      $("insider-cancel-dialog").close();
    });
  }

  openSetup() {
    const { players, you } = this.room;
    this.selected = initialSelection(players, you.id, this.topicMode());
    $("insider-problem").textContent = "";
    this.renderPicker();
    $("insider-setup").showModal();
  }

  renderPicker() {
    const { players, you } = this.room;
    const choices = selectable(players, you.id, this.topicMode());
    const names = nameLabels(players);
    $("insider-players").replaceChildren(
      ...choices.map((player) =>
        pickButton(
          names.get(player.id),
          this.selected.has(player.id),
          () => {
            if (this.selected.has(player.id)) this.selected.delete(player.id);
            else this.selected.add(player.id);
            this.renderPicker();
          },
          player.id === you.id ? "（自分）" : undefined,
        ),
      ),
    );
    $("insider-count").textContent = `${this.selected.size} 人選択中（3 人以上）`;
  }

  /** room の変化を描く。返り値は「質問の操作（押して話す）を出してよいか」。 */
  render(room) {
    // 回が替わった・段階が進んだら、もう意味のないダイアログ（前の回の役職・中止や開票の確認）を閉じる
    for (const id of dialogsToClose(this.room?.insider ?? null, room.insider ?? null)) {
      if ($(id).open) $(id).close();
    }
    // 投票が始まったら、畳んだままにならないよう投票パネルを開いておく。その後の開閉は本人に任せ、再描画で変えない
    if (room.insider?.phase === "voting" && this.room?.insider?.phase !== "voting") $("vote-panel").open = true;
    this.room = room;
    const { insider, you, players, game } = room;
    // 設定のシートを開いている間に入ってきた人も、候補に出す
    if ($("insider-setup").open) this.renderPicker();
    const active = insider && insider.phase !== "done";
    // お題当てのフォームを開いている間は、その上に出さない
    $("insider-open").hidden = Boolean(game) || Boolean(active) || !$("start-form").hidden;
    this.deadline = insider?.remaining == null ? null : performance.now() / 1000 + insider.remaining;
    const panel = $("insider-panel");
    panel.hidden = !insider;
    if (!insider) return true;
    const role = insider.you.role;
    // 役職のカード
    // 投票中は役職を見るボタンも投票パネルの中に畳む
    $("role-open").hidden = role === null || insider.phase === "voting";
    if (role !== null) {
      $("role-title").textContent = `あなたは${ROLE_LABELS[role]}`;
      $("role-image").src = insider.you.image ?? "";
      $("role-image").hidden = !insider.you.image;
      $("role-topic").textContent =
        role === "insider"
          ? insider.you.topic
            ? `お題：${insider.you.topic}`
            : "お題を決めてください"
          : "お題はわかりません。質問して当てましょう";
    }
    const status = $("insider-status");
    $("insider-topic-form").hidden = !(insider.phase === "choosing" && role === "insider");
    $("vote-panel").hidden = !(insider.phase === "voting" && role !== null);
    $("insider-cancel").hidden = !(insider.phase === "choosing" && role !== null);
    if (insider.phase === "choosing") {
      status.textContent = role === "insider" ? "あなたがインサイダーです。お題を決めてください" : "インサイダーがお題を考えています…";
    } else if (insider.phase === "asking") {
      status.textContent = role === null ? "見学中（質問・投票はできません）" : "";
    } else if (insider.phase === "voting") {
      // 参加者の進み具合は投票パネルの帯に出す。見学の人にはパネルがないので状態の行に出す
      status.textContent = role === null ? `見学中（投票はできません）・${voteWaiting(insider, players)}` : "";
      if (role !== null) this.renderVotes(insider, players, you.id);
    } else {
      status.textContent = "";
    }
    return role !== null || insider.phase === "done";
  }

  renderVotes(insider, players, myId) {
    $("vote-summary").textContent = voteSummary(insider, players);
    $("vote-waiting").textContent = voteWaiting(insider, players);
    $("vote-targets").replaceChildren(
      ...voteTargets(insider, players, myId).map((target) =>
        pickButton(target.name, insider.you.vote === target.id, () => this.send({ type: "vote", target: target.id })),
      ),
    );
  }

  /** ゲームのない間に上のバーへ出す文。なければ null。 */
  idleLabel() {
    return idleStatus(this.room?.insider);
  }

  remainingLabel() {
    if (this.deadline === null) return null;
    return formatRemaining(this.deadline - performance.now() / 1000);
  }

  /**
   * 結果のカード。勝った側があれば、正解のテロップと同じ型で GM がその陣営のコスプレで発表する
   * （集中線・飛び込むテロップ・名前をいったん「？？？」の札で隠してから明かす帯・票の一覧）。
   * 全員の負けは落ち着いたカード。className は li に付ける
   */
  static resultCard(data, players = []) {
    const view = resultView(data, players);
    const votes = view.rows.length ? [InsiderView.voteList(view.rows)] : [];
    if (view.look === "lose") {
      const nodes = [];
      if (view.label) nodes.push(element("p", "insider-result-label", view.label));
      nodes.push(element("p", "insider-result-headline", view.headline), element("p", "insider-result-title", view.title));
      if (view.topic) nodes.push(element("p", "insider-result-topic", `お題：${view.topic}`));
      return { className: "entry result insider-result lose", nodes: [...nodes, ...votes] };
    }
    const lines = element("span", "celebrate-lines");
    lines.setAttribute("aria-hidden", "true");
    const avatar = element("figure", "celebrate-avatar");
    avatar.setAttribute("aria-hidden", "true");
    const face = element("span", "celebrate-face");
    const img = document.createElement("img");
    img.src = hostImage(`${view.look}-win`);
    img.alt = "";
    img.width = 160;
    img.height = 160;
    face.append(img);
    avatar.append(face);
    // インサイダーの勝ちは、紫の光の粒がゆっくり昇る
    const dust = element("span", "celebrate-dust");
    dust.setAttribute("aria-hidden", "true");
    for (let i = 0; i < 6; i++) dust.append(document.createElement("i"));
    const body = element("div", "celebrate-body");
    // 語ごとの箱に入れ、折り返しは語の間だけ。跳ねる順番は語をまたいで続ける
    const telop = element("strong", "celebrate-telop");
    let index = 0;
    for (const word of view.telop) {
      const box = element("span", "telop-word");
      for (const char of word) {
        const span = element("span", "", char);
        span.style.setProperty("--i", String(index++));
        box.append(span);
      }
      telop.append(box);
    }
    const reveal = element("p", "celebrate-band reveal");
    const name = element("span", "reveal-name");
    const mask = element("span", "reveal-mask", "？？？");
    mask.setAttribute("aria-hidden", "true");
    name.append(mask, element("span", "reveal-real", view.reveal.name));
    reveal.append(element("span", "", `${view.reveal.lead} `), name);
    body.append(telop, reveal);
    const meta = element("p", "celebrate-meta");
    if (view.topic) meta.append(element("span", "", `お題：${view.topic}`));
    if (view.guesser) meta.append(element("span", "", `正解者：${view.guesser}`));
    if (meta.childElementCount) body.append(meta);
    body.append(...votes);
    return { className: `entry celebrate insider-result ${view.look}`, nodes: [lines, dust, avatar, body] };
  }

  static voteList(rows) {
    const list = element("ul", "insider-result-votes");
    for (const row of rows) {
      const item = element("li", row.insider ? "is-insider" : "");
      item.append(element("span", "", row.name), element("span", "count", `${row.count} 票`));
      list.append(item);
    }
    return list;
  }
}
