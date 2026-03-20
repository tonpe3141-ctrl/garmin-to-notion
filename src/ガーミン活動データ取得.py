import os
import json
from datetime import datetime, timedelta
from typing import List

import pytz
from dotenv import load_dotenv
from garminconnect import Garmin as GarminClient

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

def get_all_activities(garmin_client: GarminClient, max_limit: int = 2000) -> List[dict]:
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
            last_date = datetime.strptime(last_date_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.UTC).astimezone(local_tz)
            
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



def fetch_and_format_laps(garmin_client: GarminClient, activity_id: str) -> str:
    laps_text = ""
    splits = []
    try:
        detailed_splits = garmin_client.get_activity_splits(activity_id)
        if isinstance(detailed_splits, list):
            splits = detailed_splits
        elif isinstance(detailed_splits, dict):
            if 'splitSummaries' in detailed_splits: splits = detailed_splits['splitSummaries']
            elif 'lapSummaries' in detailed_splits: splits = detailed_splits['lapSummaries']
            elif 'lapDTOs' in detailed_splits: splits = detailed_splits['lapDTOs']
            else: splits = [] # Fallback
        else:
             splits = []
    except Exception as e:
        print(f"Warning: Could not fetch detailed splits for {activity_id}: {e}")
        return ""

    if splits:
        for i, split in enumerate(splits, 1):
            if not isinstance(split, dict): continue
            
            distance_km = round(split.get('distance', 0) / 1000, 2)
            duration_s = split.get('duration', 0)
            duration_str = format_duration(duration_s)
            avg_speed = split.get('averageSpeed', 0)
            pace = format_pace(avg_speed)
            
            raw_id = split.get('splitId') or split.get('lapIndex')
            
            split_type_val = split.get('splitType')
            split_type_key = ""
            if isinstance(split_type_val, dict): split_type_key = split_type_val.get('typeKey', '')
            elif isinstance(split_type_val, str): split_type_key = split_type_val
            
            type_label = ""
            if 'INTERVAL' in split_type_key.upper(): type_label = " [Run]"
            elif 'RECOVERY' in split_type_key.upper(): type_label = " [Rest]"
            
            if distance_km < 0.01 and duration_s < 5 and "RECOVERY" not in split_type_key.upper():
                continue

            lap_label = str(raw_id) if raw_id is not None else str(i)
            lap_hr = f" HR:{int(split.get('averageHR'))}" if split.get('averageHR') else ""
            
            laps_text += f"Lap {lap_label}{type_label}: {distance_km}km, {duration_str}, {pace}{lap_hr}\n"
            
    return laps_text[:2000] # Notion limit check

def garmin_enhance_activity(garmin_client: GarminClient, activity: dict) -> dict:
    """Fetch additional details for an activity using its activity_id."""
    activity_id = activity.get('activityId')
    
    try:
        # 1. Fetch Full Details if possible 
        try:
            full_activity = garmin_client.get_activity_details(activity_id)
            if full_activity:
                activity.update(full_activity) 
        except Exception as e:
            print(f"Warning: Could not fetch details for {activity_id}: {e}")
            
        # 2. Fetch Laps
        try:
            laps_text = fetch_and_format_laps(garmin_client, activity_id)
            activity['laps_text'] = laps_text
        except Exception as e:
            print(f"Warning: Could not fetch laps for {activity_id}: {e}")
        
        # 3. Fetch Weather
        try:
            weather = garmin_client.get_activity_weather(activity_id)
            if weather:
                activity['weather'] = weather
        except Exception as e:
            print(f"Warning: Could not fetch weather for {activity_id}: {e}")
            
    except Exception as e:
        print(f"    Warning: Enrichment failed for {activity_id}: {e}")
        
    return activity

def format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def get_google_credentials(service_account_json_str):
    try:
        info = json.loads(service_account_json_str)
        creds = Credentials.from_service_account_info(
            info, scopes=[
                'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/documents'
            ]
        )
        return creds
    except Exception as e:
        print(f"Error loading Google Service Account: {e}")
        return None

def sync_to_google_sheet(activities: List[dict], folder_id: str, service_account_json: str):
    print("\n--- Starting Google Sheets Sync (Direct from Garmin) ---")
    creds = get_google_credentials(service_account_json)
    if not creds: return

    try:
        drive_service = build('drive', 'v3', credentials=creds)
        sheets_service = build('sheets', 'v4', credentials=creds)
        
        file_name = "Garmin Running Log"
        query = f"name = '{file_name}' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files: spreadsheet_id = files[0]['id']
        else:
            file_metadata = {'name': file_name, 'parents': [folder_id], 'mimeType': 'application/vnd.google-apps.spreadsheet'}
            file = drive_service.files().create(body=file_metadata, fields='id').execute()
            spreadsheet_id = file.get('id')

        # Header with Laps restored
        header = ["日付", "種目", "詳細種目", "アクティビティ名", "距離 (km)", "タイム (分)", 
                  "カロリー", "平均ペース", "GAP", "平均心拍", "最大心拍", "ピッチ", "ストライド", 
                  "有酸素TE", "無酸素TE", "ラップ"]
        
        values = [header]
        
        for activity in activities:
            # Parse Date
            activity_date_raw = activity.get('startTimeGMT')
            date_str = datetime.strptime(activity_date_raw, '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.UTC).astimezone(local_tz).strftime('%Y-%m-%d %H:%M')
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
            
            avg_gap_speed = activity.get('avgGradeAdjustedSpeed')
            gap_str = format_pace(avg_gap_speed) if avg_gap_speed else "-"
            
            row = [
                date_str,
                activity_type,
                activity_subtype,
                activity_name,
                distance_km,
                duration_min,
                calories,
                avg_pace,
                gap_str,
                avg_hr,
                max_hr,
                cadence,
                stride,
                aerobic,
                anaerobic,
                activity.get('laps_text', "")
            ]
            values.append(row)
            
        # Write Data
        body = {'values': values}
        sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        first_sheet_title = sheet_metadata.get('sheets', '')[0].get('properties', {}).get('title', 'Sheet1')
        
        if len(values) > 1:
            print(f"Preparing to write {len(values)-1} rows. Range: {values[1][0]} ~ {values[-1][0]}")

        sheets_service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=f"'{first_sheet_title}'!A1:Z2000").execute()
        sheets_service.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=f"'{first_sheet_title}'!A1", valueInputOption='USER_ENTERED', body=body).execute()
        print(f"Successfully synced to Sheets.")
        
    except HttpError as err:
        print(f"Google API Error: {err}")


def sync_to_google_doc(activities: List[dict], folder_id: str, service_account_json: str) -> None:
    """Garminから取得したランニングデータをGoogle ドキュメントに書き込む"""
    print("\n--- Starting Google Doc Sync (Running Only) ---")
    
    creds = get_google_credentials(service_account_json)
    if not creds:
        return
    
    doc_name = "Garmin Running Log (Document)"
    
    try:
        drive_service = build('drive', 'v3', credentials=creds)
        docs_service = build('docs', 'v1', credentials=creds)
        
        # 既存ドキュメントを検索
        list_query = (
            f"'{folder_id}' in parents and trashed = false "
            f"and mimeType = 'application/vnd.google-apps.document' "
            f"and name = '{doc_name}'"
        )
        results = drive_service.files().list(
            q=list_query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        files = results.get('files', [])
        
        if files:
            document_id = files[0]['id']
            print(f"Found existing document. ID: {document_id}")
        else:
            print(f"\nError: Google Document '{doc_name}' not found in the folder.")
            print("Action Required:")
            print("1. Open Google Drive and go to your Garmin data folder.")
            print("2. Click 'New' > 'Google Docs'.")
            print(f"3. Name it: '{doc_name}'")
            print("4. Re-run this script.")
            return
        
        # ドキュメントのテキストを組み立てる
        now_str = datetime.now(local_tz).strftime('%Y-%m-%d %H:%M JST')
        lines = [f"# ランニングログ (最終更新: {now_str})\n\n"]
        lines.append(
            "このドキュメントはGarminのランニングデータを自動的に更新します。\n"
            "AIコーチング用途として最新データを参照してください。\n\n"
        )
        lines.append("---\n\n")
        
        # ランニングのみフィルタリング
        running_acts = [
            a for a in activities
            if format_activity_type(
                a.get('activityType', {}).get('typeKey', ''), a.get('activityName', '')
            )[0] == 'ランニング'
        ]
        
        print(f"  Writing {len(running_acts)} running activities to document...")
        
        for activity in running_acts:
            try:
                activity_date_raw = activity.get('startTimeGMT')
                activity_date_jst = datetime.strptime(
                    activity_date_raw, '%Y-%m-%d %H:%M:%S'
                ).replace(tzinfo=pytz.UTC).astimezone(local_tz)
                date_str = activity_date_jst.strftime('%Y-%m-%d (%a)')
                
                distance_km = round(activity.get('distance', 0) / 1000, 2)
                duration_min = activity.get('duration', 0) / 60
                m = int(duration_min)
                s = int((duration_min - m) * 60)
                time_str = f"{m}:{s:02d}"
                
                avg_pace = format_pace(activity.get('averageSpeed', 0))
                avg_gap_speed = activity.get('avgGradeAdjustedSpeed')
                gap_str = format_pace(avg_gap_speed) if avg_gap_speed else None
                avg_hr = round(activity.get('averageHR')) if activity.get('averageHR') else None
                max_hr_val = round(activity.get('maxHR')) if activity.get('maxHR') else None
                aerobic_te = round(activity.get('aerobicTrainingEffect', 0), 1)
                anaerobic_te = round(activity.get('anaerobicTrainingEffect', 0), 1)
                te_label = format_training_effect(activity.get('trainingEffectLabel', 'Unknown'))
                laps_text = activity.get('laps_text', '')
                
                lines.append(f"## {date_str} ランニング\n")
                lines.append(f"- 距離: {distance_km} km\n")
                lines.append(f"- タイム: {time_str} ({avg_pace})\n")
                if gap_str:
                    lines.append(f"- GAP: {gap_str}\n")
                if avg_hr:
                    lines.append(f"- 平均心拍: {avg_hr} bpm / 最大: {max_hr_val} bpm\n")
                lines.append(f"- トレーニング効果: {te_label} (有酸素TE: {aerobic_te} / 無酸素TE: {anaerobic_te})\n")
                if laps_text and laps_text.strip():
                    lines.append("- ラップ:\n")
                    for lap_line in laps_text.strip().split('\n'):
                        if lap_line.strip():
                            lines.append(f"  {lap_line.strip()}\n")
                lines.append("\n")
            except Exception as e:
                print(f"  Warning: Skipping activity due to error: {e}")
                continue
        
        full_text = "".join(lines)
        
        # ドキュメントを全削除→再書き込み
        doc = docs_service.documents().get(documentId=document_id).execute()
        content = doc.get('body', {}).get('content', [])
        end_index = 1
        for element in content:
            if 'endIndex' in element:
                end_index = element['endIndex']
        
        update_requests = []
        if end_index > 2:
            update_requests.append({
                'deleteContentRange': {
                    'range': {'startIndex': 1, 'endIndex': end_index - 1}
                }
            })
        update_requests.append({
            'insertText': {
                'location': {'index': 1},
                'text': full_text
            }
        })
        
        docs_service.documents().batchUpdate(
            documentId=document_id,
            body={'requests': update_requests}
        ).execute()
        
        print(f"Google Doc updated successfully! ({len(running_acts)} running records)")
        print(f"  Document URL: https://docs.google.com/document/d/{document_id}/edit")
        
    except HttpError as err:
        print(f"Google API Error (Docs): {err}")
    except Exception as e:
        print(f"Error syncing to Google Doc: {e}")
        import traceback
        traceback.print_exc()


def sync_doc_from_garmin(garmin_client: GarminClient, folder_id: str, service_account_json: str) -> None:
    """Garminから過去90日のランニングデータを独立取得し、Google ドキュメントに書き込む。
    GARMIN_ACTIVITIES_FETCH_LIMIT に関係なく常に全期間のランニング履歴を反映する。
    """
    print("\n--- Starting Google Doc Sync (Running Only, independent full fetch) ---")

    # --- 1. Garminから独立して90日分を全量取得 ---
    target_history_days = 90
    cutoff_date = datetime.now(local_tz) - timedelta(days=target_history_days)
    all_activities = []
    batch_size = 50
    start_index = 0
    print(f"  Fetching all activities for last {target_history_days} days from Garmin...")
    while True:
        try:
            batch = garmin_client.get_activities(start_index, batch_size)
            if not batch:
                break
            all_activities.extend(batch)
            last_date_str = batch[-1].get('startTimeGMT', '')
            if last_date_str:
                last_date = datetime.strptime(last_date_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.UTC).astimezone(local_tz)
                if last_date < cutoff_date:
                    break
            if len(all_activities) >= 2000:
                break
            start_index += batch_size
        except Exception as e:
            print(f"  Warning: fetch stopped at index {start_index}: {e}")
            break
    print(f"  Fetched {len(all_activities)} total activities.")

    # ランニングのみ抽出（新しい順）
    running_acts = [
        a for a in all_activities
        if format_activity_type(
            a.get('activityType', {}).get('typeKey', ''), a.get('activityName', '')
        )[0] == 'ランニング'
    ]
    running_acts.sort(key=lambda a: a.get('startTimeGMT', ''), reverse=True)
    print(f"  {len(running_acts)} running activities found. Fetching details & laps...")

    # ランニングのみ詳細取得（ラップ・心拍・動的指標）
    enriched_runs = []
    for i, act in enumerate(running_acts, 1):
        print(f"  Enriching {i}/{len(running_acts)}: {act.get('startTimeGMT', '')[:10]}", end=" ", flush=True)
        enriched = garmin_enhance_activity(garmin_client, act)
        enriched_runs.append(enriched)
        print("done")
    print(f"  Enrichment complete for {len(enriched_runs)} running activities.")

    creds = get_google_credentials(service_account_json)
    if not creds:
        return

    doc_name = "Garmin Running Log (Document)"

    try:
        drive_service = build('drive', 'v3', credentials=creds)
        docs_service = build('docs', 'v1', credentials=creds)

        list_query = (
            f"'{folder_id}' in parents and trashed = false "
            f"and mimeType = 'application/vnd.google-apps.document' "
            f"and name = '{doc_name}'"
        )
        results = drive_service.files().list(
            q=list_query, spaces='drive', fields='files(id, name)',
            supportsAllDrives=True, includeItemsFromAllDrives=True
        ).execute()
        files = results.get('files', [])

        if not files:
            print(f"\nError: Google Document '{doc_name}' not found in the folder.")
            print("Action Required:")
            print("1. Open Google Drive and go to your Garmin data folder.")
            print("2. Click 'New' > 'Google Docs'.")
            print(f"3. Name it: '{doc_name}'")
            print("4. Re-run this script.")
            return

        document_id = files[0]['id']
        print(f"  Found document. ID: {document_id}")

        # --- 2. テキスト組み立て ---
        now_str = datetime.now(local_tz).strftime('%Y-%m-%d %H:%M JST')
        lines = [f"# ランニングログ (最終更新: {now_str})\n\n"]
        lines.append(
            "このドキュメントはGarminのランニングデータを自動的に更新します。\n"
            "AIコーチング用途として最新データを参照してください。\n\n"
        )
        lines.append("---\n\n")

        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for activity in enriched_runs:
            try:
                activity_date_raw = activity.get('startTimeGMT')
                activity_date_jst = datetime.strptime(
                    activity_date_raw, '%Y-%m-%d %H:%M:%S'
                ).replace(tzinfo=pytz.UTC).astimezone(local_tz)
                date_label = f"{activity_date_jst.strftime('%Y-%m-%d')} ({weekdays[activity_date_jst.weekday()]})"

                distance_km = round(activity.get('distance', 0) / 1000, 2)
                duration_min = activity.get('duration', 0) / 60
                m_part = int(duration_min)
                s_part = int((duration_min - m_part) * 60)
                time_str = f"{m_part}:{s_part:02d}"

                avg_pace = format_pace(activity.get('averageSpeed', 0))
                avg_gap_speed = activity.get('avgGradeAdjustedSpeed')
                gap_str = format_pace(avg_gap_speed) if avg_gap_speed else None
                avg_hr = round(activity.get('averageHR')) if activity.get('averageHR') else None
                max_hr_val = round(activity.get('maxHR')) if activity.get('maxHR') else None
                aerobic_te = round(activity.get('aerobicTrainingEffect', 0), 1)
                anaerobic_te = round(activity.get('anaerobicTrainingEffect', 0), 1)
                te_label = format_training_effect(activity.get('trainingEffectLabel', 'Unknown'))
                calories = round(activity.get('calories', 0))

                # ランニングダイナミクス
                cadence = round(activity.get('averageRunningCadenceInStepsPerMinute', 0)) if activity.get('averageRunningCadenceInStepsPerMinute') else None
                stride = round(activity.get('averageStrideLength', 0) / 100, 2) if activity.get('averageStrideLength') else None
                gct = round(activity.get('avgGroundContactTime')) if activity.get('avgGroundContactTime') else None
                vo = round(activity.get('avgVerticalOscillation', 0) / 10, 1) if activity.get('avgVerticalOscillation') else None
                balance = activity.get('avgGroundContactBalance')
                if balance:
                    left_b = round(balance / 100, 1)
                    balance_str = f"L {left_b}% / R {round(100 - left_b, 1)}%"
                else:
                    balance_str = None

                laps_text = activity.get('laps_text', '')

                lines.append(f"## {date_label} ランニング\n")
                lines.append(f"- 距離: {distance_km} km\n")
                lines.append(f"- タイム: {time_str} ({avg_pace})\n")
                if gap_str:
                    lines.append(f"- GAP: {gap_str}\n")
                lines.append(f"- カロリー: {calories} kcal\n")
                if avg_hr:
                    lines.append(f"- 平均心拍: {avg_hr} bpm / 最大: {max_hr_val} bpm\n")
                lines.append(f"- トレーニング効果: {te_label} (有酸素TE: {aerobic_te} / 無酸素TE: {anaerobic_te})\n")
                # ランニングダイナミクス
                dynamics_parts = []
                if cadence: dynamics_parts.append(f"ピッチ: {cadence} spm")
                if stride: dynamics_parts.append(f"ストライド: {stride} m")
                if gct: dynamics_parts.append(f"接地時間: {gct} ms")
                if vo: dynamics_parts.append(f"上下動: {vo} cm")
                if balance_str: dynamics_parts.append(f"左右バランス: {balance_str}")
                if dynamics_parts:
                    lines.append(f"- ランニングダイナミクス: {' / '.join(dynamics_parts)}\n")
                if laps_text and laps_text.strip():
                    lines.append("- ラップ:\n")
                    for lap_line in laps_text.strip().split('\n'):
                        if lap_line.strip():
                            lines.append(f"  {lap_line.strip()}\n")
                lines.append("\n")
            except Exception as e:
                print(f"  Warning: Skipping activity due to error: {e}")
                continue

        full_text = "".join(lines)

        # --- 3. ドキュメントを全削除→再書き込み ---
        doc = docs_service.documents().get(documentId=document_id).execute()
        content = doc.get("body", {}).get("content", [])
        end_index = 1
        for element in content:
            if "endIndex" in element:
                end_index = element["endIndex"]

        update_requests = []
        if end_index > 2:
            update_requests.append({
                "deleteContentRange": {
                    "range": {"startIndex": 1, "endIndex": end_index - 1}
                }
            })
        update_requests.append({
            "insertText": {
                "location": {"index": 1},
                "text": full_text
            }
        })

        docs_service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": update_requests}
        ).execute()

        print(f"Google Doc updated successfully! ({len(running_acts)} running records)")
        print(f"  Document URL: https://docs.google.com/document/d/{document_id}/edit")

    except HttpError as err:
        print(f"Google API Error (Docs): {err}")
    except Exception as e:
        print(f"Error syncing to Google Doc: {e}")
        import traceback
        traceback.print_exc()

def main():
    load_dotenv()
    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    garmin_fetch_limit = int(os.getenv("GARMIN_ACTIVITIES_FETCH_LIMIT", "200"))

    google_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    drive_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

    token_dir = os.path.expanduser("~/.garth")
    tokens_b64 = os.getenv("GARTH_TOKENS_B64")

    # Priority 1: Actions cache (~/.garth) - most recently refreshed tokens
    # Priority 2: GitHub Secret (GARTH_TOKENS_B64) - initial tokens set manually
    # Priority 3: Fresh login - last resort (may hit Garmin rate limit)
    garmin_client = None
    try:
        garmin_client = GarminClient()
        garmin_client.login(tokenstore=token_dir)
        print("Logged in using cached Garmin tokens (~/.garth)")
    except Exception as e1:
        if tokens_b64:
            try:
                garmin_client = GarminClient()
                garmin_client.login(tokenstore_base64=tokens_b64)
                garmin_client.garth.dump(token_dir)
                print("Logged in using GARTH_TOKENS_B64 secret, tokens saved to cache")
            except Exception as e2:
                print(f"GARTH_TOKENS_B64 login failed: {e2}")
                garmin_client = None
        if garmin_client is None:
            print("Falling back to fresh login (password)...")
            garmin_client = GarminClient(garmin_email, garmin_password)
            garmin_client.login()
            garmin_client.garth.dump(token_dir)
            print("Fresh login successful, tokens saved")

    # 1. Fetch Summaries
    activities = get_all_activities(garmin_client, garmin_fetch_limit)
    print(f"Fetched {len(activities)} activities. Starting enrichment (fetching details/laps)...")

    # 2. Enrich Data (Fetch Details & Laps)
    enriched_activities = []
    for act in activities:
        enriched = garmin_enhance_activity(garmin_client, act)
        enriched_activities.append(enriched)
    print("\nEnrichment complete.")

    # 3. Sync to Google Sheets
    if google_json and drive_folder_id:
        sync_to_google_sheet(enriched_activities, drive_folder_id, google_json)

    # 4. Sync to Google Doc (Running only, always fetches full 90-day history independently)
    if google_json and drive_folder_id:
        sync_doc_from_garmin(garmin_client, drive_folder_id, google_json)


if __name__ == "__main__":
    main()

