# VM セットアップ手順書

Oracle Cloud Always Free の A1 VM 1 台に insider（Web 版・配役ツール・LINE の webhook・Discord ボット）を載せる手順。VM が停止・削除されたときの再作成にもこのまま使う。構成と理由は [docs/infra.md](../docs/infra.md) にあり、ここでは繰り返さない。

記法: `[Mac]` は手元の Mac で、`[VM]` は VM に SSH した上で実行する。`<...>` は実行時に決まる値。

ブラウザでの画面操作（Oracle Cloud のインスタンス作成、DNS、GitHub Secrets、監視の設定）は [human-steps.md](human-steps.md) にまとめてある。この文書はターミナルで打つ分だけを扱う。

## 0. 先に用意するもの

| 項目 | 値 | 備考 |
| --- | --- | --- |
| Oracle Cloud アカウント | ホームリージョン **ap-tokyo-1** | サインアップ時に決まり、後から変更できない |
| A1 インスタンス | VM.Standard.A1.Flex、2 OCPU / 12GB、Ubuntu 24.04（aarch64）、ブートボリューム 50GB | `Out of host capacity` なら時間を置いてリトライ。取れるまで Heroku のまま |
| VCN の security list | ingress 22 / 80 / 443（0.0.0.0/0）、egress は既定（全許可）のまま | egress 443 は api.line.me、api.typesafe.ai、Discord のゲートウェイに必要 |
| SSH 鍵 | インスタンス作成時に登録した公開鍵（`ubuntu` ユーザー用） | |
| ホスト名 | `<host>`（例 `insider.<domain>`）の A レコードを VM の公開 IP へ | Cloudflare なら DNS の Proxy を **OFF**（DNS only）。Caddy が直接 TLS を終端するため |
| デプロイ鍵 | `[Mac] ssh-keygen -t ed25519 -f ~/.ssh/insider-deploy -C insider-deploy -N ''` | 公開鍵は §6、秘密鍵は §10 で使う |

以降、`<IP>` は VM の公開 IP、`<host>` は取得したホスト名。

## 1. 接続と OS の初期設定

```bash
[Mac] ssh ubuntu@<IP>
[VM]  sudo apt-get update && sudo apt-get -y upgrade
[VM]  sudo apt-get install -y unattended-upgrades curl
[VM]  sudo dpkg-reconfigure -f noninteractive unattended-upgrades
[VM]  sudo timedatectl set-timezone Asia/Tokyo
```

## 2. SSH を公開鍵のみにする

```bash
[VM] sudo tee /etc/ssh/sshd_config.d/99-insider.conf > /dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
[VM] sudo sshd -t && sudo systemctl reload ssh
```

## 3. iptables で 80 / 443 を開ける

OCI の Ubuntu イメージは security list とは別に OS 側の iptables が 22 以外を塞いでいる。ここを忘れると security list を開けても疎通しない。保存に使う `netfilter-persistent` が入っていないイメージもあるので先に入れる（入っていれば何もしない）。

```bash
[VM] sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
[VM] sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
[VM] sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
[VM] sudo netfilter-persistent save
[VM] sudo iptables -L INPUT -n --line-numbers | head -12
```

期待: 80 と 443 の ACCEPT が `REJECT` 行より **上**にある。§11 の後に `sudo reboot` して、再起動後も `sudo iptables -L INPUT -n` に 2 行が残っていることを一度確かめる。

## 4. insider ユーザーと配置先

```bash
[VM] sudo useradd --system --create-home --home-dir /opt/insider --shell /bin/bash insider
[VM] sudo -u insider mkdir -p /opt/insider/releases /opt/insider/incoming /opt/insider/.ssh
[VM] sudo chmod 700 /opt/insider/.ssh
```

## 5. uv と Python

uv は insider ユーザーの `~/.local/bin` に入る。`.python-version`（3.13）の Python は uv が取得して `~/.local/share/uv/python` に置く。apt の Python には依存しない。

```bash
[VM] curl -LsSf https://astral.sh/uv/install.sh | sudo -u insider -H sh
[VM] sudo -u insider -H /opt/insider/.local/bin/uv --version
[VM] sudo -u insider -H /opt/insider/.local/bin/uv python install 3.13
```

期待: `uv 0.x.y` と、`Installed Python 3.13.x`。初回配備の `uv sync` が Python の取得で待たされないよう先に入れておく。

## 6. デプロイ鍵を insider に登録する

`restrict` で pty と転送を禁止する（コマンド実行と scp は通る）。

```bash
[Mac] cat ~/.ssh/insider-deploy.pub
[VM]  echo 'restrict <insider-deploy.pub の内容>' | sudo -u insider tee /opt/insider/.ssh/authorized_keys > /dev/null
[VM]  sudo chmod 600 /opt/insider/.ssh/authorized_keys
[Mac] ssh -i ~/.ssh/insider-deploy insider@<IP> 'echo ok'
```

期待: `ok`。

## 7. リポジトリのファイルを VM へ置く

`[Mac]` でリポジトリのルートから実行する。

```bash
[Mac] scp deploy/insider-release.sh deploy/insider-web.service deploy/insider-bot.service deploy/insider-memfloor.service deploy/journald-insider.conf deploy/sudoers-insider deploy/Caddyfile ubuntu@<IP>:/tmp/
[VM]  sudo install -o root -g root -m 0755 /tmp/insider-release.sh /usr/local/bin/insider-release.sh
[VM]  sudo install -o root -g root -m 0440 /tmp/sudoers-insider /etc/sudoers.d/insider
[VM]  sudo visudo -cf /etc/sudoers.d/insider
[VM]  sudo install -o root -g root -m 0644 /tmp/insider-web.service /tmp/insider-bot.service /tmp/insider-memfloor.service /etc/systemd/system/
[VM]  sudo systemctl daemon-reload
[VM]  sudo systemctl enable insider-web insider-bot insider-memfloor
[VM]  sudo mkdir -p /etc/systemd/journald.conf.d
[VM]  sudo install -o root -g root -m 0644 /tmp/journald-insider.conf /etc/systemd/journald.conf.d/insider.conf
[VM]  sudo systemctl restart systemd-journald
[VM]  sudo systemd-analyze verify /etc/systemd/system/insider-web.service /etc/systemd/system/insider-bot.service /etc/systemd/system/insider-memfloor.service
```

期待: `visudo -cf` が `parsed OK`、`systemd-analyze verify` が何も出力しない（`/opt/insider/current` がまだないことによる警告は出てよい）。`enable` は世代がなくても成功する（VM 再起動時の自動起動を張るだけ）。ここで済ませておくのは、初回配備が失敗したときに未 enable のまま残さないため。

メモリ床をここで起動して、効いていることを見る:

```bash
[VM] sudo systemctl start insider-memfloor
[VM] df -h /run/insider-memfloor && free -m
```

期待: `df` の Used が `3.0G`、`free` の `shared` が 3,000 前後（tmpfs は `shared` と `buff/cache` に数えられ、`used` には入らない。OCI の指標がどちらを見るかは [cutover.md](cutover.md) A-9 で実測する）。

## 8. /etc/insider.env

値は LINE Developers・Discord Developer Portal・TypeSafe のコンソールで控えたもの（[human-steps.md](human-steps.md) 1-4）。**パスワードマネージャにも保管する。** `echo` や heredoc で書くとシェルの履歴に値が残るので、エディタで貼る。

```bash
[VM] sudo install -o root -g root -m 0600 /dev/null /etc/insider.env
[VM] sudoedit /etc/insider.env
```

エディタに次の 5 行を貼り、`<...>` をパスワードマネージャからの値に置き換えて保存する:

```
DISCORD_TOKEN=<Discord のボットトークン>
TYPESAFE_API_KEY=<TypeSafe の API キー>
LINE_CHANNEL_TOKEN=<チャネルアクセストークン>
LINE_CHANNEL_SECRET=<チャネルシークレット>
PUBLIC_BASE_URL=https://<host>
```

```bash
[VM] ls -l /etc/insider.env && sudo grep -c '=.' /etc/insider.env
```

期待: `-rw------- 1 root root` と `5`（5 行とも値がある）。切替前の検証中だけ、これに `LINE_API_BASE_URL=http://127.0.0.1:18080` を足す（[cutover.md](cutover.md)）。

**Discord ボットはここで動き出すと Heroku とは無関係に本物の Discord に接続する。** VM が動いている間は Mac で `scripts/play.sh` を使わない（2 か所で動くと質問に 2 回返信する）。Mac の `.env` に `PRODUCTION_URL=https://<host>` を書いておくと、play.sh は本番の `/healthz` が `ok` の間は起動を断る。

## 9. Caddy とレート制限モジュール

```bash
[VM] sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
[VM] curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
[VM] curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
[VM] sudo apt-get update && sudo apt-get install -y caddy
[VM] sudo caddy add-package github.com/mholt/caddy-ratelimit
[VM] sudo apt-mark hold caddy
[VM] caddy list-modules | grep rate_limit
```

期待: `http.handlers.rate_limit` が出る。`apt-mark hold` により unattended-upgrades もモジュールなしのバイナリで上書きしない。

```bash
[VM] sudo sed "s/insider.example.com/<host>/" /tmp/Caddyfile | sudo tee /etc/caddy/Caddyfile > /dev/null
[VM] sudo caddy validate --config /etc/caddy/Caddyfile
[VM] sudo systemctl enable caddy
[VM] sudo systemctl restart caddy
[VM] sudo journalctl -u caddy -n 20 --no-pager
```

期待: `validate` が `Valid configuration`。journal に `certificate obtained successfully`（A レコードが向いていれば数十秒で取れる）。`restart` は `add-package` で差し替えた新しいバイナリで起動し直すために必要（`reload` では古いプロセスのまま）。

```bash
[Mac] curl -si https://<host>/healthz | head -1
```

期待: `HTTP/2 502`（TLS は終端できているが、aiohttp はまだ動いていない）。

## 10. GitHub Secrets

```bash
[Mac] ssh-keyscan -t ed25519 <IP> 2>/dev/null
[VM]  cat /etc/ssh/ssh_host_ed25519_key.pub
```

2 つの出力の鍵の部分（`ssh-ed25519 AAAA...`）が**一致する**ことを目で確かめる（keyscan は経路上で差し替えられ得るので、SSH 済みの VM の中身と突き合わせる）。一致した `ssh-keyscan` の 1 行（`<IP> ssh-ed25519 AAAA...`）を `DEPLOY_HOST_KEY` にする。

```bash
[Mac] gh secret set DEPLOY_HOST --body '<IP>'
[Mac] gh secret set DEPLOY_SSH_KEY < ~/.ssh/insider-deploy
[Mac] gh secret set DEPLOY_HOST_KEY --body '<ssh-keyscan の 1 行>'
[Mac] gh secret list
```

LINE・Discord・TypeSafe の資格情報は GitHub に置かない。

## 11. 初回配備

`main` への push が唯一のトリガー（`workflow_dispatch` は設けていない）なので、空コミットを push して配備する。

```bash
[Mac] git commit --allow-empty -m "chore: VM への初回配備" && git push
[Mac] gh run watch
[VM]  sudo systemctl status insider-web insider-bot --no-pager
[VM]  curl -s http://127.0.0.1:8080/healthz; echo
[Mac] curl -s https://<host>/healthz; echo
```

期待: deploy job が成功し、2 つの `status` が `active (running)`、`/healthz` が `ok`。job のログに `Deploy secrets are not set; skipping deploy` が出ていたら、配備は行われていない（§10 の Secrets がリポジトリに登録されていない）。初回は `uv sync` が依存を取ってくるので 1〜2 分かかる。以降の再起動は更新スクリプトが行い、VM 再起動時は §7 の `enable` により自動起動する。

ブラウザで `https://<host>/` を開き、お題当ての画面が出ることと、`https://<host>/village/new` で配役ツールが出ることを見る。

deploy job が失敗したら、job のログの `not healthy` の行で Web と bot のどちらが通らなかったかを見て、VM の journal で原因を確かめる。多くは `/etc/insider.env` の値の誤りなので、直してから失敗した job だけを再実行する。更新スクリプトは、同じ commit の世代が健康でなければ再起動して確かめる（`<run-id>` は `gh run list` で見る）:

```bash
[VM]  sudo journalctl -u insider-web -u insider-bot -n 50 --no-pager
[VM]  sudoedit /etc/insider.env
[Mac] gh run rerun --failed <run-id>
```

## 12. Monitoring プラグインの確認

OCI コンソール → Compute → Instances → 対象インスタンス → **Oracle Cloud Agent** タブで **Compute Instance Monitoring** が Enabled であることを確認する。次に **Metrics** タブで `Memory Utilization` のグラフに値が出ていることを見る（起動後 5〜10 分で現れる）。

**値が出ていなければ、アイドル回収のメモリ対策は存在しないものとして扱う**（[cutover.md](cutover.md) の PAYG の節）。

## 13. OCI Alarm（メール通知）

[human-steps.md](human-steps.md) 5-2 の画面手順で、トピック `insider-alerts` と Alarm 2 本（`MemoryUtilization` が 20 未満、および Absent。Trigger delay 30 分）を作る。

## 14. 四半期ごとの更新

| 対象 | 手順 |
| --- | --- |
| OS | unattended-upgrades が自動で当てる。カーネル更新後は `sudo reboot`（再起動後に insider-web・insider-bot・caddy が自動で上がることを §11 の `/healthz` で確認） |
| Python と依存 | `uv.lock` と `.python-version` を手元で更新して push すれば、配備の `uv sync` が反映する。VM で手で入れ替えるものはない |
| uv 本体 | `sudo -u insider -H /opt/insider/.local/bin/uv self update` |
| Caddy | 下のコマンド。組み込みモジュールを維持したまま最新へ上げ、レート制限のモジュールが残っていることを見てから再起動する |

Caddy の更新:

```bash
[VM] sudo caddy upgrade
[VM] caddy list-modules | grep rate_limit
[VM] sudo systemctl restart caddy
```

期待: `http.handlers.rate_limit` が出る。出なければ再起動せず、§9 の `add-package` をやり直す（モジュールなしで再起動すると Caddyfile の `rate_limit` を読めずに起動しない）。

## 15. VM が失われたときの再作成

§0 でインスタンスを作り直し（公開 IP が変わる）、§1〜§13 を上から実行する。`/etc/insider.env` の値はパスワードマネージャから復元する。IP が変わるので §0 の A レコード、§10 の `DEPLOY_HOST` と `DEPLOY_HOST_KEY` を更新する。完了後に [cutover.md](cutover.md) の A（切替前の検証）をやり直す。
