"""
Cookie ベースの Garmin Connect クライアント。

garth / OAuth を使わず、ブラウザセッションの Cookie で直接 API を叩く。
/oauth/exchange/user/2.0 を一切呼ばないため GitHub Actions のレート制限を回避できる。

エンドポイント試行順:
  1. connect.garmin.com/{path}             新アプリ BFF パス
  2. connect.garmin.com/modern/proxy/{path} 旧アプリ プロキシ
  3. connectapi.garmin.com/{path}           JWT_WEB を Bearer として使用（新認証方式）
"""
import json
import os
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

# Playwright が発見した動的 API パスを保存するファイル
_API_CONFIG_FILE = "/tmp/garmin_api_paths.json"


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
        # JWT_WEB を Bearer token として利用（connectapi への認証に使う）
        self.jwt_web = cookies.get("JWT_WEB", "")
        # Playwright が記録した動的 API パスを読み込む
        self._dynamic_paths: dict = {}
        if os.path.exists(_API_CONFIG_FILE):
            try:
                with open(_API_CONFIG_FILE) as f:
                    self._dynamic_paths = json.load(f)
                print(f"  ℹ Playwright が発見した動的 API パスを読み込みました: {list(self._dynamic_paths.keys())}")
            except Exception:
                pass
        self.display_name = self._fetch_display_name()

    def _build_candidates(self, path: str) -> list:
        """
        試行するURL候補リストを返す。各要素は (url, extra_headers) のタプル。
        """
        candidates = []

        # Playwright が発見したパスがあればそれを最優先
        if path in self._dynamic_paths:
            candidates.append((self._dynamic_paths[path], {}))

        # 新アプリ BFF の一般パスを試す
        candidates.append((f"{CONNECT}{path}", {}))
        candidates.append((f"{CONNECT}/modern/proxy{path}", {}))

        # JWT_WEB を Bearer として connectapi に試みる
        # JWT_WEB が新認証方式のアクセストークンであれば動作する
        if self.jwt_web:
            candidates.append((
                f"{CONNECTAPI}{path}",
                {"Authorization": f"Bearer {self.jwt_web}"},
            ))

        return candidates

    def _get(self, path: str, params: dict = None, timeout: int = 30):
        """
        複数エンドポイントを順番に試し、JSON レスポンスが得られた最初の結果を返す。
        全て失敗したら ValueError を raise する。
        """
        candidates = self._build_candidates(path)
        last_status = None

        for url, extra_headers in candidates:
            try:
                r = self.session.get(
                    url, params=params, timeout=timeout,
                    headers=extra_headers if extra_headers else None,
                )
                last_status = r.status_code
                if r.status_code in (401, 403):
                    continue  # 認証エラー → 次候補へ
                if r.status_code == 200 and _is_json_response(r):
                    # 成功したパスを動的パスとして記録
                    if url != candidates[0][0]:
                        self._dynamic_paths[path] = url
                    return r
            except Exception:
                pass

        raise ValueError(
            f"Cookie クライアント: {path} の全 API 候補で JSON 取得に失敗 "
            f"(最終ステータス={last_status})"
        )

    def _fetch_display_name(self) -> str:
        try:
            r = self._get_userinfo()
            data = r.json()
            return data.get("displayName") or data.get("userName", "")
        except Exception:
            return ""

    def _get_userinfo(self):
        """ユーザー情報を取得。複数エンドポイントを順番に試す。"""
        path = "/userprofile-service/userprofile/personal-information"
        candidates = [
            (f"{CONNECT}{path}", {}),
            (f"{CONNECT}/modern/proxy{path}", {}),
        ]
        if self.jwt_web:
            candidates.append((
                f"{CONNECTAPI}{path}",
                {"Authorization": f"Bearer {self.jwt_web}"},
            ))

        for url, extra_headers in candidates:
            try:
                r = self.session.get(
                    url, timeout=15,
                    headers=extra_headers if extra_headers else None,
                )
                if r.status_code in (401, 403):
                    continue
                if r.status_code == 200 and _is_json_response(r):
                    return r
            except Exception:
                pass

        raise ValueError(
            "userinfo エンドポイントが全て JSON を返しませんでした。"
            "JWT_WEB が有効か確認してください。"
        )

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
