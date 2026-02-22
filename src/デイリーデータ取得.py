import os
from datetime import datetime, timedelta
from typing import Optional

import pytz
from dotenv import load_dotenv
from garminconnect import Garmin as GarminClient
from notion_client import Client as NotionClient

# タイムゾーンの設定
local_tz = pytz.timezone('Asia/Tokyo')

def get_garmin_data(client: GarminClient, target_date: datetime.date) -> dict:
    date_str = target_date.isoformat()
    data = {"date": date_str}
    
    print(f"Fetching daily data for {date_str}...")

    # HRV Status
    try:
        hrv = client.get_hrv_data(date_str)
        if hrv and 'hrvSummary' in hrv:
            data['hrv'] = hrv['hrvSummary'].get('weeklyAvg') or hrv['hrvSummary'].get('lastNightAvg')
    except Exception as e:
        print(f"Failed to fetch HRV: {e}")

    # Resting Heart Rate (RHR)
    try:
        rhr = client.get_rhr_day(date_str)
        if rhr and 'allMetrics' in rhr and 'metricsMap' in rhr['allMetrics']:
            metrics = rhr['allMetrics']['metricsMap']
            if 'WELLNESS_RESTING_HEART_RATE' in metrics and metrics['WELLNESS_RESTING_HEART_RATE']:
                data['rhr'] = metrics['WELLNESS_RESTING_HEART_RATE'][0].get('value')
    except Exception as e:
        print(f"Failed to fetch RHR: {e}")

    # Sleep Score
    try:
        sleep = client.get_sleep_data(date_str)
        if sleep and 'dailySleepDTO' in sleep:
            data['sleep_score'] = sleep['dailySleepDTO'].get('sleepScores', {}).get('overall', {}).get('value')
    except Exception as e:
        print(f"Failed to fetch Sleep Score: {e}")

    # Steps
    try:
        steps_list = client.get_daily_steps(date_str, date_str)
        if steps_list and len(steps_list) > 0:
            step_obj = steps_list[0]
            data['total_steps'] = step_obj.get('totalSteps')
            data['step_goal'] = step_obj.get('stepGoal')
            
            total_dist_meters = step_obj.get('totalDistance', 0)
            data['total_distance_km'] = round(total_dist_meters / 1000, 2) if total_dist_meters else 0
    except Exception as e:
        print(f"Failed to fetch Steps: {e}")

    print(f"Fetched Data: {data}")
    return data

def daily_log_exists(notion_client: NotionClient, database_id: str, date_str: str) -> Optional[dict]:
    query = notion_client.databases.query(
        database_id=database_id,
        filter={
            "property": "日付",
            "date": {
                "equals": date_str
            }
        }
    )
    results = query.get('results', [])
    if results:
        return results[0]
    return None

def sync_to_notion(notion_client: NotionClient, database_id: str, data: dict):
    if not data:
        return

    date_str = data['date']
    
    properties = {
        "名前": {"title": [{"text": {"content": f"{date_str} の記録"}}]},
        "日付": {"date": {"start": date_str}},
        "HRV": {"number": data.get('hrv')},
        "安静時心拍": {"number": data.get('rhr')},
        "睡眠スコア": {"number": data.get('sleep_score')},
        "歩数": {"number": data.get('total_steps')},
        "目標歩数": {"number": data.get('step_goal')},
        "歩行距離 (km)": {"number": data.get('total_distance_km')}
    }

    # Remove None values
    for key in list(properties.keys()):
        if isinstance(properties[key], dict):
            if 'number' in properties[key] and properties[key]['number'] is None:
                del properties[key]

    existing = daily_log_exists(notion_client, database_id, date_str)
    
    try:
        if existing:
            notion_client.pages.update(page_id=existing['id'], properties=properties)
            print(f"Updated daily record for {date_str} in Notion.")
        else:
            notion_client.pages.create(parent={"database_id": database_id}, properties=properties)
            print(f"Created new daily record for {date_str} in Notion.")
    except Exception as e:
        print(f"Error syncing to Notion: {e}")

def main():
    load_dotenv()
    
    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    notion_token = os.getenv("NOTION_TOKEN")
    
    daily_db_id = os.getenv("NOTION_DAILY_DB_ID")

    if not all([garmin_email, garmin_password, notion_token, daily_db_id]):
        print("Missing required environment variables or DB ID (NOTION_DAILY_DB_ID).")
        return

    # Garmin Login
    try:
        garmin_client = GarminClient(garmin_email, garmin_password)
        garmin_client.login()
        print("Logged into Garmin Connect")
    except Exception as e:
        print(f"Garmin login failed: {e}")
        return

    # Notion Init
    notion_client = NotionClient(auth=notion_token)

    # Yesterday and today
    today = datetime.now(local_tz).date()
    yesterday = today - timedelta(days=1)
    
    for target_date in [yesterday, today]:
        try:
            data = get_garmin_data(garmin_client, target_date)
            if len(data) > 1:
                sync_to_notion(notion_client, daily_db_id, data)
            else:
                print(f"No data available for {target_date}.")
        except Exception as e:
            print(f"Error processing {target_date}: {e}")

if __name__ == "__main__":
    main()
