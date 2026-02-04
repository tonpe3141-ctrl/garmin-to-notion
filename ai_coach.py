import os
import sys
import datetime
from datetime import timedelta, timezone
import google.generativeai as genai
from notion_client import Client
from dotenv import load_dotenv

def main():
    load_dotenv()
    
    # Environment Variables
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DB_ID")
    
    if not all([gemini_api_key, notion_token, database_id]):
        print("Error: Missing environment variables (GEMINI_API_KEY, NOTION_TOKEN, or NOTION_DB_ID).")
        sys.exit(1)

    # Initialize Clients
    genai.configure(api_key=gemini_api_key)
    notion = Client(auth=notion_token)
    
    # 1. Fetch data from Notion (Last 30 days)
    today = datetime.datetime.now(timezone.utc)
    start_date = today - timedelta(days=30)
    
    query_params = {
        "database_id": database_id,
        "filter": {
            "property": "日付",
            "date": {
                "on_or_after": start_date.strftime("%Y-%m-%d")
            }
        },
        "sorts": [
            {
                "property": "日付",
                "direction": "descending"
            }
        ]
    }
    
    try:
        results = notion.databases.query(**query_params).get("results", [])
    except Exception as e:
        print(f"Error fetching data from Notion: {e}")
        sys.exit(1)

    if not results:
        print("No activities found in the last 30 days.")
        return

    # Flatten and Format Data
    activities = []
    for page in results:
        props = page.get("properties", {})
        
        # Extract relevant fields
        date_prop = props.get("日付", {}).get("date", {})
        date_str = date_prop.get("start") if date_prop else "Unknown"
        
        distance = props.get("距離 (km)", {}).get("number", 0)
        time_minutes = props.get("タイム (分)", {}).get("number", 0)
        
        # Handle Pace (Rich Text)
        pace_list = props.get("平均ペース", {}).get("rich_text", [])
        pace = pace_list[0].get("text", {}).get("content", "") if pace_list else ""
        
        training_effect = props.get("トレーニング効果", {}).get("select", {})
        te_name = training_effect.get("name", "") if training_effect else ""

        # Activity Type
        type_prop = props.get("種目", {}).get("select", {})
        activity_type = type_prop.get("name", "") if type_prop else ""

        activity_name_list = props.get("アクティビティ名", {}).get("title", [])
        activity_name = activity_name_list[0].get("text", {}).get("content", "") if activity_name_list else ""

        activities.append({
            "id": page["id"],
            "date": date_str,
            "type": activity_type,
            "name": activity_name,
            "distance": distance,
            "time": time_minutes,
            "pace": pace,
            "training_effect": te_name
        })

    # The latest activity is the first one in the list (descending sort)
    latest_activity = activities[0]
    
    # Check if the latest activity is "Running" related (Optional constraint, but user context implies marathon coach)
    # We will process it anyway but maybe add a note if it's not running.
    
    # 2. Construct Prompt for Gemini
    
    # Create a summary of the last 30 days
    history_text = "【直近30日間の履歴 (最新順)】\n"
    total_distance_30d = 0
    run_count = 0
    
    for act in activities:
        # Only counting Running/Trail Running/Walking for mileage context if desired, 
        # but let's list everything for the AI to decide.
        history_text += f"- {act['date']} | {act['type']} | {act['name']} | {act['distance']}km | {act['pace']} | 効果: {act['training_effect']}\n"
        if act['type'] in ["ランニング", "トレイルランニング", "Running"]:
            total_distance_30d += act['distance'] if act['distance'] else 0
            run_count += 1
            
    prompt = f"""
あなたはプロフェッショナルかつ親しみやすいAIマラソンコーチです。
クライアントの直近30日間のトレーニングデータを分析し、**最新のアクティビティ**に対する評価とアドバイスを行ってください。

【クライアントの目標】
- **目標**: 4月19日の「かすみがうらマラソン」でサブ3:15（3時間15分切り）を達成すること。
- **直近30日間の走行距離**: 合計 {round(total_distance_30d, 2)} km ({run_count} 回のラン)

【最新のアクティビティ (評価対象)】
- 日付: {latest_activity['date']}
- 種目: {latest_activity['type']}
- アクティビティ名: {latest_activity['name']}
- 距離: {latest_activity['distance']} km
- タイム: {latest_activity['time']} 分
- ペース: {latest_activity['pace']}
- トレーニング効果: {latest_activity['training_effect']}

【過去30日間の履歴】
{history_text}

【指示】
1. **ペルソナ**: 
    - 親しみやすく、ポジティブな「良きパートナー」。
    - ランナーの努力を肯定し、適切に褒める。
    - 敬語（デス・マス調）で丁寧だが、堅苦しくないこと。
    - アドバイスの最後には、必ず「がんばりましょう！🔥」などの絵文字を含めた応援メッセージを入れてください。
2. **分析の視点**:
    - 単日の結果だけでなく、「過去1ヶ月の積み重ね」と比較して評価してください（例：「今月で一番良いペースでしたね」「今月は距離を踏めているので、今日は休養でもOKです」など）。
    - サブ3:15に向けた進捗状況（ベース、スピード、スタミナのバランス）を考慮してください。
3. **アドバイス内容**:
    - 具体的に褒めるポイントを必ず入れる。
    - サブ3:15達成に向けた「改善点」や「意識すべきこと」を1〜2点、前向きなアドバイスとして添える。
    - 全体として200〜400文字程度にまとめる。

【出力形式】
アドバイスの本文のみを出力してください。
"""

    # 3. Call Gemini
    try:
        # Correct Model ID identified from logs: gemini-3-pro-preview
        model = genai.GenerativeModel("gemini-3-pro-preview") 
        response = model.generate_content(prompt)
        advice_text = response.text.strip()
        print("--- Generated Advice ---")
        print(advice_text)
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        sys.exit(1)

    # 4. Write back to Notion
    try:
        # Check if the advice property already has content? 
        # Strategy: Overwrite.
        
        notion.pages.update(
            page_id=latest_activity["id"],
            properties={
                "AIコーチのアドバイス": {
                    "rich_text": [
                        {
                            "text": {
                                "content": advice_text
                            }
                        }
                    ]
                }
            }
        )
        print(f"Successfully updated Notion page: {latest_activity['date']} - {latest_activity['name']}")
        
    except Exception as e:
        print(f"Error writing to Notion: {e}")
        print("Note: Ensure the property 'AIコーチのアドバイス' (Rich Text) exists in the database.")
        sys.exit(1)

if __name__ == "__main__":
    main()
