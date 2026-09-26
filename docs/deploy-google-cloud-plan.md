# Google Cloud デプロイ計画（概要）

- 作成日: 2026-09-27
- 目的: お題当て GM ボットを Google Cloud の無料枠（e2-micro）で 24 時間動かす

## 構成

| 項目 | 内容 |
|---|---|
| サーバー | Compute Engine e2-micro（常時無料枠）／ us-central1 ／ Ubuntu 24.04 LTS ／ 標準永続ディスク 30GB |
| コード配置 | GitHub のプライベートリポジトリから `git clone` |
| 実行 | uv + systemd（落ちても自動再起動、サーバー再起動時に自動起動） |
| 秘密情報 | `.env` はサーバー上に手で置く（Git には入れない） |

## 進め方

| # | 作業 | 担当 | 完了の目安 |
|---|---|---|---|
| 1 | Google Cloud アカウント作成、請求先登録、予算アラート（例: 月 $1）設定 | あなた | コンソールに入れる |
| 2 | GitHub にプライベートリポジトリを作って push | Claude | GitHub で見える |
| 3 | サーバー用ファイルを追加（`deploy/setup.sh`、`deploy/insider-bot.service`） | Claude | リポジトリに入っている |
| 4 | VM を作成（上記の構成） | あなた | ブラウザの SSH でログインできる |
| 5 | サーバーで `setup.sh` を実行し、`.env` を作成 | あなた（手順は Claude が用意） | `systemctl status` が active |
| 6 | 手元のボットを止めたうえで、Discord で動作確認 | 一緒に | 質問に回答が返る |

## 運用

- 更新: サーバーで `git pull` → `sudo systemctl restart insider-bot`
- ログ: `journalctl -u insider-bot -f`
- 費用: 月 1 回、請求画面で 0 円であることを確認

## 注意点

- 無料になるのは e2-micro ×1 台、米国 3 リージョン（us-west1 / us-central1 / us-east1）、標準ディスク 30GB、外向き通信 月 1GB まで。これを外れると課金される
- メモリが 1GB なので、setup.sh でスワップ（1GB）も作る
- 手元とサーバーでボットを同時に動かすと、質問に 2 回返信してしまう。どちらか一方だけで動かす

## 今後（このデプロイの後）

- 音声の聞き取り（ボイスチャンネル対応）の設計・実装
- 記録だけ残した軽微な修正 4 件
