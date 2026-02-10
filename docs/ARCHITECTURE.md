# システムアーキテクチャ解説

このプロジェクトでは、**「思考（AI）」** と **「保存（クラウド）」** で2種類のGoogleサービスを使い分けています。

## 全体像
```mermaid
graph TD
    subgraph Data Source
        Notion[(Notion Database)]
    end

    subgraph "GitHub Actions (自動化プログラム)"
        Script1[garmin-activities.py]
        Script2[ai_coach.py]
        Script3[sync_to_drive.py]
    end

    subgraph "Google AI Studio (知能)"
        GeminiAPI[Gemini API]
    end

    subgraph "Google Cloud (保存場所)"
        DriveAPI[Google Drive API]
        DriveFile[ランニング日誌.txt]
    end

    subgraph "User Interface"
        NotebookLM[NotebookLM]
        GeminiGem[Gemini Custom Gem]
    end

    Script1 -->|1. データ取得| Notion
    Script2 -->|2. アドバイス生成を依頼| GeminiAPI
    GeminiAPI -->|3. 分析結果| Script2
    Script2 -->|4. Notionに書き込み| Notion
    Script3 -->|5. 最新データを取得| Notion
    Script3 -->|6. ファイル更新| DriveAPI
    DriveAPI -->|7. 保存| DriveFile
    DriveFile -->|8. 知識として参照| NotebookLM
    DriveFile -->|8. 知識として参照| GeminiGem
```

## 1. Google AI Studio (Gemini API)
*   **役割**: **「頭脳・コーチ」**
*   **使っている場所**: `ai_coach.py`
*   **何をしているか**:
    *   過去30日間のランニングデータを受け取ります。
    *   「コーチとしての視点」でデータを分析し、褒めたりアドバイスを考えたりします。
    *   **Google Cloudの複雑な設定は不要**で、APIキー1つで手軽に「知能」を使えるのが特徴です。

## 2. Google Cloud Platform (Google Drive API)
*   **役割**: **「倉庫・ファイル管理」**
*   **使っている場所**: `sync_to_drive.py`
*   **何をしているか**:
    *   Notionのデータを、NotebookLMが読める形（テキストファイル）に変換して保存します。
    *   **NotebookLMには「APIで直接データを送る機能」がまだないため**、「Googleドライブ上のファイルを更新する」という方法で間接的に連携しています。
    *   セキュリティ（権限管理）が厳しいため、サービスアカウント（ロボット）の設定が必要でした。

## まとめ
*   **AI Coach**: Gemini APIを使って、あなたに直接アドバイスを届ける（Notion上で見る用）。
*   **Drive Sync**: Google Cloudを使って、NotebookLM/Geminiが学習するための「教科書」を作る（対話用）。

この2つが連携して、毎日のランニングをサポートするシステムになっています！🏃💨
