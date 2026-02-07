import os
import datetime
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

    # 3. Format Data for NotebookLM
    journal_content = "# Garmin Running Journal\n\n"
    journal_content += f"Last Updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    for page in all_activities:
        props = page.get("properties", {})
        
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
        
        advice_list = props.get("AIコーチのアドバイス", {}).get("rich_text", [])
        advice = advice_list[0].get("text", {}).get("content", "") if advice_list else ""
        
        journal_content += f"## {date_str} - {activity_name}\n"
        journal_content += f"- Type: {activity_type}\n"
        journal_content += f"- Distance: {distance} km\n"
        journal_content += f"- Duration: {time_minutes} min\n"
        journal_content += f"- Pace: {pace} /km\n"
        journal_content += f"- Training Effect: {training_effect}\n"
        if advice:
            journal_content += f"- Coach Advice: {advice}\n"
        journal_content += "\n---\n\n"

    # 4. Upload to Google Drive as Google Docs format
    print("Authenticating with Google Drive...")
    try:
        if google_sa_json.strip().startswith("{"):
            creds_info = json.loads(google_sa_json)
            creds = Credentials.from_service_account_info(
                creds_info, 
                scopes=[
                    'https://www.googleapis.com/auth/drive',
                    'https://www.googleapis.com/auth/documents'
                ]
            )
        else:
            creds = Credentials.from_service_account_file(
                google_sa_json, 
                scopes=[
                    'https://www.googleapis.com/auth/drive',
                    'https://www.googleapis.com/auth/documents'
                ]
            )

        if hasattr(creds, 'service_account_email'):
             print(f"Authenticated as Service Account: {creds.service_account_email}")
        
        drive_service = build('drive', 'v3', credentials=creds)
        docs_service = build('docs', 'v1', credentials=creds)
        
        # Search for existing Google Doc named "Garmin Running Journal"
        print(f"Checking contents of folder ID: {target_folder_id}...")
        doc_name = "Garmin Running Journal"
        list_query = f"'{target_folder_id}' in parents and trashed = false"
        results = drive_service.files().list(
            q=list_query, 
            spaces='drive', 
            fields='files(id, name, mimeType)', 
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
        ).execute()
        all_files = results.get('files', [])
        
        target_doc = None
        for f in all_files:
            print(f" - Found: '{f['name']}' (Type: {f['mimeType']})")
            # Look for a Google Doc (either with or without spaces in name)
            if f['mimeType'] == 'application/vnd.google-apps.document':
                if 'Garmin' in f['name'] and 'Running' in f['name']:
                    target_doc = f
                    break
        
        if target_doc:
            doc_id = target_doc['id']
            print(f"Found existing Google Doc: '{target_doc['name']}' (ID: {doc_id})")
            
            # Get document to find the end index
            doc = docs_service.documents().get(documentId=doc_id).execute()
            
            # Clear existing content (delete from index 1 to end)
            end_index = doc['body']['content'][-1]['endIndex']
            
            requests = []
            if end_index > 1:
                requests.append({
                    'deleteContentRange': {
                        'range': {
                            'startIndex': 1,
                            'endIndex': end_index - 1
                        }
                    }
                })
            
            # Insert new content
            requests.append({
                'insertText': {
                    'location': {'index': 1},
                    'text': journal_content
                }
            })
            
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={'requests': requests}
            ).execute()
            
            print("Google Doc updated successfully!")
            
        else:
            print(f"\nError: No Google Doc found in the folder.")
            print("Action Required:")
            print("1. Open Google Drive and go to your 'Garmin Data' folder.")
            print("2. Click 'New' > 'Google Docs' > 'Blank document'.")
            print(f"3. Name it: '{doc_name}'")
            print("4. Re-run this workflow.")
            sys.exit(1)
        
    except Exception as e:
        print(f"Error interacting with Google Drive/Docs: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
