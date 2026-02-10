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
        
        print("Fetching latest activity...")
        activities = client.get_activities(0, 1)
        if activities:
            latest = activities[0]
            print("\n=== Latest Activity Keys ===")
            print(json.dumps(list(latest.keys()), indent=2))
            
            print("\n=== Heart Rate Data? ===")
            hr_keys = [k for k in latest.keys() if 'hr' in k.lower() or 'heart' in k.lower()]
            print(hr_keys)
            for k in hr_keys:
                print(f"{k}: {latest[k]}")

            print("\n=== Available Methods on Client ===")
            methods = [m for m in dir(client) if not m.startswith('_')]
            print(methods)
            
            # Check for details/splits/laps
            activity_id = latest['activityId']
            print(f"\n=== Investigating Activity Details for ID: {activity_id} ===")
            
            # Try to fetch splits or details if method exists
            # Common methods in garminconnect: get_activity_splits, get_activity_details
            if 'get_activity_splits' in methods:
                try:
                    print("Fetching splits...")
                    splits = client.get_activity_splits(activity_id)
                    print(json.dumps(splits, indent=2))
                except Exception as e:
                    print(f"Error fetching splits: {e}")

            if 'get_activity_details' in methods:
                try:
                    print("Fetching details...")
                    details = client.get_activity_details(activity_id)
                    # Print summary of details (don't dump everything if huge)
                    print(json.dumps(list(details.keys()), indent=2))
                except Exception as e:
                    print(f"Error fetching details: {e}")
                    
            if 'get_activity_hr_in_timezones' in methods:
                 try:
                    print("Fetching HR zones...")
                    zones = client.get_activity_hr_in_timezones(activity_id)
                    print(json.dumps(zones, indent=2))
                 except Exception as e:
                    print(f"Error fetching HR zones: {e}")

        else:
            print("No activities found.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
