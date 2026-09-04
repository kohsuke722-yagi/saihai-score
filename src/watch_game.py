# -*- coding: utf-8 -*-
"""1試合見張り→終了直後に即カード生成(9/3社長指示「終わった直後に出したい」)
3分間隔で【試合終了】をポーリング。終了検知で当該試合のみ取得→采配計算→カードPNGまで一気に。
※重いDB再構築(palog等)は翌日用なのでここではやらない(カードは前日までのデータで計算=未来不参照)
Usage: python src/watch_game.py 0903 d-c-22
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get, save, NPB, RAW  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

mmdd, gid = sys.argv[1], sys.argv[2]
PY = sys.executable
SRC = os.path.dirname(os.path.abspath(__file__))
deadline = time.time() + 5 * 3600

while time.time() < deadline:
    try:
        box = get(f"{NPB}/scores/2026/{mmdd}/{gid}/box.html")
        # 「【試合終了】」バナーはページ確定まで出ないことがある→「◇終了 HH:MM」の刻印で判定
        done = ("【試合終了】" in box) or ("◇終了 " in box)
    except Exception as e:
        print(f"fetch err: {e}", flush=True)
        done = False
    print(f"{gid}: {'終了!' if done else '試合中...'}", flush=True)
    if done:
        save(os.path.join(RAW, mmdd, gid, "box.html"), box)
        for page in ("playbyplay.html", "index.html"):
            save(os.path.join(RAW, mmdd, gid, page),
                 get(f"{NPB}/scores/2026/{mmdd}/{gid}/{page}"))
            time.sleep(1.2)
        r1 = subprocess.run([PY, os.path.join(SRC, "phase1.py"), mmdd, gid],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(r1.stdout[-2000:] if r1.stdout else r1.stderr[-800:], flush=True)
        r2 = subprocess.run([PY, os.path.join(SRC, "build_card2.py"), mmdd, gid, "--png"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(r2.stdout if r2.stdout else r2.stderr[-800:], flush=True)
        # TikTokはXと同じcard_{gid}.png+固定CTA(data/out/tiktok_cta.png)をそのまま投稿(9/4社長裁定)
        print(f"CARD READY: {gid}")
        sys.exit(0)
    time.sleep(180)
print("timeout")
sys.exit(1)
