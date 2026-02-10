import os
from datetime import datetime, UTC, timedelta

import pytz
from dotenv import load_dotenv
from garminconnect import Garmin as GarminClient
from notion_client import Client as NotionClient

# タイムゾーンの設定
local_tz = pytz.timezone('Asia/Tokyo')

# アイコン設定（日本語キー）
ACTIVITY_ICONS = {
    "バー": "https://img.icons8.com/?size=100&id=66924&format=png&color=000000",
    "呼吸法": "https://img.icons8.com/?size=100&id=9798&format=png&color=000000",
    "有酸素運動": "https://img.icons8.com/?size=100&id=71221&format=png&color=000000",
    "サイクリング": "https://img.icons8.com/?size=100&id=47443&format=png&color=000000",
    "ハイキング": "https://img.icons8.com/?size=100&id=9844&format=png&color=000000",
    "室内カーディオ": "https://img.icons8.com/?size=100&id=62779&format=png&color=000000",
    "室内サイクリング": "https://img.icons8.com/?size=100&id=47443&format=png&color=000000",
    "室内ローイング": "https://img.icons8.com/?size=100&id=71098&format=png&color=000000",
    "ピラティス": "https://img.icons8.com/?size=100&id=9774&format=png&color=000000",
    "瞑想": "https://img.icons8.com/?size=100&id=9798&format=png&color=000000",
    "ローイング": "https://img.icons8.com/?size=100&id=71491&format=png&color=000000",
    "ランニング": "https://img.icons8.com/?size=100&id=k1l1XFkME39t&format=png&color=000000",
    "筋トレ": "https://img.icons8.com/?size=100&id=107640&format=png&color=000000",
    "ストレッチ": "https://img.icons8.com/?size=100&id=djfOcRn1m_kh&format=png&color=000000",
    "スイミング": "https://img.icons8.com/?size=100&id=9777&format=png&color=000000",
    "トレッドミル": "https://img.icons8.com/?size=100&id=9794&format=png&color=000000",
    "ウォーキング": "https://img.icons8.com/?size=100&id=9807&format=png&color=000000",
    "ヨガ": "https://img.icons8.com/?size=100&id=9783&format=png&color=000000",
    "ヨガ/ピラティス": "https://img.icons8.com/?size=100&id=9783&format=png&color=000000",
}

def get_all_activities(garmin_client: GarminClient, limit: int = 1000) -> list[dict]:
    return garmin_client.get_activities(0, limit)

def format_activity_type(activity_type: str, activity_name: str = "") -> tuple[str, str]:
    formatted_type = activity_type.replace('_', ' ').title() if activity_type else "Unknown"
    activity_subtype = formatted_type
    activity_type = formatted_type

    activity_mapping = {
        "Barre": "Strength", "Indoor Cardio": "Cardio", "Indoor Cycling": "Cycling",
        "Indoor Rowing": "Rowing", "Speed Walking": "Walking", "Strength Training": "Strength",
        "Treadmill Running": "Running"
    }

    if formatted_type == "Rowing V2":
        activity_type = "Rowing"
    elif formatted_type in ["Yoga", "Pilates"]:
        activity_type = "Yoga/Pilates"
        activity_subtype = formatted_type

    if formatted_type in activity_mapping:
        activity_type = activity_mapping[formatted_type]
        activity_subtype = formatted_type

    japanese_map = {
        "Running": "ランニング", "Cycling": "サイクリング", "Walking": "ウォーキング",
        "Strength": "筋トレ", "Yoga/Pilates": "ヨガ/ピラティス", "Stretching": "ストレッチ",
        "Meditation": "瞑想", "Swimming": "スイミング", "Rowing": "ローイング",
        "Hiking": "ハイキング", "Cardio": "有酸素運動", "Treadmill Running": "トレッドミル",
        "Indoor Cycling": "室内サイクリング", "Yoga": "ヨガ", "Pilates": "ピラティス", "Barre": "バー"
    }

    if activity_name and "meditation" in activity_name.lower(): return "瞑想", "瞑想"
    if activity_name and "barre" in activity_name.lower(): return "筋トレ", "バー"
    if activity_name and "stretch" in activity_name.lower(): return "ストレッチ", "ストレッチ"

    return japanese_map.get(activity_type, activity_type), japanese_map.get(activity_subtype, activity_subtype)

def format_training_message(message: str) -> str:
    messages = {
        'NO_': '効果なし', 'MINOR_': 'わずかな効果', 'RECOVERY_': 'リカバリー',
        'MAINTAINING_': '維持', 'IMPROVING_': '向上', 'IMPACTING_': '影響あり',
        'HIGHLY_': '高い影響', 'OVERREACHING_': 'オーバーリーチ'
    }
    for key, value in messages.items():
        if message.startswith(key): return value
    return message

def format_training_effect(training_effect_label: str) -> str:
    # 画像にあるオプションをすべて網羅
    label_map = {
        "Recovery": "リカバリー",
        "Aerobic Base": "ベース",
        "Base": "ベース",
        "Tempo": "テンポ",
        "Lactate Threshold": "乳酸閾値",
        "Threshold": "閾値",
        "Speed": "スピード",
        "Anaerobic": "無酸素",
        "Sprint": "スプリント",
        "Vo2 Max": "VO2max",  # VO2maxはそのまま
        "Maintaining": "維持",
        "Improving": "向上",
        "Impacting": "影響あり",
        "Highly Impacting": "高い影響",
        "Overreaching": "オーバーリーチ",
        "No Benefit": "効果なし",
        "Unknown": "不明"
    }
    # _ を半角スペースにしてタイトル形式にする（例: AEROBIC_BASE -> Aerobic Base）
    formatted = training_effect_label.replace('_', ' ').title()
    return label_map.get(formatted, formatted)

def format_pace(average_speed: float) -> str:
    if average_speed > 0:
        pace_min_km = 1000 / (average_speed * 60)
        minutes = int(pace_min_km)
        seconds = int((pace_min_km - minutes) * 60)
        return f"{minutes}:{seconds:02d} /km"
    return ""

def activity_exists(notion_client: NotionClient, database_id: str, activity_date: datetime, activity_type: str, activity_name: str) -> dict | None:
    lookup_type = "ストレッチ" if "stretch" in activity_name.lower() else activity_type
    lookup_min_date = activity_date - timedelta(minutes=5)
    lookup_max_date = activity_date + timedelta(minutes=5)
    query = notion_client.databases.query(
        database_id=database_id,
        filter={
            "and": [
                {"property": "日付", "date": {"on_or_after": lookup_min_date.isoformat()}},
                {"property": "日付", "date": {"on_or_before": lookup_max_date.isoformat()}},
                {"property": "種目", "select": {"equals": lookup_type}},
                {"property": "アクティビティ名", "title": {"equals": activity_name}}
            ]
        }
    )
    results = query['results']
    return results[0] if results else None

def create_activity(notion_client: NotionClient, database_id: str, activity: dict) -> None:
    activity_date = activity.get('startTimeGMT')
    activity_name = activity.get('activityName', '無題のアクティビティ')
    activity_type, activity_subtype = format_activity_type(activity.get('activityType', {}).get('typeKey', 'Unknown'), activity_name)
    icon_url = ACTIVITY_ICONS.get(activity_subtype if activity_subtype != activity_type else activity_type)

    # ... (Processing additional metrics)
    average_hr = activity.get('averageHR')
    max_hr = activity.get('maxHR')
    avg_gap_speed = activity.get('avgGradeAdjustedSpeed') # m/s
    
    # Format GAP
    gap_str = format_pace(avg_gap_speed) if avg_gap_speed else "-"

    # Format Laps (splitSummaries)
    splits = activity.get('splitSummaries', [])
    laps_text = ""
    if splits:
        for split in splits:
            distance_km = round(split.get('distance', 0) / 1000, 2)
            duration_min = format_duration(split.get('duration', 0))
            avg_speed = split.get('averageSpeed', 0)
            pace = format_pace(avg_speed)
            lap_idx = split.get('splitId', '?')
            laps_text += f"Lap {lap_idx}: {distance_km}km, {duration_min}, {pace}/km\n"

    properties = {
        "日付": {"date": {"start": activity_date}},
        "種目": {"select": {"name": activity_type}},
        "詳細種目": {"select": {"name": activity_subtype}},
        "アクティビティ名": {"title": [{"text": {"content": activity_name}}]},
        "距離 (km)": {"number": round(activity.get('distance', 0) / 1000, 2)},
        "タイム (分)": {"number": round(activity.get('duration', 0) / 60, 2)},
        "カロリー": {"number": round(activity.get('calories', 0))},
        "平均ペース": {"rich_text": [{"text": {"content": format_pace(activity.get('averageSpeed', 0))}}]},
        "GAP": {"rich_text": [{"text": {"content": gap_str}}]},
        "平均心拍": {"number": round(average_hr) if average_hr else None},
        "最大心拍": {"number": round(max_hr) if max_hr else None},
        "平均パワー": {"number": round(activity.get('avgPower', 0), 1)},
        "最大パワー": {"number": round(activity.get('maxPower', 0), 1)},
        "トレーニング効果": {"select": {"name": format_training_effect(activity.get('trainingEffectLabel', 'Unknown'))}},
        "有酸素": {"number": round(activity.get('aerobicTrainingEffect', 0), 1)},
        "有酸素効果": {"select": {"name": format_training_message(activity.get('aerobicTrainingEffectMessage', 'Unknown'))}},
        "無酸素": {"number": round(activity.get('anaerobicTrainingEffect', 0), 1)},
        "無酸素効果": {"select": {"name": format_training_message(activity.get('anaerobicTrainingEffectMessage', 'Unknown'))}},
        "ラップ": {"rich_text": [{"text": {"content": laps_text[:2000]}}]}, # Notion limit check
        "自己ベスト": {"checkbox": activity.get('pr', False)},
        "お気に入り": {"checkbox": activity.get('favorite', False)}
    }

    page = {"parent": {"database_id": database_id}, "properties": properties}
    if icon_url: page["icon"] = {"type": "external", "external": {"url": icon_url}}
    notion_client.pages.create(**page)

def format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"

def update_database_schema(notion_client: NotionClient, database_id: str) -> None:
    """Ensure new properties exist in the database."""
    try:
        notion_client.databases.update(
            database_id=database_id,
            properties={
                "平均心拍": {"number": {}},
                "最大心拍": {"number": {}},
                "GAP": {"rich_text": {}},
                "ラップ": {"rich_text": {}}
            }
        )
        print("Updated Notion Database Schema with new columns.")
    except Exception as e:
        print(f"Warning: Could not update database schema (might already exist or permission issue): {e}")

def main():
    load_dotenv()
    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DB_ID")
    garmin_fetch_limit = int(os.getenv("GARMIN_ACTIVITIES_FETCH_LIMIT", "1000"))

    garmin_client = GarminClient(garmin_email, garmin_password)
    garmin_client.login()
    notion_client = NotionClient(auth=notion_token)
    
    # Update Schema if needed
    update_database_schema(notion_client, database_id)

    activities = get_all_activities(garmin_client, garmin_fetch_limit)
    for activity in activities:
        activity_date_raw = activity.get('startTimeGMT')
        activity_date = datetime.strptime(activity_date_raw, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
        activity_name = activity.get('activityName', '無題のアクティビティ')
        activity_type, _ = format_activity_type(activity.get('activityType', {}).get('typeKey', 'Unknown'), activity_name)

        existing_activity = activity_exists(notion_client, database_id, activity_date, activity_type, activity_name)
        if not existing_activity:
            create_activity(notion_client, database_id, activity)

if __name__ == '__main__':
    main()
