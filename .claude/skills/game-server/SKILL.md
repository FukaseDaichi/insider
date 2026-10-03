---
name: game-server
description: お題当てゲーム（insider）のゲームサーバーを開始・停止・状態確認する。scripts/play.sh で Discord ボットと Web 版を起動し、Tailscale Funnel で公開 URL に出す／止める。ユーザーが「ゲーム開始」「サーバー起動して」「遊ぶ準備して」「公開して」「ゲーム止めて」「サーバー停止」「動いてる？」「URL は？」のように言ったとき、または /game-server start|stop|status で呼ばれたときは、必ずこのスキルを使う。
---

# ゲームサーバーの開始・停止・状態

`scripts/play.sh` が、Discord ボット・Web 版・Tailscale Funnel での公開・スリープ防止をまとめて動かす。Ctrl+C か SIGTERM を受けると全部を止め、公開も終える。このスキルはそれをチャットから操作する。

引数か発言から操作を選ぶ。

- start / 開始 / 起動 / 公開 → 開始
- stop / 停止 / 止めて → 停止
- status / 状態 / URL、または引数なし → 状態

状態はいつでも `.claude/skills/game-server/scripts/status.sh` で確かめられる。動作中か、待ち受けポート、公開 URL、外から届くか（HTTP コード）を表示する。

## 状態

`status.sh` を実行し、結果を短く伝える。動作中なら公開 URL と、止め方（「ゲーム止めて」と言えばよい）を添える。

## 開始

1. `status.sh` を実行する。すでに動作中なら、二重に起動せず公開 URL を伝えて終える。Discord ボットが 2 つ動くと、質問に 2 回返信してしまうため。
2. ポートが play.sh 以外のプロセスで使われていたら、何が使っているかを伝えて止まる。そのプロセスは勝手に止めない。ほかのセッション（Codex など）が開発用に動かしている場合がある。
3. ターミナルパネルで起動する。ユーザーが様子を見られ、自分で Ctrl+C でも止められるようにするため。`mcp__terminal__run_in_terminal` が未読み込みなら ToolSearch（`select:mcp__terminal__run_in_terminal,mcp__terminal__read_terminal`）で読み込み、リポジトリのルートで `bash scripts/play.sh` を実行する（タブ名は「ゲームサーバー」）。ターミナルのツールがない環境では、Bash の `run_in_background` で同じコマンドを実行する。
4. `read_terminal`（`wait_for_output_ms` を使う）で出力を見て、次のどれかになるまで待つ（初回は依存のインストールで 1 分ほどかかることがある）。
   - `Available on the internet:` → 起動できた
   - `Funnel is not enabled` → 表示されたリンクをユーザーに伝え、管理画面で Funnel を有効にしてもらう。有効にすると play.sh はそのまま公開を始める
   - `.env がありません` / `Tailscale が見つかりません` / `ポート … 使われています` / `Web 版が起動しませんでした` → その内容と直し方を伝える
5. `status.sh` で「外からの応答: 200」になるのを確かめる。起動直後は証明書の準備で `000` のことがあるので、10 秒おきに 1 分ほど確かめ直す。
6. 公開 URL を伝える。仲間にはこの URL を共有すればよく、URL は毎回同じだと添える。

## 停止

1. `pkill -TERM -f 'scripts/play.sh'` を送る。play.sh が子のプロセス（ボット・Web 版・Funnel・スリープ防止）を止めて、公開を終える。
2. 数秒待ってから `status.sh` で「停止中」「ポート 空き」を確かめる。15 秒たっても残っていれば、残っているプロセスを伝える。
3. このセッションで開いた「ゲームサーバー」のタブがあれば `mcp__terminal__stop_terminal_tab`（`close: true`）で閉じる。
4. 止まったことを伝える。止めるとルームと進行中のゲームは消える。
