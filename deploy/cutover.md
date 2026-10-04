# 切替前検証・カットオーバー・ロールバック

[setup.md](setup.md) が完了し、`main` の最新が VM で動いている状態から始める。人間が画面で操作する分（LINE Developers、外形監視、Heroku の解約、Netlify）は [human-steps.md](human-steps.md) に画面ごとの手順としてまとめてある。

記法: `[Mac]` は手元の Mac で、`[VM]` は VM に SSH した上で実行する。`<host>` は Caddy が受けるホスト名。

## A. 切替前の検証（準備 1 件＋13 項目）

### 0. Java との突き合わせ（ゴールデン）を採る

`tests/golden/line_callapi.json` がまだないので、`tests/test_line_golden.py` の比較は skip している。切替前に必ず採る。本番（Heroku）の `/callapi` は使わない（入力列が村を十数個作り、上限 50 件の FIFO で遊んでいる人の村を押し出す）。

```bash
[Mac] brew install --cask temurin@8          # 本番の LineBot と同じ Java 8
[Mac] LINE_BOT_CHANNEL_TOKEN=golden LINE_BOT_CHANNEL_SECRET=golden java -jar ~/git/LineBot/insider-game-bot/build/libs/insider-game-bot-2.7.0-SNAPSHOT.jar --server.port=18080
[Mac] uv run python -m tests.line_golden http://127.0.0.1:18080/callapi    # 別ターミナル
[Mac] uv run pytest tests/test_line_golden.py -v
```

期待: `test_python_answers_line_exactly_like_the_java_linebot` が skip ではなく PASS。差があれば伏せ方（村なしの判定・候補の altText・席番号の置換・古い fixture の検出）か Python 側を直す。採ったら docs/spec.md と README の「まだ採っていないあいだは skip」の文を直し、JSON と一緒にコミットする。jar がなければ `(cd ~/git/LineBot && ./gradlew --no-daemon :insider-game-bot:bootJar)` で作る。

### 準備: 返信をスタブへ向ける

切替前は LINE へ実際に送らず、返信内容をスタブで読む。

```bash
[Mac] scp deploy/verify/line_api_stub.py ubuntu@<IP>:/tmp/
[VM]  echo 'LINE_API_BASE_URL=http://127.0.0.1:18080' | sudo tee -a /etc/insider.env > /dev/null
[VM]  sudo systemctl restart insider-web
[VM]  python3 /tmp/line_api_stub.py 18080     # 別ターミナルで開いたままにする
```

`[Mac]` 側では次を済ませておく（`read -rs` は入力を表示せず、履歴にも値が残らない）:

```bash
[Mac] export B=https://<host>
[Mac] read -rs LINE_CHANNEL_SECRET && export LINE_CHANNEL_SECRET    # チャネルシークレットを貼って Enter
```

### 1. Caddy 経由の署名付き `/line/callback` で通常村の一連の操作

```bash
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" text Uverify01 'お題'
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" text Uverify01 'すいか'
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" text Uverify01 '3'
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" text Uverify02 '<村番号>'     # スタブに出た 4 桁
[Mac] for c in '@取得' '@配布' '@特殊' '@逆村' '@わーわーず'; do uv run python deploy/verify/post_callback.py "$B/line/callback" text Uverify01 "$c"; done
```

期待: すべて `status=200`。スタブ側に届いた返信が [docs/village.md](../docs/village.md) の文面どおり（村作成の案内、お題設定の確認、人数設定の確認、参加時の役職、各 `@` コマンドの応答）。

### 2. ポストバックとスタンプ

```bash
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" text Uverify01 '@取得'
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" postback Uverify01 '0'
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" sticker Uverify01
```

期待: `status=200`。スタブに、ポストバック `0` の応答（お題候補）と、スタンプへの製作者情報（ホームページが `https://<host>`）が届く。

### 3. 不正署名の拒否

```bash
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" text Uverify01 'お題' --bad-signature
```

期待: `status=400`。スタブに何も届かない。

### 4. `/line/callback` の所要時間

```bash
[Mac] for i in 1 2 3 4 5 6 7 8 9 10; do uv run python deploy/verify/post_callback.py "$B/line/callback" text "Utiming$i" 'お題'; done
```

期待: `elapsed_ms` が **すべて 500 ms 未満**（LINE の 2 秒制限に対して 4 倍以上のマージン。webhook は返信を待たず 200 を先に返す）。数値を下の記録表に残す。

### 5. Web と LINE の村の共有

ブラウザで `https://<host>/village/new` を開き、特殊村（または通常村）を作る。LINE 側からその番号で入る:

```bash
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" text Uverify03 '<Web で作った村番号>'
[Mac] uv run python deploy/verify/post_callback.py "$B/line/callback" text Uverify03 '@配布'
```

期待: スタブに参加の応答（特殊村ならメッセージ、通常村なら役職）が届き、Web の画面の配布状況に 1 人増える。これが Web と LINE が同じ中核を共有していることを確かめる唯一の経路。

### 6. レート制限と本文上限

レート制限の窓は 1 分で、鍵は接続元 IP。1〜5 で消費した枠が残っているので、**計測の前に 60 秒空ける**。本文上限の確認はレート制限の枠を使い切る前に行う（使い切った後は本文の判定に到達せず 429 になる）。

```bash
[Mac] sleep 60
[Mac] curl -s -o /dev/null -w '%{http_code}\n' -X POST "$B/api/village/special" -H 'Content-Type: application/json' --data-binary @<(head -c 2200000 /dev/zero | tr '\0' 'a')
[VM]  sudo journalctl -u insider-web --since '-2 min' --no-pager | tail -20
[Mac] sleep 60
[Mac] bash deploy/verify/ratelimit_check.sh "$B" /api/village/special 40     # 作成系の枠 30 回/分
[Mac] sleep 60
[Mac] bash deploy/verify/ratelimit_check.sh "$B" /api/village/mine 310       # 全体の枠 300 回/分
```

期待: 2MB 超は **`413` または `502`**（Caddy の `request_body` は Content-Length で事前に弾かず、下流が本文を読んだ時点で打ち切る。reverse_proxy は読み取りエラーを 502 に丸める）。**どちらでも aiohttp には届いていない**ことを journal で確かめる: この時刻のアクセスログも例外も出ていないこと。届いていれば aiohttp 自身の `client_max_size` が 413 を返すので、413 のときは journal を見て区別する。

`ratelimit_check.sh` は、作成系が **概ね** 30 件の `400` と 10 件の `429`、全体が **概ね** 300 件の `400` と 10 件の `429`。どちらも `elapsed` が 60 秒未満であること（超えていたら計り直す）。スライディングウィンドウなので前の計測の残りで数件ずれる。**断定した件数ではなく実測値を記録表に残す。**

続けて**実際のブラウザ**で、配役ツール（`/village/new`）の村作成 → お題 → 人数 → 配布状況の 5 秒ごとの更新を 2 分ほど眺め、DevTools の Network で `429` が出ないことを確認する。同じ Wi-Fi の端末 2〜3 台で同時に開いても出ないこと。窮屈なら `deploy/Caddyfile` の `village_all` の `events` を上げ、`/etc/caddy/Caddyfile` を差し替えて `sudo systemctl reload caddy`。確定値を記録表に書く。

### 7. `/healthz` と画面

```bash
[Mac] curl -si "$B/healthz" | sed -n '1p;$p'
[Mac] for p in / /village/new /village/special /static/app.js /nothing; do printf '%s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' "$B$p"; done
```

期待: `/healthz` が `HTTP/2 200` と本文 `ok`。`/`、`/village/new`、`/village/special`、`/static/app.js` が `200`、`/nothing` が `404`。ブラウザでお題当て（`/`）のルームを作り、別の端末で入って WebSocket が Caddy 越しに張れること（押して話すで質問が届くこと）。

### 8. 停止のタイムアウト

```bash
[VM] time sudo systemctl restart insider-web
```

期待: 誰も使っていなければ数秒で終わる。90 秒（`TimeoutStopSec`）近くかかるなら、WebSocket か LINE の返信の待ちで止まっているので journal を見る。

### 9. OCI Monitoring に `MemoryUtilization` が出ていて 20% を上回る

OCI コンソール → インスタンス → Metrics → `Memory Utilization`。期待: 直近 1 時間が **25% 以上**で安定（tmpfs の 3GB / 12GB = 25%、プロセスの RSS 込みで 26〜28%）。

**合否の境目は 20%**（アイドル回収のメモリ条件を外す水準。C の監視と setup.md §13 のアラームも 20%）。**25% は memfloor の 3GB から来る期待値**。

```bash
[VM] df -h /run/insider-memfloor && free -m
```

期待: `df` の Used が `3.0G`。**指標が tmpfs を数えていない（20% 未満）ときは、プロセスで確保する差し替えに切り替えて 30 分後にもう一度見る:**

```bash
[VM] sudo systemctl disable --now insider-memfloor
[Mac] scp deploy/insider-memfloor-process.service ubuntu@<IP>:/tmp/
[VM]  sudo install -o root -g root -m 0644 /tmp/insider-memfloor-process.service /etc/systemd/system/
[VM]  sudo systemctl daemon-reload && sudo systemctl enable --now insider-memfloor-process
[VM]  ps -o rss= -C python3 | awk '{s+=$1} END {printf "%.1f GB\n", s/1024/1024}'
```

期待: `3.0 GB` 以上。それでも 20% を下回る、または指標が出ていなければ、この対策は無いものとして扱い、E の PAYG 判断へ進む。どちらのユニットを使ったかを記録表に書き、[docs/infra.md](../docs/infra.md) の memfloor の節を実測に合わせて直す。

### 10. `systemctl restart` 後の自動復帰

```bash
[VM] sudo systemctl restart insider-web insider-bot
[VM] deadline=$((SECONDS + 60)); while [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/healthz)" != 200 ] && [ "$SECONDS" -lt "$deadline" ]; do sleep 2; done
[VM] curl -s http://127.0.0.1:8080/healthz; echo; systemctl is-active insider-bot
```

期待: `ok` と `active`。更新スクリプトと同じ「2 秒間隔で最長 60 秒」で待つ。

### 11. VM 再起動後の自動起動

```bash
[VM] sudo reboot
[Mac] sleep 90; curl -s "$B/healthz"; echo
[VM] systemctl is-active insider-web insider-bot caddy insider-memfloor     # A-9 でプロセス方式に替えたなら insider-memfloor-process
```

期待: `ok`、4 つとも `active`（tmpfs の memfloor は oneshot なので `systemctl status` では `active (exited)`）。

### 12. デプロイのヘルスチェック失敗時に直前の世代へ戻る

VM 上で壊れた世代を直接置いて更新スクリプトを呼ぶ。稼働中の世代を複製し、Web の起動だけを壊す（`uv sync` と、再起動の前の import の確認は通るので、ヘルスチェックでの復旧を確かめられる。壊す行を `if __name__ == "__main__":` の下に置くのはそのため）。

```bash
[VM] sudo -u insider bash -c '
  set -e
  fake=0000000000000000000000000000000000000000
  work=$(mktemp -d)
  tar -C /opt/insider/current --exclude=.venv --exclude=insider.tar.gz.sha256 -czf - . | tar -xzf - -C "$work"
  printf "if __name__ == \"__main__\":\n    raise SystemExit(\"broken release for the cutover test\")\n" > "$work/src/insider_bot/web/__main__.py"
  mkdir -p /opt/insider/incoming/$fake
  tar -C "$work" -czf /opt/insider/incoming/$fake/insider.tar.gz .
  (cd /opt/insider/incoming/$fake && sha256sum insider.tar.gz > insider.tar.gz.sha256)
  rm -rf "$work"'
[VM] sudo /usr/local/bin/insider-release.sh 0000000000000000000000000000000000000000; echo "exit=$?"
[VM] readlink /opt/insider/current; curl -s http://127.0.0.1:8080/healthz; echo
```

期待: `rolling back to ...` のログ、`exit=1`、`current` が元の commit の世代を指し、`/healthz` が `ok`。restart から戻しの判断まで 60 秒強で終わる。後始末: `sudo rm -rf /opt/insider/releases/0000000000000000000000000000000000000000`。偽 SHA が 40 桁の hex なのは、更新スクリプトが revision の形を検証していて、それ以外は何もせず終了コード 2 で拒否するため。

### 13. 古い commit の run を re-run すると deploy が skip する

GitHub Actions で `main` の 1 つ前の commit の run を `gh run rerun <run-id>` し、deploy job のログに `skipping deploy of` が出て成功終了することを確認する。

### 後始末: スタブを外す

```bash
[VM] sudo sed -i '/^LINE_API_BASE_URL=/d' /etc/insider.env
[VM] sudo systemctl restart insider-web
[VM] deadline=$((SECONDS + 60)); while [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/healthz)" != 200 ] && [ "$SECONDS" -lt "$deadline" ]; do sleep 2; done
[VM] curl -s http://127.0.0.1:8080/healthz; echo
[VM] sudo grep -c LINE_API_BASE_URL /etc/insider.env
```

期待: `ok`、`grep -c` が `0`。journal の起動ログに `返信先 https://api.line.me` と出る。

### 記録表

| 項目 | 実測値 | 日付 |
| --- | --- | --- |
| 0. ゴールデン比較 | PASS / 差の内容 | |
| 4. `/line/callback` の所要時間（10 回の最大） | ms | |
| 6. レート制限（作成系と全体それぞれの 400 / 429 の件数、elapsed） | | |
| 6. 本文上限の応答コード | 413 / 502 | |
| 9. MemoryUtilization | %（tmpfs / プロセス のどちらか） | |
| 12. 自動復旧 | rolling back / exit=1 | |

## B. カットオーバー

**戻せる最後の地点。** 切替対象は **LINE Developers の Webhook URL だけ**。Netlify の特殊村フォームは接続先を Heroku のまま残す（Web 版に特殊村フォームを取り込んであるので切り替えない。ロールバック時に特殊村が成立する状態を保つ）。

1. A の準備 1 件と 13 項目がすべて通り、スタブが外れている（`sudo grep -c LINE_API_BASE_URL /etc/insider.env` が `0`）
2. **プレイヤー不在の時間帯**を選ぶ（進行中の村は切替の瞬間に消える）
3. LINE Developers コンソール → 対象のチャネル → Messaging API 設定 → **Webhook URL** を `https://<host>/line/callback` に更新 → **「検証」で成功**を確認 → 「Webhook の利用」が ON であることを確認。**Webhook の再送はオフのまま**（重複排除はしていない。Java も同じ）
4. 実機で確認する:
   1. 自分の LINE から `お題` → お題を設定 → 人数を設定
   2. **別アカウント**でその村番号を送り、役職が届く
   3. `@わーわーず` で Werewords も一通り
   4. **Web（`https://<host>/village/new`）で特殊村を作る → LINE からその番号で参加 → `@配布`**。Web と LINE の村の共有を本物の LINE で確かめる唯一の経路なので飛ばさない
5. 切替日と Heroku 解約予定日（切替日＋1 か月）を human-steps.md の記録表に書く

## C. 1 か月の様子見

最初の 1 週間は毎日、以降は週 1 回。

| 見るもの | どこで | 期待 |
| --- | --- | --- |
| メモリ指標 | OCI → Instances → 対象 → Metrics → Memory Utilization | **20% を上回っている** |
| アイドル判定のメール | 自分のメール | **届いていない** |
| 外形監視の失敗通知 | 自分のメール | **届いていない** |
| アプリのログ | 下のコマンド 1 | 想定外のものがない（LINE の返信の失敗、Jev のタイムアウトの頻発がない） |
| Discord の接続 | 下のコマンド 2 | 長期の切断がない（`/healthz` は Discord を含まない） |

```bash
[VM] sudo journalctl -u insider-web -u insider-bot --since '-7 days' --no-pager | grep -E 'WARNING|ERROR|CRITICAL'    # 1. アプリのログ
[VM] sudo journalctl -u insider-bot --since '-7 days' --no-pager | grep -iE 'disconnect|resum'                     # 2. Discord の接続
```

**Oracle からアイドル判定のメールが届いた場合**: 即削除ではなく、**1 週間後に停止**という猶予付きの通知。その 1 週間のうちに E の「PAYG へ上げる」を判断する。

## D. ロールバック（Heroku へ戻す）

**破壊的操作。** OCI 上で作られた村はすべて消える。Heroku 側に切替前の古い村が残っていると番号が混乱するので、**Heroku の再起動を先に**行う。VM は止めず、原因を調べられる状態を残す。

```bash
[Mac] heroku restart -a insidergamehelper
[Mac] sleep 60; curl -s 'https://insidergamehelper.herokuapp.com/callapi?message=%E3%81%8A%E9%A1%8C&userId=rollback-check'
```

期待: Heroku が 4 桁の村番号を返す（この確認で作った村は 1 つだけなので FIFO への影響は小さい）。

1. プレイヤーがいないことを確認する（やむを得ず進行中に戻すなら、村が失われることを先に告知する）
2. 上の再起動と確認
3. LINE Developers コンソールの Webhook URL を Heroku のもの（`https://insidergamehelper.herokuapp.com/callback`）へ戻し、「検証」で成功を確認する
4. 実機で `お題` が返ることを確認する
5. Netlify フォームは切替で触っていないので戻す作業はない

Heroku は切替後 1 か月維持する。

## E. PAYG へ上げる（アイドル通知が来たとき）

Always Free のまま回収を避けられないと判断したら、OCI コンソールでアカウントを Pay As You Go に上げる。無料枠の範囲なら請求は $0 のままで、回収の対象から外れる。同時に **Budgets で $1 超過のメール通知**を設定する（[human-steps.md](human-steps.md) の別枠）。上げた日と理由を記録表に書き、[docs/infra.md](../docs/infra.md) の memfloor の節を直す。
