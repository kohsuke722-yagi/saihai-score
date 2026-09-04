# -*- coding: utf-8 -*-
"""試合終了待ち: 指定試合のboxに【試合終了】が出るまで10分間隔でポーリング(最大4時間)
Usage: python src/wait_end.py 0903 d-c-22 s-t-21
終了検知で exit 0 / タイムアウトで exit 1
"""
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get, NPB  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

mmdd, gids = sys.argv[1], sys.argv[2:]
deadline = time.time() + 4 * 3600
while time.time() < deadline:
    states = {}
    for g in gids:
        try:
            states[g] = "【試合終了】" in get(f"{NPB}/scores/2026/{mmdd}/{g}/box.html")
        except Exception as e:
            states[g] = False
            print(f"{g}: fetch err {e}", flush=True)
    print(f"status: " + " ".join(f"{g}={'終了' if v else '試合中'}" for g, v in states.items()), flush=True)
    if all(states.values()):
        print("all finished")
        sys.exit(0)
    time.sleep(600)
print("timeout")
sys.exit(1)
