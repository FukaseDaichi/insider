// 返事モデル（/api/village の JSON）を画面に描く。文字はすべて textContent で入れ、innerHTML は使わない。
// Web には文字数の制限がないので、LINE 向けの代わりの返事は届かず、本体だけを描く。

/** 画像やリンクに使ってよい URL。https か、このサイト（origin）の URL だけを許す。 */
export function safeUrl(url, origin) {
  if (typeof url !== "string" || url === "") return null;
  let parsed;
  try {
    parsed = new URL(url, origin);
  } catch {
    return null;
  }
  if (parsed.origin === origin || parsed.protocol === "https:") return parsed.href;
  return null;
}

/** ボタン 1 つ。押したときの動作（文字列の送信・ポストバック・リンク）と値に直す。 */
export function actionView(action, origin) {
  if (action?.type === "message") return { label: action.label, kind: "text", value: action.text };
  if (action?.type === "postback") return { label: action.label, kind: "postback", value: action.data };
  if (action?.type === "uri") {
    const href = safeUrl(action.uri, origin);
    return href ? { label: action.label, kind: "link", value: href } : null;
  }
  return null;
}

/** 返事 1 つを描く部品の形にする。知らない形と、使えない URL の画像は描かない。 */
export function replyView(reply, origin) {
  if (reply?.type === "text") return { kind: "text", text: reply.text };
  if (reply?.type === "image") {
    const src = safeUrl(reply.url, origin);
    return src ? { kind: "image", src } : null;
  }
  if (reply?.type === "buttons" || reply?.type === "confirm") {
    return {
      kind: "card",
      title: reply.title ?? null,
      text: reply.text,
      image: safeUrl(reply.image, origin),
      actions: (reply.actions ?? []).map((action) => actionView(action, origin)).filter(Boolean),
    };
  }
  return null;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function image(className, src) {
  const node = element("img", className);
  node.src = src;
  // 役職は本文にも書いてあるので、読み上げでは画像を飛ばす
  node.alt = "";
  return node;
}

function renderActions(actions, onAction) {
  const row = element("div", "reply-actions");
  for (const action of actions) {
    if (action.kind === "link") {
      const link = element("a", "button secondary", action.label);
      link.href = action.value;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      row.append(link);
      continue;
    }
    const button = element("button", "secondary", action.label);
    button.type = "button";
    button.addEventListener("click", () => onAction(action));
    row.append(button);
  }
  return row;
}

function renderView(view, onAction) {
  if (view.kind === "text") return element("p", "reply-text", view.text);
  if (view.kind === "image") return image("reply-image", view.src);
  const card = element("div", "reply-card");
  if (view.image) card.append(image("reply-card-image", view.image));
  if (view.title) card.append(element("p", "reply-card-title", view.title));
  card.append(element("p", "reply-text", view.text));
  if (view.actions.length) card.append(renderActions(view.actions, onAction));
  return card;
}

/** 返事の列で container の中身を置き換える。ボタンが押されたら onAction({label, kind, value}) を呼ぶ。 */
export function renderReplies(container, replies, onAction, origin = location.origin) {
  container.replaceChildren();
  for (const reply of replies) {
    const view = replyView(reply, origin);
    if (view) container.append(renderView(view, onAction));
  }
}
