# お題当てゲーム GM ボット

Discord で「お題当てゲーム」の GM を務めるボットです。出題者が登録したお題について、
参加者の質問に TypeSafe AI の Jev が「はい／いいえ」とその割合で答え、言い当てたら「正解です」でゲーム終了します。

ブラウザで遊べる **Web 版** もあります。ボタンを押している間に話した言葉が質問になります（[Web 版](#web-版押して話す音声入力)）。

## 遊び方

1. 出題者がゲームをするチャンネルで `/odai set お題:りんご 補足:赤い果物`（補足は任意）
   - お題は出題者本人にしか表示されません
2. 参加者はそのチャンネルに、最後に「？」をつけて質問を書き込む
   ```
   ❓ 果物ですか？
   ✅ はい　　はい 82% ██████████░░ いいえ 18%
   ```
3. お題を言い当てると `🎉 正解です！` でゲーム終了
- `/odai status` … 進行状況（質問数・経過時間）
- `/odai giveup` … お題を公開して終了

ゲーム中のチャンネルでは、出題者以外の発言のうち末尾が「？」か「?」のものだけが質問として扱われます（答えを言うときも「りんご？」のように「？」をつけます）。それ以外の発言は雑談として無視されます。
ボットを再起動すると進行中のゲームは消えます。

## Web 版（押して話す音声入力）

Discord の代わりにブラウザで遊べます。Discord 版とは別のゲームで、会話は Discord や Zoom の通話で行う想定です。

1. トップページで名前を入れて「ルームを作る」→ 招待パネルの URL か QR コードを仲間に共有する
2. 誰かが「お題を出す」でお題を登録する（お題は出題者の画面にだけ表示され、誰が出したかは表示されない）
3. 全員（出題者も）が「🎙 押して話す」を押しながら質問し、離すと送られる（末尾の「？」は自動で付く）。ボタンの外で指を離すと取り消し。PC はスペースキー長押しでも話せる
4. 正解かギブアップで終了（ギブアップは誰でもできる）

- 音声入力は Chrome / Edge / Safari で使えます（iPhone で話せないときは、画面に出る「設定のしかた」に従って Safari の音声認識をオンに）。使えないブラウザでは文字で質問します
- トップページの「📷 QR で参加」で、カメラから QR コードを読み取って参加できます
- ゲームが始まると開始の音声（3 種類からランダム）が、質問に返事が出ると はい % に応じた声が、全員の画面で流れます。画面を一度も触っていないときや、別のアプリ・タブを見ているときは鳴りません。ルーム画面の「🔊 音あり」を押すと音を止められます
- サーバーを再起動するとルームは消えます

```bash
uv run --env-file .env python -m insider_bot.web   # http://localhost:8080 を開く
```

`localhost` 以外からマイクを使うには HTTPS が必要です。

### インサイダーの配役

Web 版の `/village`（トップページの「インサイダーの配役」）で、LINE Bot と同じように役職とお題を配れます。

1. 「村を作る」で種類・お題・人数を決め、表示された村番号か QR を参加者に伝える
2. 参加者は `/village` で村番号を入れるか QR を読み取り、自分の役職を見る（同じブラウザなら、もう一度開いても同じ役職）
3. 「特殊村を作る」では、1 行 1 通で入れたメッセージを、参加した人に 1 通ずつ配れる

役職画像は神・GM・村人・インサイダー各5枚を同梱し、表示するたびに同じ役職の5枚から等確率で選びます。画像URLにはバージョンを付け、画像を更新した際に旧画像のキャッシュが使われないようにします。

### LINE Bot

Web 版のプロセスが LINE Bot の webhook も受けます。`LINE_CHANNEL_SECRET`・`LINE_CHANNEL_TOKEN` と、https の `PUBLIC_BASE_URL` を設定すると `/line/callback` が有効になります。LINE で作った村に Web から入れます（逆も同じ）。

1. LINE Developers のチャネルで、Webhook URL を `https://<公開 URL>/line/callback` にし、Webhook の利用をオンにする（応答メッセージはオフ）
2. コンソールの「検証」で成功を確かめる

LINE へ送らずに確かめるときは、返信 API のスタブを起動し、Web 版を `LINE_API_BASE_URL=http://127.0.0.1:18080` を足して起動してから、署名付きの webhook を送ります。署名のチャネルシークレットは `.env` の `LINE_CHANNEL_SECRET`（Web 版と同じ値）から読みます。返信の中身はスタブの端末に出ます。

```bash
uv run python deploy/verify/line_api_stub.py 18080
```

```bash
uv run --env-file .env python deploy/verify/post_callback.py http://127.0.0.1:8080/line/callback text U0000 お題
```

LINE の返信が Java の LineBot と同じかは `tests/test_line_golden.py` が確かめます。比べる JSON（`tests/golden/line_callapi.json`）は、Java の LineBot を手元で動かして採ります（`<LineBot>` は LineBot のリポジトリ。Java は本番と同じ 8 を使う）。JSON は 2026-10-06 に Java 8 の LineBot 2.7.0 から採ってあります。`tests/line_golden.py` の手順を変えたら採り直します（採っていない状態では比較を飛ばします）。

```bash
LINE_BOT_CHANNEL_TOKEN=golden LINE_BOT_CHANNEL_SECRET=golden java -jar <LineBot>/insider-game-bot/build/libs/insider-game-bot-2.7.0-SNAPSHOT.jar --server.port=18080
```

```bash
uv run python -m tests.line_golden http://127.0.0.1:18080/callapi
```

### 本番（Oracle Cloud の VM で 24 時間動かす）

Always Free の A1 1 台に Caddy と systemd で載せ、`main` への push で GitHub Actions が配備します（構成は [docs/infra.md](docs/infra.md)）。VM のセットアップは [deploy/setup.md](deploy/setup.md)、画面操作は [deploy/human-steps.md](deploy/human-steps.md)、LINE の切替前検証と切替は [deploy/cutover.md](deploy/cutover.md)。GitHub Secrets（`DEPLOY_HOST`、`DEPLOY_SSH_KEY`、`DEPLOY_HOST_KEY`）が 3 つとも未登録のあいだ、deploy job は配備を飛ばして成功で終わります（一部だけなら失敗します）。本番の VM が動いている間は、下の Mac での起動を使いません（Discord ボットが 2 か所で動くと質問に 2 回返信します）。Mac の `.env` に `PRODUCTION_URL=https://<host>` を書いておくと、`scripts/play.sh` は本番が動いている間は起動を断ります。

### 仲間と遊ぶとき（Mac で起動して公開する）

本番の VM がないあいだ、Discord ボットと Web 版をまとめて起動し、Web 版を Tailscale Funnel で公開します（構成の考え方は [docs/infra.md](docs/infra.md)）。

1. 初回だけ: [Tailscale](https://tailscale.com/download/mac) を入れてログインする
2. `bash scripts/play.sh` を実行し、表示された `https://….ts.net` を仲間に共有する（初回は Funnel を有効にする案内が出るので従う）
3. 遊び終わったら Ctrl+C（ボット・Web 版・公開がすべて止まる）

動いている間は Mac がスリープしません。ノートの蓋を閉じると止まります。

## セットアップ

### 1. Discord ボットを作る

1. https://discord.com/developers/applications で「New Application」
2. 「Bot」タブでトークンを発行（Reset Token）し控える
3. 同じ「Bot」タブの **Privileged Gateway Intents → MESSAGE CONTENT INTENT** をオンにする
4. 「OAuth2 → URL Generator」で Scopes に `bot` と `applications.commands`、
   Bot Permissions に「View Channels」「Send Messages」「Read Message History」を選び、生成された URL でサーバーに招待する

### 2. TypeSafe の API キーを発行する

https://console.typesafe.ai でキーを発行する。

### 3. 設定して起動する

[uv](https://docs.astral.sh/uv/) が必要です。

```bash
cp .env.example .env   # DISCORD_TOKEN と TYPESAFE_API_KEY を記入
uv sync
uv run --env-file .env python -m insider_bot
```

開発中は `.env` に `DISCORD_GUILD_ID`（サーバーを右クリック →「サーバー ID をコピー」、開発者モードが必要）を
入れると、スラッシュコマンドがすぐに反映されます。未指定だと全サーバー向け登録になり、反映に時間がかかることがあります。

| 環境変数 | 必須 | 既定 | 説明 |
|---|---|---|---|
| `DISCORD_TOKEN` | ✓ | — | Discord ボットトークン |
| `TYPESAFE_API_KEY` | ✓ | — | TypeSafe API キー |
| `DISCORD_GUILD_ID` | | — | コマンドを即時反映するサーバー ID |
| `CORRECT_THRESHOLD` | | 0.8 | 正解とみなすしきい値（0〜1） |
| `JEV_TIMEOUT_SECONDS` | | 10 | Jev 呼び出しのタイムアウト秒数 |
| `WEB_HOST` | | 127.0.0.1 | Web 版が待ち受けるアドレス |
| `WEB_PORT` | | 8080 | Web 版が待ち受けるポート |
| `PUBLIC_BASE_URL` | | — | Web 版の公開 URL（例 `https://game.example.com`）。配役ツールの役職画像と特殊村フォームの URL に使う。未設定ならサイト内のパス |
| `LINE_CHANNEL_SECRET` | | — | LINE Bot のチャネルシークレット。`LINE_CHANNEL_TOKEN` と両方設定すると `/line/callback` で webhook を受ける（`PUBLIC_BASE_URL` に https の公開 URL が要る） |
| `LINE_CHANNEL_TOKEN` | | — | LINE Bot のチャネルアクセストークン（長期） |
| `LINE_API_BASE_URL` | | `https://api.line.me` | LINE の返信 API の送り先。切替前の検証でスタブへ向けるときだけ変える |

## 開発

```bash
uv run pytest                                   # 単体テスト
uv run --env-file .env pytest -m integration    # 実際の Jev を呼ぶテスト
uv run --env-file .env python scripts/jev_probe.py  # Jev の日本語判定の確認表
node --test tests/js/*.test.mjs                 # Web 版の画面の単体テスト（Node が必要）
bash deploy/test/release_test.sh                # VM 上の更新スクリプトのテスト（CI では Linux で走る）
```
