import os
import datetime
import sys
from notion_client import Client
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from dotenv import load_dotenv
import io
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
    
    # Sort descending to get latest first, but we want chronological for the log?
    # Usually a journal is chronological (Old -> New) or Reverse (New -> Old).
    # LLMs handle both, but New -> Old is often better for "Recent Context".
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
            
            # Safety break to avoid infinite loops or massive fetches (start with 1000 limit?)
            if len(all_activities) > 500:
                break
                
    except Exception as e:
        print(f"Error fetching from Notion: {e}")
        sys.exit(1)

    print(f"Fetched {len(all_activities)} activities.")

    # 3. Format Data for NotebookLM
    # We want a text format that explicitly describes the data points.
    
    journal_content = "# Garmin Running Journal\n\n"
    journal_content += f"Last Updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    for page in all_activities:
        props = page.get("properties", {})
        
        # Extract Fields
        date_prop = props.get("日付", {}).get("date", {})
        date_str = date_prop.get("start") if date_prop else "Unknown"
        
        activity_type = props.get("種目", {}).get("select", {}).get("name", "Unknown")
        activity_name_list = props.get("アクティビティ名", {}).get("title", [])
        activity_name = activity_name_list[0].get("text", {}).get("content", "") if activity_name_list else "Untitled"
        
        distance = props.get("距離 (km)", {}).get("number", 0)
        time_minutes = props.get("タイム (分)", {}).get("number", 0)
        
        pace_list = props.get("平均ペース", {}).get("rich_text", [])
        pace = pace_list[0].get("text", {}).get("content", "") if pace_list else "-"
        
        te_select = props.get("トレーニング効果", {}).get("select", {})
        training_effect = te_select.get("name", "-") if te_select else "-"
        
        # Advice
        advice_list = props.get("AIコーチのアドバイス", {}).get("rich_text", [])
        advice = advice_list[0].get("text", {}).get("content", "") if advice_list else ""
        
        # Format Entry
        journal_content += f"## {date_str} - {activity_name}\n"
        journal_content += f"- Type: {activity_type}\n"
        journal_content += f"- Distance: {distance} km\n"
        journal_content += f"- Duration: {time_minutes} min\n"
        journal_content += f"- Pace: {pace} /km\n"
        journal_content += f"- Training Effect: {training_effect}\n"
        if advice:
            journal_content += f"- Coach Advice: {advice}\n"
        journal_content += "\n---\n\n"

    # 4. Upload to Google Drive via Service Account
    print("Authenticating with Google Drive...")
    try:
        # Load JSON from string (env var) or file?
        # If env var starts with '{', treat as string content. Else treat as path.
        if google_sa_json.strip().startswith("{"):
            creds_info = json.loads(google_sa_json)
            creds = Credentials.from_service_account_info(
                creds_info, 
                scopes=['https://www.googleapis.com/auth/drive.file'] 
                # Use drive.file to only access files created by this app (safer) 
                # BUT user initiates shared folder. 'drive' or 'drive.file' needed.
                # If using Shared Folder, the SA needs to see it.
            )
        else:
            creds = Credentials.from_service_account_file(
                google_sa_json, 
                scopes=['https://www.googleapis.com/auth/drive']
            )
            
        service = build('drive', 'v3', credentials=creds)
        
        # Check if file exists in the folder
        file_name = "Garmin_Running_Journal.txt"
        
        # Query: name = '...' and '<folder_id>' in parents and trashed = false
        query = f"name = '{file_name}' and '{target_folder_id}' in parents and trashed = false"
        # supportAllDrives=True allows looking into Shared Drives if applicable
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)', supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files = results.get('files', [])
        
        media = MediaIoBaseUpload(io.BytesIO(journal_content.encode('utf-8')), mimetype='text/plain', resumable=True)
        
        if files:
            # Update existing file
            file_id = files[0]['id']
            print(f"Updating existing file: {file_name} (ID: {file_id})")
            service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True
            ).execute()
        else:
            # Cannot create new file because Service Accounts have 0 storage quota.
            # We must ask the user to create it first.
            print(f"Error: Target file '{file_name}' not found in folder.")
            print("Action Required: Please create an empty text file named 'Garmin_Running_Journal.txt' in your Google Drive folder manually.")
            print("Reason: Service Accounts cannot create new files (0 storage quota), they can only edit existing ones owned by you.")
            sys.exit(1)
            
        print("Upload successful!")
        
    except Exception as e:
        print(f"Error interacting with Google Drive: {e}")
        # Don't fail the whole workflow if Drive fails? Or should we?
        # Let's fail so user knows.
        sys.exit(1)

if __name__ == "__main__":
    main()
