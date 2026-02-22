[![Sync Garmin to Notion](https://github.com/chloevoyer/garmin-to-notion/actions/workflows/sync_garmin_to_notion.yml/badge.svg?branch=main)](https://github.com/chloevoyer/garmin-to-notion/actions/workflows/sync_garmin_to_notion.yml)
# Garmin to Notion Integration :watch:
This project connects your Garmin activities and personal records to your Notion database, allowing you to keep track of your performance metrics in one place.

## Features :sparkles:  
  🔄 Automatically sync Garmin activities to Notion in real-time  
  📊 Track detailed activity metrics (distance, pace, heart rate, dynamics)  
  👣 Log daily steps, HRV, resting heart rate, and sleep score
  📈 Generate automated weekly performance reports
  🤖 Zero-touch automation once configured  
  📱 Compatible with all Garmin activities and devices  
  🔧 Easy setup with automated database creation and minimal coding required

## Prerequisites :hammer_and_wrench:  
- A Notion account with API access.
- A Garmin Connect account to pull activity data.
- If you wish to sync your Peloton workouts with Garmin, see [peloton-to-garmin](https://github.com/philosowaffle/peloton-to-garmin)
## Getting Started :dart:
A detailed step-by-step guide is provided on my Notion template [here](https://chloevoyer.notion.site/Set-up-Guide-17915ce7058880559a3ac9f8a0720046).
For more advanced users, follow these steps to set up the integration:
### 1. Clone this GitHub Repository
### 2. Create Notion Parent Page
* Create a blank page in your Notion and copy its page ID from the URL (the string of characters at the end).
### 3. Create Notion Token
* Go to [Notion Integrations](https://www.notion.so/profile/integrations).
* Create a new integration and copy the integration token.
* Share the integration with the target page in Notion.
### 4. Set Environment Variables
* Create a `.env` file based on `.example.env`
* Fill in:
  * GARMIN_EMAIL
  * GARMIN_PASSWORD
  * NOTION_TOKEN
### 5. Automated Setup & Run Scripts
* Run the one-time setup script to create your 3 databases (Activities, Daily Logs, Weekly Reports) based on your parent page:
`python src/Notionデータベース一括作成.py`
* Run activity sync:
`python src/ガーミン活動データ取得.py` 
* Run daily log (steps, sleep, HRV) sync:
`python src/デイリーデータ取得.py`
* Run weekly report generation:
`python src/週間レポート生成.py`
## Example Configuration :pencil:  
You can customize the scripts to fit your needs by modifying environment variables and Notion database settings.  

Here is a screenshot of what my Notion dashboard looks like:  
![garmin-to-notion-template](https://github.com/user-attachments/assets/b37077cc-fe87-466f-9424-8ba9e4efa909)


My Notion template is available for free and can be duplicated to your Notion [here](https://www.notion.so/templates/fitness-tracker-738)

## Acknowledgements :raised_hands:  
- Reference dictionary and examples can be found in [cyberjunky/python-garminconnect](https://github.com/cyberjunky/python-garminconnect.git).
- This project was inspired by [n-kratz/garmin-notion](https://github.com/n-kratz/garmin-notion.git).
## Contributing :handshake:   
Contributions are welcome! If you find a bug or want to add a feature, feel free to open an issue or submit a pull request. Financial contributions are also greatly appreciated :blush:    

<a href="https://www.buymeacoffee.com/cvoyer" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174"></a>   

## :copyright: License  
This project is licensed under the MIT License. See the LICENSE file for more details.