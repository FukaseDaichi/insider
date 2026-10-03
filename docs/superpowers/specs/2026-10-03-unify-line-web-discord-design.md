# LINE・Web・Discord を 1 つのシステムに統合し Oracle Cloud へ移す設計

## 背景と目的

いま、仲間内で遊ぶゲームの道具が 2 つのリポジトリに分かれている。

| | insider（このリポジトリ） | LineBot |
|---|---|---|
| 言語 | Python（uv / aiohttp / asyncio） | Java 8（Spring Boot 2.1.5、同梱の LINE SDK） |
| 役割 | お題当てゲーム。Jev が GM 役で はい／いいえ を返す。Discord 版と Web 版 | インサイダーゲームと Werewords の配役を LINE の 1 対 1 トークで配る |
| 稼働 | 遊ぶときだけ Mac で起動し Tailscale Funnel で公開 | Heroku Eco（$5/月）。Oracle Cloud 移行の設計・実装・手順書は完成済みだが、A1 の在庫待ちで VM 未取得 |

**この設計は、LineBot の Java を廃止し、insider が LINE・Web・Discord の 3 つの入口を持つ 1 つのシステムになる形を定める。** 村の配役という中核を Python に移し、LINE Bot の機能を「全く同じ」に保ったまま Web 版からも使えるようにし、最終的に Oracle Cloud Always Free の VM 1 台で動かす。

### 範囲

- 村の中核（通常村・神モード・逆村・ランダム村・特殊村・Werewords、お題辞書、役職画像）の Python への移植
- Web 版の **配役ツール**: 村を作る、番号で入って自分の役職を見る、特殊村を作る（Netlify の外部フォームの置き換え）
- LINE アダプタ: webhook の受信、署名検証、返信 API、テンプレートの組み立て
- Oracle Cloud への移行: VM 1 台、Caddy、systemd、CI からの配備、Heroku からの 1 回の切替
- LineBot リポジトリと Netlify フォームの後片付け

### 範囲外

- Jev のお題当てルームに役職・タイマー・投票を混ぜること（次の段階。参加者の識別子の形だけ揃えておく）
- 村の永続化（両リポジトリ共通の「状態を持たない」原則を保つ）
- 認証の導入（LINE 版と同じく「番号を知る人が入る」前提）
- `/callapi` と `/specialvillage` の移植（Netlify フォームを Web 版に取り込むので不要になる）
- Discord への配役機能の追加

## 全体構成

```
                  Caddy（TLS 終端、独自ドメインの 1 ホスト名）
                             │ 127.0.0.1:8080
   ┌─────────────────────────▼─────────────────────────┐   ┌─────────────────────┐
   │ insider-web.service（aiohttp 1 プロセス）           │   │ insider-bot.service │
   │   /               お題当て Web 版（既存）           │   │   Discord ボット（既存）│
   │   /village/…      配役ツール（新）                 │   │   村の状態は持たない   │
   │   /api/village/…  配役ツールの API（新）           │   └─────────────────────┘
   │   /line/callback  LINE webhook（新）               │
   │   /healthz        ヘルスチェック（新）             │
   │   ── 中核 ──  GameService（Jev）   VillageService   │
   └───────────────────────────────────────────────────┘
```

### 設計判断

- **Web と LINE は同じプロセス。** 村のレジストリはメモリにしかないので、「LINE で作った村に Web から入る」を成立させる唯一の形である。永続化しない原則を保ったまま入口を増やせる。
- **Discord は別プロセスのまま。** 村の状態を使わないので、片方の不具合がもう片方に及ばないという既存の判断をそのまま残す。
- **お題当ての中核（`GameService`）と村の中核（`VillageService`）は結合しない。** 同じプロセスにいるが互いを知らない。将来 Jev ルームに配役を混ぜるときは、両方を知る進行役（`RoomHub` 相当）を足す。
- **リポジトリは insider 1 つ。** パッケージ名 `insider_bot` は変えない（名前の変更は差分を増やすだけで、動作に寄与しない）。`village/` と `line/` のサブパッケージを足す。
- **Oracle Cloud は A1 を 1 台。** Always Free の枠（1,500 OCPU 時間／月）は A1 を 2 台並べた瞬間に超える。LineBot 設計がすでに確かめた制約で、同居は好みではなく枠の帰結である。

## 村の中核（`insider_bot/village/`）

### モジュール

| モジュール | 役割 | Java での対応 |
|---|---|---|
| `model.py` | 通常村と特殊村の状態、不変条件、席による配役 | `Village`、`SpecialVillage`、`InsiderRole` |
| `registry.py` | 採番（4 桁 1000〜9999、5 桁 10000〜99998）、上限（50 件／30 件）で古い村から FIFO で削除、所有者の最新の村の検索 | `VillageRegistry`、`SpecialVillageRegistry` |
| `words.py` | お題辞書 CSV の読み込み、難易度区間の導出、不正な辞書の破棄 | `WordGetter` |
| `werewords.py` | 占師・インサイダー・村人の役職列と「欠け」の生成 | `CreateWereWordsLogic`、`CommonSubLogic` |
| `illust.py` | 役職画像。同梱の既定画像と、任意の外部カタログからの重み付き抽選 | `CommonModule`、`IllustrationCatalogJob` |
| `service.py` | 構造化操作: 作成（通常／神／ランダム）、人数設定、お題設定、逆村化、Werewords 変換、参加、入室状況、特殊村の作成と参加 | `VillageService`、`CreateVillage` |
| `commands.py` | テキストの解釈: 数値の境界、コマンド表、お題の自動取得の候補 | `TextCommandHandler` |
| `texts.py` | 文言 | `MessageConst` |
| `reply.py` | 経路中立の返事モデル | （LINE SDK の `Message` を置き換える） |

Java の `game-spec.md` と `interfaces.md` の LINE 部分を `docs/village.md` に移植し、村の外部仕様の契約とする。入力と応答の対応、数値の解釈（100 以下は人数、101〜999 は該当なしの村番号、1000〜9999 は通常村、10000 以上は特殊村）、配役の決まり方（人数確定時に席を抽選）、村の消滅条件は、そこに書かれたとおりに動く。

### 返事モデル

中核は LINE の JSON ではなく、次のデータを返す。

```
Text(text)
Image(url)
Buttons(text, actions, image=None, title=None, overflow=())
Confirm(text, actions)

MessageAction(label, text)      # 押すと text を送信したことになる
PostbackAction(label, data)     # 押すと data が postback で届く
UriAction(label, uri)
```

- 操作の戻り値は `list[Reply] | None`。`None` は「対象の村がない」で、Java と同じく**エラーではなく通常の結果**として扱う。経路ごとの既定応答（LINE は「村の作成をしますか？」の確認テンプレート、Web は案内文）への変換は入口が行う。
- `Buttons.overflow` は、表示側が本文を文字数に収められないときに代わりに出す返事の列。Java が「画像つきなら 60 文字、画像なしなら 160 文字を超えたら Text＋入室状況の 2 通に落とす」としていた分岐を、**中核が意図（本体と代替）を返し、LINE レンダラが判断する**形に置き換える。Web は制限がないので常に本体を描く。
- LINE 固有の形（サムネイルなし・タイトルなしのボタン、`altText`）は返事モデルに現れない。LINE レンダラが `image` と `title` の有無から選ぶ。

### 並行性

asyncio は 1 スレッドなので Java の `synchronized` は不要。代わりに、**中核の 1 操作の途中で `await` を挟まない**（既存 Web 版の `RoomHub` と同じ規律）。人数確定と配役抽選、お題設定、逆村化、参加（席の確保と配役）、採番と登録は、それぞれ同期関数 1 つで完結する。中核に Jev のような外部待ちはない。

### 識別子

参加者は不透明な文字列で識別する。`line:<LINE ユーザー ID>`、`web:<ブラウザのトークン>`。村側は接頭辞を解釈しない。LINE と Web の同一人物は紐づけない（別人として扱う。配役ツールでは本人が村番号を 2 回入れない限り問題にならない）。

### 役職画像

- 既定画像 4 枚（INSIDER / VILLAGERS / GM / GOD）と友だち追加用の QR 画像を `web/static/roles/` に同梱し、自前のドメインから配信する。LineBot リポジトリの `raw.githubusercontent.com` への依存を断ち、LineBot をアーカイブできるようにする。
- LINE はテンプレートの画像を HTTPS で公開された URL でしか受け取れないので、URL は `PUBLIC_BASE_URL` から組み立てる。
- `ILLUSTRATION_CATALOG_URL` を設定したときだけ、Google Apps Script のカタログを 5 分ごとに取り直して重み付きで抽選する。失敗時は前回分、一度も取れていなければ既定画像。未設定なら取りに行かない。

### お題辞書

`word.csv`（8,436 語、1 列目がお題、2 列目が難易度 1〜5）をパッケージのリソースとして同梱し、起動時に 1 度だけ読む。難易度の区間は 2 列目から導出する。難易度が読めない行、昇順を破る行、語のない難易度があれば辞書全体を破棄し、ERROR ログを出し、お題の抽選は `None` を返す。Java と同じく、破棄したことは利用者には見えない（「お題は『None』です」のように応答に現れる）。これは Java の挙動を保つための判断で、辞書は CI のテストで読めることを確かめる。

## LINE アダプタ（`insider_bot/line/`）

### 公式 SDK を使わない

必要なのは 3 つだけである。

1. **署名検証**: 本文の bytes に対する HMAC-SHA256 をチャネルシークレットで計算し、Base64 にして `X-Line-Signature` と定数時間で比較する
2. **返信 API**: `POST https://api.line.me/v2/bot/message/reply` に Bearer トークンで `{"replyToken", "messages"}` を送る。1 返信 5 通まで。httpx はすでに依存にある
3. **レンダラ**: 返事モデル → LINE のメッセージ JSON

LineBot は同梱 SDK のモデルに手を入れて、サムネイルやタイトルを省いたボタンテンプレートを作っていた。JSON を自分で組み立てるほうがその形を確実に再現でき、依存も増えない。

### webhook（`POST /line/callback`）

- 本文を bytes で読み、署名を検証してから JSON として解釈する。署名が合わなければ 400（Java の SDK と同じ）。
- イベントごとに分岐する。

| イベント | 動作 |
|---|---|
| テキスト | `source.userId` がなければ「1 対 1 のトークから操作してください」。あれば `commands.handle(f"line:{userId}", text)` |
| ポストバック | `data` が 0〜9 ならお題候補（userId 不要）。10〜9999 なら通常村の入室状況、10000 以上なら特殊村の入室状況（userId が必要）。数値でなければ既定応答 |
| スタンプ | 製作者情報（ご意見フォームとホームページへの `UriAction`） |
| それ以外 | 種別だけ DEBUG ログ。返信しない |

- **返信は待たない。** `asyncio.create_task` で送り、webhook は 200 を即座に返す。LINE は 2 秒以内の応答を求め、返信 API の所要時間はこちらで制御できない。送信の失敗は WARNING ログだけで、再試行しない（replyToken は 1 回限りで短命）。利用者はもう一度送れば同じ応答を受け取れる。
- **イベント本文はログに出さない。** 本文には LINE ユーザー ID とお題（ゲームの答え）が含まれる。記録するのはイベント種別と処理結果まで。
- 返信 API のタイムアウトは 10 秒。

### URL の差し替え

- `@特殊` の案内先は Netlify の URL から `PUBLIC_BASE_URL + /village/special` に変わる
- スタンプ応答のホームページも `PUBLIC_BASE_URL` に変わる。ご意見フォーム（Google フォーム）の URL は変えない

### 提供しないもの

`/callapi` と `/specialvillage`。無認証で `userId` を名乗れる状態変更 API であり、Netlify フォームを Web 版に取り込めば呼び出し元がなくなる。

## Web の配役ツール（`/village/…`）

### 画面

トップページに「お題当て」と「インサイダーの配役」の 2 つの入口を置く。既存のダーク＋ライムのデザイン、`textContent` のみで描く規律、44px 以上の操作対象、`prefers-reduced-motion` の尊重を踏襲する。

| 画面 | 内容 |
|---|---|
| 村を作る | 種類（通常／神／ランダム）→ お題（手入力、または辞書から「初心者／上級者／変態」で引き直し。ランダム村は聞かない）→ 人数 → 村番号と配布状況。逆村への切替と Werewords 変換もここから |
| 村に入る | 番号を入れる、または `/v/<番号>` を開く（QR は既存の部品で表示・読み取り）→ 役職カード（画像、何番目か、入室状況）。再表示できる |
| 特殊村を作る | メッセージを 1 行 1 通で入力（1〜100 通、各 5,000 文字まで）→ 5 桁の番号。Netlify フォームの置き換え |

配布状況は「再確認」ボタンと数秒間隔の自動更新で足りる。WebSocket は使わない（お題当てルームの進行役とは要件が違い、1 秒を争わない）。

### 識別

ブラウザがトークンを localStorage に持ち、初回に生成する。API には `web:<トークン>` として渡す。トークンを知る人だけがその「人」として振る舞えるので、URL やログに出さない。

### API（`/api/village/…`）

- `POST` の JSON で中核の構造化操作を 1 対 1 で呼ぶ。応答は返事モデルの JSON で、画面側の `reply.js` が描く。
- 「対象の村がない」は 200 で案内文（LINE の既定応答に相当）。入力不正は 400。
- CORS は同一オリジンのみ。Netlify 廃止で外部からの呼び出しがなくなる。
- 文言は中核の `texts.py` をそのまま出す。LINE と「全く同じ」に揃えるため、Web だけ言い回しを変えない。

### セキュリティ

認証はしない。無認証の作成を繰り返して進行中の村を追い出せる既知の問題は LINE 版から引き継ぐ。Caddy のレート制限（LineBot 設計の流用）で 1 IP からの追い出しを遅らせるが、防ぎはしない。解消には認証の導入が必要で、範囲外とする。

## インフラ

LineBot で確定済みの前提を引き継ぐ: VM.Standard.A1.Flex 2 OCPU / 12GB、ap-tokyo-1、Ubuntu 24.04、ブート 50GB、独自ドメイン（Cloudflare なら Proxy OFF）、Caddy による TLS 終端、systemd、journald の上限 200MB、security list と OS の iptables の両方で 80/443 を開放、SSH は公開鍵のみ。Oracle の無料枠を「契約」ではなく「予告なく変わる好意」として扱い、VM は失われ得るものとして再作成手順と秘密情報の復元手段を持つ、という姿勢も変えない。

### LineBot 設計からの変更点

| 項目 | LineBot 設計 | 本設計 |
|---|---|---|
| ホスト名 | `bot.<domain>` | `<短い名前>.<domain>` 1 つ。Web 版の URL を兼ねる |
| Caddy が流すパス | 4 パスだけ、他は 404 | `/line/callback` は制限なし（署名あり）。`/api/village/*` は IP ごと 30 回／分。それ以外（画面、静的ファイル、お題当ての WebSocket）はそのまま。本文上限 2MB は踏襲 |
| プロセス | Java 1 本 | `insider-web.service`（Web＋LINE）と `insider-bot.service`（Discord） |
| ランタイム | Temurin 8 を `/opt/java` に手置き | uv が `.python-version` の Python を取得・固定する。apt の Python に依存しない |
| 公開 | Caddy | Caddy。**Tailscale Funnel は本番で使わない。** Mac でのローカル遊び（`scripts/play.sh`）にだけ残す |
| 外向き通信 | api.line.me、script.google.com | ＋ api.typesafe.ai（Jev）、Discord ゲートウェイ |
| アイドル回収対策 | JVM の `-Xms3g -XX:+AlwaysPreTouch` | `memfloor` ユニット（下記） |

### systemd ユニット

- 専用の非 root ユーザー `insider`。`EnvironmentFile=/etc/insider.env`（root:root 0600）。
- `insider-web.service`: `/opt/insider/current/.venv/bin/python -m insider_bot.web`。待ち受けは `127.0.0.1:8080` のみ。
- `insider-bot.service`: `/opt/insider/current/.venv/bin/python -m insider_bot`。
- どちらも `Restart=always`、`NoNewPrivileges`、`PrivateTmp`、`ProtectSystem=full`、`ProtectHome`。
- 既存の `deploy/setup.sh` と `deploy/*.service` は「clone したディレクトリで通常ユーザーとして動かす」前提で書かれており、1GB の VM 向けのスワップ設定も含む。OCI 向けには `/opt/insider/releases/<sha>/` と `current` のシンボリックリンクを前提に書き直す。

### アイドル回収のメモリ床（`memfloor`）

Always Free の A1 は、7 日間 CPU・ネットワーク・メモリの 3 つすべてが 20% 未満だと回収の通知が来る。このシステムの CPU とネットワークは届かないので、外せるのはメモリ条件だけである。Java は `-Xms3g` でヒープを実際に触って RSS を 3GB にしていたが、Python のプロセスにその大きさはない。

代わりに、起動時に 3GB の tmpfs を確保して埋める systemd ユニットを置く。コードに依存せず、アプリの大きさと無関係に床を保てる。

- **OCI の `MemoryUtilization` が tmpfs を「使用中」として数えるかは、切替前の検証で実測する。** 数えなければ、プロセスとして 3GB を確保して眠るだけの小さなユニットに差し替える。それでも 20% を下回るなら、Java 設計と同じく PAYG へのアップグレードで回収対象から外す。
- これは設計上の成立であって保証ではない。回収の通知が届いたら、猶予の 1 週間のうちに PAYG へ上げ、OCI Budget で $1 超過のメール通知を設定する。

### 監視

- OCI Alarm 2 本: `MemoryUtilization` が 20% 未満（Trigger delay 30 分）、および指標が欠測（Absent）。通知先はメール。
- 外形監視: `GET https://<host>/healthz` を 5 分ごと、本文のキーワードで判定する無料サービス。
- `/healthz` は Web プロセスが HTTP を受け付けていることだけを示す。Discord の生死は journald で見る（Discord の切断は discord.py が再接続するので、ヘルスチェックの対象にしない）。

### 秘密情報

`/etc/insider.env` に `DISCORD_TOKEN`、`TYPESAFE_API_KEY`、`LINE_CHANNEL_TOKEN`、`LINE_CHANNEL_SECRET`、`PUBLIC_BASE_URL`、任意で `ILLUSTRATION_CATALOG_URL`、`LINE_API_BASE_URL`（切替前の検証でスタブへ向けるときだけ）。値はパスワードマネージャに保管し、VM の再作成時はそこから復元する。GitHub Secrets には `DEPLOY_HOST`、`DEPLOY_SSH_KEY`、`DEPLOY_HOST_KEY` の 3 つだけを置く。

## デプロイ

LineBot の「検証 → 原子的昇格 → 再起動 → ヘルスチェック → 自動復旧」を Python 向けに移植する。

1. **CI（`build`）**: `uv sync` → pytest → node のテスト → リポジトリをその SHA で tar に固め、sha256 を添えて成果物にする
2. **CI（`deploy`、main への push のみ）**: `concurrency` で直列化（`cancel-in-progress: false`）。排他を取った後に `git ls-remote` で main の最新 SHA を確認し、違えば何もせず成功終了。ホスト鍵を固定した SSH で `/opt/insider/releases/<sha>/` へ転送
3. **VM 上の更新スクリプト（`flock`）**: sha256 検証 → 展開先で `uv sync --frozen --no-dev` → `current` のシンボリックリンクを新しい世代へ差し替え → 2 ユニットを再起動 → `/healthz` を 2 秒間隔で最長 60 秒ポーリング → 失敗なら `previous` に戻して再起動し同じ契約で再確認、それでも通らなければ停止して job を落とす。世代は 5 つ残す
4. 再起動で進行中のルームと村は消える。利用者が少ないので受け入れる（両リポジトリとも同じ判断）。手動の承認ステップは設けない

## カットオーバーとロールバック

### 切替は 1 回

Heroku の Java は Python 版が検証を通るまで触らない。切替対象は **LINE Developers の Webhook URL だけ**である。LineBot 設計では Netlify フォームの接続先も同時に切り替える必要があったが、本設計ではフォームを Web 版に取り込むので、フォームは切り替えない。

1. Python 版を OCI に配備し、切替前検証（後述）をすべて通す。LINE の返信はスタブに向けて内容を読む
2. `/etc/insider.env` から `LINE_API_BASE_URL` を消して再起動する
3. プレイヤー不在の時間帯に、Webhook URL を `https://<host>/line/callback` へ切り替え、コンソールの「検証」で成功を確認する
4. 実機で確認する: 通常村を作り別アカウントで参加、`@わーわーず`、**Web で特殊村を作る → LINE からその番号で参加 → `@配布`**。最後の 1 つが Web と LINE の村の共有を確かめる唯一の経路
5. **Netlify フォームは切替時に触らない。** 接続先を Heroku のまま残し、ロールバック時に特殊村が成立する状態を保つ
6. 1 か月の様子見: メモリ指標が 20% を上回る、回収のメールが来ない、外形監視の失敗通知が来ない、journald に想定外の WARN／ERROR がない
7. Heroku アプリの削除と、**Eco dynos の Unsubscribe**（アプリを消しただけでは $5 が止まらない）。同時に Netlify フォームを「移転しました」の案内（新 URL へのリンク）に差し替える
8. LineBot リポジトリをアーカイブする。README に移転先を書く。役職画像は insider に移転済みなので、アーカイブしても利用者に影響しない

### ロールバック

Webhook URL を Heroku のものへ戻すだけ。Heroku は切替後 1 か月維持する。OCI 上で作られた村はすべて消え、Heroku 側に切替前の古い村が残っていると番号が混乱するので、**戻す前に Heroku を再起動する**。VM は止めず、原因を調べられる状態を残す。

## テスト

- **契約**: `docs/village.md`（Java の `game-spec.md` と `interfaces.md` の LINE 部分の移植）
- **中核**: Java のテスト（`VillageTest`、`VillageServiceTest`、`VillageRegistryTest`、`WordGetterTest`、`CreateWereWordsLogicTest`、`SpecialVillageTest`）を pytest に移植する。乱数は注入して決定的にする。辞書は実物の `word.csv` が読めることと、壊した辞書が破棄されることの両方を確かめる
- **経路の一致**: Java の `RouteParityTest` に相当するものとして、テキスト解釈（`commands.handle`）と構造化操作（`service`）が同じ返事モデルを返すことを固定する。LINE レンダラの JSON と Web の JSON が同じ返事モデルから作られることも確かめる
- **Java との突き合わせ（ゴールデン）**: 切替前に、Heroku で動いている Java の `/callapi` へ同じ入力列（村の作成、お題、人数、参加、各 `@` コマンド、既定応答、お題候補）を送って JSON を採取し、Python の LINE レンダラの出力と比較する。村番号・配役・画像の抽選はランダムなので、それらを正規化して比べる。「全く同じ」を主観ではなく機械で確かめる手段である。ポストバックとスタンプは `/callapi` に入口がないので、Java の `LineEventHandlerPostbackTest` と `StickerReplyEvent` のコードから期待値を起こす
- **LINE アダプタ**: 署名検証（正しい署名、不正な署名、本文の改ざん）、イベントの分岐、userId なしの拒否、返信を待たずに 200 を返すこと、返信の失敗がログに留まること、ログに本文が出ないこと
- **Web**: aiohttp のテストクライアントで `/api/village/*` の各操作と入力不正。node で `reply.js` の描画（既存の `tests/js/` と同じ方式）
- **切替前検証**: LineBot の `deploy/verify/`（`post_callback.py`、`line_api_stub.py`。どちらも Python）を insider に移し、検証項目を insider 向けに書き直す。Caddy 経由の署名付き `/line/callback`、スタブに届く返信の内容、不正署名の拒否、応答時間、レート制限、`/healthz`、`MemoryUtilization` の実測、再起動と VM 再起動後の自動復帰、デプロイの自動復旧、古い commit の re-run で deploy が skip すること

## ドキュメント

- `docs/village.md` を新設し、村の外部仕様と LINE の契約を置く
- `docs/spec.md` に、お題当てと配役ツールの関係（同じプロセス、結合しない）と Web の配役ツールの画面・識別・API を追記する
- `docs/infra.md` を「Oracle Cloud の 1 台で 24 時間動かす」構成に書き換え、Mac での起動はローカル遊び用として残す
- `deploy/` に OCI 向けのセットアップ手順、切替前検証、画面操作の手順書を置く。LineBot の `deploy/setup.md`、`cutover.md`、`human-steps.md` を insider 向けに書き直す
- 完了後、本設計書は docs/ 直下に蒸留して削除する（docs/AGENTS.md の運用）

## マイルストーン

| # | 内容 | 依存 |
|---|---|---|
| M1 | 村の中核の移植（返事モデル、辞書、文言、画像、テスト、`docs/village.md`）。入口にはまだつながない | なし |
| M2 | Web の配役ツール（API、画面、特殊村フォーム、画像配信、`/healthz`） | M1 |
| M3 | LINE アダプタ（署名、webhook、レンダラ、返信 API、ゴールデン比較、スタブ） | M1 |
| M4 | インフラ（手順書、Caddy、systemd、memfloor、CI からの配備） | A1 の確保。アカウント作成とドメイン取得は先に進められる |
| M5 | 切替前検証とカットオーバー | M2〜M4 |
| M6 | 後片付け（Heroku 解約、Netlify 差し替え、LineBot アーカイブ、docs の蒸留） | M5 の 1 か月後 |

M1〜M3 はコードだけで進められ、A1 の在庫に左右されない。M2 と M3 は独立なので並行できる。実装計画は M1、M2、M3、M4〜M6 の 4 本に分ける。

## 残るリスク

- **A1 の在庫**: 取れるまで切替は始まらない。LineBot 設計と同じく、取れない間は Heroku のまま運用し、一定期間試して取れなければ保留とする。M1〜M3 の成果は Mac でのローカル遊びと将来の移行にそのまま使える
- **無料枠の縮小**: 次に半減（1 OCPU / 6GB）すれば memfloor の値は見直しになるが、Python のプロセス自体は小さいので動作は続く。Java 設計より縮小に強い
- **文面の差**: ゴールデン比較で機械的に確かめるが、`/callapi` に入口のないポストバックとスタンプは目視と手で起こした期待値に頼る
- **Discord の再接続**: `/healthz` の対象外。長期の切断は journald でしか気づけない。問題になったら Discord のゲートウェイ接続状態を `/healthz` に含める
