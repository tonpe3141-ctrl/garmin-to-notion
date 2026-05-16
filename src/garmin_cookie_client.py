"""
Cookie ベースの Garmin Connect クライアント。

garth / OAuth を使わず、ブラウザセッションの Cookie で直接 API を叩く。
/oauth/exchange/user/2.0 を一切呼ばないため GitHub Actions のレート制限を回避できる。

エンドポイント試行順:
  1. connect.garmin.com/{path}             新アプリ (/app) が使う直接パス
  2. connect.garmin.com/modern/proxy/{path} 旧アプリ (/modern) プロキシ
  3. connectapi.garmin.com/{path}           直接 API（OAuth 必要だが最終手段）
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
    "Origin": "https://connect.garmin.com",
    "Referer": "https://connect.garmin.com/app/home",
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


def _is_json_response(r) -> bool:
    """レスポンスが JSON として解析できるか確認。"""
    ct = r.headers.get("Content-Type", "")
    if "text/html" in ct:
        return False
    try:
        r.json()
        return True
    except Exception:
        return False


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
        """
        複数エンドポイントを順番に試し、JSON レスポンスが得られた最初の結果を返す。
        全て失敗したら最後のエラーを raise する。
        """
        candidates = [
            f"{CONNECT}{path}",               # 新アプリ直接パス
            f"{CONNECT}/modern/proxy{path}",   # 旧プロキシ
            f"{CONNECTAPI}{path}",             # connectapi 直接
        ]

        last_exc = None
        for url in candidates:
            try:
                r = self.session.get(url, params=params, timeout=timeout)
                if r.status_code == 200 and _is_json_response(r):
                    return r
            except Exception as e:
                last_exc = e

        # どれも JSON を返さなかった場合は最後の URL で raise_for_status
        r = self.session.get(candidates[-1], params=params, timeout=timeout)
        r.raise_for_status()
        return r

    def _fetch_display_name(self) -> str:
        try:
            r = self._get_userinfo()
            data = r.json()
            return data.get("displayName") or data.get("userName", "")
        except Exception:
            return ""

    def _get_userinfo(self):
        """ユーザー情報を取得。複数エンドポイントを試す。"""
        paths = [
            "/userprofile-service/userprofile/personal-information",
            "/modern/proxy/userprofile-service/userprofile/personal-information",
        ]
        for path in paths:
            try:
                r = self.session.get(f"{CONNECT}{path}", timeout=15)
                if r.status_code == 200 and _is_json_response(r):
                    return r
            except Exception:
                pass
        # 最後の手段
        r = self.session.get(
            f"{CONNECT}/modern/proxy/userprofile-service/userprofile/personal-information",
            timeout=15,
        )
        r.raise_for_status()
        if not _is_json_response(r):
            raise ValueError(f"userinfo endpoint returned non-JSON (status={r.status_code})")
        return r

    def get_full_name(self) -> str:
        """認証テスト兼フルネーム取得。失敗時は例外を送出。"""
        r = self._get_userinfo()
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
