# -*- coding: utf-8 -*-
"""選手キャッシュの鮮度リフレッシュ(9/7監査#6: 無期限凍結で現役選手が古い成績のままになる)
- 前日出場した選手のうち、キャッシュが古い(7日+)か空(bat/pitともNone)のものを再取得
- 深夜便のDB再構築後に実行(batters/pitchers.jsonの前日行で出場者を特定)
Usage: python src/refresh_players.py [MMDD=昨日JST]
"""
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stats import fetch_player, CACHE  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JST = datetime.timezone(datetime.timedelta(hours=9))
MAX_FETCH = 120  # 礼儀上の上限(fetch_player内に1秒スリープあり)


def main():
    mmdd = sys.argv[1] if len(sys.argv) > 1 else \
        (datetime.datetime.now(JST) - datetime.timedelta(days=1)).strftime("%m%d")
    pids = set()
    for f in ("batters.json", "pitchers.json"):
        try:
            log = json.load(open(os.path.join(BASE, "data", "logs", f), encoding="utf-8"))
        except Exception:
            continue
        for pid, rows in log.items():
            if any(r[0] == mmdd for r in rows):
                pids.add(pid)
    today = datetime.datetime.now(JST).strftime("%m%d")

    def age_days(f0):
        try:
            a = datetime.date(2026, int(today[:2]), int(today[2:]))
            b = datetime.date(2026, int(f0[:2]), int(f0[2:]))
            return (a - b).days
        except Exception:
            return 999

    stale = []
    for pid in sorted(pids):
        cp = os.path.join(CACHE, f"{pid}.json")
        if not os.path.exists(cp):
            continue  # 未取得は試合処理時にfetch_playerが作る
        try:
            d = json.load(open(cp, encoding="utf-8"))
        except Exception:
            stale.append(pid)
            continue
        empty = d.get("bat") is None and d.get("pit") is None
        if empty or age_days(d.get("fetched", "0000")) >= 7:
            stale.append(pid)
    done = 0
    for pid in stale[:MAX_FETCH]:
        try:
            os.remove(os.path.join(CACHE, f"{pid}.json"))
            fetch_player(pid)
            done += 1
        except Exception as e:
            print(f"FAIL {pid}: {e}")
    print(f"{mmdd}出場{len(pids)}人中 要更新{len(stale)}人 → 再取得{done}人")


if __name__ == "__main__":
    main()
