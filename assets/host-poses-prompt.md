# GM の場面ごとの絵（6 枚）の生成プロンプト

Web 版のルームで、GM の吹き出しと勝敗のカードに出す絵。`static/host.png`（ウインクでピース）と `static/host-correct.png`（両手を上げて喜ぶ）に続く同じキャラクターの別ポーズ。
OGP 画像（`og-gm-v1-prompt.txt`）と同じく、`host.png` をキャラクターの参照画像にして 1 枚ずつ生成する。

2026-10-11 に Codex（内蔵 image_gen、gpt-6-sol）でこのプロンプトから 6 枚を生成し、`src/insider_bot/web/static/` に下の名前で置いた（`static/host.js` の `HOST_IMAGES` が参照）。作り直すときも同じ名前で上書きする。画面では円く切り抜いて顔に寄せる（`.host-face img` は 1.3 倍、`.celebrate-face img` は 1.1 倍）ので、顔を中央やや上に置き、小物は顔のすぐ横に入れる。

## 共通の指定（毎回プロンプトの先頭に付ける）

```
Generation mode: built-in image_gen, imagegen skill.
Character reference: src/insider_bot/web/static/host.png (CHARACTER IDENTITY AND ILLUSTRATION STYLE REFERENCE).
Output: 512 x 512 PNG, square, opaque background.

Preserve this same recognizable GM girl: black chin-length bob with bangs, warm brown eyes, black ring choker, oversized black hoodie with bright acid-lime (#dfef78) lining and drawstrings. Same expressive anime illustration style as the reference: clean line art, soft cel shading, warm natural skin tones.
Scene: dark charcoal background (#191a20) with sparse soft lime light particles, as in the reference. Bust-up portrait, face centered slightly above the middle of the canvas, head fully inside the frame with margin (the image is shown cropped to a circle around the face). No text, no logos, no watermark, no extra characters, no frame or border.
```

## 1. `host-secret.png` — 口に指「しーっ」（配役直後、インサイダーがお題を考えている間）

```
Pose/expression: index finger raised vertically to her lips in a "shh" gesture, one eye closed in a playful wink, the other eye looking at the viewer, small mischievous closed-mouth smile, slight head tilt. Mood: a shared secret, conspiratorial and cute.
Lighting: subtle lavender (#bdb2e4) rim light on the hair and hoodie in addition to the lime particles.
```

## 2. `host-hurry.png` — 時計を抱えて慌てる（残り 1 分・時間切れ）

```
Pose/expression: hugging a big round classic twin-bell alarm clock with both hands at chest level, clock face visible and slightly tilted; wide-open eyes, raised eyebrows, mouth open in a flustered "ah!", two small comic sweat drops near the temple, a few motion lines. Mood: hurry, panic in a cute way.
Lighting: warm orange (#ffb347) rim light on the clock and hair in addition to the lime particles.
```

## 3. `host-detective.png` — 探偵帽と虫眼鏡（お題が当たって投票へ）

```
Pose/expression: wearing a dark gray detective deerstalker hat over the black bob, holding a large round magnifying glass up to one eye so that eye appears comically enlarged through the lens; the other eye narrowed, confident smirk. Hoodie lining and drawstrings still visible under the hat. Mood: "who is the insider?" sleuthing, playful.
Lighting: lime rim light, a small lime glint on the lens.
```

## 4. `host-giveup.png` — 白旗で苦笑（ギブアップ）

```
Pose/expression: holding a small white flag on a short stick in one raised hand, waving it gently; eyebrows drawn up in a sheepish, apologetic wry smile, eyes half closed, a single sweat drop, shoulders slightly shrugged. Mood: "oh well, nice try", gentle and kind.
Lighting: cooler, softer, slightly desaturated gray-lavender rim light, fewer lime particles.
```

## 5. `host-villagers-win.png` — 村人のコスプレで両手を上げる（村人の勝ち）

```
Pose/expression: the GM girl cosplaying as the villager from the role card: an off-white (#f4f3eb) kerchief head scarf tied over her black bob (bangs still showing), a cream peasant blouse with a lime-green (#dfef78) apron over it, and a small wicker basket of vegetables (carrots, tomato, leafy greens) held in one hand; both arms raised in celebration, big open-mouth happy smile with eyes closed in joy, rosy cheeks. The choker stays visible. Mood: harvest festival victory, warm and cheerful.
Secondary reference for the costume and basket: src/insider_bot/web/static/roles/VILLAGERS.png (COSTUME REFERENCE ONLY; keep the GM girl's face, hair and style from host.png).
Background: dark charcoal with lime and soft green (#8fe3a0) confetti pieces, as in host-correct.png.
```

## 6. `host-insider-win.png` — インサイダーのコスプレで口に指（インサイダーの勝ち）

```
Pose/expression: the GM girl cosplaying as the insider from the role card: a deep purple (#3b2a66) hooded cloak with gold trim and a round gold clasp, hood pulled up over her black bob with the bangs and eyes still clearly visible in shadow; one index finger to her lips in a "shh" gesture, eyes narrowed in a sly, triumphant, knowing smile. Hoodie lining and choker can peek out under the cloak. Mood: "I got away with it", mysterious and smug but charming.
Secondary reference for the cloak and hood: src/insider_bot/web/static/roles/INSIDER.png (COSTUME REFERENCE ONLY; keep the GM girl's face, hair and style from host.png).
Background: darker charcoal (#120f1c) with drifting purple (#bdb2e4, #8a6fd0) light particles and a faint purple glow behind her, no confetti.
```
