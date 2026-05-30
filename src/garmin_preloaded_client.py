"""
Playwright が事前取得したデータを使う Garmin クライアント。

/gc-api/ エンドポイントへのリクエストが Python から 403 になる場合
（Garmin の DPoP / TLS フィンガープリント保護）でも、
Playwright のブラウザが事前に取得した JSON データを使うことで動作する。

データは /tmp/garmin_prefetch.json に保存される。
"""
import json
import os


PREFETCH_FILE = "/tmp/garmin_prefetch.json"


def is_available() -> bool:
    return os.path.exists(PREFETCH_FILE)


class _DummyGarth:
    def dumps(self) -> str:
        return ""


class GarminPreloadedClient:
    """Playwright が事前取得したデータを提供するクライアント。"""

    def __init__(self):
        self.garth = _DummyGarth()
        with open(PREFETCH_FILE) as f:
            data = json.load(f)
        self._activities: list = data.get("activities", [])
        self._splits: dict = data.get("splits", {})      # {activity_id: splits_data}
        self._details: dict = data.get("details", {})    # {activity_id: details_data}
        print(f"  ℹ プリロード: {len(self._activities)} アクティビティ, "
              f"{len(self._splits)} splits, {len(self._details)} details")

    def get_full_name(self) -> str:
        return "Garmin User (preloaded)"

    def get_activities(self, start: int, limit: int) -> list:
        return self._activities[start:start + limit]

    def get_activity_splits(self, activity_id):
        aid = str(activity_id)
        if aid in self._splits:
            return self._splits[aid]
        return []

    def get_activity_details(self, activity_id, maxchart=2000, maxpoly=4000):
        aid = str(activity_id)
        if aid in self._details:
            return self._details[aid]
        return {}

    def get_activity_weather(self, activity_id):
        return {}
