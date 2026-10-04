# インフラ構成

Discord ボットと Web 版をどこで動かすかの結論と理由。起動の手順は [README](../README.md)。

## 結論

| | 構成 | 費用 |
|---|---|---|
| 現在 | 遊ぶときだけ手元の Mac で起動する（`scripts/play.sh`） | 0 円（電気代のみ） |
| 将来（24 時間動かすとき） | Oracle Cloud の Always Free の VM | 0 円の見込み（移行前に確かめる点がある） |
| 採らない | Google Cloud | 外部 IPv4 だけで月 約 $3.6 |

どの構成でも、TypeSafe（Jev）の利用料は別にかかる。

## 共通の方針

- Discord ボットと Web 版は別のプロセスで動かす。片方の不具合がもう片方に及ばないようにするため。どちらも外向きの通信だけで動き、受け付けのポートを開けない。
- Web 版は `127.0.0.1` で待ち受け、Tailscale Funnel で `https://<マシン名>.<tailnet名>.ts.net` として公開する。マイクに HTTPS が要るため。Funnel は無料で、URL が固定され、ドメインが要らない。
- Discord ボットは 1 か所でだけ動かす。2 か所で動くと質問に 2 回返信する。

## 現在: Mac で遊ぶときだけ起動する

- 仲間内で遊ぶゲームなので、遊ぶ間だけ動いていれば足りる。
- `scripts/play.sh` がボットと Web 版を起動し、Web 版が応答してから Funnel で公開する。Ctrl+C か、どれか 1 つが止まったときに全部を止め、公開も終える。
- 前回の公開の設定が持ち主のプロセスなしで残っていると公開できないので、起動のはじめに消す。`--bg` で常時公開している設定は消さない。
- 動いている間は `caffeinate` で Mac のスリープを防ぐ。ノートの蓋を閉じると止まる。
- 止めるとルームと進行中のゲームは消える（状態を保存しない仕様のため）。

## 将来: Oracle Cloud（Always Free）

- 公開 IPv4 と外向き通信（月 10TB）まで無料枠に入るとされ、24 時間動かしても 0 円で済む見込み。`deploy/setup.sh` と `deploy/*.service`（Ubuntu 24.04 ＋ systemd）、Funnel での公開をそのまま使える。
- 無料枠: x86 の VM.Standard.E2.1.Micro（メモリ 1GB）2 台、または Arm の A1（合計 2 OCPU・12GB）。ディスクは合計 200GB。ホームリージョンの中だけで、ホームリージョンは後から変えられない。
- 移行前に確かめること
  - 公開 IPv4 が無料か。公式の無料枠ページには記載がなく、利用者の間では無料とされている。
  - アイドルな VM の回収。7 日間、CPU（95 パーセンタイル）と通信がともに 20% 未満だと回収されうる。このボットは当てはまる。Pay As You Go に切り替えると回収されないとされる（第三者の情報）。切り替えると無料枠を超えた分は課金されるので、予算アラートを設定する。
  - カードの登録が要る。登録の審査で断られることがある。
- 手順書は移行するときに書く。

## 採らない構成

- **Google Cloud**: e2-micro と標準ディスク 30GB は無料枠だが、外部 IPv4 の無料分はアカウントあたり月 1 時間だけで、24 時間動かすと月 約 $3.6 かかる。IPv6 だけにもできない（Discord と GitHub が IPv6 に対応していない）。IPv4 なしで外に出る Cloud NAT はさらに高い。
- **AWS**: 無料なのは最初の 6 か月のクレジットだけで、その後は公開 IPv4 が Google Cloud と同じく有料。
- **スリープする無料枠（Render など）**: 一定時間使わないと止まり、常時接続の Discord ボットを動かせない。

## 出典

- [Google Cloud: VPC network pricing（外部 IP）](https://cloud.google.com/vpc/network-pricing)
- [Google Cloud: Free Program](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [Oracle Cloud: Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
