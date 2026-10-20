#!/usr/bin/env python3
"""
「成長の記録」タブの自己記録（5km・10km・ハーフ・フルの最速タイム）用に、Garmin の自己記録を書き出す。

    python3 scripts/export_base_pb.py  > base_pb.json

ローカルの ~/.garth の認証で Garmin Connect の自己記録（Personal Records）を読むだけで、何も書き込まない。
出力は {"5": {"sec": 秒, "d": "YYYY-MM-DD"}, "10": …, "21": …, "42": …} （見つからない距離は含めない）。
dashboard/index.html の `const BASE_PB = {…}` の中身に貼る。

Artifact の db（評価の履歴）のラップから数えられるのは 2026-09-02 以降の走りだけなので、それ以前のベストはこれで補う。
描画側は、ラップから数えた最速とこの値のうち速いほうを出す。
Garmin の自己記録の typeId: 3 = 5km, 4 = 10km, 5 = ハーフ, 6 = フル。
"""
import json
import os
import sys

import garminconnect

TYPE_TO_KEY = {3: "5", 4: "10", 5: "21", 6: "42"}

g = garminconnect.Garmin()
g.login(tokenstore=os.path.expanduser("~/.garth"))

out = {}
for pr in g.get_personal_record() or []:
    key = TYPE_TO_KEY.get(pr.get("typeId"))
    value = pr.get("value")
    if not key or not value:
        continue
    # 日付は走った日（現地時間）。取れなければ null（描画側は日付なしで出す）
    stamp = pr.get("prStartTimeLocal") or pr.get("prStartTimeGmtFormatted") or pr.get("actStartTimeGMT") or ""
    day = str(stamp)[:10] if len(str(stamp)) >= 10 and str(stamp)[4] == "-" else None
    out[key] = {"sec": round(value), "d": day}

if not out:
    print("5km・10km・ハーフ・フルの自己記録が見つからなかった", file=sys.stderr)
print(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
