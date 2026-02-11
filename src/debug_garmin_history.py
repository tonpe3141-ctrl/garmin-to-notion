import os
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from garminconnect import Garmin
import pytz

# Setup
load_dotenv()
local_tz = pytz.timezone('Asia/Tokyo')
UTC = timezone.utc

def main():
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    
    if not email or not password:
        print("Error: GARMIN_EMAIL or GARMIN_PASSWORD not set.")
        return

    print("Logging in to Garmin...")
    try:
        client = Garmin(email, password)
        client.login()
        print("Login succesful.")
    except Exception as e:
        print(f"Login failed: {e}")
        return

    print("\n--- TEST 1: Chunked Date Range (Last 60 days) ---")
    all_activities_chunked = []
    end_date = datetime.now(local_tz)
    final_start_date = end_date - timedelta(days=60)
    current_end = end_date
    
    while current_end > final_start_date:
        current_start = current_end - timedelta(days=6)
        start_str = current_start.strftime("%Y-%m-%d")
        end_str = current_end.strftime("%Y-%m-%d")
        
        print(f"Requesting {start_str} to {end_str}...", end=" ")
        try:
            activities = client.get_activities_by_date(start_str, end_str, "")
            count = len(activities) if activities else 0
            print(f"Found: {count}")
            if activities:
                all_activities_chunked.extend(activities)
        except Exception as e:
            print(f"Error: {e}")
            
        current_end = current_start - timedelta(days=1)

    print(f"Total found via Date Range: {len(all_activities_chunked)}")
    if all_activities_chunked:
        print(f"Oldest Activity: {all_activities_chunked[-1].get('startTimeLocal')}")
        print(f"Newest Activity: {all_activities_chunked[0].get('startTimeLocal')}")


    print("\n--- TEST 2: Pagination (First 200 items) ---")
    all_activities_paged = []
    try:
        batch = client.get_activities(0, 200)
        print(f"Fetched batch of {len(batch)}")
        all_activities_paged.extend(batch)
    except Exception as e:
        print(f"Pagination error: {e}")

    print(f"Total found via Pagination: {len(all_activities_paged)}")
    if all_activities_paged:
        # Sort to find oldest
        all_activities_paged.sort(key=lambda x: x.get('startTimeGMT'), reverse=True)
        print(f"Oldest Activity: {all_activities_paged[-1].get('startTimeLocal')}")
        print(f"Newest Activity: {all_activities_paged[0].get('startTimeLocal')}")

    print("\n--- COMPARISON ---")
    ids_chunked = set(a['activityId'] for a in all_activities_chunked)
    ids_paged = set(a['activityId'] for a in all_activities_paged)
    
    print(f"Unique IDs in Chunked: {len(ids_chunked)}")
    print(f"Unique IDs in Paged: {len(ids_paged)}")
    print(f"Intersection: {len(ids_chunked.intersection(ids_paged))}")
    
    missing_in_chunked = ids_paged - ids_chunked
    if missing_in_chunked:
        print(f"IDs missing from Chunked strategy (Sample): {list(missing_in_chunked)[:5]}")

if __name__ == "__main__":
    main()
