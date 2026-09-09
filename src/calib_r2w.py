# -*- coding: utf-8 -*-
"""R2W_AVG較正(9/9フェーズ3・9/7残穴#3): 翌日コストの点→勝率換算=0.10(仮置き)を実測。
定義: 実際にリリーフが投入された全場面での「1失点の勝率価値」ΔWPの平均
(=明日そのアームが必要になる場面の平均レバレッジの代理)。データ=全季_ph.jsonのrelief記録
Usage: python src/calib_r2w.py
"""
import glob
import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import wp_of  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    vals = []
    for f in glob.glob(os.path.join(BASE, "data", "out", "*", "*_ph.json")):
        try:
            recs = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for r in recs:
            if r.get("kind") != "relief" or r.get("accident"):
                continue
            try:
                w0 = wp_of(r["inning"], r["half"], r.get("diff") or 0,
                           r.get("state") or "", r.get("outs") or 0)
                w1 = wp_of(r["inning"], r["half"], (r.get("diff") or 0) + 1,
                           r.get("state") or "", r.get("outs") or 0)
            except Exception:
                continue
            if w0 is None or w1 is None:
                continue
            vals.append(abs(w1 - w0))
    if not vals:
        print("WP表が使えません")
        return
    vals.sort()
    n = len(vals)
    print(f"リリーフ投入場面 {n}件の「1点の勝率価値」ΔWP:")
    print(f"  平均 {sum(vals) / n:.4f} / 中央値 {vals[n // 2]:.4f} / "
          f"四分位 [{vals[n // 4]:.4f}, {vals[3 * n // 4]:.4f}]")
    print(f"  現行仮置き R2W_AVG=0.10 → 較正値(平均)= {sum(vals) / n:.3f}")


if __name__ == "__main__":
    main()
