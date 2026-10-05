#!/usr/bin/env python3
"""
「成長の記録」タブの月間走行距離・過去の月のカレンダー用に、日別の走行距離を書き出す。

    python3 scripts/export_base_km.py [開始日 YYYY-MM-DD] [終了日]  > base_km.json

ローカルの ~/.garth の認証で Garmin Connect から走行アクティビティを読むだけで、何も書き込まない。
出力は {"YYYY-MM-DD": km} （同じ日に複数本走った日は合計、小数1桁）。
dashboard/index.html の `const BASE_KM = {…}` の中身に貼る。

Artifact の db（評価の履歴）は 2026-09-02 からしか無いので、それ以前の距離はこれで補っている。
db に評価がある日は描画側が db を優先するため、基準データは古くなっても害はない。
"""
import json
import sys
import collections
import os

import garminconnect

RUN_TYPES = {"running", "trail_running", "treadmill_running", "track_running"}

start = sys.argv[1] if len(sys.argv) > 1 else "2025-10-01"
end = sys.argv[2] if len(sys.argv) > 2 else __import__("datetime").date.today().isoformat()

g = garminconnect.Garmin()
g.login(tokenstore=os.path.expanduser("~/.garth"))
days = collections.defaultdict(float)
for a in g.get_activities_by_date(start, end):
    if (a.get("activityType") or {}).get("typeKey") in RUN_TYPES:
        days[a["startTimeLocal"][:10]] += a["distance"] / 1000
out = {d: round(v, 1) for d, v in sorted(days.items()) if v > 0}
print(json.dumps(out, separators=(",", ":")))
