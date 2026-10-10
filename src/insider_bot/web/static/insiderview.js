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
  voteProgress,
  voteTargets,
} from "./insider.js";

const $ = (id) => document.getElementById(id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// 名前ごとの大きなボタン。押すと選ぶ・外す（aria-pressed）
function pickButton(label, pressed, onClick) {
  const button = element("button", "pick", label);
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
        pickButton(player.id === you.id ? `${names.get(player.id)}（自分）` : names.get(player.id), this.selected.has(player.id), () => {
          if (this.selected.has(player.id)) this.selected.delete(player.id);
          else this.selected.add(player.id);
          this.renderPicker();
        }),
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
    $("role-open").hidden = role === null;
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
      status.textContent = voteProgress(insider, players);
      if (role !== null) this.renderVotes(insider, players, you.id);
    } else {
      status.textContent = "";
    }
    return role !== null || insider.phase === "done";
  }

  renderVotes(insider, players, myId) {
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

  static resultNodes(data, players = []) {
    const view = resultView(data, players);
    const nodes = [element("p", "insider-result-headline", view.headline), element("p", "insider-result-title", view.title)];
    if (view.topic) nodes.push(element("p", "insider-result-topic", `お題：${view.topic}`));
    if (view.guesser) nodes.push(element("p", "insider-result-meta", `正解者：${view.guesser}`));
    if (view.rows.length) {
      const list = element("ul", "insider-result-votes");
      for (const row of view.rows) {
        const item = element("li", row.insider ? "is-insider" : "");
        item.append(element("span", "", row.name), element("span", "count", `${row.count} 票`));
        list.append(item);
      }
      nodes.push(list);
    }
    return nodes;
  }
}
