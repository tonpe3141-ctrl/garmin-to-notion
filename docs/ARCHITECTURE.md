# システムアーキテクチャ解説

このプロジェクトでは、Running Logデータを**Googleドライブ**に自動保存し、AIツール（NotebookLM）で活用します。

## 全体像
```mermaid
graph TD
    subgraph Data Source
        Notion[(Notion Database)]
    end

    subgraph "GitHub Actions (自動化プログラム)"
        Script1[ガーミン活動データ取得.py]
        Script3[Googleドライブ同期.py]
    end

    subgraph "Google Cloud (保存場所)"
        DriveAPI[Google Drive API]
        DriveFile[Running Log (Google Doc)]
    end

    subgraph "User Interface"
        NotebookLM[NotebookLM]
        GeminiGem[Gemini Custom Gem]
    end

    Script1 -->|1. データ取得| Notion
    Script3 -->|2. 最新データを取得| Notion
    Script3 -->|3. ファイル更新| DriveAPI
    DriveAPI -->|4. 保存| DriveFile
    DriveFile -->|5. 知識として参照| NotebookLM
    DriveFile -->|5. 知識として参照| GeminiGem
```

## Google Cloud Platform (Google Drive API)
*   **役割**: **「倉庫・ファイル管理」**
*   **使っている場所**: `src/Googleドライブ同期.py`
*   **何をしているか**:
    *   Notionのデータを、NotebookLMが読める形（Googleドキュメント）に変換して保存します。
    *   **NotebookLMには「APIで直接データを送る機能」がまだないため**、「Googleドライブ上のファイルを更新する」という方法で間接的に連携しています。
    *   セキュリティ（権限管理）が厳しいため、サービスアカウント（ロボット）の設定が必要です。

## まとめ
*   **Running Log**: 毎日のランニングデータを自動的にGoogleドキュメントに記録し、あなたの「ランニングの教科書」として常に最新の状態に保ちます。

