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

/** 投票できる相手（自分以外の参加者）。名前はルームの参加者一覧から引く。 */
export function voteTargets(insider, players, myId) {
  const names = new Map(players.map((player) => [player.id, player.name]));
  return insider.participants.filter((id) => id !== myId).map((id) => ({ id, name: names.get(id) ?? "?" }));
}

const HEADLINES = {
  villagers: "村人の勝ち！",
  insider: "インサイダーの勝ち！",
};

/** 結果のカードに出す形。誰が誰に入れたかはサーバーも送らない。 */
export function resultView(data) {
  let headline = HEADLINES[data.winner] ?? "全員の負け…";
  if (data.ending === "time_up") headline = "時間切れ　全員の負け…";
  if (data.ending === "giveup") headline = "ギブアップ　全員の負け…";
  return {
    title: `インサイダーは ${data.insider}`,
    headline,
    topic: data.topic ?? null,
    guesser: data.guesser ?? null,
    // 同じ名前の人がいても取り違えないよう、インサイダーの行は ID で見分ける
    rows: (data.votes ?? []).map((vote) => ({ name: vote.name, count: vote.count, insider: vote.id === data.insider_id })),
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
