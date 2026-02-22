import os
from datetime import datetime, timedelta
from typing import Optional, List

import pytz
from dotenv import load_dotenv
from notion_client import Client as NotionClient

local_tz = pytz.timezone('Asia/Tokyo')

def get_last_week_range() -> tuple[datetime, datetime]:
    """Returns the start (Monday) and end (Sunday) datetime of the previous week in JST."""
    today = datetime.now(local_tz)
    # 0 = Monday, 6 = Sunday
    days_since_monday = today.weekday()
    
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_monday_start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    
    last_sunday = last_monday_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return last_monday_start, last_sunday

def fetch_weekly_activities(notion_client: NotionClient, db_id: str, start_dt: datetime, end_dt: datetime) -> List[dict]:
    """Fetch activities within the week range."""
    # Notion expects ISO strings
    start_str = start_dt.isoformat()
    end_str = end_dt.isoformat()
    
    try:
        query = notion_client.databases.query(
            database_id=db_id,
            filter={
                "and": [
                    {"property": "日付", "date": {"on_or_after": start_str}},
                    {"property": "日付", "date": {"on_or_before": end_str}},
                    {"property": "種目", "select": {"equals": "ランニング"}} # Filter for running only or remove this to include all
                ]
            }
        )
        return query.get('results', [])
    except Exception as e:
        print(f"Error fetching activities: {e}")
        return []

def fetch_weekly_conditions(notion_client: NotionClient, db_id: str, start_dt: datetime, end_dt: datetime) -> List[dict]:
    """Fetch conditions within the week range."""
    start_str = start_dt.isoformat()
    end_str = end_dt.isoformat()
    
    try:
        query = notion_client.databases.query(
            database_id=db_id,
            filter={
                "and": [
                    {"property": "日付", "date": {"on_or_after": start_str}},
                    {"property": "日付", "date": {"on_or_before": end_str}}
                ]
            }
        )
        return query.get('results', [])
    except Exception as e:
        print(f"Error fetching conditions: {e}")
        return []

def calculate_weekly_stats(activities: List[dict], conditions: List[dict]) -> dict:
    total_distance_km = 0.0
    total_duration_min = 0.0
    total_hr = 0
    hr_count = 0
    
    for act in activities:
        props = act.get('properties', {})
        
        # Distance mapping: "距離 (km)"
        dist_prop = props.get('距離 (km)', {}).get('number')
        if dist_prop: total_distance_km += dist_prop
            
        dur_prop = props.get('タイム (分)', {}).get('number')
        if dur_prop: total_duration_min += dur_prop
            
        hr_prop = props.get('平均心拍', {}).get('number')
        if hr_prop:
            total_hr += hr_prop
            hr_count += 1
            
    avg_hr = total_hr / hr_count if hr_count > 0 else 0
    
    total_hrv = 0
    hrv_count = 0
    for cond in conditions:
        props = cond.get('properties', {})
        hrv_prop = props.get('HRV', {}).get('number')
        if hrv_prop:
            total_hrv += hrv_prop
            hrv_count += 1
            
    avg_hrv = total_hrv / hrv_count if hrv_count > 0 else 0
    
    return {
        "distance": round(total_distance_km, 2),
        "duration": round(total_duration_min, 1),
        "activities_count": len(activities),
        "avg_hr": round(avg_hr),
        "avg_hrv": round(avg_hrv)
    }

def create_report_in_notion(notion_client: NotionClient, report_db_id: str, start_dt: datetime, end_dt: datetime, stats: dict):
    title = f"{start_dt.strftime('%Y年%m月')} 第{(start_dt.day-1)//7+1}週 レポート ({start_dt.strftime('%m/%d')}-{end_dt.strftime('%m/%d')})"
    
    # Block contents for the page details
    content_blocks = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "📊 今週のサマリー"}}]
            }
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": f"ランニング回数: {stats['activities_count']}回"}}]
            }
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": f"週間合計距離: {stats['distance']} km"}}]
            }
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": f"合計時間: {stats['duration']} 分"}}]
            }
        }
    ]

    properties = {
        "タイトル": {"title": [{"text": {"content": title}}]},
        "対象週": {"date": {"start": start_dt.strftime('%Y-%m-%d'), "end": end_dt.strftime('%Y-%m-%d')}},
        "総走行距離 (km)": {"number": stats['distance']},
        "平均心拍": {"number": stats['avg_hr'] if stats['avg_hr'] > 0 else None},
        "平均HRV": {"number": stats['avg_hrv'] if stats['avg_hrv'] > 0 else None},
        "所感": {"rich_text": [{"text": {"content": "今週のトレーニングの振り返りをここに記載します。"}}]}
    }
    
    # Remove None values
    for key in list(properties.keys()):
        if isinstance(properties[key], dict):
            if 'number' in properties[key] and properties[key]['number'] is None:
                del properties[key]

    try:
        # Check if already exists for this week start date
        query = notion_client.databases.query(
            database_id=report_db_id,
            filter={
                "property": "タイトル",
                "title": {"equals": title}
            }
        )
        
        if query.get('results'):
            print(f"Report for {title} already exists. Skipping creation.")
            return
            
        print(f"Creating weekly report: {title}")
        notion_client.pages.create(
            parent={"database_id": report_db_id},
            properties=properties,
            children=content_blocks,
            icon={"type": "emoji", "emoji": "📈"}
        )
        print("Weekly report created successfully!")
    except Exception as e:
        print(f"Error creating report page: {e}")

def main():
    load_dotenv()
    notion_token = os.getenv("NOTION_TOKEN")
    
    activity_db_id = os.getenv("NOTION_DB_ID") # Existing Activity DB ID
    daily_db_id = os.getenv("NOTION_DAILY_DB_ID")
    report_db_id = os.getenv("NOTION_REPORT_DB_ID")

    if not all([notion_token, activity_db_id, daily_db_id, report_db_id]):
        print("Missing required environment variables or DB IDs.")
        return

    notion_client = NotionClient(auth=notion_token)
    
    start_dt, end_dt = get_last_week_range()
    print(f"Generating report for: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")

    activities = fetch_weekly_activities(notion_client, activity_db_id, start_dt, end_dt)
    conditions = fetch_weekly_conditions(notion_client, daily_db_id, start_dt, end_dt)
    
    stats = calculate_weekly_stats(activities, conditions)
    print(f"Weekly Stats: {stats}")
    
    create_report_in_notion(notion_client, report_db_id, start_dt, end_dt, stats)

if __name__ == "__main__":
    main()
