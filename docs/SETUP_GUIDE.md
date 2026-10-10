# セットアップガイド

Garmin のデータを毎朝 Google ドライブへ取り込むまでの設定です（GitHub Actions 側）。
分析とダッシュボード（Claude Routine 側）の設定は最後の「6」にまとめています。

## 1. Google Cloud プロジェクトの準備

1. [Google Cloud Console](https://console.cloud.google.com/) で新しいプロジェクトを作る（名前は任意。例: `garmin-coach`）。
2. 「APIとサービス」→「ライブラリ」で、次の **3つ** を有効にする。
   - **Google Drive API**（ファイルを探す・作る）
   - **Google Sheets API**（スプレッドシートを書く）
   - **Google Docs API**（ドキュメント「ランニングログ」を書く。これが無いと Routine が読むデータが更新されない）

## 2. サービスアカウントと鍵

1. 「APIとサービス」→「認証情報」→「+ 認証情報を作成」→「サービスアカウント」。
2. 名前を付けて作成する（例: `garmin-uploader`）。ロールは付けなくてよい（権限はドライブのフォルダ共有で与える）。
3. 作成したサービスアカウントを開き、「キー」→「鍵を追加」→「新しい鍵を作成」→「JSON」。
4. ダウンロードした JSON ファイルの**中身すべて**を、あとで GitHub のシークレットに貼る。

## 3. Google ドライブの準備

1. ドライブにフォルダを作る（例: `Garmin Data`）。
2. フォルダを右クリック →「共有」→ サービスアカウントのメールアドレスを **編集者** で追加する。
3. フォルダを開いた状態の URL 末尾の文字列（フォルダID）を控える。
4. **そのフォルダの中に Google ドキュメントを1つ手で作り、名前を正確に `Garmin Running Log (Document)` にする。**
   - サービスアカウントは自分の容量を持たないので、ドキュメントは自動では作れない。無いと取得ジョブのログに
     `Google Document 'Garmin Running Log (Document)' not found` と出て、ドキュメントの更新を飛ばす。
   - 中身は毎朝まるごと書き換わる（先頭行は `# ランニングログ (最終更新: …)`）。
   - Routine はこのドキュメントを **ファイルID** で読む。作ったら URL の `/d/` と `/edit` の間の文字列を
     `docs/daily_coach_routine.md` の STEP 2 と `docs/claude_project_running_instructions.md` のデータソースに書く。
5. スプレッドシート `Garmin Running Log` は自動で作られる（見出し行・`Daily Health`・`Weekly Summary` タブも自動）。
   手で作る必要はない。

## 4. GitHub のシークレット

リポジトリの **Settings → Secrets and variables → Actions** に登録する。

| 名前 | 必須 | 中身 |
|------|------|------|
| `GARMIN_EMAIL` | ○ | Garmin Connect のメールアドレス |
| `GARMIN_PASSWORD` | ○ | Garmin Connect のパスワード |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | ○ | 手順2の JSON ファイルの中身すべて |
| `GOOGLE_DRIVE_FOLDER_ID` | ○ | 手順3のフォルダID |
| `GARTH_TOKENS_B64` | 推奨 | Garmin の OAuth トークン。パスワードログインが 429 で弾かれたときの保険。手元で `python scripts/generate_garth_token.py`（だめならブラウザ版 `scripts/generate_garth_token_browser.py`）を実行して出た文字列 |
| `GH_PAT_SECRETS` | 任意 | リポジトリのシークレットを書ける Personal Access Token。あれば、取得に成功したトークンで `GARTH_TOKENS_B64` を毎回書き換える |
| `GARMIN_SESSION_COOKIES` | 任意 | ブラウザのセッション Cookie（`scripts/extract_garmin_cookies.py`）。他の方法がすべて失敗するときの最後の手段 |

## 5. 動かして確かめる

1. **Actions** タブ →「Running Log」→「Run workflow」で手動実行する。
2. 成功したら、ドライブのドキュメントの先頭行 `最終更新:` が今の時刻になっていることを確かめる。
3. 以降は毎朝 8:30 JST に自動で動く（`.github/workflows/sync_garmin_to_notion.yml` の `cron`）。

手元で試すときは `.example.env` を `.env` にコピーして値を入れ、`python src/ガーミン活動データ取得.py` を実行する。

## 6. 分析とダッシュボード（Claude Routine）

1. https://claude.ai/code/routines で、このリポジトリを対象に毎日 02:57 UTC（11:57 JST）の Routine を作る。
   プロンプトは「`docs/daily_coach_routine.md` を読んで、書かれているとおりに実行せよ」だけでよい。
2. Routine の許可ツールに Google Drive コネクタ・Artifact・WebSearch・PushNotification を入れる。
   Notion はウィジェットを使う場合だけ（書けるのは `.claude/settings.json` のフックが許す1ページだけ）。
3. 初回はダッシュボードの固定 URL がまだ無いので、`dashboard/index.html` を一度公開し、
   出た URL を `docs/daily_coach_routine.md` と `widget/running_widget.js` に書く。
4. 目標レースなどの前提は `docs/athlete_profile.md` に書く。
5. iPhone ウィジェットを使うなら [`widget/README.md`](../widget/README.md) の手順へ。

## 付録: NotebookLM / Gemini で使う

- **NotebookLM**: ソースの追加で Google ドライブを選び、ドキュメント `Garmin Running Log (Document)` かスプレッドシート `Garmin Running Log` を選ぶ。
- **Gemini のカスタム Gem**: 知識にドライブ上の同じファイルを選ぶ。
