import os
from datetime import datetime, timezone, timedelta
import sys
from notion_client import Client
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
import json

def main():
    load_dotenv()
    
    # 1. Environment Setup
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DB_ID")
    
    # Google Auth can come from a file path OR a raw JSON string (better for GitHub Secrets)
    google_sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    target_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    
    if not all([notion_token, database_id, google_sa_json, target_folder_id]):
        print("Error: Missing environment variables.")
        print("Required: NOTION_TOKEN, NOTION_DB_ID, GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_DRIVE_FOLDER_ID")
        sys.exit(1)

    # 2. Fetch Data from Notion (All history or last 1 year)
    print("Fetching data from Notion...")
    notion = Client(auth=notion_token)
    
    query_params = {
        "database_id": database_id,
        "sorts": [{"property": "日付", "direction": "descending"}]
    }

    all_activities = []
    has_more = True
    start_cursor = None

    try:
        while has_more:
            if start_cursor:
                query_params["start_cursor"] = start_cursor
            
            response = notion.databases.query(**query_params)
            results = response.get("results", [])
            all_activities.extend(results)
            
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")
            
            if len(all_activities) > 500:
                break
                
    except Exception as e:
        print(f"Error fetching from Notion: {e}")
        sys.exit(1)

    print(f"Fetched {len(all_activities)} activities.")

    # 3. Format Data for Google Sheets
    # Prepare header and rows
    headers = [
        "Date", "Type", "Sub Type", "Name", "Distance (km)", "Time (min)", 
        "Pace (/km)", "GAP (/km)", "Avg HR", "Max HR", "Calories", 
        "Avg Power", "Max Power", 
        "Training Effect", "Aerobic TE", "Anaerobic TE", "Laps"
    ]
    rows = [headers]
    
    # Timezone
    jst = timezone(timedelta(hours=9))

    for page in all_activities:
        props = page.get("properties", {})
        
        # Date Parsing & Formatting
        date_str = props.get('日付', {}).get('date', {}).get('start', '')
        if date_str:
            try:
                # Notion ISO date to datetime obj
                if 'Z' in date_str:
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    dt = datetime.fromisoformat(date_str)
                
                # Convert to JST
                dt_jst = dt.astimezone(jst)
                date_str = dt_jst.strftime('%Y-%m-%d %H:%M')
            except ValueError:
                pass # keep original if parse fails
        
        # 2. Type & Sub Type
        activity_type = props.get("種目", {}).get("select", {}).get("name", "Unknown")
        sub_type = props.get("詳細種目", {}).get("select", {}).get("name", "-")
        
        # 3. Name
        activity_name_list = props.get("アクティビティ名", {}).get("title", [])
        activity_name = activity_name_list[0].get("text", {}).get("content", "") if activity_name_list else "Untitled"
        
        # 4. Metrics
        distance = props.get("距離 (km)", {}).get("number", 0)
        time_minutes = props.get("タイム (分)", {}).get("number", 0)
        calories = props.get("カロリー", {}).get("number", 0)
        
        # 5. Pace & GAP
        pace_list = props.get("平均ペース", {}).get("rich_text", [])
        pace = pace_list[0].get("text", {}).get("content", "") if pace_list else "-"
        
        gap_list = props.get("GAP", {}).get("rich_text", [])
        gap = gap_list[0].get("text", {}).get("content", "") if gap_list else "-"
        
        # 6. Heart Rate & Power
        avg_hr = props.get("平均心拍", {}).get("number", "0")
        max_hr = props.get("最大心拍", {}).get("number", "0")
        avg_power = props.get("平均パワー", {}).get("number", 0)
        max_power = props.get("最大パワー", {}).get("number", 0)
        
        # 7. Training Effect
        te_select = props.get("トレーニング効果", {}).get("select", {})
        training_effect = te_select.get("name", "-") if te_select else "-"
        
        aerobic_te = props.get("有酸素", {}).get("number", 0)
        anaerobic_te = props.get("無酸素", {}).get("number", 0)
        
        # 8. Laps
        laps_list = props.get("ラップ", {}).get("rich_text", [])
        laps = laps_list[0].get("text", {}).get("content", "") if laps_list else "-"
        
        rows.append([
            date_str,
            activity_type,
            sub_type,
            activity_name,
            distance,
            time_minutes,
            pace,
            gap,
            avg_hr,
            max_hr,
            calories,
            avg_power,
            max_power,
            training_effect,
            aerobic_te,
            anaerobic_te,
            laps
        ])

    # 4. Upload to Google Drive as Google Sheets
    print("Authenticating with Google Drive & Sheets...")
    try:
        scopes = [
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/documents'
        ]
        
        if google_sa_json.strip().startswith("{"):
            creds_info = json.loads(google_sa_json)
            creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        else:
            creds = Credentials.from_service_account_file(google_sa_json, scopes=scopes)

        if hasattr(creds, 'service_account_email'):
             print(f"Authenticated as Service Account: {creds.service_account_email}")
        
        drive_service = build('drive', 'v3', credentials=creds)
        sheets_service = build('sheets', 'v4', credentials=creds)
        
        # Search for existing Google Sheet named "Garmin Running Log"
        print(f"Checking contents of folder ID: {target_folder_id}...")
        sheet_name = "Garmin Running Log"
        # mimeType for Google Sheets is application/vnd.google-apps.spreadsheet
        list_query = f"'{target_folder_id}' in parents and trashed = false and mimeType = 'application/vnd.google-apps.spreadsheet'"
        results = drive_service.files().list(
            q=list_query, 
            spaces='drive', 
            fields='files(id, name, mimeType)', 
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
        ).execute()
        all_files = results.get('files', [])
        
        target_sheet = None
        for f in all_files:
            print(f" - Found: '{f['name']}' (ID: {f['id']})")
            if f['name'] == sheet_name:
                target_sheet = f
                break
        
        if target_sheet:
            spreadsheet_id = target_sheet['id']
            print(f"Found existing Google Sheet: '{target_sheet['name']}' (ID: {spreadsheet_id})")
            
            # Get spreadsheet metadata to find the correct sheet name
            spreadsheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheets = spreadsheet_metadata.get('sheets', [])
            if not sheets:
                print("Error: No sheets found in the spreadsheet.")
                sys.exit(1)
            
            # Use the first sheet's title
            first_sheet_title = sheets[0].get("properties", {}).get("title", "Sheet1")
            print(f"Using sheet: '{first_sheet_title}'")
            
            # 1. Clear existing content
            print("Clearing existing content...")
            sheets_service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"'{first_sheet_title}'!A1:Z1000"
            ).execute()
            
            # 2. Write new content
            print("Writing new data...")
            body = {
                'values': rows
            }
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{first_sheet_title}'!A1",
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            
            print(f"Google Sheet updated successfully! ({len(rows)} rows)")
            
        else:
            print(f"\nError: Google Sheet '{sheet_name}' not found in the folder.")
            print("Action Required:")
            print("1. Open Google Drive and go to your 'Garmin Data' folder.")
            print("2. Click 'New' > 'Google Sheets'.")
            print(f"3. Name it: '{sheet_name}'")
            print("4. (Optional) Rename the first sheet tab to 'Sheet1' if it isn't already.")
            print("5. Re-run this workflow.")
            sys.exit(1)

        # --- Google Doc Sync (ランニングのみ) ---
        running_rows = [rows[0]] + [r for r in rows[1:] if r[1] == "ランニング"]
        sync_to_google_doc(
            rows=running_rows,
            folder_id=target_folder_id,
            creds=creds,
            drive_service=drive_service
        )
        
    except Exception as e:
        print(f"Error interacting with Google Drive/Sheets: {e}")
        if "403" in str(e) and "Sheets API" in str(e):
            print("HINT: Have you enabled the 'Google Sheets API' in Google Cloud Console?")
        sys.exit(1)


def sync_to_google_doc(rows: list, folder_id: str, creds, drive_service) -> None:
    """Notionから取得したランニングデータをGoogle ドキュメントに書き込む"""
    print("\n--- Starting Google Doc Sync (Running Only) ---")
    
    doc_name = "Garmin Running Log (Document)"
    
    try:
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
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
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
        
        # ドキュメントの内容を組み立てる
        jst = timezone(timedelta(hours=9))
        now_str = datetime.now(jst).strftime('%Y-%m-%d %H:%M JST')
        
        lines = [f"# ランニングログ (最終更新: {now_str})\n\n"]
        lines.append(
            "このドキュメントはGarminのランニングデータを自動的に更新します。\n"
            "AIコーチング用途として最新データを参照してください。\n\n"
        )
        lines.append("---\n\n")
        
        # ヘッダー行を除いたデータ行を処理 (rows[0] はヘッダー)
        headers = rows[0]
        idx = {h: i for i, h in enumerate(headers)}
        
        # 過去2ヶ月以内のデータのみに絞り込む
        cutoff_date = datetime.now(jst) - timedelta(days=62)
        print(f"  Cutoff date: {cutoff_date.strftime('%Y-%m-%d')} (keeping records on/after this date)")
        
        def parse_date(date_val: str):
            """複数フォーマットの日付文字列をdatetimeにパースする"""
            for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                try:
                    return datetime.strptime(date_val[:len(fmt)], fmt).replace(tzinfo=jst)
                except ValueError:
                    continue
            return None
        
        filtered_rows = []
        excluded_count = 0
        for row in rows[1:]:
            date_val = row[idx.get("Date", 0)] if "Date" in idx else row[0]
            dt = parse_date(str(date_val))
            if dt is None:
                # パース失敗は除外しない（安全のため保持）
                print(f"  Warning: Could not parse date '{date_val}', keeping row.")
                filtered_rows.append(row)
            elif dt >= cutoff_date:
                filtered_rows.append(row)
            else:
                excluded_count += 1
        
        print(f"  Total: {len(rows)-1} records, kept: {len(filtered_rows)}, excluded (old): {excluded_count}")
        

        for row in filtered_rows:
            try:
                date_str = row[idx.get("Date", 0)] if "Date" in idx else row[0]
                distance = row[idx.get("Distance (km)", 4)] if "Distance (km)" in idx else row[4]
                time_min = row[idx.get("Time (min)", 5)] if "Time (min)" in idx else row[5]
                pace = row[idx.get("Pace (/km)", 6)] if "Pace (/km)" in idx else row[6]
                gap = row[idx.get("GAP (/km)", 7)] if "GAP (/km)" in idx else row[7]
                avg_hr = row[idx.get("Avg HR", 8)] if "Avg HR" in idx else row[8]
                max_hr = row[idx.get("Max HR", 9)] if "Max HR" in idx else row[9]
                aerobic_te = row[idx.get("Aerobic TE", 14)] if "Aerobic TE" in idx else (row[14] if len(row) > 14 else "")
                anaerobic_te = row[idx.get("Anaerobic TE", 15)] if "Anaerobic TE" in idx else (row[15] if len(row) > 15 else "")
                laps = row[idx.get("Laps", 16)] if "Laps" in idx else (row[16] if len(row) > 16 else "")
                
                # 時間 (分) を mm:ss 形式に変換
                try:
                    total_min = float(time_min)
                    m = int(total_min)
                    s = int((total_min - m) * 60)
                    time_str = f"{m}:{s:02d}"
                except:
                    time_str = str(time_min)
                
                lines.append(f"## {date_str} ランニング\n")
                lines.append(f"- 距離: {distance} km\n")
                lines.append(f"- タイム: {time_str} ({pace})\n")
                if gap and gap != "-":
                    lines.append(f"- GAP: {gap}\n")
                lines.append(f"- 平均心拍: {avg_hr} bpm / 最大: {max_hr} bpm\n")
                if aerobic_te:
                    lines.append(f"- 有酸素TE: {aerobic_te} / 無酸素TE: {anaerobic_te}\n")
                if laps and laps.strip():
                    lines.append("- ラップ:\n")
                    for lap_line in laps.strip().split("\n"):
                        if lap_line.strip():
                            lines.append(f"  {lap_line.strip()}\n")
                lines.append("\n")
            except Exception as e:
                print(f"  Warning: Skipping row due to error: {e}")
                continue
        
        full_text = "".join(lines)
        
        # 既存のドキュメントのコンテンツを取得して全削除→再書き込み
        doc = docs_service.documents().get(documentId=document_id).execute()
        content = doc.get('body', {}).get('content', [])
        
        # 末尾のインデックスを取得 (最低1)
        end_index = 1
        for element in content:
            if 'endIndex' in element:
                end_index = element['endIndex']
        
        requests = []
        
        # 既存テキストを全削除 (内容がある場合のみ)
        if end_index > 2:
            requests.append({
                'deleteContentRange': {
                    'range': {
                        'startIndex': 1,
                        'endIndex': end_index - 1
                    }
                }
            })
        
        # 新しいテキストを挿入
        requests.append({
            'insertText': {
                'location': {'index': 1},
                'text': full_text
            }
        })
        
        if requests:
            docs_service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()
        
        data_count = len(filtered_rows)
        print(f"Google Doc updated successfully! ({data_count} running records within last 2 months)")
        print(f"  Document URL: https://docs.google.com/document/d/{document_id}/edit")
        
    except Exception as e:
        print(f"Error syncing to Google Doc: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

