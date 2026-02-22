import os
from notion_client import Client as NotionClient
from dotenv import load_dotenv

def create_databases(notion_token: str, parent_page_id: str):
    notion_client = NotionClient(auth=notion_token)

    # コンディションデータベース作成
    try:
        condition_db = notion_client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "コンディションログ"}}],
            properties={
                "名前": {"title": {}}, # Mandatory title property (ex: "2024-01-01")
                "日付": {"date": {}},
                "HRV": {"number": {}},
                "Body Battery": {"number": {}},
                "安静時心拍": {"number": {}},
                "トレーニングステータス": {"select": {}},
                "トレーニング負荷": {"number": {}},
                "睡眠スコア": {"number": {}},
            }
        )
        print(f"✅ コンディションログDB作成成功! ID: {condition_db['id']}")
    except Exception as e:
        print(f"❌ コンディションログDB作成失敗: {e}")

    # 週間レポートデータベース作成
    try:
        report_db = notion_client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "週間ランニングレポート"}}],
            properties={
                "タイトル": {"title": {}}, # e.g. "2024年W01 レポート"
                "対象週": {"date": {}},
                "総走行距離 (km)": {"number": {}},
                "平均心拍": {"number": {}},
                "平均HRV": {"number": {}},
                "所感": {"rich_text": {}}
            }
        )
        print(f"✅ 週間ランニングレポートDB作成成功! ID: {report_db['id']}")
    except Exception as e:
        print(f"❌ 週間ランニングレポートDB作成失敗: {e}")

if __name__ == "__main__":
    load_dotenv()
    notion_token = os.getenv("NOTION_TOKEN")
    
    # ユーザーが指定した親ページID
    parent_page_id = "2f4862c3def7808581fefb783c400313"
    
    if not notion_token:
        print("NOTION_TOKEN が .env に見つかりません。")
    else:
        print(f"Creating databases under parent page: {parent_page_id}")
        create_databases(notion_token, parent_page_id)
