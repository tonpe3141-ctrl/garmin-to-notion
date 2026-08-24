# 毎日12:00 JST ランニングコーチ Routine — 実行手順書

このファイルは **Claude Routine（クラウドエージェント）が毎日読み込んで実行する手順書**です。
Routine のトリガー側には「このファイルを読んで、書かれているとおりに実行せよ」としか書かれていません。
**運用を変えたいときは、このファイルを編集してコミットするだけで反映されます。**

- Routine ID: `trig_01YGr4cSdLmfUgQS9iwasgQr`
- 管理画面: https://claude.ai/code/routines
- 実行時刻: 毎日 02:57 UTC（= 11:57 JST）。完了は 12:00 JST 前後。
- 実行環境: Anthropic クラウド。**ユーザーのMacの電源・スリープとは無関係に動作する。**

---

## 前提となる制約（調査済み・2026-08-21 時点）

| 項目 | 可否 | 備考 |
|------|------|------|
| Garmin API への直接アクセス | **不可** | サンドボックスの egress プロキシが `*.garmin.com` を 403 で拒否 |
| Google ドライブ読み取り | 可 | Google_Drive MCP コネクタ経由 |
| Notion 読み書き | 可 | Notion MCP コネクタ経由 |
| Artifact の発行・更新 | 可 | 固定URLへ上書き更新できる。更新前に WebFetch での既読が必須 |
| GitHub Actions の手動起動 | **不可** | GitHub App に Actions 書き込み権限がない（403） |
| リポジトリへの push / コミット | **不可** | 同上（403）。`git push` も GitHub MCP も通らない。読み取りは可 |

**したがって Garmin からのデータ取得はこの Routine の仕事ではない。**
取得は GitHub Actions（`.github/workflows/sync_garmin_to_notion.yml`、毎日 8:30 JST 前後）が担当し、
この Routine は **その結果を読んで分析・公開する**役割に徹する。
8:30 の取得が数時間遅れても 12:00 までには十分間に合うため、これまでの「いつ分析を頼めばいいか分からない」問題は解消される。

---

## 実行手順

### STEP 0 — 今日の日付を確定する

```bash
TZ=Asia/Tokyo date +"%Y-%m-%d (%a) %H:%M JST"
```

以降「今日」はこの JST の日付を指す。UTC の日付と混同しないこと。

### STEP 1 — 前提条件と分析手順を読む

**必ずこの順で2つとも読む。**

1. `docs/athlete_profile.md` — **前提条件の唯一の正。**
   目標レース・レース日・目標タイム・ペースゾーン・身体データ・ロードマップ・現状の課題・
   コーチングの基本姿勢が書かれている。
2. `docs/claude_project_running_instructions.md` — 分析手順。
   練習種別の判定基準・5軸評価・Notion登録フォーマットが書かれている。

**前提条件は絶対に他の場所から拾わない。** この手順書にも、トリガーのプロンプトにも、
昨日のダッシュボードにも、レース名や日付が書かれていることがあるが、
それらはすべて古い可能性がある。`athlete_profile.md` の内容だけを信じること。

矛盾が生じた場合の優先順位は `athlete_profile.md` > `claude_project_running_instructions.md` > この手順書。

### STEP 2 — データを取得する

Google Drive MCP の `read_file_content` で以下を読む。

- fileId: `1OnOX6UxztuNBqixW8g8-N8YljathVDJ26HboLNdQISU`（ドキュメント名「ランニングログ」）

読んだら先頭行の `最終更新: YYYY-MM-DD HH:MM JST` を必ず確認する。

- **更新日が今日** → 通常どおり進む（`sourceFresh: true`）
- **更新日が今日より前** → `sourceFresh: false` にし、`alerts` に
  「データが N 日前のものです。GitHub Actions の同期が失敗している可能性があります」を **level: "warn"** で追加する。
  分析自体は入手できている最新データで続行し、勝手に中止しない。

### STEP 3 — 前日の状態を読む（**公開済みダッシュボードから読む**）

WebFetch で固定URLを取得する。

```
WebFetch(
  url: "https://claude.ai/code/artifact/eedcbce5-cbe3-45f2-8181-4fffcd8b79c4",
  prompt: "DATA ブロックの today.date, today.verdict, today.verdictReason, tomorrow の全項目, week.totalKm を報告して"
)
```

これが**昨日の分析結果**である。特に `tomorrow`（昨日出した今日向けの指示）を確認し、
**その指示に対して実際の走りがどうだったかを、今日の評価に必ず織り込む。**
これがこの仕組みの肝で、単発の講評ではなく連続したコーチングになる部分。

> **リポジトリの `dashboard/index.html` を昨日の状態だと思わないこと。**
> このRoutineはリポジトリに書き込めない（GitHub App に権限がないため 403）。
> リポジトリのファイルは**構造のテンプレート**であり、中身のDATAは初期値のまま更新されない。
> 最新の状態は常に公開済みArtifactの側にある。
>
> なおこのWebFetchは STEP 6 の publish でも必須になる（未読のまま publish しようとすると
> 「This session hasn't viewed the latest version」で拒否される）。ここで1回読んでおけば足りる。

### STEP 4 — 分析する

`docs/claude_project_running_instructions.md` の STEP 3（コーチ分析）に従う。

1. **練習種別の判定** — 平均心拍・距離・ラップ構成・トレーニング効果から判定
2. **5軸評価** — ペース管理 / 心拍コントロール / フォーム指標 / 疲労・コンディション / 総合評価
3. **総合評価** — ◎完璧 / ○合格 / △要調整 / ✕中止

守るべき姿勢:

- **過大評価しない。△の走りに○をつけない。**
- 「心拍で走る、ペースは結果」——心拍が主、ペースが従
- 週間距離の前週比 +10% 超は過負荷リスクとして必ず指摘する
- 上下動はドライブの値を ×10 して cm として評価する（0.8 → 8cm）
- 疲労・コンディション軸は**必ず健康データで裏を取る**。走行データだけで疲労を語らない。
  警戒サインの優先順位は次のとおり:
  1. トレーニング準備度の前週比 −20% 以上
  2. ボディバッテリー最低値が 20 未満（特に連日）
  3. HRV がバランス域を下抜け、または前週比 −10% 以上
  4. 安静時心拍の前週比 +3bpm 以上
  5. 睡眠スコアの週平均が 70 未満
  該当したサインは `alerts` に **level: "warn"** で、具体的な数値とともに書く。
- 健康データが空欄の日がある場合は、その項目を `null` にして
  「取れていない」ことを `alerts` に **level: "info"** で明記する。
  0 や推測値で埋めない。

**今日走っていない場合**（最新のランが今日でない）:
`today.type` を `"休養日"`、`verdict` を `"—"`、`verdictLabel` を `"休養"`、`stats` と `laps` を空配列にし、
`verdictReason` に休養の妥当性（連続走行日数・週間距離から見て適切か）を書く。
評価軸と明日のメニューは通常どおり出す。休養日こそ翌日の設計が重要。

### STEP 5 — 明日のメニューを決める

`tomorrow` に、そのまま実行できる具体度で書く。抽象論を書かない。

- `title` — メニュー名（例: `Eペースロング 14km`）
- `headline` — 明日いちばん意識すべき一文
- `prescription` — 距離 / ペース / 心拍 / 意識 / スタート時刻 を具体的な数値で
- `why` — なぜこの内容なのかを、週間距離・疲労・フェーズから説明する
- `alt` — 体調が悪い場合の切り替え条件（落とす判断を肯定的に書く）
- `next` — その先1〜2日の位置づけ

### STEP 5.5 — 明日から1週間の流れを引く

`weekPlan` に明日から7日分を書く。**要点だけ。** 詳細は `tomorrow` 側に書くので重複させない。

- `days[]` は明日を先頭に7日。各日 `d` / `dow` / `type` / `title` / `km` / `note`
  - `type` は `"E"` / `"M"` / `"T"` / `"R"` / `"rest"`（週間バーと同じ区分）
  - `title` はメニュー名だけ（例: `Eペースロング`）。長い説明を入れない
  - `km` は文字列。幅がある日は `"14〜16"`、休養日は `"0"`（描画側が「—」にする）
  - `note` は一行。守るべき心拍かペース、または落とす条件をひとつだけ
- `policy` — その週の方針を一文で
- `totalKm` — 予定合計の目安（文字列。例 `"53〜55"`）

引くときの原則:

**まず骨格を置き、そのあとで調整する。** 空いた日をEで埋めていくのではなく、
先に質練習を配置してから残りをEと休養で埋めること。順序を逆にすると質が痩せる。

1. **フェーズ規定の質練習を先に置く**（`athlete_profile.md` のロードマップ表）。
   Phase 4以降は週3本 — Mペース1／閾値かインターバル1／ロング（後半M混走）1。
   **この本数は下限であって上限ではない。** 減らしてよいのは
   プロファイルの「負荷の下限 — 落としてよい条件」に当てはまったときだけ。
2. **質練習の間隔を空ける。** 中1〜2日。連続させない。翌日はEジョグか休養。
3. **残りをEで埋めて週間距離の下限に届かせる。** 届かないなら、
   休養日をEジョグに替えるか、Eの距離を伸ばす。**質練習を削って調整しない。**
4. **休養はフェーズ規定の日数まで。** Phase 4・5は週1日。
   2日以上入れるのは、健康データに実際の警戒サインが出ている週だけ。
5. **前週比 +10%** は、通常週の増やし方の目安。
   吸収週の翌週や、前週が谷だった週には機械的に適用しない
   （前週38kmの翌週に41.8kmしか組めない、という使い方は誤り）。

引き終わったら、**出す前に自己チェックする:**

- 質練習はフェーズ規定の本数に届いているか
- 週間距離はフェーズ規定の下限に届いているか
- Mペースと、閾値またはインターバルが**両方**入っているか
- 休養日がフェーズ規定を超えていないか

**届いていない項目があるのに落とした場合は、その理由（どの警戒サインが出たか）を
`weekPlan.policy` と `alerts` の両方に必ず書く。** 理由を書けないなら、それは
落としてよい週ではない。

### STEP 6 — ダッシュボードを更新する

1. `dashboard/index.html` の **DATA オブジェクトの中身だけ**を新しい内容に差し替える。
   **HTML・CSS・描画スクリプトには一切触れないこと。** 構造を変えると設計が壊れる。

   > **⚠ 置換位置の目印には必ず `<script id="coach-data">` を使うこと。**
   > 差し替える範囲は `<script id="coach-data">` の直後から、次に現れる `</script>` の直前まで。
   > **DATA の代入文そのものを検索の目印にしてはいけない。**
   > ファイル冒頭の説明コメントにも似た文字列が現れることがあり、そちらにヒットすると
   > コメントの閉じタグ `-->` と `<script>` 開始タグを巻き込んで削除してしまう。
   > するとページ全体が未終了の HTML コメントに飲み込まれ、**真っ白になる。**
   > 2026-08-24 の Routine 実行で実際にこれが起きた。
   >
   > 差し替えたら publish の前に必ず次を確認する:
   > - ファイル内に DATA の代入文がちょうど1つだけあること
   > - `-->` と `<script id="coach-data">` と `<div class="wrap" id="app">` が残っていること

   ダッシュボードは2つのタブに分かれている（描画側が自動で振り分けるので DATA 側の操作は不要）:
   - **走りの評価** — `today` / `axes` / `good` / `issues` / `tomorrow` / `weekPlan` / `week`
   - **コンディション** — `health`

   `race` カウンターと `alerts` は**両タブ共通で常に上部に出る**。
   したがって見落とさせたくない警告は必ず `alerts` に入れること。
   タブ側にしか書かれていない警告は、そのタブを開くまで目に入らない。
2. データ構造は既存のものを厳密に踏襲する。キー名を変えない、増やさない、減らさない。
   - `stats[].state` は `"ok"` / `"warn"` / `"crit"` のいずれか
   - `axes[].state` は `"good"` / `"warn"` / `"crit"` のいずれか
   - `week.days[].type` は `"E"` / `"M"` / `"T"` / `"R"` / `"rest"` のいずれか
   - `laps[].sec` はそのラップのペースを秒に直した整数（5:37 → 337）
   - `health` は Garmin の健康データをそのまま入れる（`docs/../src/ガーミン活動データ取得.py`
     が Doc とスプレッドシートに出力している値）:
     - `health.summary[]` は最新日の値 `value`、今週平均 `avg`、前週平均 `prev`、
       `state`（`"ok"` / `"warn"` / `"crit"`）、`note`（一行の解釈）。
       `avg` / `prev` はドキュメントの **「週平均と前週比」の行**からそのまま取る。
       前週平均が出せない項目は `prev: null` にする（描画側が比較行を出さない）。
       安静時心拍とストレスには `lowerIsBetter: true` を付ける
       （上昇を悪化として色付けするため。付け忘れると赤緑が逆になる）。
     - `health.days[]` は直近7日を古い順に。キーは
       `hrv` / `rhr` / `sleep`（スコア） / `sleepMin`（分） /
       `sleepDeep` / `sleepRem` / `sleepLight`（分・積み上げグラフ用） /
       `bbLow` / `stress` / `readiness`。
       取れなかった値は `null`。描画側が「—」を出す。
     - `health.sleepTargetMin` は睡眠の目標ライン（分）。グラフの基準線になる。
       通常は `420`（7時間）のままでよい。
     - `health.baseline` は HRV のバランス域（Garmin が返す `baseline.balancedLow` / `balancedUpper`）。
     - `health.fitness` は VO2max・トレーニングステータス・レース予測タイム。
     - `health.read` は健康データ全体の読み取りを3〜4文で。走行データとの整合も書く。
   - `race` / `tuneup` / `phase` は **`docs/athlete_profile.md` の値をそのまま反映する。**
     日付をこの手順書から拾わないこと。
     `daysLeft` は今日からプロファイルの `race.date` / `tuneup.date` までの日数を計算して入れる:
     ```bash
     python3 -c "import datetime;print((datetime.date(YYYY,M,D)-datetime.date.today()).days)"
     ```
     プロファイルの `tuneup.name` が `null` の場合は `DATA.tuneup` を `null` にする
     （描画側は `tuneup` が `null` ならそのカウンターを出さない）。
3. Artifact ツールで publish する。**必ず `url` を渡すこと。渡さないと別のURLが発行され、固定URLが壊れる。**

```
Artifact(
  file_path: "dashboard/index.html",
  url: "https://claude.ai/code/artifact/eedcbce5-cbe3-45f2-8181-4fffcd8b79c4",
  favicon: "🏃",
  title: "サブ3デイリーコーチ"
)
```

`favicon` と `title` は**毎回同じものを使う**。変えるとユーザーがタブを見失う。

### STEP 7 — Notion に登録する

今日走っていない場合はこのステップを丸ごとスキップする。

1. **重複チェック（必須）** — Notion MCP の `notion-search` で「[練習種別] [YYYY-MM-DD]」を検索し、
   同じ日付のページが既にあれば登録をスキップする。
2. なければ `docs/claude_project_running_instructions.md` の STEP 5 の
   プロパティ定義とページ本文構成にそのまま従って登録する。
   データソースID: `2fd862c3-def7-80f2-8b7d-000b148b15e5`
   （見つからない場合は `notion-search` で「Garmin」を検索して解決する）

### STEP 8 — コミットしない

**このRoutineはリポジトリに書き込めない。** `git push` も GitHub MCP の
`create_or_update_file` も `403 Resource not accessible by integration` で失敗する
（Claude の GitHub App にこのリポジトリへの書き込み権限がないため）。

**push を試みて時間を使わないこと。** サンドボックス内のファイル変更は破棄されてよい。
日々の記録は Artifact（固定URL・版履歴あり）と Notion に残るので、リポジトリへの
コミットは不要である。翌日の継続性は STEP 3 の WebFetch が担保する。

**Artifact の publish が成功したら、作業ツリーを必ず元に戻すこと。**

```bash
git checkout -- dashboard/index.html
git status --porcelain   # 何も出なければOK
```

この環境には「未コミットの変更が残っていたらコミットして push しろ」と要求する
Stop フックが仕込まれている。上のコマンドで作業ツリーを綺麗にしておけば、
フックは発火せず、無駄なやり取りが起きない。**publish の前に実行しないこと**
（publish はこのファイルを読むため、先に戻すと内容が失われる）。

### STEP 9 — 通知する

`PushNotification` で、総合評価と明日のメニュー名を1行で送る。

例: `8/21 Eペース走 ○合格 ／ 明日: Eペースロング 14km（HR140厳守）`

---

## 失敗したときの扱い

- **どのステップで失敗しても、そこで止まらず残りを実行する。**
- Google ドライブが読めなかった場合のみ、ダッシュボード更新を諦めてよい。
  その場合は `PushNotification` で「ドライブが読めず分析できませんでした」と通知する。
- Notion 登録の失敗はダッシュボード更新を妨げない。ダッシュボードが本体、Notion は記録用。

---

## 将来の拡張（未実施）

現在 Garmin 取得だけが GitHub Actions に残っている。これを Routine 側に取り込むには、
実行環境（`env_01QHh6nUAEy1hnSFxHJerFUs`）のネットワーク許可リストに
`sso.garmin.com` / `connect.garmin.com` / `connectapi.garmin.com` を追加し、
Garmin と Google の認証情報を環境変数として登録する必要がある。
これが実現すれば GitHub Actions を完全に廃止でき、パイプライン全体が 12:00 JST の一本にまとまる。
設定場所: https://claude.ai/code/environments
