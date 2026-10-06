# LINE Bot を Oracle Cloud の insider へ移す設計（後片付け）

## 背景と目的

LINE Bot（LineBot リポジトリ、Java 8、Heroku Eco $5/月）の機能は insider に移植済みで、insider は LINE・Web・Discord の 3 つの入口を持つ 1 つのシステムになっている。村の中核・Web の配役ツール・LINE アダプタの設計は [仕様書](../../spec.md)・[村の外部仕様](../../village.md)・README に、Oracle Cloud の 1 台で 24 時間動かす構成と配備の仕組みは [インフラ構成](../../infra.md) と `deploy/` に蒸留した。VM の作成・切替前の検証・LINE の webhook の切替は済み（実測は [deploy/cutover.md](../../../deploy/cutover.md) の記録表、日付は [deploy/human-steps.md](../../../deploy/human-steps.md) の記録表）。

残っているのは、**1 か月の様子見のあとに LineBot と Netlify フォームを片付ける**ことである。本設計書はその部分だけを持つ。

### 範囲

- 様子見の期間に Heroku へ戻せる状態を保つこと
- LineBot リポジトリと Netlify フォームの後片付け

### 範囲外

- Jev のお題当てルームに役職・タイマー・投票を混ぜること
- 村の永続化（「状態を持たない」原則を保つ）
- 認証の導入（「番号を知る人が入る」前提のまま）

## 様子見とロールバック

切替対象は **LINE Developers の Webhook URL だけ**だった。特殊村フォームは Web 版に取り込んであるので、Netlify フォームの接続先は切り替えておらず、Heroku のまま残っている。Heroku は切替後 1 か月維持し、戻し先として使える。

- **様子見**（[deploy/cutover.md](../../../deploy/cutover.md) C）: メモリ指標が 20% を上回る、回収のメールが来ない、外形監視の失敗通知が来ない、journald に想定外の WARNING／ERROR がない、Discord の長期の切断がない
- **ロールバック**（同 D）: Webhook URL を Heroku のものへ戻すだけ。OCI 上で作られた村はすべて消え、Heroku 側に切替前の古い村が残っていると番号が混乱するので、**戻す前に Heroku を再起動する**。VM は止めず、原因を調べられる状態を残す

## 後片付け

様子見で問題がなければ、この順で行う（[deploy/human-steps.md](../../../deploy/human-steps.md) Phase 8）。

1. Heroku アプリの削除と、**Eco dynos の Unsubscribe**（アプリを消しただけでは $5 が止まらない）
2. 同時に Netlify フォームを「移転しました」の案内（Web 版の `/village/special` へのリンク）に差し替える。Heroku が消えた後にフォームから送ると失敗するため
3. LineBot リポジトリをアーカイブする。README に移転先を書く。役職画像は insider に同梱済みなので、アーカイブしても利用者に影響しない
4. 本設計書を削除し、cutover.md の D（ロールバック）と human-steps.md の Phase 6〜8・別枠を消す（docs/AGENTS.md の運用）。human-steps.md の Phase 1〜5、setup.md、cutover.md の A〜C は VM の再作成と運用に要るので残す

## マイルストーン

| # | 内容 | 依存 |
|---|---|---|
| M6 | 後片付け（Heroku 解約、Netlify 差し替え、LineBot アーカイブ、docs の蒸留） | 切替の 1 か月後 |

M1〜M5 は実装済みで、設計は docs/ に、実測は deploy/ の記録表に蒸留した。

## 残るリスク

- **無料枠の縮小**: 次に半減（1 OCPU / 6GB）すれば memfloor の値は見直しになるが、Python のプロセス自体は小さいので動作は続く
- **Discord の再接続**: `/healthz` の対象外。長期の切断は journald でしか気づけない。問題になったら Discord のゲートウェイ接続状態を `/healthz` に含める
- **Heroku を消した後の戻し先がない**: 後片付けの後に VM が失われたら、setup.md で作り直すまで LINE は止まる。手元の Mac での起動は Discord と Web だけで、LINE の webhook は公開 URL が固定でないので受けられない
