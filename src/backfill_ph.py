# -*- coding: utf-8 -*-
"""phase1のバックフィル: 全取得済み試合の_ph.jsonを現行コードで再計算(9/7)
目的: RE vs WPの並走検品データを全季分作る(WP主判定昇格の裁定材料)
Usage: python src/backfill_ph.py [開始MMDD=0801]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import iter_games  # noqa
from phase1 import analyze_ph, BASE  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "0801"
    done = fail = 0
    for mmdd, gid in iter_games():
        if mmdd < start:
            continue
        try:
            res = analyze_ph(mmdd, gid)
        except Exception as e:
            print(f"FAIL {mmdd}/{gid}: {e}", flush=True)
            fail += 1
            continue
        outp = os.path.join(BASE, "data", "out", mmdd, f"{gid}_ph.json")
        os.makedirs(os.path.dirname(outp), exist_ok=True)
        with open(outp, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        done += 1
        if done % 25 == 0:
            print(f"{done}試合完了(直近 {mmdd}/{gid})", flush=True)
    print(f"done={done} fail={fail}")


if __name__ == "__main__":
    main()
