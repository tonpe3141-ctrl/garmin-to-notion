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

def get_all_activities(garmin_client: GarminClient, max_limit: int = 1000) -> list[dict]:
    # 確実性を高めるため、7日ずつ小分けにして過去60日分を取得する
    all_activities = []
    
    # 今日から遡る
    end_date = datetime.now(local_tz)
    # 60日前まで（約2ヶ月）
    final_start_date = end_date - timedelta(days=60)
    
    current_end = end_date
    
    print(f"Fetching activities in chunks (7 days per request) from {final_start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}...")
    
    while current_end > final_start_date:
        current_start = current_end - timedelta(days=6) # 7-day window
        
        start_str = current_start.strftime("%Y-%m-%d")
        end_str = current_end.strftime("%Y-%m-%d")
        
        print(f"  Fetching {start_str} to {end_str}...", end=" ", flush=True)
        try:
            # activityType='' gets all types
            activities = garmin_client.get_activities_by_date(start_str, end_str, "")
            if activities:
                print(f"Found {len(activities)} activities.")
                all_activities.extend(activities)
            else:
                print("None.")
                
        except Exception as e:
            print(f"Error: {e}")
        
        # Move back for next iteration
        current_end = current_start - timedelta(days=1)
        
        if len(all_activities) >= max_limit:
            break
            
    # Deduplicate by activityId
    unique_activities = {act['activityId']: act for act in all_activities}
    result = list(unique_activities.values())
    
    # Sort by date desc (Newest first)
    result.sort(key=lambda x: x.get('startTimeGMT'), reverse=True)
    
    print(f"Total unique activities fetched: {len(result)}")
    return result[:max_limit]

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

def activity_exists(notion_client: NotionClient, database_id: str, activity_date: datetime) -> dict | None:
    # タイムゾーン考慮: Garminの時間をJSTに変換して、その「日付(YYYY-MM-DD)」が一致するものを探す
    # activity_date は UTC で渡されてくる前提
    if activity_date.tzinfo is None:
        activity_date = activity_date.replace(tzinfo=UTC)
    
    activity_jst = activity_date.astimezone(local_tz)
    target_date_str = activity_jst.strftime('%Y-%m-%d')
    
    # 検索範囲: Notion上でその日のタイムレンジ（JST 00:00 - 23:59）
    # Notionでは日付クエリはISO文字列で行うが、安全のため前後24h広めに取ってフィルタするのは維持し、
    # Python側で厳密に文字列マッチさせる
    lookup_min_date = activity_date - timedelta(hours=24)
    lookup_max_date = activity_date + timedelta(hours=24)
    
    query = notion_client.databases.query(
        database_id=database_id,
        filter={
            "and": [
                {"property": "日付", "date": {"on_or_after": lookup_min_date.isoformat()}},
                {"property": "日付", "date": {"on_or_before": lookup_max_date.isoformat()}},
            ]
        }
    )
    results = query['results']
    
    if not results:
        return None
        
    # 文字列（YYYY-MM-DD）で完全一致するものを探す（これが最も確実）
    for page in results:
        try:
            date_prop = page['properties']['日付']['date']
            if not date_prop: continue
            
            start_str = date_prop['start'] # ISO string or YYYY-MM-DD
            page_date_str = start_str[:10] # 先頭10文字 (YYYY-MM-DD)
            
            if page_date_str == target_date_str:
                print(f"Match found by Date String: {page_date_str} (Page ID: {page['id']})")
                return page
                
        except Exception as e:
            print(f"Warning: Error checking page {page['id']}: {e}")
            continue

    print(f"No match found for {target_date_str} among {len(results)} candidates.")
    return None

def get_activity_properties(garmin_client: GarminClient, activity: dict) -> dict:
    activity_id = activity.get('activityId')
    
    # リスト取得のデータだと情報が欠けている場合があるため、詳細データを改めて取得する
    try:
        full_activity = garmin_client.get_activity(activity_id)
        if full_activity:
            activity = full_activity # Use the full data source
    except Exception as e:
        print(f"Warning: Could not fetch full activity details for {activity_id}, using summary: {e}")

    activity_date_raw = activity.get('startTimeGMT')
    activity_date_utc = datetime.strptime(activity_date_raw, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
    activity_date_jst = activity_date_utc.astimezone(local_tz)
    
    activity_name = activity.get('activityName', '無題のアクティビティ')
    activity_type, activity_subtype = format_activity_type(activity.get('activityType', {}).get('typeKey', 'Unknown'), activity_name)
    
    # ... (Processing additional metrics)
    average_hr = activity.get('averageHR')
    max_hr = activity.get('maxHR')
    avg_gap_speed = activity.get('avgGradeAdjustedSpeed') # m/s
    
    # Format GAP
    gap_str = format_pace(avg_gap_speed) if avg_gap_speed else "-"

    # Format Laps (Try to fetch detailed splits first, fall back to summary)
    laps_text = ""
    splits = []
    try:
        # 詳細なスプリット情報を取得（インターバル等の詳細が含まれる可能性が高い）
        detailed_splits = garmin_client.get_activity_splits(activity_id)
        
        if isinstance(detailed_splits, list):
            splits = detailed_splits
        elif isinstance(detailed_splits, dict):
            # 辞書の場合は中身を探す
            if 'splitSummaries' in detailed_splits:
                splits = detailed_splits['splitSummaries']
            elif 'lapSummaries' in detailed_splits:
                splits = detailed_splits['lapSummaries']
            elif 'lapDTOs' in detailed_splits:
                splits = detailed_splits['lapDTOs']
            else:
                print(f"Warning: detailed_splits is a dict with keys {list(detailed_splits.keys())}, falling back to summary.")
                splits = activity.get('splitSummaries', [])
        else:
             splits = activity.get('splitSummaries', [])
             
    except Exception as e:
        print(f"Warning: Could not fetch detailed splits for {activity_id}: ({type(e).__name__}) {e}")
        splits = activity.get('splitSummaries', [])

    if splits:
        for i, split in enumerate(splits, 1):
            if not isinstance(split, dict):
                continue
            
            distance_km = round(split.get('distance', 0) / 1000, 2)
            duration_s = split.get('duration', 0)
            duration_str = format_duration(duration_s)
            avg_speed = split.get('averageSpeed', 0)
            pace = format_pace(avg_speed)
            
            # Garminの生のsplitIdを使う（なければ連番）
            raw_id = split.get('splitId') or split.get('lapIndex') # lapDTOs uses lapIndex
            
            # splitType: RINTERVAL (Run), RRECOVERY (Rest), etc.
            # splitType might be a dict (with typeKey) or a simple string, or missing
            split_type_val = split.get('splitType')
            split_type_key = ""
            if isinstance(split_type_val, dict):
                split_type_key = split_type_val.get('typeKey', '')
            elif isinstance(split_type_val, str):
                split_type_key = split_type_val
            
            type_label = ""
            if 'INTERVAL' in split_type_key.upper(): type_label = " [Run]"
            elif 'RECOVERY' in split_type_key.upper(): type_label = " [Rest]"
            
            # 距離が短すぎる、かつ時間が短いものはノイズとしてスキップ（ただしインターバルのレストは0kmでも残す）
            if distance_km < 0.01 and duration_s < 5 and "RECOVERY" not in split_type_key.upper():
                continue

            lap_label = str(raw_id) if raw_id is not None else str(i)
            # ラップごとの心拍数があれば表示
            lap_hr = f" HR:{int(split.get('averageHR'))}" if split.get('averageHR') else ""
            
            laps_text += f"Lap {lap_label}{type_label}: {distance_km}km, {duration_str}, {pace}{lap_hr}\n"

    properties = {
        "日付": {"date": {"start": activity_date_jst.isoformat()}},
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
    return properties, icon_url_from_type(activity_type, activity_subtype)

def icon_url_from_type(activity_type, activity_subtype):
    return ACTIVITY_ICONS.get(activity_subtype if activity_subtype != activity_type else activity_type)

def create_activity(notion_client: NotionClient, database_id: str, activity: dict, garmin_client: GarminClient) -> None:
    properties, icon_url = get_activity_properties(garmin_client, activity)
    page = {"parent": {"database_id": database_id}, "properties": properties}
    if icon_url: page["icon"] = {"type": "external", "external": {"url": icon_url}}
    notion_client.pages.create(**page)
    print(f"Created: {properties['日付']['date']['start']} - {properties['種目']['select']['name']}")

def update_activity(notion_client: NotionClient, page_id: str, activity: dict, garmin_client: GarminClient) -> None:
    properties, icon_url = get_activity_properties(garmin_client, activity)
    # Remove '日付' from updates to avoid timezone shifts if not necessary, but here we keep it for consistency
    # Notion API 'update' merges properties.
    page = {"properties": properties}
    if icon_url: page["icon"] = {"type": "external", "external": {"url": icon_url}}
    notion_client.pages.update(page_id, **page)
    print(f"Updated Backfill: {properties['日付']['date']['start']} - {properties['種目']['select']['name']}")

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
    garmin_fetch_limit = int(os.getenv("GARMIN_ACTIVITIES_FETCH_LIMIT", "200")) # Increased to 200 for deep backfillory

    garmin_client = GarminClient(garmin_email, garmin_password)
    garmin_client.login()
    notion_client = NotionClient(auth=notion_token)
    
    # Update Schema if needed
    update_database_schema(notion_client, database_id)

    activities = get_all_activities(garmin_client, garmin_fetch_limit)
    print(f"Fetched {len(activities)} activities from Garmin.")
    
    for activity in activities:
        try:
            activity_date_raw = activity.get('startTimeGMT')
            activity_date = datetime.strptime(activity_date_raw, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
            activity_name = activity.get('activityName', '無題のアクティビティ')
            activity_type, _ = format_activity_type(activity.get('activityType', {}).get('typeKey', 'Unknown'), activity_name)

            # 日付のみで検索して、既存データ（英語・古い形式含む）を捕捉する
            existing_activity = activity_exists(notion_client, database_id, activity_date)
            if existing_activity:
                # Update existing activity to fill in new fields (HR, GAP, Laps)
                # 古いデータ（ "Running" 等）も新しいデータ内容で上書き更新される
                # activity['activityId'] を使って詳細スプリットを取得するため、clientを渡す
                update_activity(notion_client, existing_activity['id'], activity, garmin_client)
            else:
                create_activity(notion_client, database_id, activity, garmin_client)
        except Exception as e:
            print(f"Error processing activity {activity.get('activityId')}, skipping: {e}")
            continue
