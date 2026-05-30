"""
Cookie ベースの Garmin Connect クライアント。

garth / OAuth を使わず、ブラウザセッションの Cookie で直接 API を叩く。
/oauth/exchange/user/2.0 を一切呼ばないため GitHub Actions のレート制限を回避できる。

エンドポイント試行順:
  1. connect.garmin.com/gc-api/{path}      新アプリ BFF（JWT_WEB + Cookie で認証）
  2. connect.garmin.com/{path}             旧直接パス
  3. connect.garmin.com/modern/proxy/{path} 旧プロキシ
  4. connectapi.garmin.com/{path}           JWT_WEB を Bearer として使用（最終手段）
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
        # JWT_WEB を Bearer token として利用（connectapi への最終手段）
        self.jwt_web = cookies.get("JWT_WEB", "")
        # Playwright が記録した動的 API パスを読み込む
        self._dynamic_paths: dict = {}
        if os.path.exists(_API_CONFIG_FILE):
            try:
                with open(_API_CONFIG_FILE) as f:
                    self._dynamic_paths = json.load(f)
                print(f"  ℹ Playwright 発見パス: {len(self._dynamic_paths)} 件読み込み")
            except Exception:
                pass
        self.display_name = self._fetch_display_name()

    def _request(self, url: str, params: dict = None, extra_headers: dict = None,
                 timeout: int = 30, debug: bool = False):
        """単一 URL にリクエストを送り、200 + JSON なら Response を返す。失敗は None。"""
        try:
            r = self.session.get(
                url, params=params, timeout=timeout,
                headers=extra_headers if extra_headers else None,
                allow_redirects=True,
            )
            ct = r.headers.get("Content-Type", "")
            if debug:
                print(f"    [{r.status_code}] {url[:80]} ct={ct[:30]} final={r.url[:60]}")
            if r.status_code in (401, 403):
                return None
            if r.status_code == 200 and _is_json_response(r):
                return r
        except Exception as e:
            if debug:
                print(f"    [ERR] {url[:80]}: {e}")
        return None

    def _build_candidates(self, path: str) -> list:
        """
        試行する (url, extra_headers) のリストを返す。
        """
        candidates = []

        # Playwright が発見したパスを最優先
        if path in self._dynamic_paths:
            candidates.append((self._dynamic_paths[path], {}))

        # 新アプリ BFF: /gc-api/ プレフィックス（JWT_WEB Cookie で認証）
        candidates.append((f"{CONNECT}/gc-api{path}", {}))

        # 旧直接パス
        candidates.append((f"{CONNECT}{path}", {}))
        # 旧プロキシ
        candidates.append((f"{CONNECT}/modern/proxy{path}", {}))

        # JWT_WEB を Bearer として connectapi に試みる（最終手段）
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

        for url, extra_headers in candidates:
            r = self._request(url, params=params, extra_headers=extra_headers,
                              timeout=timeout)
            if r is not None:
                # 成功したパスを記録（次回のために動的パスへ追加）
                normalized = url.replace("https://connect.garmin.com/gc-api", "")
                if path != normalized:
                    self._dynamic_paths[path] = url
                return r

        raise ValueError(
            f"Cookie クライアント: '{path}' の全 API 候補で JSON 取得に失敗"
        )

    def _fetch_display_name(self) -> str:
        try:
            r = self._get_userinfo()
            data = r.json()
            return data.get("displayName") or data.get("userName", "")
        except Exception:
            return ""

    def _get_userinfo(self):
        """ユーザー情報を取得。新アプリ BFF パスを優先して試す。"""
        # 新アプリは /gc-api/ プレフィックスを使う。ユーザー ID 不要なパスを優先。
        gc_api_candidates = [
            (f"{CONNECT}/gc-api/userprofile-service/userprofile/user-settings/", {}),
            (f"{CONNECT}/gc-api/userprofile-service/userprofile/userProfileBase", {}),
            (f"{CONNECT}/gc-api/userprofile-service/userprofile/personal-information/", {}),
        ]
        legacy_candidates = [
            (f"{CONNECT}/userprofile-service/userprofile/personal-information", {}),
            (f"{CONNECT}/modern/proxy/userprofile-service/userprofile/personal-information", {}),
        ]
        connectapi_candidates = []
        if self.jwt_web:
            connectapi_candidates.append((
                f"{CONNECTAPI}/userprofile-service/userprofile/personal-information",
                {"Authorization": f"Bearer {self.jwt_web}"},
            ))

        all_candidates = gc_api_candidates + legacy_candidates + connectapi_candidates

        for url, extra_headers in all_candidates:
            r = self._request(url, extra_headers=extra_headers, debug=True)
            if r is not None:
                return r

        raise ValueError(
            "userinfo エンドポイントが全て JSON を返しませんでした "
            f"(jwt_web={'あり' if self.jwt_web else 'なし'})"
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
