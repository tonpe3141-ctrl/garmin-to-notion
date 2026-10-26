# このリポジトリで質問に答えるときの決まり

ランニングの質問（レース戦略・直近の調子・練習の評価など）に答えるときは、
**記憶や推測で答えず、下の手順で今のデータを取ってから答える。**

## Notion は参照しない

- Notion には、もうランニングのデータは連携していない。Garmin ログ DB は 2026-09-11 で更新が止まっており、
  目標・戦略のページも古いまま残っている。**読むと古い情報で答えてしまう。**
- `mcp__Notion__*` の検索・取得・クエリ系ツールは呼ばない（`.claude/settings.json` で拒否している）。
- 例外は、毎日の Routine が iPhone ウィジェット用ページを書き換える1か所だけ
  （`docs/daily_coach_routine.md` の STEP 6.8）。質問への回答では使わない。

## ランニングのデータはここから取る

| 知りたいこと | 取り方 |
|---|---|
| 直近の走り・ラップ・睡眠/HRV/ボディバッテリー・レース予測 | Google ドライブのドキュメント「Garmin Running Log (Document)」を `mcp__Google_Drive__read_file_content` で読む。fileId は `1OnOX6UxztuNBqixW8g8-N8YljathVDJ26HboLNdQISU` |
| 4週より前の全活動・日次の健康データ・週次の推移 | 同じフォルダのスプレッドシート「Garmin Running Log」。`mcp__Google_Drive__search_files`（`title = 'Garmin Running Log'` かつ `mimeType = 'application/vnd.google-apps.spreadsheet'`）で fileId を探して読む |
| 昨日までのコーチ評価・次の練習の指示 | ダッシュボードの Artifact を `Artifact`（`action: "read"`）で読む。`https://claude.ai/code/artifact/eedcbce5-cbe3-45f2-8181-4fffcd8b79c4`。`DATA` ブロックの `today` / `tomorrow` / `week` を見る |
| 過去の評価の履歴（1日1件） | 同じ Artifact の db を `ArtifactData`（`action: "query"`、`collection: "runs"`、`query.order_by` は `d` の降順）で読む。`list` は doc_id の昇順で古い日から返すので、件数が多いと直近が抜ける。質問への回答では**読むだけ**で、書き込まない（書くのは Routine の STEP 6.6） |
| 本人の体感（脚の張り・きつさ・痛み・補強・メモ） | 同じ db の `runs` にある doc_id `note-YYYY-MM-DD`（`kind: "note"`）。ダッシュボードの「体感メモ」で本人が書く。読んだら `node scripts/recent_notes.js <保存先>` で一覧できる。**書き込まない・消さない** |
| 目標レース・目標タイム・ペースゾーン・レース戦略・ロードマップ | `docs/athlete_profile.md` が唯一の正。ここから取る |

- 2026-10-26 より前に同期されたドキュメント・スプレッドシートは、8〜10月の活動が二重に入っていて週の距離が約2倍に出ている
  （取得側の不具合。同日に修正）。その時点の週次の距離は、ダッシュボードの db（`runs`）の日ごとの `km` から数え直す。
- ドキュメントの先頭行 `最終更新: YYYY-MM-DD HH:MM JST` を必ず確認する。今日より前なら、
  「データは○日時点のもの」と回答の冒頭で断る（同期は毎朝 8:30 JST の GitHub Actions）。
- 回答に使った数字は、どれを見て出したか（ドキュメントの日付、Artifact の日付など）を添える。
- 取れなかったデータは取れなかったと言う。Notion や記憶で埋めない。
- 優先順位が食い違ったら `docs/athlete_profile.md` > `docs/claude_project_running_instructions.md` > `docs/daily_coach_routine.md`。
- 構成の全体像は `docs/ARCHITECTURE.md`。
