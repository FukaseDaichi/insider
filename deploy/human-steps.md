# 画面操作の手順書（人間がやること）

ブラウザでの画面操作、アカウント登録、値の記録をまとめる。ターミナルで打つ分は [setup.md](setup.md)、切替前の検証と切替の判断は [cutover.md](cutover.md)。

| 文書 | 何が書いてあるか | 誰が読むか |
| --- | --- | --- |
| **この文書** | ブラウザでの画面操作、アカウント登録、値の記録 | 画面の前にいるとき |
| [setup.md](setup.md) | VM に SSH して打つコマンド（§0〜§15） | ターミナルの前にいるとき |
| [cutover.md](cutover.md) | 切替前検証（準備 1 件＋13 項目）とその期待値、切替、戻し方 | 切替の判断をするとき |

## 触るサービスの一覧

| サービス | アカウント | ここでやること | 費用 |
| --- | --- | --- | --- |
| Oracle Cloud | 新規作成が必要 | VM を作る、通信を開ける、監視とメール通知を設定する | $0（Always Free） |
| ドメイン登録事業者 | 既にある（なければ新規） | ホスト名の A レコードを VM の IP へ向ける | 年 $10 前後 |
| GitHub | 既にある | Secrets を 3 つ登録する | $0 |
| LINE Developers | 既にある | Webhook URL を差し替える | $0 |
| Discord Developer Portal | 既にある | ボットトークンを控える（Mac で使っているものと同じでよい） | $0 |
| TypeSafe | 既にある | API キーを控える | 利用料は別 |
| 外形監視サービス | 新規作成が必要 | `/healthz` を 5 分ごとに見てメールで知らせる | $0 |
| Heroku | 既にある | 最後に解約する | 現 $5/月 → $0 |
| Netlify | 既にある | 最後に特殊村フォームを移転の案内に差し替える | $0 |

## 記録しておく値

| 項目 | 値 | いつ決まるか |
| --- | --- | --- |
| VM の公開 IP | | Phase 2 |
| ホスト名 `<host>` | `insidergame.fyi`（Cloudflare Registrar、2026-10-05 取得、年 $5.20、2027-10-05 まで。サブドメインは使わずルートをそのまま使う） | Phase 1 |
| 切替日 | | Phase 6 |
| Heroku 解約予定日 | 切替日 + 1 か月 | Phase 6 |
| memfloor の方式（tmpfs / プロセス） | | Phase 5 |

## 全体の流れ

```
Phase 1  準備          ホスト名を決める / Oracle アカウントを作る / 鍵と資格情報   ← VM が取れなくても進められる
Phase 2  VM を作る      A1 インスタンス + 通信の開放                              ← ここが取れるまで Heroku のまま
Phase 3  DNS を向ける    A レコード
Phase 4  配備           VM の設定 → GitHub Secrets → 初回配備                    （setup.md §1〜§11）
Phase 5  監視の下地      Monitoring 確認 + メール通知 + 外形監視
Phase 6  切替           LINE の Webhook URL だけ                                 ← 戻せる最後の地点
Phase 7  1 か月の様子見
Phase 8  後片付け        Heroku + Netlify + LineBot のアーカイブ

別枠  ロールバック（戻したいとき） / PAYG へ上げる（アイドル通知が来たとき）
```

---

# Phase 1: 準備

## 1-1. ホスト名を決める

ドメインを 1 つ取り、ルートをそのままホスト名にする（取得済み: `insidergame.fyi`。既にあるドメインに `insider.<domain>` のような短い名前を足してもよい）。Web 版の URL も LINE の webhook も同じホスト名を使う。記録表に書く。

## 1-2. Oracle Cloud のアカウントを作る

https://www.oracle.com/cloud/free/ から。ホームリージョンは **Japan East (Tokyo)**（`ap-tokyo-1`）。後から変えられない。クレジットカードの登録が要り、審査で断られることがある。無料枠は「契約」ではなく「予告なく変わる好意」として扱う。

## 1-3. デプロイ用の SSH 鍵を作る

```bash
ssh-keygen -t ed25519 -f ~/.ssh/insider-deploy -C insider-deploy -N ''
```

| ファイル | 用途 |
| --- | --- |
| `~/.ssh/insider-deploy.pub`（公開鍵） | VM 側に登録する（setup.md §6） |
| `~/.ssh/insider-deploy`（秘密鍵） | GitHub Secrets に登録する（Phase 4） |

## 1-4. 資格情報を控える

すべてパスワードマネージャに保管する。VM の再作成時はここから復元する。

| 値 | 場所 |
| --- | --- |
| LINE チャネルアクセストークン | LINE Developers → 対象チャネル → **Messaging API 設定** タブ → 「チャネルアクセストークン（長期）」 |
| LINE チャネルシークレット | 同 → **チャネル基本設定** タブ → 「チャネルシークレット」 |
| Discord ボットトークン | Discord Developer Portal → 対象アプリ → **Bot** タブ。Mac の `.env` と同じ値でよい |
| TypeSafe API キー | https://console.typesafe.ai。Mac の `.env` と同じ値でよい |

---

# Phase 2: VM を作る

## 2-1. A1 インスタンスを作る

OCI コンソール → **Compute** → **Instances** → **Create instance**

| 画面の項目 | 入れる値 |
| --- | --- |
| Name | 何でもよい（例 `insider`） |
| Placement → Availability domain | 既定のまま（作れなければ別の AD も試す） |
| Image and shape → **Change image** | Canonical **Ubuntu** → **24.04**（aarch64 用が選ばれる） |
| Image and shape → **Change shape** | **Ampere** → **VM.Standard.A1.Flex** → OCPU **2**、Memory **12** GB |
| Networking | 新しい VCN を作らせる。**Assign a public IPv4 address = はい** |
| Add SSH keys | **Paste public keys** に `~/.ssh/id_ed25519.pub` など**普段使いの公開鍵**を貼る（デプロイ鍵ではない） |
| Boot volume | **Specify a custom boot volume size** にチェック → **50** GB |

`Out of host capacity` が出たら時間を置いて何度でも試す。取れるまで Heroku のまま運用し、一定期間試して取れなければ保留とする。手で押し直すより、下の 2-1b で機械に繰り返させる方が早い。

作れたら **公開 IP** を記録表に書く。

## 2-1b. 空きが出るまで自動で繰り返す（コンソールで取れないとき）

`scripts/oci-launch-a1.sh` が、2-1 と同じ値で数分おきに作成を試し、作れたら公開 IP を表示して終わる。準備が 3 つ要る。

**(1) OCI CLI を入れる**（Mac）

```bash
uv tool install oci-cli
```

**(2) API キーを作る**（コンソール）

右上のプロフィールアイコン → **My profile** → 左の **API keys** → **Add API key** → **Generate API key pair** → **Download private key** → **Add**。閉じる前に表示される **Configuration file preview** を控える（`[DEFAULT]` から `region=` までの数行）。

ターミナルで鍵を置き、控えた内容を `~/.oci/config` に書く。`key_file=` の行だけ鍵の実際の場所に直す:

```bash
mkdir -p ~/.oci && mv ~/Downloads/*.pem ~/.oci/oci_api_key.pem && chmod 700 ~/.oci && chmod 600 ~/.oci/oci_api_key.pem
```

```bash
nano ~/.oci/config
```

`key_file=~/.oci/oci_api_key.pem` にして保存。確かめる:

```bash
oci iam region list --query 'data[0].name' --raw-output
```

**(3) VCN と公開サブネットを先に作る**（コンソール）

**Networking** → **Virtual cloud networks** → **Actions** → **Start VCN Wizard** → **Create VCN with Internet Connectivity**。名前は何でもよい（例 `insider`）。他は既定のまま。コンソールのインスタンス作成で失敗した回数だけ `vcn-<日付>` が残っていることがあるので、1 つだけ残して他は **Terminate** する（スクリプトは公開サブネットが 1 つだけのときに自動で選ぶ。複数あるなら `SUBNET_OCID=ocid1.subnet…` で指定する）。

**回す**

```bash
bash scripts/oci-launch-a1.sh
```

既定は 120 秒おき。`INTERVAL=60` のように環境変数で変えられる。Ctrl+C で止まる。回している間は Mac をスリープさせない。記録は `~/.oci/launch-a1.log`。作れたら公開 IP が出るので記録表に書き、2-2 へ進む。公開 IP の割り当て（`--assign-public-ip`）はスクリプトが済ませる。

## 2-2. 通信を開ける（security list）

OCI コンソール → **Networking** → **Virtual cloud networks** → 作られた VCN → **Security Lists** → Default Security List → **Add Ingress Rules**

| Source CIDR | IP Protocol | Destination Port Range |
| --- | --- | --- |
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

22 は既定で開いている。egress は既定（全許可）のまま。OS 側の iptables は setup.md §3 で開ける。

---

# Phase 3: DNS を向ける

ドメイン登録事業者の DNS 設定で A レコードを 1 つ足す。

| 項目 | 値 |
| --- | --- |
| タイプ | **A** |
| 名前 / ホスト | `@`（ルートの `insidergame.fyi` をそのまま使うため。サブドメインにするならその短い名前） |
| 値 / IP アドレス | Phase 2 で記録した**公開 IP** |
| TTL | 既定のまま |
| Proxy（Cloudflare の場合） | **OFF（DNS only）**。Caddy が自分で TLS を終端する |

`dig +short <host>` で公開 IP が返れば完了。

---

# Phase 4: 配備

先に setup.md §1〜§9 を上から実行する（SSH と OS の初期設定、iptables、`insider` ユーザー、uv、デプロイ鍵、ファイルの配置、`/etc/insider.env`、Caddy）。§9 の証明書の取得は Phase 3 の A レコードを使う。4-1 は setup.md §10、4-2 は §11 にあたる。

## 4-1. GitHub Secrets を 3 つ登録する

GitHub のリポジトリ → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**。コマンドなら setup.md §10 の `gh secret set`。

| Name | Secret に入れる値 |
| --- | --- |
| `DEPLOY_HOST` | VM の公開 IP |
| `DEPLOY_SSH_KEY` | `~/.ssh/insider-deploy` の**中身をそのまま全部**（`-----BEGIN` から `-----END` の行まで） |
| `DEPLOY_HOST_KEY` | `ssh-keyscan -t ed25519 <IP>` の出力 1 行（`<IP> ssh-ed25519 AAAA...`）。鍵の部分（`ssh-ed25519 AAAA...`）が VM の `/etc/ssh/ssh_host_ed25519_key.pub` と一致することを確かめてから登録する（setup.md §10。keyscan の結果は経路上で差し替えられ得る） |

LINE・Discord・TypeSafe の値は GitHub に置かない（VM の `/etc/insider.env` だけ）。

## 4-2. 初回配備

setup.md §11。`main` への空コミットを push し、Actions の `deploy` job が緑になることを見る。緑でもログに `Deploy secrets are not set; skipping deploy` が出ていれば配備されていない（4-1 の Secrets がリポジトリに登録されていない）。

---

# Phase 5: 監視の下地

VM が動き出したら、止まったことに気付ける状態を作る。**ボットが黙っても利用者からの報告以外に検知手段がない**状態を避けるため。

## 5-1. メモリ指標が出ているか確認する（最重要）

**なぜ重要か**: Oracle は 7 日間アイドルの VM を停止する。判定は CPU・ネットワーク・メモリの **3 つすべてが 20% 未満のとき**で、このシステムが唯一外せるのはメモリ条件。そのために `insider-memfloor` が 3GB の tmpfs を埋めている。**ただしこれは OCI 側にメモリ指標が報告されていて、かつ tmpfs を使用中に数えていないと効かない。**

OCI コンソール → **Compute** → **Instances** → 対象インスタンス:

1. **Oracle Cloud Agent** タブ → **Compute Instance Monitoring** が **Enabled** であること
2. **Metrics** タブ → **Memory Utilization** のグラフに**値が出ていること**（起動後 5〜10 分で現れる）
3. 値が **20% を上回っている**こと（3GB / 12GB = 25% が期待値）

20% を下回っていれば cutover.md A-9 の手順でプロセス方式に差し替え、どちらにしたかを記録表に書く。**グラフに値が出ていなければ**、メモリ対策は存在しないものとして扱い、切替前に「PAYG へ上げるか」を決める（別枠）。

## 5-2. メール通知を設定する

### まず通知先を作る

OCI コンソール → **Developer Services** → **Notifications** → **Topics** → **Create Topic**

| 項目 | 値 |
| --- | --- |
| Name | `insider-alerts` |

作ったトピックを開き → **Create Subscription**

| 項目 | 値 |
| --- | --- |
| Protocol | **Email** |
| Email | 自分のアドレス |

**確認メールが届くので、本文のリンクを押して承認する。** 承認しないと通知が飛ばない（Status が `Pending` のままになる）。

### アラームを 2 つ作る

OCI コンソール → **Observability & Management** → **Monitoring** → **Alarm Definitions** → **Create Alarm**

**1 本目 — メモリが下がった（アイドル判定に近づいた）**

| 項目 | 値 |
| --- | --- |
| Alarm name | `insider-memory-low` |
| Metric namespace | `oci_computeagent` |
| Metric name | `MemoryUtilization` |
| Interval | 5 minutes |
| Statistic | Mean |
| Dimension | `resourceId` = 対象インスタンス |
| Trigger rule → Operator | **less than** |
| Trigger rule → Value | `20` |
| Trigger delay minutes | `30` |
| Destination | Topic `insider-alerts` |

**2 本目 — 指標が来なくなった（エージェント停止か VM 停止）**

Alarm name `insider-metrics-absent`。1 本目と同じ設定で、Trigger rule の Operator を **Absent** にする。Trigger delay は `30`。

> 1 本目だけだと「VM が止まって指標ごと来なくなった」ケースを検知できない。**値の異常と欠測は別の事象**なので 2 本必要。

## 5-3. 外形監視を登録する

OCI の監視は「VM が動いているか」しか見ない。**アプリが応答しているか**は外から見る。

| 条件 | 値 |
| --- | --- |
| 監視 URL | `https://<host>/healthz` |
| 間隔 | 5 分 |
| 成功の条件 | 応答本文に **`ok`** を含む（キーワード監視） |
| 通知 | メール |

UptimeRobot や Better Stack などが候補。**無料枠でキーワード監視ができるかは事前に確認する。** 登録したら、一度 VM 上で `sudo systemctl stop insider-web` してから通知が来ることを確かめると確実。確認後は `sudo systemctl start insider-web` で戻す。

`/healthz` は Web プロセスが HTTP を受け付けていることだけを示す。Discord ボットの生死は journald で見る（cutover.md C）。

---

# Phase 6: 切替（カットオーバー）

**戻せる最後の地点。** 切り替えるのは **LINE Developers の Webhook URL の 1 か所だけ**。Netlify の特殊村フォームは触らない（Web 版に取り込んであるので、接続先を Heroku のまま残してロールバックに備える）。

## 事前の確認

1. cutover.md の **A の準備 1 件と 13 項目がすべて通っている**
2. スタブが外れている: `[VM] sudo grep -c LINE_API_BASE_URL /etc/insider.env` が **`0`**
3. **プレイヤーがいない時間帯を選ぶ**（進行中の村は切替の瞬間に消える）

## 6-1. LINE の Webhook URL

LINE Developers コンソール → 対象のチャネル → **Messaging API 設定** タブ:

1. **Webhook URL** の「編集」→ `https://<host>/line/callback` → 「更新」
2. **「検証」ボタンを押す** → 期待: **成功**
3. **「Webhook の利用」が ON** になっていることを確認する（OFF だとイベントが届かない）
4. **「Webhook の再送」は OFF のまま**（重複排除はしていない。Java も同じ）
5. 「応答メッセージ」は OFF のまま

## 6-2. 実機で確かめる

cutover.md B-4 の 4 項目。**Web で特殊村を作る → LINE からその番号で参加 → `@配布`** は飛ばさない。

## 6-3. 日付を記録する

| | |
| --- | --- |
| 切替日 | |
| Heroku 解約予定日 | 切替日 + 1 か月 |

---

# Phase 7: 1 か月の様子見

cutover.md C。最初の 1 週間は毎日、以降は週 1 回。

---

# Phase 8: 後片付け

Phase 7 で問題がなければ。**順序が大事**で、8-2 を飛ばすと課金が止まらない。

## 8-1. Heroku アプリを削除する

Heroku ダッシュボード → `insidergamehelper` → **Settings** → 一番下の **Delete app**

## 8-2. Eco dynos を Unsubscribe する ← 忘れやすい

Heroku → 右上のアバター → **Account settings** → **Billing** → **Eco dynos** の **Unsubscribe**

> **Eco はアプリ単位ではなくアカウント単位の月額契約。** アプリを削除しただけでは **$5/月 は止まらない。** 翌月の請求が $0 になっていることを必ず確認する。

## 8-3. Netlify の特殊村フォームを移転の案内に差し替える

公開フォーム（`insidergametool.netlify.app`）のリポジトリで、フォームの画面を「移転しました」の案内と `https://<host>/village/special` へのリンクだけにしてデプロイする。Heroku が消えた後にフォームから送ると失敗するので、同じタイミングで行う。

## 8-4. LineBot リポジトリをアーカイブする

GitHub → LineBot のリポジトリ → **Settings** → **General** → **Danger Zone** → **Archive this repository**。先に README の先頭に移転先（insider のリポジトリと `https://<host>`）を書いてコミットする。役職画像は insider に同梱済みなので、アーカイブしても利用者に影響しない。

## 8-5. docs の蒸留

統合設計書（`docs/superpowers/specs/2026-10-03-unify-line-web-discord-design.md`）の結論を docs/ 直下に蒸留して削除する（docs/AGENTS.md の運用）。この手順書のうち Phase 1〜5 は VM の再作成に要るので残す。Phase 6〜8 と別枠のロールバックは Heroku が消えた時点で用済みになるので消す。

---

# 別枠: ロールバック（Heroku へ戻したいとき）

**破壊的操作。** OCI 上で作られた村はすべて消える。手順とコマンドは cutover.md D。画面操作は 1 つ:

**LINE Developers コンソールの Webhook URL を `https://insidergamehelper.herokuapp.com/callback` へ戻し、「検証」で成功を確認する。** その前に `heroku restart` で古い村を破棄する。**VM は止めない。**

---

# 別枠: PAYG へ上げる（アイドル通知が来たとき）

OCI コンソール → **Billing & Cost Management** → **Upgrade and Manage Payment** → **Upgrade to Pay As You Go**。無料枠の範囲なら請求は $0 のままで、アイドル回収の対象から外れる。

同時に予算の通知を作る: **Billing & Cost Management** → **Budgets** → **Create Budget**

| 項目 | 値 |
| --- | --- |
| Name | `insider-budget` |
| Amount | `1`（USD） |
| Alert rule | Actual spend が 100% を超えたらメール |

上げた日と理由を記録表に書く。
