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
| ファイアウォール | HTTP・HTTPS とも許可しない（ボットは外向きの通信だけ） |
| バックアップ・スナップショット | 設定しない（無料枠の対象外） |

ブートディスクの種類は既定が「バランス永続ディスク」になっていることがあり、そのままだと課金されるので必ず「標準」に変える。

## サーバーで初期設定する

VM 一覧の「SSH」ボタンでブラウザの SSH を開き、次を実行する。

```bash
git clone https://github.com/FukaseDaichi/insider.git
cd insider
bash deploy/setup.sh
```

1 回目は `.env` のひな形を作って止まる。トークンを記入してからもう一度実行すると、ボットが起動する。

```bash
nano .env               # DISCORD_TOKEN と TYPESAFE_API_KEY を記入（Ctrl+O で保存、Ctrl+X で終了）
bash deploy/setup.sh
```

最後に表示される `systemctl status` が `active (running)` なら成功。
手元のボットは止めてから Discord で動作確認する（両方動いていると 2 回返信される）。
`DISCORD_GUILD_ID` は手元の `.env` と同じ値にしておくと、スラッシュコマンドがすぐ反映される。

## 運用

```bash
cd ~/insider && git pull && sudo systemctl restart insider-bot   # 更新（依存の変更も起動時に反映される）
journalctl -u insider-bot -f                                    # ログを見る
sudo systemctl stop insider-bot                                 # 止める
```
