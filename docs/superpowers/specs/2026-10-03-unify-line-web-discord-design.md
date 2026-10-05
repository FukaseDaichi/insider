# LINE Bot を Oracle Cloud の insider へ移す設計（切替と後片付け）

## 背景と目的

LINE Bot（LineBot リポジトリ、Java 8、Heroku Eco $5/月）の機能は insider に移植済みで、insider は LINE・Web・Discord の 3 つの入口を持つ 1 つのシステムになっている。村の中核・Web の配役ツール・LINE アダプタの設計は [仕様書](../../spec.md)・[村の外部仕様](../../village.md)・README に、Oracle Cloud の 1 台で 24 時間動かす構成と配備の仕組みは [インフラ構成](../../infra.md) と `deploy/` に蒸留した。

残っているのは、**A1 を確保して VM を作り、切替前の検証を通し、LINE の webhook を Heroku から切り替え、LineBot と Netlify フォームを片付ける**ことである。本設計書はその部分だけを持つ。

### 範囲

- VM の作成と切替前の検証、Heroku からの 1 回の切替
- LineBot リポジトリと Netlify フォームの後片付け

### 範囲外

- Jev のお題当てルームに役職・タイマー・投票を混ぜること
- 村の永続化（「状態を持たない」原則を保つ）
- 認証の導入（「番号を知る人が入る」前提のまま）

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

手順は [deploy/cutover.md](../../../deploy/cutover.md)（B〜E）と [deploy/human-steps.md](../../../deploy/human-steps.md)（Phase 6〜8）。

### ロールバック

Webhook URL を Heroku のものへ戻すだけ。Heroku は切替後 1 か月維持する。OCI 上で作られた村はすべて消え、Heroku 側に切替前の古い村が残っていると番号が混乱するので、**戻す前に Heroku を再起動する**。VM は止めず、原因を調べられる状態を残す。

## 切替前の検証

- **Java との突き合わせ（ゴールデン）**: 切替前に必ず採る。本番と同じ Java 8（Temurin 8）で手元に起動した LineBot の `/callapi` へ同じ入力列を送って JSON を採取し（`uv run python -m tests.line_golden http://127.0.0.1:18080/callapi`）、`tests/golden/line_callapi.json` に置く。採ったら `tests/test_line_golden.py` の比較が skip から実行に変わるので、伏せ方（村なしの判定・候補の altText・席番号の置換・古い fixture の検出）を見直し、docs/spec.md と README の「まだ採っていないあいだは skip」の文を直す。Heroku の本番の `/callapi` は使わない（入力列が村を十数個作り、上限 50 件の FIFO で遊んでいる人の村を押し出す）。
- **VM 上の検証**: [deploy/cutover.md](../../../deploy/cutover.md) の A（準備 1 件＋13 項目）。Caddy 経由の署名付き `/line/callback`、スタブに届く返信の内容、不正署名の拒否、応答時間、レート制限と本文上限、`/healthz`、`MemoryUtilization` の実測、再起動と VM 再起動後の自動復帰、デプロイの自動復旧（Web を壊す世代と bot を壊す世代の両方）、古い commit の re-run で deploy が skip すること。手元のテストは systemctl・curl・uv を偽物に差し替えて本人として動くので、`sudo -u insider` を通る経路、本物の GitHub Actions（Secrets 未登録のあいだの skip と、登録後の初回配備）、Caddy のレート制限の評価順は、この検証が唯一の確認になる。
- **実測して決めること**: memfloor の方式（tmpfs かプロセスか。docs/infra.md に記す）、レート制限の確定値（配役ツールの画面を同じ Wi-Fi から複数人が開いても 429 にならないか。全体の 300 回／分で窮屈なら `deploy/Caddyfile` を直す）、停止にかかる時間（接続中の端末を複数つないだまま `systemctl restart insider-web` して `TimeoutStopSec` の 90 秒に収まるか）。

## ドキュメント

- 切替後、docs/infra.md の「結論」の表の「現在」を Oracle Cloud に書き換え、memfloor の方式を記す（cutover.md B の手順に含む）
- 完了後、本設計書は docs/ 直下に蒸留して削除する（docs/AGENTS.md の運用）。同時に cutover.md の B〜E と human-steps.md の Phase 6〜8・別枠を消す。human-steps.md の Phase 1〜5 と setup.md は VM の再作成に要るので残す

## マイルストーン

| # | 内容 | 依存 |
|---|---|---|
| M4 | インフラ（Caddy、systemd、memfloor、VM 上の更新スクリプト、CI からの配備、手順書） | 済み。`deploy/`、`.github/workflows/ci.yml`、docs/infra.md |
| M5 | VM の作成（deploy/setup.md）、切替前検証（ゴールデンの採取を含む）とカットオーバー（deploy/cutover.md） | A1 の確保。アカウント作成とドメイン取得は先に進められる |
| M6 | 後片付け（Heroku 解約、Netlify 差し替え、LineBot アーカイブ、docs の蒸留。deploy/human-steps.md Phase 8） | M5 の 1 か月後 |

M1〜M4 は実装済みで、設計は docs/ に蒸留した。M5・M6 の作業は手順書が持つ。

## 残るリスク

- **A1 の在庫**: 取れるまで切替は始まらない。LineBot 設計と同じく、取れない間は Heroku のまま運用し、一定期間試して取れなければ保留とする。そのあいだは Mac でのローカル遊び（`scripts/play.sh`）をそのまま続ける
- **無料枠の縮小**: 次に半減（1 OCPU / 6GB）すれば memfloor の値は見直しになるが、Python のプロセス自体は小さいので動作は続く。Java 設計より縮小に強い
- **文面の差**: ゴールデン比較で機械的に確かめるが、`/callapi` に入口のないポストバックとスタンプは目視と手で起こした期待値に頼る
- **Discord の再接続**: `/healthz` の対象外。長期の切断は journald でしか気づけない。問題になったら Discord のゲートウェイ接続状態を `/healthz` に含める
