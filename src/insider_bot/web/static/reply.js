// 返事モデル（/api/village の JSON）を LINE のトークと同じ形（吹き出し・画像・テンプレートのカード）で描く。
// 文字はすべて textContent で入れ、innerHTML は使わない。
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
      // LINE の確認テンプレートは、ボタンを横に並べる
      confirm: reply.type === "confirm",
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
  const row = element("div", "tpl-actions");
  for (const action of actions) {
    if (action.kind === "link") {
      const link = element("a", "tpl-action", action.label);
      link.href = action.value;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      row.append(link);
      continue;
    }
    const button = element("button", "tpl-action", action.label);
    button.type = "button";
    button.addEventListener("click", () => onAction(action));
    row.append(button);
  }
  return row;
}

function renderView(view, onAction) {
  if (view.kind === "text") return element("p", "bubble", view.text);
  if (view.kind === "image") return image("photo", view.src);
  const card = element("div", view.confirm ? "tpl tpl-confirm" : "tpl");
  if (view.image) card.append(image("tpl-image", view.image));
  const body = element("div", "tpl-body");
  if (view.title) body.append(element("p", "tpl-title", view.title));
  body.append(element("p", "tpl-text", view.text));
  card.append(body);
  if (view.actions.length) card.append(renderActions(view.actions, onAction));
  return card;
}

/** 返事の列を、吹き出しなどの要素の列にする。ボタンが押されたら onAction({label, kind, value}) を呼ぶ。 */
export function replyNodes(replies, onAction, origin = location.origin) {
  const nodes = [];
  for (const reply of replies) {
    const view = replyView(reply, origin);
    if (view) nodes.push(renderView(view, onAction));
  }
  return nodes;
}
