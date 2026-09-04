# -*- coding: utf-8 -*-
"""過去日付のplaybyplay+indexを一括取得(直近成績・回別成績・打順トラッキング用)
Usage: python src/backfill.py 0801 0901   # 開始日〜終了日(含む)
既取得はファイル単位でスキップ。1リクエスト1.2秒ウェイト。
"""
import sys, os, time, datetime
from fetch import game_urls, get, save, RAW, NPB

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def daterange(mmdd0, mmdd1):
    d0 = datetime.date(2026, int(mmdd0[:2]), int(mmdd0[2:]))
    d1 = datetime.date(2026, int(mmdd1[:2]), int(mmdd1[2:]))
    d = d0
    while d <= d1:
        yield f"{d.month:02d}{d.day:02d}"
        d += datetime.timedelta(days=1)


def main(mmdd0, mmdd1):
    total = 0
    for mmdd in daterange(mmdd0, mmdd1):
        try:
            urls = game_urls(mmdd)
        except Exception as e:
            print(f"{mmdd}: schedule FAIL {e}")
            continue
        got = 0
        for u in urls:
            gid = u.rstrip("/").split("/")[-1]
            done = True
            for page in ("playbyplay.html", "index.html", "box.html"):
                path = os.path.join(RAW, mmdd, gid, page)
                if os.path.exists(path):
                    continue
                try:
                    html = get(NPB + u + page)
                    save(path, html)
                    total += 1
                except Exception as e:
                    print(f"  FAIL {mmdd}/{gid}/{page}: {e}")
                    done = False
                time.sleep(1.2)
            if done:
                got += 1
        print(f"{mmdd}: {got}/{len(urls)} games", flush=True)
    print(f"downloaded {total} new games")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
