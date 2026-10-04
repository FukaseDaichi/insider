// 正解のときのクラッカー。画面の左下と右下の隅から紙吹雪を打ち上げ、ひらひら舞い落ちさせる。
// 画面全体に重ねたキャンバスに描き、紙片が全部消えたら取り除く。
// 速さ・重力・落ちる速さは画面の高さに比例させ、どの画面でも高さの 6〜8 割まで上がるようにする
const COLORS = ["#dfef78", "#bdb2e4", "#f1f0e9", "#ff9f80", "#7fe0c8", "#ffd75e"];
const PER_SIDE = 80;
// この高さの画面を基準に、速さ・重力・落ちる速さを決めてある
const BASE_HEIGHT = 600;
const GRAVITY = 0.22;
const FALL_SPEED = 3.2;
const DRAG = 0.975;
const SWAY = 0.7;
// 寿命（フレーム数、60fps で約 5.7 秒）。尽きる前の 40 フレームで薄くして消す
const LIFE = 340;
const FADE = 40;
// 回転しながら下の縁を越えても、すぐには消さない
const MARGIN = 30;
// 左右を少しずらして、ポン、ポンと 2 回鳴った感じにする
const RIGHT_DELAY_MS = 130;
const FRAME_MS = 1000 / 60;
// 裏から戻ったときなどに、紙片が一気に飛ばないようにする
const MAX_DT = 2.5;
const TAU = Math.PI * 2;

/** 片側のクラッカーから飛び出す紙片。左は右上へ、右はそれを左右反転して左上へ飛ぶ。 */
export function burst(side, width, height, random = Math.random) {
  const scale = height / BASE_HEIGHT;
  const direction = side === "left" ? 1 : -1;
  return Array.from({ length: PER_SIDE }, () => {
    // 角度と強さを少しずつばらつかせて、扇形に広げる
    const angle = -1.15 + (random() - 0.5) * 0.5;
    const speed = (20 + random() * 10) * scale;
    return {
      x: side === "left" ? 0 : width,
      y: height,
      vx: Math.cos(angle) * speed * direction,
      vy: Math.sin(angle) * speed,
      scale,
      t: 0,
      life: LIFE,
      rotation: random() * TAU,
      spin: (random() - 0.5) * 0.25,
      // 紙片が裏返る角度。裏を向いている間は暗く描く
      flip: random() * TAU,
      flipSpeed: 0.08 + random() * 0.18,
      phase: random() * TAU,
      width: 7 + random() * 6,
      height: 4 + random() * 4,
      color: COLORS[Math.floor(random() * COLORS.length)],
    };
  });
}

/** dt フレームぶん動かし、画面の下へ抜けた紙片と寿命が尽きた紙片を除いて返す。 */
export function step(particles, dt, height) {
  const drag = DRAG ** dt;
  for (const p of particles) {
    p.t += dt;
    p.vx *= drag;
    p.vy = Math.min(p.vy * drag + GRAVITY * p.scale * dt, FALL_SPEED * p.scale);
    // 勢いが落ちてから、左右に揺れながら落ちる
    const sway = Math.sin(p.t * 0.08 + p.phase) * SWAY * p.scale * Math.min(1, p.t / FADE);
    p.x += (p.vx + sway) * dt;
    p.y += p.vy * dt;
    p.rotation += p.spin * dt;
    p.flip += p.flipSpeed * dt;
  }
  return particles.filter((p) => p.y < height + MARGIN && p.t < p.life);
}

function draw(context, particles, width, height) {
  context.clearRect(0, 0, width, height);
  for (const p of particles) {
    const facing = Math.cos(p.flip);
    context.save();
    context.globalAlpha = Math.min(1, (p.life - p.t) / FADE);
    context.translate(p.x, p.y);
    context.rotate(p.rotation);
    context.scale(1, facing);
    context.fillStyle = p.color;
    context.fillRect(-p.width / 2, -p.height / 2, p.width, p.height);
    if (facing < 0) {
      context.fillStyle = "rgba(0, 0, 0, 0.28)";
      context.fillRect(-p.width / 2, -p.height / 2, p.width, p.height);
    }
    context.restore();
  }
}

/**
 * 左右のクラッカーを鳴らす。画面が裏にあるときと、視差効果を減らす設定では出さない。
 * 出したら true。裏に回ったら、戻ったときに残りを出さずに片付ける。
 */
export function fireCrackers({ doc = document, view = window, random = Math.random } = {}) {
  if (doc.visibilityState === "hidden") return false;
  if (view.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  const canvas = doc.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) return false;
  const width = view.innerWidth;
  const height = view.innerHeight;
  const ratio = Math.min(view.devicePixelRatio || 1, 2);
  canvas.className = "confetti";
  canvas.setAttribute("aria-hidden", "true");
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  context.scale(ratio, ratio);
  doc.body.append(canvas);

  let particles = burst("left", width, height, random);
  let rightFired = false;
  let start = null;
  let last = null;
  const frame = (now) => {
    start ??= now;
    const dt = last === null ? 1 : Math.min((now - last) / FRAME_MS, MAX_DT);
    last = now;
    if (!rightFired && now - start >= RIGHT_DELAY_MS) {
      particles.push(...burst("right", width, height, random));
      rightFired = true;
    }
    particles = step(particles, dt, height);
    if (doc.visibilityState === "hidden" || (rightFired && particles.length === 0)) {
      canvas.remove();
      return;
    }
    draw(context, particles, width, height);
    view.requestAnimationFrame(frame);
  };
  view.requestAnimationFrame(frame);
  return true;
}
