# インフラ構成

本番の構成は Oracle Cloud Always Free の VM 1 台で 24 時間動かすもので、配備の一式は `deploy/` にある。VM を確保して LINE の webhook を切り替えるまでは、仲間と遊ぶときだけ手元の Mac で起動する。手順は [deploy/setup.md](../deploy/setup.md)（VM）、[deploy/human-steps.md](../deploy/human-steps.md)（画面操作）、[README](../README.md)（Mac）。

## 結論

| | 構成 | 費用 |
|---|---|---|
| 現在 | 遊ぶときだけ手元の Mac で起動する（`scripts/play.sh`）。Tailscale Funnel で公開 | 0 円（電気代のみ） |
| 本番（VM を確保して切り替えた後） | Oracle Cloud の Always Free の A1 1 台。Caddy と systemd。`deploy/` の一式で配備する | 0 円の見込み（アイドル回収への対策を持つ） |
| 採らない | Google Cloud、AWS、スリープする無料枠 | 下記 |

どの構成でも、TypeSafe（Jev）の利用料は別にかかる。

## 本番: Oracle Cloud の 1 台

```
                  Caddy（TLS 終端、独自ドメインの 1 ホスト名）
                             │ 127.0.0.1:8080
   ┌─────────────────────────▼─────────────────────────┐   ┌─────────────────────┐
   │ insider-web.service（aiohttp 1 プロセス）           │   │ insider-bot.service │
   │   /               お題当て Web 版                   │   │   Discord ボット      │
   │   /village/…      配役ツール                       │   │   村の状態は持たない   │
   │   /api/village/…  配役ツールの API                 │   └─────────────────────┘
   │   /line/callback  LINE webhook                     │   ┌─────────────────────┐
   │   /healthz        ヘルスチェック                   │   │ insider-memfloor    │
   └───────────────────────────────────────────────────┘   │   3GB の tmpfs      │
                                                           └─────────────────────┘
```

- **VM は A1 を 1 台**（VM.Standard.A1.Flex 2 OCPU / 12GB、ap-tokyo-1、Ubuntu 24.04、ブート 50GB）。Always Free の枠（1,500 OCPU 時間／月）は A1 を 2 台並べた瞬間に超えるので、Web＋LINE と Discord の同居は好みではなく枠の帰結。
- **ホスト名は 1 つ**で、Web 版の URL と LINE の webhook を兼ねる。Cloudflare なら Proxy OFF（Caddy が直接 TLS を終端する）。
- **Caddy**（`deploy/Caddyfile`）が TLS を終端し、すべてのパスを `127.0.0.1:8080` の aiohttp へ流す。`/api/village/*` は IP ごとに 2 段で制限する: 村を作る操作（`create`、`special`、`werewords`、`text`）は **30 回／分**、全体は **300 回／分**（無認証の作成を繰り返して村の FIFO を押し出すのを遅らせる。配役ツールの画面が配布状況を 5 秒ごとに取るので、全体の枠は同じ Wi-Fi の 20 画面ぶん。防止はできない）。`/line/callback` は署名があるので制限しない。**本文上限は 2MiB**（2×1024×1024 バイト）で、aiohttp 側の `client_max_size` と同じ値（特殊村の最大 100 通×5,000 文字が約 1.5MB）。超過は Caddy が下流の読み取りの時点で打ち切るので 413 とは限らず 502 にもなる。
- **プロセスは 2 つ**（`deploy/insider-web.service`、`deploy/insider-bot.service`）。片方の不具合がもう片方に及ばないようにするため。専用の非 root ユーザー `insider`、`/etc/insider.env`（root:root 0600）、`Restart=always`、`NoNewPrivileges`、`PrivateTmp`、`ProtectSystem=full`、`ProtectHome`。Web は `127.0.0.1:8080` だけで待つ。
- **停止**: aiohttp は停止の合図の後に届いた本文を捨て、受信中の要求を最大 60 秒待ってから取り消す。WebSocket はすべて同時に閉じる（1 本ずつ待つと応答しない端末の数だけ 10 秒が積み上がる）。そのあと送りかけの LINE の返信（タイムアウト 10 秒）を待つ。`TimeoutStopSec=90` は 60＋10＋10 に余裕を足した値。Discord ボットは `KillSignal=SIGINT` で、asyncio が主タスクを取り消してゲートウェイを閉じてから終わる。
- **ランタイム**: uv が `.python-version` の Python を取得・固定する。apt の Python に依存しない。依存は `uv sync --locked --no-dev --no-editable` で入れる（編集可能インストールは世代のディレクトリを動かすと import できなくなるため）。
- **外向き通信**: api.line.me、api.typesafe.ai（Jev）、Discord のゲートウェイだけ。Gemini TTS は手元で音声を作るときだけで、本番からは呼ばない（`GEMINI_API_KEY` は本番に置かない）。
- **Tailscale Funnel は本番で使わない。** Mac のローカル遊びにだけ使う。
- SSH は公開鍵のみ。80/443 は security list と OS の iptables の両方で開ける。journald の上限は 200MB。
- Oracle の無料枠は「契約」ではなく「予告なく変わる好意」として扱い、VM は失われ得るものとして再作成手順（setup.md §15）と秘密情報の復元手段（パスワードマネージャ）を持つ。

### アイドル回収のメモリ床（memfloor）

Always Free の A1 は、7 日間 CPU・ネットワーク・メモリの 3 つすべてが 20% 未満だと回収の通知が来る。このシステムの CPU とネットワークは届かないので、外せるのはメモリ条件だけ。`deploy/insider-memfloor.service` が起動時に 3GB（12GB の 25%）の tmpfs を確保して埋める。コードに依存せず、アプリの大きさと無関係に床を保てる。

- OCI の `MemoryUtilization` が tmpfs を「使用中」に数えなければ、`deploy/insider-memfloor-process.service`（`deploy/memfloor.py` が 3GB を確保してページを触り、眠り続ける）に差し替える。両方を同時に有効にしない。どちらを使っているかは切替前の検証で決め、ここに記す。
- これは設計上の成立であって保証ではない。回収の通知が届いたら、猶予の 1 週間のうちに PAYG へ上げ、OCI Budget で $1 超過のメール通知を設定する。

### 監視

- OCI Alarm 2 本: `MemoryUtilization` が 20% 未満（Trigger delay 30 分）、および指標が欠測（Absent）。通知先はメール。
- 外形監視: `GET https://<host>/healthz` を 5 分ごと、本文のキーワード `ok` で判定する無料サービス。
- `/healthz` は Web プロセスが HTTP を受け付けていることだけを示す。Discord の生死は journald で見る。

### 秘密情報

`/etc/insider.env` に `DISCORD_TOKEN`、`TYPESAFE_API_KEY`、`LINE_CHANNEL_TOKEN`、`LINE_CHANNEL_SECRET`、`PUBLIC_BASE_URL`、任意で `LINE_API_BASE_URL`（切替前の検証でスタブへ向けるときだけ）。値はパスワードマネージャに保管する。GitHub Secrets には `DEPLOY_HOST`、`DEPLOY_SSH_KEY`、`DEPLOY_HOST_KEY` の 3 つだけを置く。

### デプロイ

`main` への push で GitHub Actions（`.github/workflows/ci.yml`）が配備する。手動の承認ステップは設けない。

1. **build**: `uv sync --locked` → pytest → node のテスト → 更新スクリプトのテスト → リポジトリをその SHA で tar に固め、sha256 を添えて成果物にする
2. **deploy**（main への push のみ）: Secrets が 3 つとも未登録のあいだ、deploy job は配備を飛ばして成功で終わる（`::notice::` を出す）。一部だけなら失敗する。`concurrency` で直列化（`cancel-in-progress: false`）。排他を取った後に `git ls-remote` で main の最新 SHA を確認し、違えば何もせず成功終了。ホスト鍵を固定した SSH で `/opt/insider/incoming/<sha>/` へ転送し、`sudo /usr/local/bin/insider-release.sh <sha>` を呼ぶ。job は 20 分で打ち切り、SSH は `ConnectTimeout` と `ServerAlive` で繋がらない・止まった接続を見切る（止まった job が group を塞ぎ続けないため。runner 側が切れても、VM 上の更新スクリプトは完走する）
3. **VM 上の更新スクリプト**（`deploy/insider-release.sh`。root で呼ばれるが、ファイルの操作はすべて `insider` として行い、root がするのは systemctl だけ。排他は root 所有のスクリプト自身への `flock` で取る。SIGHUP と SIGPIPE を無視するので、SSH が途中で切れても戻しまで完走する）: sha256 検証 → 稼働中の世代と同じ SHA なら健康を 1 回確かめ、健康なら何もせず成功、そうでなければその世代のまま再起動して同じ契約で確かめる（通らなければ、自分の確認が通らないユニットだけを止めて job を落とす）→ `releases/.staging-<sha>/` に展開して `uv sync --locked --no-dev --no-editable`（失敗なら `current` を変えずに終わる）→ `releases/<sha>/` へ移し、2 つの入口（`insider_bot.__main__` と `insider_bot.web.__main__`）を import できることを確かめる（失敗なら `current` を変えずに終わる）→ `current` のシンボリックリンクを原子的に差し替え → 2 ユニットを再起動（それぞれ直前に `reset-failed` する。落ちて自動再起動を待っているユニットへの restart では `NRestarts` が 0 に戻らないため）→ `/healthz` が 200 で本文 `ok`、かつ `insider-bot` が active で `NRestarts` が 0 になるまで 2 秒間隔で最長 60 秒、通ったら 10 秒置いてもう一度 → 失敗なら `previous` に戻して再起動し同じ契約で再確認する。戻せても job は落とす（exit 1。push した commit は動いていない）。戻し先がない、または戻しても通らなければ、自分の確認が通らないユニットだけを止めて job を落とす（`/healthz` が通る Web と、active で `NRestarts` が 0 の bot は動かしたままにする。Discord の障害で bot だけが落ちても Web と LINE を止めないため）。世代は 5 つ残す（`current`／`previous` が指す世代は残す）。revision は 40 桁の小文字 hex に限る（sudoers は引数を制限できないため）
4. 再起動で進行中のルームと村は消える。利用者が少ないので受け入れる

振る舞いは `deploy/test/release_test.sh` が systemctl・curl・uv を偽物に差し替えて確かめる（CI の build で走る）。

## ローカル: Mac で遊ぶときだけ起動する

- `scripts/play.sh` がボットと Web 版を起動し、Web 版が応答してから Tailscale Funnel で `https://<マシン名>.<tailnet名>.ts.net` として公開する。マイクに HTTPS が要るため。Funnel は無料で、URL が固定され、ドメインが要らない。
- Ctrl+C か、どれか 1 つが止まったときに全部を止め、公開も終える。前回の公開の設定が持ち主のプロセスなしで残っていると公開できないので、起動のはじめに消す。`--bg` で常時公開している設定は消さない。
- 動いている間は `caffeinate` で Mac のスリープを防ぐ。ノートの蓋を閉じると止まる。
- 止めるとルームと進行中のゲームは消える（状態を保存しない仕様のため）。
- **Discord ボットは 1 か所でだけ動かす。** 本番の VM が動いている間は `scripts/play.sh` を使わない（2 か所で動くと質問に 2 回返信する）。`.env` に `PRODUCTION_URL` を書いておくと、play.sh は起動の前に本番の `/healthz` を見て、`ok` なら何も起動せずに終わる。届かなければ本番が止まっていると見なして起動する。

## 採らない構成

- **Google Cloud**: e2-micro と標準ディスク 30GB は無料枠だが、外部 IPv4 の無料分はアカウントあたり月 1 時間だけで、24 時間動かすと月 約 $3.6 かかる。IPv6 だけにもできない（Discord と GitHub が IPv6 に対応していない）。IPv4 なしで外に出る Cloud NAT はさらに高い。
- **AWS**: 無料なのは最初の 6 か月のクレジットだけで、その後は公開 IPv4 が Google Cloud と同じく有料。
- **スリープする無料枠（Render など）**: 一定時間使わないと止まり、常時接続の Discord ボットを動かせない。
- **A1 を 2 台**: Always Free の OCPU 時間の枠を超える。

## 出典

- [Oracle Cloud: Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Oracle Cloud: Idle Compute Instances（アイドル回収の条件）](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm#compute__idleinstances)
- [Google Cloud: VPC network pricing（外部 IP）](https://cloud.google.com/vpc/network-pricing)
- [Google Cloud: Free Program](https://docs.cloud.google.com/free/docs/free-cloud-features)
