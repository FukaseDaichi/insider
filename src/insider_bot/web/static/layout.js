// スマホでは参加者一覧などの固定情報をハンバーガーメニューへ寄せ、
// 広い画面では元の場所へ戻す。要素そのものを動かすので id は変わらず、描画側は影響を受けない。

export function placeChrome(compact, moves) {
  for (const { node, wide, narrow } of moves) (compact ? narrow : wide).append(node);
}

// matchMedia の結果を、最初の状態とその後の変化の両方で知らせる
export function watchCompact(media, onChange) {
  onChange(media.matches);
  media.addEventListener("change", (event) => onChange(event.matches));
}
