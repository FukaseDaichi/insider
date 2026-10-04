# Gemini TTS で音声を作るスキル（voice）の設計

## 背景と目的

Web 版はゲーム開始時に 3 種類の音声を鳴らしている。元の WAV は AI Studio の画面で手作業で作り、`afconvert` で AAC に変換して置いた。今後は「はい」「いいえ」の返事など音声を増やしていくので、**チャットで「『いいえ、違います！』の声を作って」と言えば WAV ができる**道具にする。

### 範囲

- Gemini TTS（`gemini-3.8-flash-tts`、既定の話者 Zephyr）でセリフ 1 つから WAV を作るスクリプト `scripts/tts.py`
- それをチャットから使うスキル `.claude/skills/voice/`
- 配信用 AAC への変換（開始の音声と同じ経路）

### 範囲外

- 台本カタログの管理や一括生成（セリフを渡して作る単発の道具にとどめる）
- 「はい」「いいえ」を Web 版で鳴らす機能と、はい % の帯分け（別の設計で決める。このスキルはそのときの素材を作る道具）
- `hub.py` などゲーム側への組み込み

## 全体構成

```
  チャット「『いいえ、違います！』を no-1 で作って」
        │
        ▼
  .claude/skills/voice/SKILL.md ── セリフ・ファイル名・話し方を決める
        │
        ▼
  uv run scripts/tts.py "いいえ、違います！" --out assets/sounds/no-1.wav --m4a
        │   PEP 723 で google-genai を宣言。GEMINI_API_KEY は環境変数か .env
        ├─▶ Gemini Interactions API → WAV（24kHz・モノラル・16bit）→ assets/sounds/no-1.wav
        └─▶ afconvert → src/insider_bot/web/static/sounds/no-1.m4a
        │
        ▼
  afplay で鳴らして聞いてもらう
```

### 設計判断

- **Python スクリプト＋薄いスキル。** API の呼び方・JSON・base64 の扱いをスクリプトに閉じ込め、スキルは「何を作るか決めて呼ぶ」だけにする。Codex やターミナルからも同じスクリプトが使える。
- **依存はスクリプト内の inline metadata（PEP 723）。** ボット本体は実行時に Gemini を使わないので、`pyproject.toml` の依存は変えない。`uv run scripts/tts.py` だけで動く。
- **話し方は `speech_metadata.style` で渡す。** Gemini 3.8 TTS は本文を一字一句そのまま読むので、「きっぱり」などの指示を本文に混ぜない。
- **変換は `afconvert`。** ffmpeg は入れない。開始の音声と同じく WAV を `assets/sounds/` に、AAC を `static/sounds/` に置く。
- **複数の読みを一度に作れる。** 同じセリフでも読みが毎回変わるので、`--takes N` で N 本作って選ぶ。開始の音声が 3 種類あるのと同じ使い方。

## スクリプト `scripts/tts.py`

### 使い方

```
uv run scripts/tts.py "いいえ、違います！" --out assets/sounds/no-1.wav
    [--voice Zephyr] [--style "きっぱり、少し残念そうに"] [--takes 3] [--m4a]
```

| 引数 | 既定 | 意味 |
|---|---|---|
| 本文（位置引数） | 必須 | 読み上げるセリフ。そのまま読まれる |
| `--out` | 必須 | WAV の出力先。`.wav` で終わること |
| `--voice` | `Zephyr` | 話者名 |
| `--style` | なし | 話し方。`speech_metadata.style` に渡す。省けば素のまま読む |
| `--takes` | `1` | 作る本数。2 以上なら `no-1.wav` → `no-1-1.wav`, `no-1-2.wav`, … と枝番を付ける |
| `--m4a` | なし | 付けると `src/insider_bot/web/static/sounds/<同じ名前>.m4a` に AAC を置く |

### 動き

1. `GEMINI_API_KEY` を環境変数から読む。無ければリポジトリ直下の `.env` から読む（`KEY=値` の行だけ見る簡単な読み方。依存は足さない）。どちらにも無ければ、AI Studio の鍵アイコンで作って `.env` に書くよう案内して終了コード 1 で止まる。
2. `client.interactions.create(model="gemini-3.8-flash-tts", ...)` を本数ぶん呼ぶ。`response_format={"type": "audio"}` で WAV が base64 で返るので、そのまま書く（サンプルレートの変換はしない）。
3. `--m4a` なら `afconvert -f m4af -d aac <wav> <m4a>` で変換する。`afconvert` が無い環境（Mac 以外）では WAV だけ書いて、その旨を出す。
4. 作ったファイルのパスと長さ（秒）を 1 行ずつ出す。

### 失敗の扱い

- API の失敗（鍵が無効、モデル名の変更、レート制限）は、API のメッセージをそのまま出して終了コード 1。再試行はしない（本数が少ない手作業の道具なので、人が見て判断する）。
- `--out` の親ディレクトリが無ければ作る。すでに同名のファイルがあれば上書きする（やり直しが前提の道具）。

## スキル `.claude/skills/voice/SKILL.md`

- **呼ばれるとき**: 「音声を作って」「声を作って」「セリフを生成して」「〜と言わせて」、または `/voice "セリフ"`。
- **決めること**: セリフ、ファイル名、話し方、本数。発言から決め、ファイル名が決められないときだけ聞く。ゲームで使う声（開始・はい・いいえ など）は `assets/sounds/` に置き `--m4a` を付ける。試しに聞くだけなら scratchpad に置き `--m4a` を付けない。
- **実行後**: できた WAV を `afplay` で順に鳴らし、パスと長さを伝える。複数作ったときは「どれにするか」を聞き、選ばれなかったものを消す（WAV と m4a の両方）。
- **範囲外のこと**: ゲームへの組み込み（`hub.py`・`docs/spec.md`）は別の作業だと伝える。

## テスト

- `tests/test_tts.py`（pytest、既定で動く）: `.env` の読み取り、枝番付きの出力名、m4a の出力先の決め方、`afconvert` のコマンドの組み立て。API の呼び出しは差し替えて、返った base64 がそのまま WAV として書かれることを確かめる。
- `integration` マーカー（`pyproject.toml` にある既存の仕組み）: `GEMINI_API_KEY` があるときだけ、短いセリフを実際に 1 本作り、WAV のヘッダが 24kHz・モノラル・16bit であることを確かめる。

## 設計書・設定の更新

- `.env.example` に `GEMINI_API_KEY` を足す（任意、音声を作るときだけ要る）。
- `docs/spec.md` の音声の段落に、音声は `scripts/tts.py`（Gemini 3.8 Flash TTS、Zephyr）で作ることを足す。
- `README.md` は変えない（遊ぶ人には関係ない）。
