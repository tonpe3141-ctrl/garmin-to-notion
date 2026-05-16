"""
Cookie ベースの Garmin Connect クライアント。

garth / OAuth を使わず、ブラウザセッションのCookieで直接APIを叩く。
/oauth/exchange/user/2.0 を一切呼ばないため GitHub Actions のレート制限を回避できる。

APIアクセスは connect.garmin.com/modern/proxy/... (Proxy経由) を優先し、
失敗した場合のみ connectapi.garmin.com 直接呼び出しにフォールバックする。
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

    def _get(self, path: str, params: dict = None, timeout: int = 30):
        """Proxy経由を試し、失敗したら connectapi 直接呼び出しにフォールバック。"""
        proxy_url = f"{CONNECT}/modern/proxy{path}"
        direct_url = f"{CONNECTAPI}{path}"

        # Proxy経由（セッションクッキーで認証できる）
        try:
            r = self.session.get(proxy_url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            # 401/403はfallthrough
        except Exception:
            pass

        # connectapi直接（旧動作との互換性）
        r = self.session.get(direct_url, params=params, timeout=timeout)
        r.raise_for_status()
        return r

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
        r = self._get(
            "/activitylist-service/activities/search/activities",
            params={"start": str(start), "limit": str(limit)},
        )
        return r.json()

    def get_activity_splits(self, activity_id):
        r = self._get(f"/activity-service/activity/{activity_id}/splits")
        return r.json()

    def get_activity_details(self, activity_id, maxchart=2000, maxpoly=4000):
        r = self._get(
            f"/activity-service/activity/{activity_id}/details",
            params={"maxChartSize": str(maxchart), "maxPolylineSize": str(maxpoly)},
        )
        return r.json()

    def get_activity_weather(self, activity_id):
        r = self._get(f"/activity-service/activity/{activity_id}/weather")
        return r.json()
