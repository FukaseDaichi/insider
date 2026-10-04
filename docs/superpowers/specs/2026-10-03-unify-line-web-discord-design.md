# LINE Bot を Oracle Cloud の insider へ移す設計（切替と後片付け）

## 背景と目的

LINE Bot（LineBot リポジトリ、Java 8、Heroku Eco $5/月）の機能は insider に移植済みで、insider は LINE・Web・Discord の 3 つの入口を持つ 1 つのシステムになっている。村の中核・Web の配役ツール・LINE アダプタの設計は [仕様書](../../spec.md)・[村の外部仕様](../../village.md)・README に蒸留した。

残っているのは、**insider を Oracle Cloud Always Free の VM 1 台で 24 時間動かし、LINE の webhook を Heroku から切り替え、LineBot と Netlify フォームを片付ける**ことである。本設計書はその部分だけを持つ。

### 範囲

- Oracle Cloud への移行: VM 1 台、Caddy、systemd、CI からの配備、Heroku からの 1 回の切替
- LineBot リポジトリと Netlify フォームの後片付け

### 範囲外

- Jev のお題当てルームに役職・タイマー・投票を混ぜること
- 村の永続化（「状態を持たない」原則を保つ）
- 認証の導入（「番号を知る人が入る」前提のまま）

## 全体構成（移行後）

```
                  Caddy（TLS 終端、独自ドメインの 1 ホスト名）
                             │ 127.0.0.1:8080
   ┌─────────────────────────▼─────────────────────────┐   ┌─────────────────────┐
   │ insider-web.service（aiohttp 1 プロセス）           │   │ insider-bot.service │
   │   /               お題当て Web 版                   │   │   Discord ボット      │
   │   /village/…      配役ツール                       │   │   村の状態は持たない   │
   │   /api/village/…  配役ツールの API                 │   └─────────────────────┘
   │   /line/callback  LINE webhook                     │
   │   /healthz        ヘルスチェック                   │
   │   ── 中核 ──  GameService（Jev）   VillageService   │
   └───────────────────────────────────────────────────┘
```

- **Oracle Cloud は A1 を 1 台。** Always Free の枠（1,500 OCPU 時間／月）は A1 を 2 台並べた瞬間に超える。LineBot 設計がすでに確かめた制約で、同居は好みではなく枠の帰結である。

## インフラ

LineBot で確定済みの前提を引き継ぐ: VM.Standard.A1.Flex 2 OCPU / 12GB、ap-tokyo-1、Ubuntu 24.04、ブート 50GB、独自ドメイン（Cloudflare なら Proxy OFF）、Caddy による TLS 終端、systemd、journald の上限 200MB、security list と OS の iptables の両方で 80/443 を開放、SSH は公開鍵のみ。Oracle の無料枠を「契約」ではなく「予告なく変わる好意」として扱い、VM は失われ得るものとして再作成手順と秘密情報の復元手段を持つ、という姿勢も変えない。

### LineBot 設計からの変更点

| 項目 | LineBot 設計 | 本設計 |
|---|---|---|
| ホスト名 | `bot.<domain>` | `<短い名前>.<domain>` 1 つ。Web 版の URL を兼ねる |
| Caddy が流すパス | 4 パスだけ、他は 404 | `/line/callback` は制限なし（署名あり）。`/api/village/*` は IP ごと 30 回／分。それ以外（画面、静的ファイル、お題当ての WebSocket）はそのまま。本文上限 2MB は踏襲（`server.py` の `MAX_REQUEST_BYTES` と同じ値。Caddy を入れたら `docs/infra.md` にも書く） |
| プロセス | Java 1 本 | `insider-web.service`（Web＋LINE）と `insider-bot.service`（Discord） |
| ランタイム | Temurin 8 を `/opt/java` に手置き | uv が `.python-version` の Python を取得・固定する。apt の Python に依存しない |
| 公開 | Caddy | Caddy。**Tailscale Funnel は本番で使わない。** Mac でのローカル遊び（`scripts/play.sh`）にだけ残す |
| 外向き通信 | api.line.me、script.google.com | api.line.me、api.typesafe.ai（Jev）、Discord ゲートウェイ（画像カタログがないので script.google.com は要らない。Gemini TTS は手元で音声を作るときだけで、本番からは呼ばない） |
| アイドル回収対策 | JVM の `-Xms3g -XX:+AlwaysPreTouch` | `memfloor` ユニット（下記） |

### systemd ユニット

- 専用の非 root ユーザー `insider`。`EnvironmentFile=/etc/insider.env`（root:root 0600）。
- `insider-web.service`: `/opt/insider/current/.venv/bin/python -m insider_bot.web`。待ち受けは `127.0.0.1:8080` のみ。
- `insider-bot.service`: `/opt/insider/current/.venv/bin/python -m insider_bot`。
- どちらも `Restart=always`、`NoNewPrivileges`、`PrivateTmp`、`ProtectSystem=full`、`ProtectHome`。
- 既存の `deploy/setup.sh` と `deploy/*.service` は「clone したディレクトリで通常ユーザーとして動かす」前提で書かれており、1GB の VM 向けのスワップ設定も含む。OCI 向けには `/opt/insider/releases/<sha>/` と `current` のシンボリックリンクを前提に書き直す。
- 停止のタイムアウト: aiohttp は停止の合図の後に届いた本文を捨て、受信中の要求は最大 60 秒止まってから取り消される。`TimeoutStopSec` はこれと LINE の返信（送りかけを待つ）に合わせて決める。

### アイドル回収のメモリ床（`memfloor`）

Always Free の A1 は、7 日間 CPU・ネットワーク・メモリの 3 つすべてが 20% 未満だと回収の通知が来る。このシステムの CPU とネットワークは届かないので、外せるのはメモリ条件だけである。Java は `-Xms3g` でヒープを実際に触って RSS を 3GB にしていたが、Python のプロセスにその大きさはない。

代わりに、起動時に 3GB の tmpfs を確保して埋める systemd ユニットを置く。コードに依存せず、アプリの大きさと無関係に床を保てる。

- **OCI の `MemoryUtilization` が tmpfs を「使用中」として数えるかは、切替前の検証で実測する。** 数えなければ、プロセスとして 3GB を確保して眠るだけの小さなユニットに差し替える。それでも 20% を下回るなら、Java 設計と同じく PAYG へのアップグレードで回収対象から外す。
- これは設計上の成立であって保証ではない。回収の通知が届いたら、猶予の 1 週間のうちに PAYG へ上げ、OCI Budget で $1 超過のメール通知を設定する。

### 監視

- OCI Alarm 2 本: `MemoryUtilization` が 20% 未満（Trigger delay 30 分）、および指標が欠測（Absent）。通知先はメール。
- 外形監視: `GET https://<host>/healthz` を 5 分ごと、本文のキーワードで判定する無料サービス。
- `/healthz` は Web プロセスが HTTP を受け付けていることだけを示す。Discord の生死は journald で見る。

### 秘密情報

`/etc/insider.env` に `DISCORD_TOKEN`、`TYPESAFE_API_KEY`、`LINE_CHANNEL_TOKEN`、`LINE_CHANNEL_SECRET`、`PUBLIC_BASE_URL`、任意で `LINE_API_BASE_URL`（切替前の検証でスタブへ向けるときだけ）。`GEMINI_API_KEY` は本番に置かない（音声は手元で作る）。値はパスワードマネージャに保管し、VM の再作成時はそこから復元する。GitHub Secrets には `DEPLOY_HOST`、`DEPLOY_SSH_KEY`、`DEPLOY_HOST_KEY` の 3 つだけを置く。

## デプロイ

LineBot の「検証 → 原子的昇格 → 再起動 → ヘルスチェック → 自動復旧」を Python 向けに移植する。

1. **CI（`build`）**: `uv sync` → pytest → node のテスト → リポジトリをその SHA で tar に固め、sha256 を添えて成果物にする
2. **CI（`deploy`、main への push のみ）**: `concurrency` で直列化（`cancel-in-progress: false`）。排他を取った後に `git ls-remote` で main の最新 SHA を確認し、違えば何もせず成功終了。ホスト鍵を固定した SSH で `/opt/insider/releases/<sha>/` へ転送
3. **VM 上の更新スクリプト（`flock`）**: sha256 検証 → 展開先で `uv sync --frozen --no-dev` → `current` のシンボリックリンクを新しい世代へ差し替え → 2 ユニットを再起動 → `/healthz` を 2 秒間隔で最長 60 秒ポーリング → 失敗なら `previous` に戻して再起動し同じ契約で再確認、それでも通らなければ停止して job を落とす。世代は 5 つ残す
4. 再起動で進行中のルームと村は消える。利用者が少ないので受け入れる（両リポジトリとも同じ判断）。手動の承認ステップは設けない

## カットオーバーとロールバック

### 切替は 1 回

Heroku の Java は Python 版が検証を通るまで触らない。切替対象は **LINE Developers の Webhook URL だけ**である。特殊村フォームは Web 版に取り込んであるので、Netlify フォームの接続先は切り替えない。

1. Python 版を OCI に配備し、切替前検証（後述）をすべて通す。LINE の返信はスタブに向けて内容を読む
2. `/etc/insider.env` から `LINE_API_BASE_URL` を消して再起動する
3. プレイヤー不在の時間帯に、Webhook URL を `https://<host>/line/callback` へ切り替え、コンソールの「検証」で成功を確認する。コンソールの webhook の再送はオフのまま（重複排除はしていない。Java も同じ）
4. 実機で確認する: 通常村を作り別アカウントで参加、`@わーわーず`、**Web で特殊村を作る → LINE からその番号で参加 → `@配布`**。最後の 1 つが Web と LINE の村の共有を確かめる唯一の経路
5. **Netlify フォームは切替時に触らない。** 接続先を Heroku のまま残し、ロールバック時に特殊村が成立する状態を保つ
6. 1 か月の様子見: メモリ指標が 20% を上回る、回収のメールが来ない、外形監視の失敗通知が来ない、journald に想定外の WARN／ERROR がない
7. Heroku アプリの削除と、**Eco dynos の Unsubscribe**（アプリを消しただけでは $5 が止まらない）。同時に Netlify フォームを「移転しました」の案内（新 URL へのリンク）に差し替える
8. LineBot リポジトリをアーカイブする。README に移転先を書く。役職画像は insider に同梱済みなので、アーカイブしても利用者に影響しない

### ロールバック

Webhook URL を Heroku のものへ戻すだけ。Heroku は切替後 1 か月維持する。OCI 上で作られた村はすべて消え、Heroku 側に切替前の古い村が残っていると番号が混乱するので、**戻す前に Heroku を再起動する**。VM は止めず、原因を調べられる状態を残す。

## 切替前の検証

- **Java との突き合わせ（ゴールデン）**: 切替前に必ず採る。本番と同じ Java 8（Temurin 8）で手元に起動した LineBot の `/callapi` へ同じ入力列を送って JSON を採取し（`uv run python -m tests.line_golden http://127.0.0.1:18080/callapi`）、`tests/golden/line_callapi.json` に置く。採ったら `tests/test_line_golden.py` の比較が skip から実行に変わるので、伏せ方（村なしの判定・候補の altText・席番号の置換・古い fixture の検出）を見直し、docs/spec.md と README の「まだ採っていないあいだは skip」の文を直す。Heroku の本番の `/callapi` は使わない（入力列が村を十数個作り、上限 50 件の FIFO で遊んでいる人の村を押し出す）。
- **VM 上の検証**: LineBot から移した `deploy/verify/`（`post_callback.py`、`line_api_stub.py`）で、Caddy 経由の署名付き `/line/callback`、スタブに届く返信の内容、不正署名の拒否、応答時間、レート制限、`/healthz`、`MemoryUtilization` の実測、再起動と VM 再起動後の自動復帰、デプロイの自動復旧、古い commit の re-run で deploy が skip すること。

## ドキュメント

- `docs/infra.md` を「Oracle Cloud の 1 台で 24 時間動かす」構成に書き換え、Mac での起動はローカル遊び用として残す。Caddy の本文上限 2MB もここに書く
- `deploy/` に OCI 向けのセットアップ手順、切替前検証、画面操作の手順書を置く。LineBot の `deploy/setup.md`、`cutover.md`、`human-steps.md` を insider 向けに書き直す
- 完了後、本設計書は docs/ 直下に蒸留して削除する（docs/AGENTS.md の運用）

## マイルストーン

| # | 内容 | 依存 |
|---|---|---|
| M4 | インフラ（手順書、Caddy、systemd、memfloor、CI からの配備） | A1 の確保。アカウント作成とドメイン取得は先に進められる |
| M5 | 切替前検証（ゴールデンの採取を含む）とカットオーバー | M4 |
| M6 | 後片付け（Heroku 解約、Netlify 差し替え、LineBot アーカイブ、docs の蒸留） | M5 の 1 か月後 |

M1〜M3（村の中核、Web の配役ツール、LINE アダプタ）は実装済みで、設計は docs/ に蒸留した。実装計画は M4〜M6 で 1 本にする。

## 残るリスク

- **A1 の在庫**: 取れるまで切替は始まらない。LineBot 設計と同じく、取れない間は Heroku のまま運用し、一定期間試して取れなければ保留とする。M1〜M3 の成果は Mac でのローカル遊びにそのまま使っている
- **無料枠の縮小**: 次に半減（1 OCPU / 6GB）すれば memfloor の値は見直しになるが、Python のプロセス自体は小さいので動作は続く。Java 設計より縮小に強い
- **文面の差**: ゴールデン比較で機械的に確かめるが、`/callapi` に入口のないポストバックとスタンプは目視と手で起こした期待値に頼る
- **Discord の再接続**: `/healthz` の対象外。長期の切断は journald でしか気づけない。問題になったら Discord のゲートウェイ接続状態を `/healthz` に含める
