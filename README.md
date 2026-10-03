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
- ゲームが始まると、開始の音声（3 種類からランダム）が全員の画面で流れます。画面を一度も触っていないと鳴りません
- サーバーを再起動するとルームは消えます

```bash
uv run --env-file .env python -m insider_bot.web   # http://localhost:8080 を開く
```

`localhost` 以外からマイクを使うには HTTPS が必要です。

### 仲間と遊ぶとき（Mac で起動して公開する）

Discord ボットと Web 版をまとめて起動し、Web 版を Tailscale Funnel で公開します（構成の考え方は [docs/infra.md](docs/infra.md)）。

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

## 開発

```bash
uv run pytest                                   # 単体テスト
uv run --env-file .env pytest -m integration    # 実際の Jev を呼ぶテスト
uv run --env-file .env python scripts/jev_probe.py  # Jev の日本語判定の確認表
node --test tests/js/*.test.mjs                 # Web 版の画面の単体テスト（Node が必要）
```
