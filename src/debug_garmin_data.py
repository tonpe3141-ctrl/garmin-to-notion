import os
import json
from garminconnect import Garmin
from dotenv import load_dotenv

def main():
    load_dotenv()
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    
    if not email or not password:
        print("Error: GARMIN_EMAIL and GARMIN_PASSWORD are required.")
        return

    try:
        print("Logging in to Garmin...")
        client = Garmin(email, password)
        client.login()
        
        print("Fetching latest 5 activities...")
        activities = client.get_activities(0, 5)
        if activities:
            for idx, act in enumerate(activities):
                act_id = act['activityId']
                name = act['activityName']
                date = act['startTimeGMT']
                print(f"\n--- Activity {idx+1}: {name} ({date}) [ID: {act_id}] ---")
                
                # Check splits
                splits = act.get('splitSummaries', [])
                print(f"Splits found: {len(splits)}")
                for i, s in enumerate(splits):
                    # Print essential split data
                    sid = s.get('splitId')
                    dist = s.get('distance')
                    dur = s.get('duration')
                    print(f"  - Split[{i}] ID={sid}: Dist={dist}m, Time={dur}s, Keys={list(s.keys())}")
        else:
            print("No activities found.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
