# お題当てゲーム GM ボット 設計書

- 作成日: 2026-09-26
- ステータス: レビュー待ち（Codex レビュー指摘を反映済み）

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
| Discord | discord.py（`Client` + `app_commands.CommandTree`、Message Content Intent） |
| 判定 AI | TypeSafe AI Jev（`typesafe-sdk`、Noul 型） |
| テスト | pytest（非同期は pytest-asyncio） |
| 設定読み込み | `uv run --env-file .env`（追加ライブラリなし） |

## 3. 遊び方（ユーザー向けの仕様）

### 3.1 お題の登録

- 出題者がゲームを行うチャンネルで `/odai set お題:<文字列> 補足:<任意の文字列>` を実行する。
  - お題は 1〜50 文字、補足は 0〜300 文字（スラッシュコマンドの `min_length` / `max_length` で制限）。
- 応答はエフェメラル（出題者本人にのみ表示）で「お題『<お題>』を登録しました」。
- チャンネルには公開メッセージ「🎮 ゲーム開始！<出題者>さんがお題を出しました。質問をどうぞ」を投稿する。
- 補足はお題の説明（例: 「青森産の赤いりんご」）。Jev の判定材料として渡す。
- 1 チャンネルにつき同時に 1 ゲーム。進行中のチャンネルで `/odai set` した場合はエフェメラルで
  「このチャンネルではゲームが進行中です」と返し、登録しない。

### 3.2 質問

- ゲーム進行中のチャンネルでは、全メッセージを質問として扱う。
- 以下は無視する: ボット自身・他のボットの発言、出題者本人の発言、空白のみ（添付ファイルのみ等）。
- 返信フォーマット（質問メッセージへのリプライ）:

  ```
  ❓ 果物ですか？
  ✅ はい　　はい 82% ██████████░░ いいえ 18%
  ```

  - 四捨五入後の「はい」の割合が 50% 以上なら「✅ はい」、それ未満なら「❌ いいえ」（割合表示とラベルを一致させる）。
  - 割合は `yes_prob` を 0〜100 の整数に四捨五入し、いいえ = 100 − はい。
  - バーは 12 マス。はい側のマス数 = `round(はい% / 100 × 12)`。
  - 表示する質問文は 200 文字を超えたら先頭 200 文字＋「…」に省略する（判定には全文を渡す）。

### 3.3 正解

- 正解判定（§4.2）が真なら、次を投稿してゲームを終了する（はい／いいえの割合行は出さない）:

  ```
  🎉 正解です！お題は「りんご」でした
  正解者: <発言者>　質問数: 14　経過時間: 6分32秒
  ```

- 質問数 = 判定に成功した質問の数（正解の質問を含む）。判定失敗・無視した発言は数えない。

### 3.4 その他のコマンド

- `/odai status`: エフェメラルで、進行中なら「質問数 / 経過時間 / 出題者」、なければ「進行中のゲームはありません」。
- `/odai giveup`: 誰でも実行可。進行中なら公開で「🏳️ ギブアップ！お題は『<お題>』でした（質問数: N）」と投稿し終了。
  進行中ゲームがなければエフェメラルで「進行中のゲームはありません」。
- すべてのメッセージは 2,000 文字（Discord の上限）以内に収まる。§3.1 の文字数制限と §3.2 の省略でこれを保証する。

## 4. 判定ロジック（案A）

### 4.1 表記ゆれの正規化 `normalize(text)`

即決（§4.2 手順 1）の比較専用。意味の区別を壊さない最小限の処理に限る。

1. Unicode NFKC 正規化（全角英数・半角カナを統一）
2. 英字を小文字化
3. カタカナをひらがなに変換
4. 空白文字（スペース・タブ・改行）をすべて除去

長音「ー」、お題を構成する記号（`C++` の `+` 等）は**保持する**（「ビール」と「ビル」を区別するため）。
漢字⇔かな（「林檎」⇔「りんご」）はここでは一致させない。Jev の `is_correct` で拾う。

### 4.2 判定手順 `judge(topic, hint, question) -> Verdict`

1. **完全一致の即決**: 質問から推測候補を取り出し、お題と完全一致する場合だけ Jev を呼ばずに正解とする。
   - 推測候補は次の 2 つ（`extract_guess` はこの集合を返す）:
     - 候補 1 = `normalize(question)` の末尾の記号（`？ ? ！ ! 。 ． . 、 ，`）をすべて取り除いたもの
     - 候補 2 = 候補 1 の末尾が問いかけ表現（`でしょうか` `ですか` `だよね` `ですね` `かな` `だね`、
       長いものから順に照合）で終わる場合に、その 1 つだけを取り除いたもの
   - 1 文字の語尾（「か」「ね」）は取り除かない（お題「すい」に「すいか？」が一致するのを防ぐ）。
   - `normalize(topic)` がいずれかの候補と一致すれば `Verdict(yes_prob=1.0, is_correct=True, source="exact")`。
   - 例（お題「りんご」）: 「リンゴ？」「りんごですか」「りんごかな？」→ 即決で正解。
     「りんごか？」「りんごではない？」「りんごより大きい？」「青りんごですか」→ 即決しない（Jev に渡す）。
     お題「さかな」に「さかな？」→ 候補 1 と一致して即決で正解。
   - 部分文字列一致は使わない。
2. **Jev 問い合わせ**（1 リクエスト）:
   - state: `{"topic": <お題>, "hint": <補足 or "">, "question": <質問文>}`
   - questions:
     - `is_yes`: Noul — 「お題がこの topic（hint はその補足説明）であるとき、question の答えは『はい』である」
     - `is_correct`: Noul — 「question は単一の答えとして topic そのものを肯定的に推測している
       （否定・比較・複数候補の選択・topic を含む別のものの質問は該当しない）」
   - `is_correct >= CORRECT_THRESHOLD`（既定 0.8）なら `is_correct=True`。
   - 戻り値: `Verdict(yes_prob=is_yes, is_correct=..., source="jev")`

※ instructions の具体的な文言は実装ステップ 1（日本語検証）の結果で調整する。
  検証ケースには §4.2 の例（否定・比較・「青りんご」）を必ず含める。

### 4.3 失敗時

- Jev 呼び出しの例外・タイムアウト（既定 10 秒）は `JudgeError` に変換する。
- `JudgeError` 時は「⚠️ 判定できませんでした。もう一度どうぞ」と返信し、質問数に数えない。

## 5. 構成

```
insider/
├── pyproject.toml          # uv 管理
├── .env.example            # 環境変数の雛形（§6）
├── .gitignore              # .env, .venv 等
├── README.md
├── src/insider_bot/
│   ├── __main__.py         # 起動エントリ
│   ├── config.py           # 環境変数の読み込み・検証
│   ├── game.py             # Game / GameManager（Discord・Jev 非依存）
│   ├── judge.py            # normalize, extract_guess, Verdict, Judge プロトコル, JevJudge
│   ├── format.py           # 返信文の組み立て
│   ├── service.py          # GameService：ゲーム進行の中核（Discord 非依存）
│   └── bot.py              # discord.py の接続・スラッシュコマンド・on_message
└── tests/
```

### 5.1 各ユニット

- **game.py**
  - `Game`: `game_id`（ゲームごとに一意な連番）, `channel_id, topic, hint, setter_id, setter_name, started_at, question_count`
  - `GameManager`: `start(channel_id, topic, hint, setter_id, setter_name) -> Game`（進行中なら `GameAlreadyRunning`）、
    `get(channel_id) -> Game | None`、`end(channel_id) -> Game | None`
  - 時刻は注入可能な `clock` 関数で取得（テスト用）。
- **judge.py**
  - `normalize(text)`（§4.1）、`extract_guess(question)`（§4.2 手順 1 の推測候補）
  - `Judge` プロトコル: `async judge(topic, hint, question) -> Verdict`
  - `JevJudge`: typesafe-sdk を使う実装。SDK が同期 API なら `asyncio.to_thread` で実行。
  - テストでは `FakeJudge`（固定値を返す／例外を投げる）を使う。
- **format.py**: `format_answer(question, verdict)`, `format_correct(game, answerer_name, elapsed)`,
  `format_giveup(game)`, `format_status(game, now)`, `format_error()` など。純粋関数。
- **service.py** — `GameService(manager, judge, clock)`
  - 戻り値は Discord 非依存の構造体 `Outcome(private: str | None, public: str | None)`。
    `private` は操作した本人だけに見せる本文、`public` はチャンネルに投稿する本文。両方 None なら何もしない。
  - `async start(channel_id, setter_id, setter_name, topic, hint) -> Outcome`
    - 成功: `private`=登録確認、`public`=開始通知。進行中: `private`=「進行中です」のみ。
  - `async status(channel_id) -> Outcome` — `private` のみ。
  - `async giveup(channel_id) -> Outcome` — 成功: `public`=ギブアップ通知。ゲームなし: `private` のみ。
  - `async handle_question(channel_id, author_id, author_name, text) -> Outcome`
    - 質問への返信は `public` に入れる（無視する場合は両方 None）。
    - `channel_id` は**ゲームを登録したテキストチャンネルの ID**。
  - **排他制御**:
    - チャンネルごとに `asyncio.Lock` を 1 つ持つ（`dict[channel_id, Lock]`、作成後は削除しない。
      ボットが参加するチャンネル数ぶんしか増えないため許容する）。
    - `start` / `status` / `giveup` / `handle_question` はすべて同じチャンネルのロックを取得してから処理する。
    - `handle_question` は、ロックを取る**前に**進行中ゲームの `game_id` を記録する（ゲームがなければ即 None）。
      ロック取得後、現在のゲームが存在しない、または `game_id` が異なる場合は無視する
      （終了済みゲームや、次のゲームに古い質問が流れ込むのを防ぐ）。
    - ロックは Jev 判定と状態更新（質問数加算・終了）が終わるまで保持する。
      giveup は実行中の質問の完了を待つ（キャンセルはしない）。
  - 質問の処理順（ロック取得・`game_id` 確認後）:
    1. 出題者本人・空白のみ → 無視
    2. `judge` を呼ぶ。`JudgeError` → `public`=エラー文（カウントしない）
    3. 成功したら `question_count += 1`（正解・不正解・exact・jev を問わず、分岐の前に加算）
    4. 正解 → `manager.end` して `public`=正解通知／不正解 → `public`=はい・いいえの回答
- **bot.py**
  - `intents = discord.Intents.default(); intents.message_content = True` を `Client` に渡す
    （Developer Portal 側の Message Content Intent 有効化も必要）。
  - `app_commands.CommandTree` に `/odai`（`set` / `status` / `giveup`）を登録し、
    `setup_hook` で `await tree.sync(guild=...)` を実行する。`DISCORD_GUILD_ID` があればそのサーバーにだけ同期
    （即時反映）、なければグローバル同期。
  - **スラッシュコマンド**: ロック待ちで Discord の初回応答期限（3 秒）を超えないよう、最初に
    `await interaction.response.defer(ephemeral=True, thinking=True)` する。処理後、
    `Outcome.private` があれば `interaction.followup.send(..., ephemeral=True)`、
    なければ followup で「完了しました」相当を送る。`Outcome.public` があれば `channel.send()` で別途投稿。
  - **on_message**: `message.author.bot` が真ならサービスを呼ばずに return する。
    それ以外は `handle_question(message.channel.id, message.author.id, message.author.display_name, message.content)` を呼ぶ。
    `Outcome.public` があれば
    `message.channel.send(本文, reference=message.to_reference(fail_if_not_exists=False))` で返信する
    （元メッセージが削除されていても通常投稿として届く）。
    送信に失敗しても判定・質問数・終了処理はやり直さない（ログに記録するのみ）。

### 5.2 データの流れ

```
Discord メッセージ ─┐   （bot.py でボットの発言を除外）
（将来）音声→STT ─┴→ GameService.handle_question(channel_id, author_id, author_name, text) -> Outcome
    → ロック前: 進行中ゲームの game_id を記録（なければ無視）
    → チャンネルロック取得 → game_id 再確認（不一致なら無視）
    → 出題者/空白のみ → 無視
    → Judge.judge(topic, hint, text)       … 完全一致 → 即正解 / Jev
    → 失敗: format_error（カウントしない）
      成功: question_count += 1
        正解: GameManager.end, format_correct
        不正解: format_answer
    → 呼び出し側（bot.py / 将来の音声アダプター）が Outcome.public をゲームチャンネルに投稿
```

## 6. 設定

| 環境変数 | 必須 | 既定 | 説明 |
|---|---|---|---|
| `DISCORD_TOKEN` | ✓ | — | Discord ボットトークン |
| `TYPESAFE_API_KEY` | ✓ | — | TypeSafe API キー（SDK が読む） |
| `DISCORD_GUILD_ID` | | — | 指定するとスラッシュコマンドをこのサーバーにだけ即時同期（開発向け） |
| `CORRECT_THRESHOLD` | | 0.8 | `is_correct` の正解しきい値 |
| `JEV_TIMEOUT_SECONDS` | | 10 | Jev 呼び出しのタイムアウト |

起動: `uv run --env-file .env python -m insider_bot`
必須変数が欠けていれば起動時にエラーメッセージを出して終了する。

Discord 側の必要設定: Developer Portal で Message Content Intent を有効化、招待スコープ `bot` + `applications.commands`、
権限「チャンネルを見る」「メッセージを送信」「メッセージ履歴を読む」。

## 7. テスト方針

- `uv run pytest` で実行。
- game / format / judge の正規化 / service は Discord・Jev を使わずに単体テスト（`FakeJudge`、固定 `clock`）。
  - normalize / extract_guess（お題「りんご」）:
    「リンゴ？」「ﾘﾝｺﾞ」「りんごですか」「りんごかな？」→ 即決正解。
    「りんごか？」「りんごではない？」「りんごより大きい？」「青りんごですか」「林檎」→ 即決しない。
    「ビル」はお題「ビール」と一致しない。「すいか？」はお題「すい」と一致しない。「さかな？」はお題「さかな」と一致する。
  - service:
    - 質問→回答、正解→終了、出題者の発言・空白のみを無視
    - 最初の質問で正解したとき質問数が 1
    - Jev 失敗時にカウントしない
    - 同時に 2 つの正解質問が来ても正解通知は 1 回だけ
    - 判定中に giveup → giveup は判定完了を待ち、正解ならゲームなしの応答、不正解ならギブアップ成功
    - 旧ゲームの質問がロック待ち中に新ゲームが始まっても、新ゲームでは判定されない（game_id 不一致で無視）
    - start / status / giveup の Outcome の private / public の振り分け
- JevJudge: SDK 呼び出し部分をモックして、戻り値の変換と例外・タイムアウト→`JudgeError` を確認。
- 実 API テスト: `TYPESAFE_API_KEY` がある時のみ実行（`@pytest.mark.integration`）。日本語の質問で妥当な確率が出るか。
- bot.py は自動テストしない。実サーバーで手動確認。

## 8. 実装順

1. Jev の日本語検証（実 API に日本語で問い合わせ、精度と instructions 文言を確認。否定・比較の質問も含める。実用にならなければ相談）
2. プロジェクト雛形（uv init、依存追加、.gitignore、.env.example）
3. game.py / format.py / normalize・extract_guess（TDD）
4. judge.py（JevJudge）
5. service.py（TDD）
6. bot.py、実サーバーで動作確認
7. README

## 9. 将来の拡張（今回は作らない）

- ボイスチャンネル聞き取り: ボットが VC に参加し、発話を STT（Whisper 等）でテキスト化する。
  音声アダプターは「VC → ゲームを登録したテキストチャンネル」の対応を解決し、
  そのテキストチャンネル ID で `GameService.handle_question` を呼び、`Outcome.public` をゲームチャンネルに投稿する。
  ボット自身の音声は `handle_question` を呼ぶ前に除外する。
- 制限時間、インサイダー役職・投票。
