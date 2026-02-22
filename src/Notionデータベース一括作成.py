import os
import re
from notion_client import Client as NotionClient
from dotenv import load_dotenv

def update_env_file(env_path: str, updates: dict):
    if not os.path.exists(env_path):
        print(f"Error: {env_path} does not exist.")
        return

    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()

    for key, value in updates.items():
        if value:
            if re.search(f"^{key}=.*$", content, re.MULTILINE):
                content = re.sub(f"^{key}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
            else:
                content += f"\n{key}={value}"

    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ .env ファイルを更新しました: {list(updates.keys())}")

def create_all_databases(notion_token: str, parent_page_id: str):
    notion_client = NotionClient(auth=notion_token)
    new_ids = {}

    print(f"\n親ページ ({parent_page_id}) にデータベースを作成中...\n")

    # 1. アクティビティDB (Weather/Temp removed, keeping dynamics)
    try:
        db = notion_client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "Garmin アクティビティ"}}],
            properties={
                "アクティビティ名": {"title": {}},
                "日付": {"date": {}},
                "種目": {"select": {}},
                "詳細種目": {"select": {}},
                "距離 (km)": {"number": {}},
                "タイム (分)": {"number": {}},
                "カロリー": {"number": {}},
                "平均ペース": {"rich_text": {}},
                "GAP": {"rich_text": {}},
                "平均心拍": {"number": {}},
                "最大心拍": {"number": {}},
                "平均パワー": {"number": {}},
                "最大パワー": {"number": {}},
                "トレーニング効果": {"select": {}},
                "有酸素": {"number": {}},
                "有酸素効果": {"select": {}},
                "無酸素": {"number": {}},
                "無酸素効果": {"select": {}},
                "ラップ": {"rich_text": {}},
                "自己ベスト": {"checkbox": {}},
                "お気に入り": {"checkbox": {}},
                "接地時間 (ms)": {"number": {}},
                "上下動 (cm)": {"number": {}},
                "左右バランス": {"rich_text": {}},
                "ピッチ (spm)": {"number": {}},
                "ストライド (m)": {"number": {}}
            },
            icon={"type": "emoji", "emoji": "🏃"}
        )
        new_ids["NOTION_DB_ID"] = db['id']
        print(f"✅ アクティビティDB作成完了: {db['id']}")
    except Exception as e:
        print(f"❌ アクティビティDB作成失敗: {e}")

    # 2. デイリーログDB (Condition + Steps merged, dropped variables that are often empty)
    try:
        db = notion_client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "Garmin デイリーログ"}}],
            properties={
                "名前": {"title": {}},
                "日付": {"date": {}},
                "HRV": {"number": {}},
                "安静時心拍": {"number": {}},
                "睡眠スコア": {"number": {}},
                "歩数": {"number": {}},
                "目標歩数": {"number": {}},
                "歩行距離 (km)": {"number": {}}
            },
            icon={"type": "emoji", "emoji": "🔋"}
        )
        new_ids["NOTION_DAILY_DB_ID"] = db['id']
        print(f"✅ デイリーログDB作成完了: {db['id']}")
    except Exception as e:
        print(f"❌ デイリーログDB作成失敗: {e}")

    # 3. レポートDB
    try:
        db = notion_client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "Garmin 週間ランニングレポート"}}],
            properties={
                "タイトル": {"title": {}},
                "対象週": {"date": {}},
                "総走行距離 (km)": {"number": {}},
                "平均心拍": {"number": {}},
                "平均HRV": {"number": {}},
                "所感": {"rich_text": {}}
            },
            icon={"type": "emoji", "emoji": "📊"}
        )
        new_ids["NOTION_REPORT_DB_ID"] = db['id']
        print(f"✅ 週間レポートDB作成完了: {db['id']}")
    except Exception as e:
        print(f"❌ 週間レポートDB作成失敗: {e}")
        
    return new_ids

if __name__ == "__main__":
    load_dotenv()
    notion_token = os.getenv("NOTION_TOKEN")
    
    if not notion_token or notion_token == "CHANGEME":
        print("エラー: .env に NOTION_TOKEN が設定されていません。")
        exit(1)
        
    parent_page_id = input("Notionの親ページのIDを入力してください (例: 2f4862c3def7808581fefb783c400313): ").strip()
    
    if not parent_page_id:
        print("エラー: 親ページIDが必要です。")
        exit(1)
        
    new_ids = create_all_databases(notion_token, parent_page_id)
    
    if new_ids:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        update_env_file(env_path, new_ids)
        print("\n🎉すべてのセットアップが完了しました！ .env ファイルも自動更新されています。")
