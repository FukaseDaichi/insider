// ルームのインサイダーゲームの、画面の判断だけを持つ純粋関数。描画は insiderview.js
export const MIN_PARTICIPANTS = 3;
export const MIN_MINUTES = 1;
export const MAX_MINUTES = 30;
export const DEFAULT_MINUTES = 5;
export const TOPIC_MAX = 50;
export const ROLE_LABELS = { insider: "インサイダー", villager: "村人" };

/** 参加者に選べる人。お題を自分で決めるときは、お題を知るので自分を外す。 */
export function selectable(players, myId, topicMode) {
  return topicMode === "self" ? players.filter((player) => player.id !== myId) : players;
}

/** 設定のシートを開いたときに選んでおく人（接続中の人）。 */
export function initialSelection(players, myId, topicMode) {
  return new Set(selectable(players, myId, topicMode).filter((player) => player.online).map((player) => player.id));
}

/** 始められない理由。始められるなら null。サーバーも同じ検査をする。 */
export function setupProblem({ selected, topicMode, topic, minutes }) {
  if (selected.size < MIN_PARTICIPANTS) return `参加者を${MIN_PARTICIPANTS}人以上選んでください`;
  if (topicMode === "self") {
    const trimmed = topic.trim();
    if (trimmed === "") return "お題を入力してください";
    if (trimmed.length > TOPIC_MAX) return `お題は${TOPIC_MAX}文字までです`;
  }
  if (minutes !== null && !(minutes >= MIN_MINUTES && minutes <= MAX_MINUTES)) {
    return `制限時間は${MIN_MINUTES}〜${MAX_MINUTES}分で選んでください`;
  }
  return null;
}

export function startMessage({ selected, topicMode, topic, minutes }) {
  return {
    type: "insider_start",
    participants: [...selected],
    topic_mode: topicMode,
    topic: topicMode === "self" ? topic.trim() : null,
    minutes,
  };
}

export function formatRemaining(seconds) {
  const total = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** 参加者 ID → 画面に出す名前。同じ名前の人には、入った順に（1）（2）を添えて見分ける。 */
export function nameLabels(players) {
  const total = new Map();
  for (const player of players) total.set(player.name, (total.get(player.name) ?? 0) + 1);
  const seen = new Map();
  const labels = new Map();
  for (const player of players) {
    if (total.get(player.name) === 1) {
      labels.set(player.id, player.name);
      continue;
    }
    const n = (seen.get(player.name) ?? 0) + 1;
    seen.set(player.name, n);
    labels.set(player.id, `${player.name}（${n}）`);
  }
  return labels;
}

/** 投票できる相手（自分以外の参加者）。名前はルームの参加者一覧から引く。 */
export function voteTargets(insider, players, myId) {
  const names = nameLabels(players);
  return insider.participants.filter((id) => id !== myId).map((id) => ({ id, name: names.get(id) ?? "?" }));
}

const HEADLINES = {
  villagers: "村人の勝ち！",
  insider: "インサイダーの勝ち！",
};

/** 結果のカードに出す形。誰が誰に入れたかはサーバーも送らない。名前はルームの参加者一覧で見分けを付ける。 */
export function resultView(data, players = []) {
  const names = nameLabels(players);
  let headline = HEADLINES[data.winner] ?? "全員の負け…";
  if (data.ending === "time_up") headline = "時間切れ　全員の負け…";
  if (data.ending === "giveup") headline = "ギブアップ　全員の負け…";
  return {
    title: `インサイダーは ${names.get(data.insider_id) ?? data.insider}`,
    headline,
    topic: data.topic ?? null,
    guesser: data.guesser ?? null,
    // 同じ名前の人がいても取り違えないよう、インサイダーの行は ID で見分ける
    rows: (data.votes ?? []).map((vote) => ({
      name: names.get(vote.id) ?? vote.name,
      count: vote.count,
      insider: vote.id === data.insider_id,
    })),
  };
}

const IDLE_STATUS = {
  choosing: "インサイダーがお題を考えています…",
  voting: "投票中 — インサイダーは誰？",
};

/** お題当てのゲームがない間の上のバー。インサイダーゲームのお題待ち・投票中だけ文を返し、それ以外は null。 */
export function idleStatus(insider) {
  return IDLE_STATUS[insider?.phase] ?? null;
}

/** 投票の進み具合。開票を締め切るか決められるよう、まだ入れていない人の名前を添える。 */
export function voteProgress(insider, players) {
  const names = nameLabels(players);
  const voted = new Set(insider.voted);
  const waiting = insider.participants.filter((id) => !voted.has(id)).map((id) => names.get(id) ?? "?");
  const count = `投票 ${voted.size} / ${insider.participants.length} 人`;
  return waiting.length ? `${count}（まだ：${waiting.join("・")}）` : count;
}

/**
 * 状態が変わって、もう意味のなくなったダイアログの id。
 * 役職のカードは回がなくなったか新しい回になったら、中止の確認はお題待ちでなくなったら、開票の確認は投票中でなくなったら閉じる。
 */
export function dialogsToClose(previous, next) {
  const ids = [];
  const newRound =
    next == null ||
    (previous?.phase === "done" && next.phase !== "done") ||
    JSON.stringify(previous?.participants) !== JSON.stringify(next.participants);
  if (newRound) ids.push("role-dialog");
  if (next?.phase !== "choosing") ids.push("insider-cancel-dialog");
  if (next?.phase !== "voting") ids.push("close-vote-dialog");
  return ids;
}
