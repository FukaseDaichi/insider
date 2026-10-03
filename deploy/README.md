# サーバーへのデプロイ手順

全体の方針は [デプロイ計画](../docs/deploy-google-cloud-plan.md) を参照。

## VM を作る（Google Cloud コンソール）

「Compute Engine → VM インスタンス → インスタンスを作成」（初回は Compute Engine API の有効化を求められる）。

| 項目 | 設定 |
|---|---|
| 名前 | `insider-bot` |
| リージョン | `us-central1`（ゾーンはどれでもよい） |
| マシンタイプ | E2 → `e2-micro` |
| ブートディスク | Ubuntu 24.04 LTS（x86/64）／**標準永続ディスク**／30GB |
| ファイアウォール | HTTP・HTTPS とも許可しない（ボットは外向きの通信だけ。Web 版は Tailscale Funnel で公開する） |
| バックアップ・スナップショット | 設定しない（無料枠の対象外） |

ブートディスクの種類は既定が「バランス永続ディスク」になっていることがあり、そのままだと課金されるので必ず「標準」に変える。

## サーバーで初期設定する

VM 一覧の「SSH」ボタンでブラウザの SSH を開き、次を実行する。

```bash
git clone https://github.com/FukaseDaichi/insider.git
cd insider
bash deploy/setup.sh
```

1 回目は `.env` のひな形を作って止まる。トークンを記入してからもう一度実行すると、Discord ボット（`insider-bot`）と Web 版（`insider-web`）が起動する。

```bash
nano .env               # DISCORD_TOKEN と TYPESAFE_API_KEY を記入（Ctrl+O で保存、Ctrl+X で終了）
bash deploy/setup.sh
```

最後に表示される `systemctl status` が両方とも `active (running)` なら成功。
手元のボットは止めてから Discord で動作確認する（両方動いていると 2 回返信される）。
`DISCORD_GUILD_ID` は手元の `.env` と同じ値にしておくと、スラッシュコマンドがすぐ反映される。

すでにボットだけ動かしているサーバーに Web 版を足すときも、`cd ~/insider && git pull && bash deploy/setup.sh` を実行すればよい。

## Web 版を公開する（Tailscale Funnel）

Web 版は VM の中（`127.0.0.1:8080`）でだけ待ち受ける。マイクを使うには HTTPS が必要なので、Tailscale Funnel で `https://<マシン名>.<tailnet名>.ts.net` として公開する。無料で、ドメインは要らず、VM のファイアウォールも閉じたままでよい。

1. https://login.tailscale.com でアカウントを作る（Google アカウントなどでログインできる）
2. VM に Tailscale を入れてログインする

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up        # 表示された URL をブラウザで開いてログインする
   ```

3. 公開する

   ```bash
   sudo tailscale funnel --bg 8080
   ```

   初回は管理画面で Funnel を有効にするリンクが表示されるので、開いて有効にしてからもう一度実行する。設定は VM を再起動しても残る。公開中の URL は `sudo tailscale funnel status` で確かめられる

4. 表示された `https://….ts.net` をスマホで開き、ルームを作って質問に答えが返ることを確かめる（答えが返れば WebSocket も Funnel を通っている）

公開をやめるときは `sudo tailscale funnel reset`。

## 運用

```bash
cd ~/insider && git pull && sudo systemctl restart insider-bot insider-web   # 更新（依存の変更も起動時に反映される）
systemctl status insider-bot insider-web --no-pager                         # 両方が active (running) か確かめる
journalctl -u insider-bot -f                                                # Discord ボットのログ
journalctl -u insider-web -f                                                # Web 版のログ
sudo systemctl stop insider-bot insider-web                                 # 止める
```

更新のときは必ず両方を再起動する。片方だけだと、もう片方が古いコードのまま動き続ける。
