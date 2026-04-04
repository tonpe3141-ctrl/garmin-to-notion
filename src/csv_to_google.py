"""
Garmin Connect から手動でダウンロードした CSV を
Google スプレッドシートと Google ドキュメントに同期するスクリプト。

【CSVのダウンロード方法】
1. https://connect.garmin.com/modern/activities にアクセス
2. ページ下部まで全アクティビティを読み込む（スクロールして全件表示）
3. 右上の「エクスポート CSV」をクリック
4. ダウンロードされた Activities.csv をこのリポジトリのルートに置く

【使い方】
  source .venv/bin/activate
  python src/csv_to_google.py
  # または特定のファイルを指定:
  python src/csv_to_google.py ~/Downloads/Activities.csv
"""
import csv
import json
import os
import re
import sys
from datetime import datetime
from typing import List, Optional

import pytz
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

local_tz = pytz.timezone('Asia/Tokyo')

# ─── アクティビティ種目マッピング ───────────────────────────────────────────
ACTIVITY_TYPE_MAP = {
    # 英語（Garmin CSV の "Activity Type" 列）→ 日本語
    "Running": "ランニング",
    "Treadmill Running": "ランニング",
    "Trail Running": "ランニング",
    "Cycling": "サイクリング",
    "Indoor Cycling": "サイクリング",
    "Walking": "ウォーキング",
    "Speed Walking": "ウォーキング",
    "Hiking": "ハイキング",
    "Strength Training": "筋トレ",
    "Barre": "筋トレ",
    "Yoga": "ヨガ/ピラティス",
    "Pilates": "ヨガ/ピラティス",
    "Stretching": "ストレッチ",
    "Meditation": "瞑想",
    "Swimming": "スイミング",
    "Rowing": "ローイング",
    "Indoor Rowing": "ローイング",
    "Cardio": "有酸素運動",
    "Indoor Cardio": "有酸素運動",
    "Elliptical": "有酸素運動",
    "Other": "その他",
}

SUBTYPE_MAP = {
    "Treadmill Running": "トレッドミル",
    "Trail Running": "トレイルラン",
    "Indoor Cycling": "室内サイクリング",
    "Speed Walking": "スピードウォーク",
    "Strength Training": "筋トレ",
    "Barre": "バー",
    "Yoga": "ヨガ",
    "Pilates": "ピラティス",
    "Indoor Rowing": "室内ローイング",
    "Indoor Cardio": "室内カーディオ",
}


def map_activity(activity_type_str: str, title: str = "") -> tuple[str, str]:
    """Garmin CSV の Activity Type を日本語に変換する。"""
    t = activity_type_str.strip()
    title_lower = title.lower()

    # タイトルで補正
    if "meditation" in title_lower or "瞑想" in title_lower:
        return "瞑想", "瞑想"
    if "barre" in title_lower:
        return "筋トレ", "バー"
    if "stretch" in title_lower or "ストレッチ" in title_lower:
        return "ストレッチ", "ストレッチ"

    jp_type = ACTIVITY_TYPE_MAP.get(t, t)
    jp_sub = SUBTYPE_MAP.get(t, jp_type)
    return jp_type, jp_sub


def parse_duration_to_min(duration_str: str) -> float:
    """'HH:MM:SS' または 'MM:SS' 形式を分に変換する。"""
    if not duration_str:
        return 0.0
    parts = duration_str.strip().split(":")
    try:
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return round(h * 60 + m + s / 60, 2)
        elif len(parts) == 2:
            m, s = int(parts[0]), int(parts[1])
            return round(m + s / 60, 2)
    except ValueError:
        pass
    return 0.0


def parse_pace(pace_str: str) -> str:
    """ペース文字列をそのまま返す（'5:30' など）。空なら空文字。"""
    if not pace_str or pace_str.strip() in ("--", ""):
        return ""
    return pace_str.strip()


def parse_float(s: str) -> float:
    """カンマや記号を除いて float に変換。失敗したら 0.0。"""
    if not s:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", s)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_int(s: str) -> int:
    """カンマや記号を除いて int に変換。失敗したら 0。"""
    return int(parse_float(s))


def load_csv(csv_path: str) -> List[dict]:
    """Garmin CSV を読み込んで dict のリストとして返す。"""
    activities = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            activities.append(row)
    print(f"  CSV から {len(activities)} 件のアクティビティを読み込みました。")
    return activities


def csv_row_to_sheet_row(row: dict) -> Optional[list]:
    """
    CSV の1行を Google Sheets の行に変換する。
    変換できない場合は None を返す。
    """
    try:
        # 日付: "2024-04-01 08:30:00" または "2024-04-01" 形式
        date_raw = row.get("Date", "").strip()
        if not date_raw:
            return None
        try:
            # 'YYYY-MM-DD HH:MM:SS' もしくは 'YYYY-MM-DD'
            if " " in date_raw:
                dt = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.strptime(date_raw, "%Y-%m-%d")
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            date_str = date_raw

        title = row.get("Title", "").strip()
        act_type_raw = row.get("Activity Type", "").strip()
        activity_type, activity_subtype = map_activity(act_type_raw, title)

        # 距離: CSV は km 表記が多いが、場合によりマイル/メートル
        distance_raw = parse_float(row.get("Distance", "0"))
        # Garmin CSV は km 単位が基本
        distance_km = round(distance_raw, 2)

        duration_min = parse_duration_to_min(row.get("Time", ""))
        calories = parse_int(row.get("Calories", "0"))

        avg_hr_raw = parse_int(row.get("Avg HR", "0"))
        avg_hr = avg_hr_raw if avg_hr_raw > 0 else ""
        max_hr_raw = parse_int(row.get("Max HR", "0"))
        max_hr = max_hr_raw if max_hr_raw > 0 else ""

        aerobic = round(parse_float(row.get("Aerobic TE", "0")), 1)

        # ペース（Avg Pace / Avg Speed）
        avg_pace = parse_pace(row.get("Avg Pace", row.get("Avg Speed", "")))

        return [
            date_str,
            activity_type,
            activity_subtype,
            title,
            distance_km,
            duration_min,
            calories,
            avg_pace,
            "",          # GAP (CSVには含まれない)
            avg_hr,
            max_hr,
            "",          # ピッチ (CSVには含まれない)
            "",          # ストライド (CSVには含まれない)
            aerobic,
            "",          # 無酸素TE (CSVには含まれない)
            "",          # ラップ (CSVには含まれない)
        ]
    except Exception as e:
        print(f"  ⚠ 行変換エラー: {e} | row: {dict(list(row.items())[:5])}")
        return None


def get_google_credentials(service_account_json_str: str) -> Optional[Credentials]:
    try:
        info = json.loads(service_account_json_str)
        return Credentials.from_service_account_info(
            info,
            scopes=[
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/documents",
            ],
        )
    except Exception as e:
        print(f"❌ Google Service Account 読み込みエラー: {e}")
        return None


def sync_csv_to_google_sheet(rows: List[list], folder_id: str, service_account_json: str):
    """変換済み行を Google スプレッドシートに書き込む。"""
    print("\n--- Google Sheets に同期中 ---")
    creds = get_google_credentials(service_account_json)
    if not creds:
        return

    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)

    file_name = "Garmin Running Log"
    query = (
        f"name = '{file_name}' and '{folder_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
    )
    results = drive_service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        spreadsheet_id = files[0]["id"]
        print(f"  既存スプレッドシートを更新します: {file_name}")
    else:
        meta = {
            "name": file_name,
            "parents": [folder_id],
            "mimeType": "application/vnd.google-apps.spreadsheet",
        }
        file = drive_service.files().create(body=meta, fields="id").execute()
        spreadsheet_id = file.get("id")
        print(f"  新規スプレッドシートを作成しました: {file_name}")

    header = [
        "日付", "種目", "詳細種目", "アクティビティ名", "距離 (km)", "タイム (分)",
        "カロリー", "平均ペース", "GAP", "平均心拍", "最大心拍", "ピッチ", "ストライド",
        "有酸素TE", "無酸素TE", "ラップ"
    ]
    values = [header] + rows

    sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    first_sheet_title = (
        sheet_metadata.get("sheets", [{}])[0].get("properties", {}).get("title", "Sheet1")
    )

    sheets_service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"'{first_sheet_title}'!A1:Z5000"
    ).execute()
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{first_sheet_title}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()

    print(f"  ✅ {len(rows)} 件を Google Sheets に書き込みました。")


def sync_running_to_google_doc(raw_activities: List[dict], folder_id: str, service_account_json: str):
    """ランニングアクティビティのみを Google ドキュメントに書き込む。"""
    print("\n--- Google Doc に同期中（ランニングのみ）---")
    creds = get_google_credentials(service_account_json)
    if not creds:
        return

    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)

    doc_name = "Garmin Running Log (Document)"
    list_query = (
        f"'{folder_id}' in parents and trashed = false "
        f"and mimeType = 'application/vnd.google-apps.document' "
        f"and name = '{doc_name}'"
    )
    results = drive_service.files().list(
        q=list_query, spaces="drive", fields="files(id, name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = results.get("files", [])

    if not files:
        print(f"  ❌ Google ドキュメント '{doc_name}' が見つかりません。")
        print("  Google Drive でドキュメントを作成してサービスアカウントに共有してください。")
        return

    document_id = files[0]["id"]
    print(f"  ドキュメント ID: {document_id}")

    # ランニングのみ抽出
    running_acts = []
    for row in raw_activities:
        act_type_raw = row.get("Activity Type", "").strip()
        title = row.get("Title", "").strip()
        jp_type, _ = map_activity(act_type_raw, title)
        if jp_type == "ランニング":
            running_acts.append(row)

    print(f"  ランニング {len(running_acts)} 件を書き込みます。")

    now_str = datetime.now(local_tz).strftime("%Y-%m-%d %H:%M JST")
    lines = [
        f"# ランニングログ (最終更新: {now_str})\n\n",
        "このドキュメントはGarminのランニングデータを自動的に更新します。\n"
        "AIコーチング用途として最新データを参照してください。\n\n",
        "---\n\n",
    ]

    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    written = 0
    for row in running_acts:
        try:
            date_raw = row.get("Date", "").strip()
            if " " in date_raw:
                dt = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.strptime(date_raw, "%Y-%m-%d")
            date_label = f"{dt.strftime('%Y-%m-%d')} ({weekdays[dt.weekday()]})"

            distance_km = round(parse_float(row.get("Distance", "0")), 2)
            duration_min = parse_duration_to_min(row.get("Time", ""))
            m_part = int(duration_min)
            s_part = int((duration_min - m_part) * 60)
            time_str = f"{m_part}:{s_part:02d}"

            avg_pace = parse_pace(row.get("Avg Pace", ""))
            avg_hr_raw = parse_int(row.get("Avg HR", "0"))
            max_hr_raw = parse_int(row.get("Max HR", "0"))
            calories = parse_int(row.get("Calories", "0"))
            aerobic = round(parse_float(row.get("Aerobic TE", "0")), 1)

            lines.append(f"## {date_label} ランニング\n")
            lines.append(f"- 距離: {distance_km} km\n")
            lines.append(f"- タイム: {time_str} ({avg_pace})\n")
            lines.append(f"- カロリー: {calories} kcal\n")
            if avg_hr_raw > 0:
                lines.append(f"- 平均心拍: {avg_hr_raw} bpm / 最大: {max_hr_raw} bpm\n")
            if aerobic > 0:
                lines.append(f"- 有酸素トレーニング効果: {aerobic}\n")
            lines.append("\n")
            written += 1
        except Exception as e:
            print(f"  ⚠ 行スキップ: {e}")
            continue

    full_text = "".join(lines)

    # ドキュメントを全削除 → 再書き込み
    doc = docs_service.documents().get(documentId=document_id).execute()
    content = doc.get("body", {}).get("content", [])
    end_index = 1
    for element in content:
        if "endIndex" in element:
            end_index = element["endIndex"]

    update_requests = []
    if end_index > 2:
        update_requests.append({
            "deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}
        })
    update_requests.append({
        "insertText": {"location": {"index": 1}, "text": full_text}
    })

    docs_service.documents().batchUpdate(
        documentId=document_id, body={"requests": update_requests}
    ).execute()

    print(f"  ✅ Google Doc を更新しました（{written} 件のランニング記録）。")


def main():
    # CSV ファイルのパスを決定
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        # デフォルト: リポジトリルートの Activities.csv
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(script_dir)
        csv_path = os.path.join(repo_root, "Activities.csv")

    if not os.path.exists(csv_path):
        print(f"❌ CSV ファイルが見つかりません: {csv_path}")
        print()
        print("【CSVのダウンロード方法】")
        print("1. https://connect.garmin.com/modern/activities を開く")
        print("2. ページを一番下までスクロールして全アクティビティを読み込む")
        print("3. 右上の「エクスポート CSV」をクリック")
        print(f"4. ダウンロードした Activities.csv を以下に置く:")
        print(f"   {csv_path}")
        print()
        print("または引数でパスを指定:")
        print("  python src/csv_to_google.py ~/Downloads/Activities.csv")
        sys.exit(1)

    google_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    drive_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

    if not google_json or not drive_folder_id:
        print("❌ 環境変数 GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_DRIVE_FOLDER_ID が未設定です。")
        print("   .env ファイルを確認してください。")
        sys.exit(1)

    print(f"\n📁 CSV を読み込み中: {csv_path}")
    raw_activities = load_csv(csv_path)

    if not raw_activities:
        print("❌ CSV にアクティビティが見つかりませんでした。")
        sys.exit(1)

    # Sheet 用に変換
    sheet_rows = []
    for row in raw_activities:
        converted = csv_row_to_sheet_row(row)
        if converted:
            sheet_rows.append(converted)

    print(f"  変換成功: {len(sheet_rows)} / {len(raw_activities)} 件")

    # Google Sheets に同期
    sync_csv_to_google_sheet(sheet_rows, drive_folder_id, google_json)

    # Google Doc に同期（ランニングのみ）
    sync_running_to_google_doc(raw_activities, drive_folder_id, google_json)

    print("\n✅ 完了！")


if __name__ == "__main__":
    main()
