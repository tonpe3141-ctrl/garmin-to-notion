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
        # health: {"YYYY-MM-DD": {"hrv": {...}, "sleep": {...}, ...}}
        self._health: dict = data.get("health", {})
        self._race_predictions: dict = data.get("race_predictions", {})
        # 健康データのフォールバック先（Cookie / garth クライアント）。
        # プリフェッチに無い日付・種別はこちらへ委譲する。
        self._fallback = None
        self.display_name = None

        if len(self._activities) == 0:
            raise ValueError("プリフェッチファイルにアクティビティデータがありません")

        print(f"  ℹ プリロード: {len(self._activities)} アクティビティ, "
              f"{len(self._splits)} splits, {len(self._details)} details, "
              f"{len(self._health)} 日分の健康データ "
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

    # --- 日次健康データ API ---
    # Playwright が事前取得した健康データを返す。プリフェッチに無い場合は
    # set_fallback() で渡されたライブクライアント（Cookie / garth）へ委譲する。

    def set_fallback(self, client) -> None:
        """プリフェッチに無い健康データを取りにいくライブクライアントを登録する。"""
        self._fallback = client
        if client is not None:
            # display_name を要求する API（睡眠・RHR・レース予測）のため引き継ぐ
            name = getattr(client, "display_name", None)
            if name:
                self.display_name = name

    def has_health_data(self) -> bool:
        """プリフェッチに健康データが1日分でも含まれているか。"""
        return bool(self._health)

    def _health_value(self, date_str: str, key: str, empty):
        day = self._health.get(date_str) or {}
        value = day.get(key)
        return value if value not in (None, {}, []) else empty

    def _from_prefetch_or_fallback(self, date_str: str, key: str, empty, fb_call):
        """プリフェッチ優先、無ければフォールバッククライアントへ委譲する。"""
        value = self._health_value(date_str, key, None)
        if value is not None:
            return value
        if self._fallback is not None:
            return fb_call(self._fallback)
        return empty

    def get_hrv_data(self, date_str: str) -> dict:
        return self._from_prefetch_or_fallback(
            date_str, "hrv", {}, lambda c: c.get_hrv_data(date_str))

    def get_rhr_day(self, date_str: str) -> dict:
        return self._from_prefetch_or_fallback(
            date_str, "rhr", {}, lambda c: c.get_rhr_day(date_str))

    def get_sleep_data(self, date_str: str) -> dict:
        return self._from_prefetch_or_fallback(
            date_str, "sleep", {}, lambda c: c.get_sleep_data(date_str))

    def get_daily_steps(self, start: str, end: str) -> list:
        return self._from_prefetch_or_fallback(
            start, "steps", [], lambda c: c.get_daily_steps(start, end))

    def get_body_battery(self, start: str, end: str = None) -> list:
        return self._from_prefetch_or_fallback(
            start, "body_battery", [], lambda c: c.get_body_battery(start, end))

    def get_stress_data(self, date_str: str) -> dict:
        return self._from_prefetch_or_fallback(
            date_str, "stress", {}, lambda c: c.get_stress_data(date_str))

    def get_training_readiness(self, date_str: str):
        return self._from_prefetch_or_fallback(
            date_str, "training_readiness", {},
            lambda c: c.get_training_readiness(date_str))

    def get_max_metrics(self, date_str: str):
        return self._from_prefetch_or_fallback(
            date_str, "max_metrics", [], lambda c: c.get_max_metrics(date_str))

    def get_training_status(self, date_str: str) -> dict:
        return self._from_prefetch_or_fallback(
            date_str, "training_status", {},
            lambda c: c.get_training_status(date_str))

    def get_spo2_data(self, date_str: str) -> dict:
        return self._from_prefetch_or_fallback(
            date_str, "spo2", {}, lambda c: c.get_spo2_data(date_str))

    def get_respiration_data(self, date_str: str) -> dict:
        return self._from_prefetch_or_fallback(
            date_str, "respiration", {},
            lambda c: c.get_respiration_data(date_str))

    def get_race_predictions(self) -> dict:
        if self._race_predictions:
            return self._race_predictions
        if self._fallback is not None:
            return self._fallback.get_race_predictions()
        return {}
