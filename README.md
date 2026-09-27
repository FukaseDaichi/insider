# お題当てゲーム GM ボット

Discord で「お題当てゲーム」の GM を務めるボットです。出題者が登録したお題について、
参加者の質問に TypeSafe AI の Jev が「はい／いいえ」とその割合で答え、言い当てたら「正解です」でゲーム終了します。

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

## 開発

```bash
uv run pytest                                   # 単体テスト
uv run --env-file .env pytest -m integration    # 実際の Jev を呼ぶテスト
uv run --env-file .env python scripts/jev_probe.py  # Jev の日本語判定の確認表
```
