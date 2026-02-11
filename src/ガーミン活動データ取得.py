import os
import json
from datetime import datetime, UTC, timedelta

import pytz
from dotenv import load_dotenv
from garminconnect import Garmin as GarminClient
from notion_client import Client as NotionClient

# Google API Imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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

def get_all_activities(garmin_client: GarminClient, max_limit: int = 2000) -> list[dict]:
    # 日付指定が不安定なため、確実な「インデックス指定（ページネーション）」で過去データを総ざらいする
    all_activities = []
    batch_size = 50 # 安全のため少し小さめに
    start_index = 0
    
    # どこまで遡るか（例: 90日前）
    target_history_days = 90
    cutoff_date = datetime.now(local_tz) - timedelta(days=target_history_days)
    
    print(f"Fetching activities via Pagination (Target: Last {target_history_days} days)...")
    
    while True:
        try:
            print(f"  Fetching index {start_index} to {start_index + batch_size}...", end=" ", flush=True)
            activities = garmin_client.get_activities(start_index, batch_size)
            
            if not activities:
                print("No more activities found.")
                break
                
            all_activities.extend(activities)
            print(f"Fetched {len(activities)} items.")
            
            # 日付チェック：一番古いデータがカットオフより古ければ終了
            last_activity = activities[-1]
            last_date_str = last_activity.get('startTimeGMT')
            last_date = datetime.strptime(last_date_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC).astimezone(local_tz)
            
            print(f"    Oldest in batch: {last_date.strftime('%Y-%m-%d')}")
            
            if last_date < cutoff_date:
                print(f"    Reached cutoff date ({cutoff_date.strftime('%Y-%m-%d')}). stopping.")
                break
                
            if len(all_activities) >= max_limit:
                print(f"    Reached max limit ({max_limit}). stopping.")
                break
            
            start_index += batch_size
            
        except Exception as e:
            print(f"Error in pagination at index {start_index}: {e}")
            # エラーが出ても、そこまで取れた分は返す
            break
            
    print(f"Total fetched: {len(all_activities)}")
    return all_activities

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
    
    print(f"Target Activity Date (JST): {target_date_str} (Original UTC: {activity_date})")
    
    # 検索範囲: Notion上でその日のタイムレンジ（JST 00:00 - 23:59）
    # Notionでは日付クエリはISO文字列で行うが、安全のため前後24h広めに取ってフィルタするのは維持し、
    # Python側で厳密に文字列マッチさせる
    lookup_min_date = activity_date - timedelta(hours=48) # 念のため48時間に拡大
    lookup_max_date = activity_date + timedelta(hours=48)
    
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
    print(f"  Notion Query found {len(results)} candidates in range.")
    
    if not results:
        return None
        
    # 文字列（YYYY-MM-DD）で完全一致するものを探す（これが最も確実）
    # 文字列（YYYY-MM-DD）で完全一致するものを探す（これが最も確実）
    for page in results:
        try:
            date_prop = page['properties']['日付']['date']
            if not date_prop: continue
            
            start_str = date_prop['start'] # ISO string or YYYY-MM-DD
            page_date_str = start_str[:10] # 先頭10文字 (YYYY-MM-DD)
            
            # print(f"  - Compare: Notion({page_date_str}) vs Target({target_date_str}) [ID: {page['id']}]")
            
            if page_date_str == target_date_str:
                print(f"    -> MATCH FOUND (Exact Date)!")
                return page
            
            # フォールバック用: 時間差計算
            if 'T' in start_str:
                page_date_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            else:
                page_date_dt = datetime.fromisoformat(start_str).replace(tzinfo=UTC)
            
            if page_date_dt.tzinfo is None: page_date_dt = page_date_dt.replace(tzinfo=UTC)
            
            diff = abs((page_date_dt - activity_date).total_seconds())
            if diff < min_diff:
                min_diff = diff
                closest_match = page
                
        except Exception as e:
            print(f"Warning: Error checking page {page['id']}: {e}")
            continue

    # 文字列一致がなくても、48時間以内のデータがあればそれを使う（表記揺れやタイムゾーンずれの救済）
    if closest_match and min_diff < 48 * 3600:
         print(f"    -> MATCH FOUND (Approximate, Diff: {min_diff/3600:.1f}h)!")
         return closest_match

    print(f"  No match found.")
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


def get_google_credentials(service_account_json_str):
    try:
        info = json.loads(service_account_json_str)
        creds = Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
        )
        return creds
    except Exception as e:
        print(f"Error loading Google Service Account: {e}")
        return None

def sync_to_google_sheet(activities: list[dict], folder_id: str, service_account_json: str):
    print("\n--- Starting Google Sheets Sync (Direct from Garmin) ---")
    creds = get_google_credentials(service_account_json)
    if not creds:
        print("Skipping Google Sync: No credentials.")
        return

    try:
        drive_service = build('drive', 'v3', credentials=creds)
        sheets_service = build('sheets', 'v4', credentials=creds)
        
        # 1. Check for existing file
        file_name = "Garmin Running Log"
        query = f"name = '{file_name}' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            spreadsheet_id = files[0]['id']
            print(f"Found existing Sheet: {spreadsheet_id}")
        else:
            print("Creating new Sheet...")
            file_metadata = {
                'name': file_name,
                'parents': [folder_id],
                'mimeType': 'application/vnd.google-apps.spreadsheet'
            }
            file = drive_service.files().create(body=file_metadata, fields='id').execute()
            spreadsheet_id = file.get('id')
            print(f"Created new Sheet: {spreadsheet_id}")

        # 2. Prepare Data
        # Header matches Notion structure roughly
        header = ["日付", "種目", "詳細種目", "アクティビティ名", "距離 (km)", "タイム (分)", 
                  "カロリー", "平均ペース", "平均心拍", "最大心拍", "ピッチ", "ストライド", 
                  "有酸素TE", "無酸素TE", "タイムスタンプ"]
        
        values = [header]
        
        for activity in activities:
            # Parse Date
            activity_date_raw = activity.get('startTimeGMT')
            activity_date_utc = datetime.strptime(activity_date_raw, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
            activity_date_jst = activity_date_utc.astimezone(local_tz)
            date_str = activity_date_jst.strftime('%Y-%m-%d %H:%M')
            
            activity_name = activity.get('activityName', '無題')
            activity_type, activity_subtype = format_activity_type(activity.get('activityType', {}).get('typeKey', 'Unknown'), activity_name)
            
            distance_km = round(activity.get('distance', 0) / 1000, 2)
            duration_min = round(activity.get('duration', 0) / 60, 2)
            calories = round(activity.get('calories', 0))
            avg_pace = format_pace(activity.get('averageSpeed', 0))
            avg_hr = round(activity.get('averageHR')) if activity.get('averageHR') else ""
            max_hr = round(activity.get('maxHR')) if activity.get('maxHR') else ""
            
            cadence = round(activity.get('averageRunningCadenceInStepsPerMinute', 0)) if activity.get('averageRunningCadenceInStepsPerMinute') else ""
            stride = round(activity.get('averageStrideLength', 0) / 100, 2) if activity.get('averageStrideLength') else "" # cm to m? normally displayed in m or cm. Garmin sends cm usually. Notion asks for what? Let's assume m for now or cm. usually cm.
            
            aerobic = round(activity.get('aerobicTrainingEffect', 0), 1)
            anaerobic = round(activity.get('anaerobicTrainingEffect', 0), 1)
            
            row = [
                date_str,
                activity_type,
                activity_subtype,
                activity_name,
                distance_km,
                duration_min,
                calories,
                avg_pace,
                avg_hr,
                max_hr,
                cadence,
                stride,
                aerobic,
                anaerobic,
                datetime.now(local_tz).isoformat()
            ]
            values.append(row)
            
        # 3. Write Data
        body = {'values': values}
        range_name = 'Sheet1!A1' # Default sheet name often "Sheet1" or "シート1". Try A1.
        
        # Try to clear first or just overwrite? update updates info.
        # Let's clear to be safe or overwrite. 
        # Actually, let's just update. "USER_ENTERED" allows parsing.
        
        # Check sheet name logic? Usually "Sheet1" in English, "シート1" in Japanese locale.
        # We can get sheet info but let's just try default.
        # Or better: Get the first sheet's name.
        sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        first_sheet_title = sheet_metadata.get('sheets', '')[0].get('properties', {}).get('title', 'Sheet1')
        range_name = f"{first_sheet_title}!A1"
        
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=range_name,
            valueInputOption='USER_ENTERED', body=body
        ).execute()
        
        print(f"Successfully synced {len(values)-1} rows to Google Sheets.")
        
    except HttpError as err:
        print(f"Google API Error: {err}")


def main():
    load_dotenv()
    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DB_ID")
    garmin_fetch_limit = int(os.getenv("GARMIN_ACTIVITIES_FETCH_LIMIT", "200"))
    
    # Google Auth
    google_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    drive_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

    garmin_client = GarminClient(garmin_email, garmin_password)
    garmin_client.login()
    notion_client = NotionClient(auth=notion_token)
    
    # Update Schema if needed
    update_database_schema(notion_client, database_id)

    activities = get_all_activities(garmin_client, garmin_fetch_limit)
    print(f"Fetched {len(activities)} activities from Garmin.")
    
    # --- GOOGLE SHEETS SYNC (Direct) ---
    if google_json and drive_folder_id:
        sync_to_google_sheet(activities, drive_folder_id, google_json)
    
    print("\n--- Starting Notion Sync ---")
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
                update_activity(notion_client, existing_activity['id'], activity, garmin_client)
            else:
                create_activity(notion_client, database_id, activity, garmin_client)
        except Exception as e:
            print(f"Error processing activity {activity.get('activityId')}, skipping: {e}")
            continue

