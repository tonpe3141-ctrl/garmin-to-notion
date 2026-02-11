import os
from datetime import datetime
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
    
    for page in all_activities:
        props = page.get("properties", {})
        
        # Date Parsing & Formatting
        date_str = props.get('日付', {}).get('date', {}).get('start', '')
        if date_str:
            try:
                # Notion ISO date to datetime obj
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                # If naive, assume UTC or let JST strings be. But standard notion date is localized or UTC.
                # Just formatting:
                date_str = dt.strftime('%Y-%m-%d %H:%M')
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
            'https://www.googleapis.com/auth/spreadsheets'
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
        
    except Exception as e:
        print(f"Error interacting with Google Drive/Sheets: {e}")
        if "403" in str(e) and "Sheets API" in str(e):
            print("HINT: Have you enabled the 'Google Sheets API' in Google Cloud Console?")
        sys.exit(1)

if __name__ == "__main__":
    main()
