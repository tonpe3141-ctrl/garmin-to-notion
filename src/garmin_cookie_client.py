"""
Cookie ベースの Garmin Connect クライアント。

garth / OAuth を使わず、ブラウザセッションのCookieで直接APIを叩く。
GarminClient (garminconnect) と同じインターフェースを実装。
"""
import requests


CONNECTAPI = "https://connectapi.garmin.com"
CONNECT = "https://connect.garmin.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "NK": "NT",
    "X-Requested-With": "XMLHttpRequest",
}


def parse_cookie_string(cookie_str: str) -> dict:
    """'key=val; key2=val2' 形式の文字列を dict に変換。"""
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


class _DummyGarth:
    """garth 互換シム（トークン保存ステップのエラー回避用）。"""
    def dumps(self) -> str:
        return ""


class GarminCookieClient:
    """Cookie ベースの Garmin Connect クライアント。"""

    def __init__(self, cookies: dict):
        self.session = requests.Session()
        self.session.cookies.update(cookies)
        self.session.headers.update(_HEADERS)
        self.garth = _DummyGarth()
        self.display_name = self._fetch_display_name()

    def _fetch_display_name(self) -> str:
        try:
            r = self.session.get(
                f"{CONNECT}/modern/proxy/userprofile-service/userprofile/personal-information",
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            return data.get("displayName") or data.get("userName", "")
        except Exception:
            return ""

    def get_full_name(self) -> str:
        """認証テスト兼フルネーム取得。失敗時は例外を送出。"""
        r = self.session.get(
            f"{CONNECT}/modern/proxy/userprofile-service/userprofile/personal-information",
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("fullName") or data.get("displayName") or data.get("userName", "")

    def get_activities(self, start: int, limit: int):
        r = self.session.get(
            f"{CONNECTAPI}/activitylist-service/activities/search/activities",
            params={"start": str(start), "limit": str(limit)},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_activity_splits(self, activity_id):
        r = self.session.get(
            f"{CONNECTAPI}/activity-service/activity/{activity_id}/splits",
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_activity_details(self, activity_id, maxchart=2000, maxpoly=4000):
        r = self.session.get(
            f"{CONNECTAPI}/activity-service/activity/{activity_id}/details",
            params={"maxChartSize": str(maxchart), "maxPolylineSize": str(maxpoly)},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_activity_weather(self, activity_id):
        r = self.session.get(
            f"{CONNECTAPI}/activity-service/activity/{activity_id}/weather",
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
