# お題当てゲーム GM ボット 設計書

- 作成日: 2026-09-26
- ステータス: レビュー待ち

## 1. 目的

Discord 上で「お題当てゲーム」の GM（はい／いいえで答える役）をボットが担当する。
出題者が事前にお題を登録し、参加者の質問に対してボットが TypeSafe AI の Jev を使って
「はい／いいえ」とその割合を返す。質問がお題を言い当てたら「正解です」と答え、1 ゲームが終了する。

### 成功の条件

- 出題者以外にお題が漏れずに登録できる
- 質問ごとに「はい／いいえ」と、はい・いいえの割合（%）が表示される
- 正解の質問で「正解です」と表示され、ゲームが終了する
- 後から音声入力（ボイスチャンネル聞き取り）を、ゲーム部分を変えずに追加できる

### 対象外（このスコープでは作らない）

- インサイダーゲームの役職配布・投票・タイマー
- ボイスチャンネルでの音声聞き取り（別仕様で後から追加。各自の端末の音声入力でテキストチャンネルに書く運用は今回から可能）
- ゲーム状態の永続化（再起動で進行中ゲームは消える）

## 2. 技術選定

| 項目 | 選定 |
|---|---|
| 言語 | Python 3.13 |
| パッケージ・実行管理 | uv（必須。pip / システム Python は使わない） |
| Discord | discord.py（スラッシュコマンド、Message Content Intent） |
| 判定 AI | TypeSafe AI Jev（`typesafe-sdk`、Noul 型） |
| テスト | pytest（非同期は pytest-asyncio） |
| 設定読み込み | `uv run --env-file .env`（追加ライブラリなし） |

## 3. 遊び方（ユーザー向けの仕様）

### 3.1 お題の登録

- 出題者がゲームを行うチャンネルで `/odai set お題:<文字列> 補足:<任意の文字列>` を実行する。
- 応答はエフェメラル（出題者本人にのみ表示）で「お題『<お題>』を登録しました」。
- チャンネルには公開メッセージ「🎮 ゲーム開始！<出題者>さんがお題を出しました。質問をどうぞ」を投稿する。
- 補足はお題の説明（例: 「青森産の赤いりんご」）。Jev の判定材料として渡す。
- 1 チャンネルにつき同時に 1 ゲーム。進行中のチャンネルで `/odai set` した場合はエフェメラルで
  「このチャンネルではゲームが進行中です」と返し、登録しない。

### 3.2 質問

- ゲーム進行中のチャンネルでは、全メッセージを質問として扱う。
- 以下は無視する: ボット自身・他のボットの発言、出題者本人の発言、空文字（添付ファイルのみ等）。
- 返信フォーマット（質問メッセージへのリプライ）:

  ```
  ❓ 果物ですか？
  ✅ はい　　はい 82% ██████████░░ いいえ 18%
  ```

  - `yes_prob >= 0.5` なら「✅ はい」、それ未満なら「❌ いいえ」。
  - 割合は `yes_prob` を 0〜100 の整数に四捨五入し、いいえ = 100 − はい。
  - バーは 12 マス。はい側のマス数 = `round(はい% / 100 × 12)`。

### 3.3 正解

- 正解判定（§4.2）が真なら、次を投稿してゲームを終了する:

  ```
  🎉 正解です！お題は「りんご」でした
  正解者: <発言者>　質問数: 14　経過時間: 6分32秒
  ```

- 質問数は正解の質問を含む、判定に成功した質問の数。

### 3.4 その他のコマンド

- `/odai status`: 進行中なら「質問数 / 経過時間 / 出題者」、なければ「進行中のゲームはありません」。
- `/odai giveup`: 誰でも実行可。「🏳️ ギブアップ！お題は『<お題>』でした（質問数: N）」と投稿し終了。
  進行中ゲームがなければエフェメラルで「進行中のゲームはありません」。

## 4. 判定ロジック（案A）

### 4.1 表記ゆれの正規化 `normalize(text)`

1. Unicode NFKC 正規化（全角英数・半角カナを統一）
2. 英字を小文字化
3. カタカナをひらがなに変換
4. 空白・句読点・記号（`？?！!。、・「」『』()（）ー〜~` 等、Unicode カテゴリ P* / S* / Z*）を除去

※ 長音「ー」は記号扱いで除去する（「ケーキ」→「けき」になるが、比較は両辺同じ処理なので一致判定には問題ない）。
※ 漢字⇔かな（「林檎」⇔「りんご」）はここでは一致させない。Jev の `is_correct` で拾う。

### 4.2 判定手順 `judge(topic, hint, question) -> Verdict`

1. **文字列一致の即決**: `normalize(topic)` が空でなく `normalize(question)` に部分文字列として含まれるなら、
   Jev を呼ばずに `Verdict(yes_prob=1.0, is_correct=True, source="exact")` を返す。
2. **Jev 問い合わせ**（1 リクエスト）:
   - state: `{"topic": <お題>, "hint": <補足 or "">, "question": <質問文>}`
   - questions:
     - `is_yes`: Noul — 「お題がこの topic（hint はその補足説明）であるとき、question の答えは『はい』である」
     - `is_correct`: Noul — 「question は topic そのものを言い当てている（topic と同じものを指して、それかどうかを尋ねている）」
   - `is_correct >= CORRECT_THRESHOLD`（既定 0.8）なら `is_correct=True`。
   - 戻り値: `Verdict(yes_prob=is_yes, is_correct=..., source="jev")`
3. 正解時の表示は「🎉 正解です」を優先し、はい/いいえの割合行は出さない。

※ instructions の具体的な文言は実装ステップ 1（日本語検証）の結果で調整する。

### 4.3 失敗時

- Jev 呼び出しの例外・タイムアウト（既定 10 秒）は `JudgeError` に変換する。
- `JudgeError` 時は「⚠️ 判定できませんでした。もう一度どうぞ」と返信し、質問数に数えない。

## 5. 構成

```
insider/
├── pyproject.toml          # uv 管理
├── .env.example            # DISCORD_TOKEN= / TYPESAFE_API_KEY= / CORRECT_THRESHOLD=0.8
├── .gitignore              # .env, .venv 等
├── README.md
├── src/insider_bot/
│   ├── __main__.py         # 起動エントリ
│   ├── config.py           # 環境変数の読み込み・検証
│   ├── game.py             # Game / GameManager（Discord・Jev 非依存）
│   ├── judge.py            # normalize, Verdict, Judge プロトコル, JevJudge
│   ├── format.py           # 返信文の組み立て
│   ├── service.py          # handle_question 等、ゲーム進行の中核（Discord 非依存）
│   └── bot.py              # discord.py の接続・スラッシュコマンド・on_message
└── tests/
```

### 5.1 各ユニット

- **game.py**
  - `Game`: `channel_id, topic, hint, setter_id, started_at, question_count`
  - `GameManager`: `start(channel_id, topic, hint, setter_id) -> Game`（進行中なら `GameAlreadyRunning`）、
    `get(channel_id) -> Game | None`、`end(channel_id) -> Game | None`
  - 時刻は注入可能な `clock` 関数で取得（テスト用）。
- **judge.py**
  - `Judge` プロトコル: `async judge(topic, hint, question) -> Verdict`
  - `JevJudge`: typesafe-sdk を使う実装。SDK が同期 API なら `asyncio.to_thread` で実行。
  - テストでは `FakeJudge`（固定値を返す）を使う。
- **format.py**: `format_answer(question, verdict)`, `format_correct(game, answerer, elapsed)`,
  `format_giveup(game)`, `format_status(game, now)`, `format_error()`。純粋関数。
- **service.py**
  - `GameService(manager, judge, clock)`
  - `async handle_question(channel_id, author_id, author_name, text) -> str | None`
    - 返信すべき文字列を返す（無視する場合は None）。
    - チャンネルごとの `asyncio.Lock` で直列化。ロック取得後にゲームの存在を再確認し、終了済みなら None。
  - `start`, `status`, `giveup` も同様に文字列を返す。
  - **音声入力を追加する際もこの `handle_question` を呼ぶ。**
- **bot.py**: discord.py の `Client` + `app_commands`。`on_message` で `handle_question` を呼び、
  結果があれば `message.reply()`。スラッシュコマンドは `GameService` に委譲するだけ。

### 5.2 データの流れ

```
Discord メッセージ ─┐
（将来）音声→STT ─┴→ GameService.handle_question(channel, author, text)
    → GameManager.get(channel)            … ゲームなし/出題者/空文字 → None
    → Judge.judge(topic, hint, text)       … 文字列一致 → 即正解 / Jev
    → 正解: GameManager.end, format_correct
      不正解: question_count += 1, format_answer
      失敗: format_error（カウントしない）
    → bot.py が reply
```

## 6. 設定

| 環境変数 | 必須 | 既定 | 説明 |
|---|---|---|---|
| `DISCORD_TOKEN` | ✓ | — | Discord ボットトークン |
| `TYPESAFE_API_KEY` | ✓ | — | TypeSafe API キー（SDK が読む） |
| `CORRECT_THRESHOLD` | | 0.8 | `is_correct` の正解しきい値 |
| `JEV_TIMEOUT_SECONDS` | | 10 | Jev 呼び出しのタイムアウト |

起動: `uv run --env-file .env python -m insider_bot`
必須変数が欠けていれば起動時にエラーメッセージを出して終了する。

Discord 側の必要設定: Message Content Intent を有効化、招待スコープ `bot` + `applications.commands`、
権限「メッセージを送信」「メッセージ履歴を読む」。

## 7. テスト方針

- `uv run pytest` で実行。
- game / format / normalize / service は Discord・Jev を使わずに単体テスト（`FakeJudge`、固定 `clock`）。
  - normalize: 「リンゴ？」「ﾘﾝｺﾞ」「りんご！」が「りんご」と一致、「林檎」は一致しない、など。
  - service: 質問→返信、正解→終了、出題者の発言を無視、Jev 失敗時にカウントしない、
    同時に 2 つの正解質問が来ても正解メッセージは 1 回だけ。
- JevJudge: SDK 呼び出し部分をモックして、戻り値の変換と例外→`JudgeError` を確認。
- 実 API テスト: `TYPESAFE_API_KEY` がある時のみ実行（`@pytest.mark.integration`）。日本語の質問で妥当な確率が出るか。
- bot.py は自動テストしない。実サーバーで手動確認。

## 8. 実装順

1. Jev の日本語検証（実 API に日本語で問い合わせ、精度と instructions 文言を確認。実用にならなければ相談）
2. プロジェクト雛形（uv init、依存追加、.gitignore、.env.example）
3. game.py / format.py / normalize（TDD）
4. judge.py（JevJudge）
5. service.py（TDD）
6. bot.py、実サーバーで動作確認
7. README

## 9. 将来の拡張（今回は作らない）

- ボイスチャンネル聞き取り: ボットが VC に参加し、発話を STT（Whisper 等）でテキスト化して
  `GameService.handle_question` に渡す。返信はゲームチャンネルに投稿。
- 制限時間、インサイダー役職・投票。
