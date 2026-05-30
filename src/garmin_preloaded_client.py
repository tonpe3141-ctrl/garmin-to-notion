"""
Playwright が事前取得したデータを使う Garmin クライアント。

/gc-api/ エンドポイントへのリクエストが Python から 403 になる場合
（Garmin の connect-csrf-token 要求 / DPoP 保護）でも、
Playwright のブラウザが事前に取得した JSON データを使うことで動作する。

データは /tmp/garmin_prefetch.json に保存される。
"""
import json
import os
import time


PREFETCH_FILE = "/tmp/garmin_prefetch.json"
MAX_AGE_SECONDS = 7200  # 2時間以上古いファイルは警告


def is_available() -> bool:
    if not os.path.exists(PREFETCH_FILE):
        return False
    age = time.time() - os.path.getmtime(PREFETCH_FILE)
    return age < MAX_AGE_SECONDS


class _DummyGarth:
    def dumps(self) -> str:
        return ""


class GarminPreloadedClient:
    """Playwright が事前取得したデータを提供するクライアント。"""

    def __init__(self):
        self.garth = _DummyGarth()
        if not os.path.exists(PREFETCH_FILE):
            raise FileNotFoundError(f"プリフェッチファイルが存在しません: {PREFETCH_FILE}")

        age = time.time() - os.path.getmtime(PREFETCH_FILE)
        if age > MAX_AGE_SECONDS:
            raise ValueError(
                f"プリフェッチファイルが古すぎます ({age/3600:.1f}時間)。"
                "Playwright ステップを再実行してください。"
            )

        with open(PREFETCH_FILE) as f:
            data = json.load(f)

        self._activities: list = data.get("activities", [])
        self._splits: dict = data.get("splits", {})
        self._details: dict = data.get("details", {})

        if len(self._activities) == 0:
            raise ValueError("プリフェッチファイルにアクティビティデータがありません")

        print(f"  ℹ プリロード: {len(self._activities)} アクティビティ, "
              f"{len(self._splits)} splits, {len(self._details)} details "
              f"(ファイル更新: {age:.0f}秒前)")

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
