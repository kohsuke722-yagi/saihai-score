# -*- coding: utf-8 -*-
"""K_SPLIT較正(9/9フェーズ4): 左右スプリットの自立打席数=100(仮置き)を実データで較正。
方法: 時間分割(8/20前=学習/8/20以降=検証)。打者ごとに学習期の総合出塁率×リーグ左右比を
事前分布、学習期の対左/対右実測をKでブレンドし、検証期の対左/対右打席の被出塁を予測、
対数損失をKグリッドで比較
Usage: python src/calib_ksplit.py
"""
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ONB = ("BB", "HBP", "1B", "2B", "3B", "HR", "ROE")
SKIP = ("SH", "IBB", "?")
CUT = "0820"


def main():
    blog = json.load(open(os.path.join(BASE, "data", "logs", "batters.json"),
                          encoding="utf-8"))
    meta = json.load(open(os.path.join(BASE, "data", "logs", "meta.json"),
                          encoding="utf-8"))
    # リーグの対左右出塁率(事前分布の左右比に使用)
    lg = {}
    for h in ("左", "右"):
        d = meta.get(f"league_dist_vs{h}") or {}
        lg[h] = sum(d.get(k, 0.0) for k in ONB)
    lg_all = sum(meta["league_dist"].get(k, 0.0) for k in ONB)
    grid = [30, 60, 100, 200, 400, 10**9]
    loss = {k: 0.0 for k in grid}
    n_pts = 0
    for pid, rows in blog.items():
        tr = [(r[1], r[4]) for r in rows if r[0] < CUT and r[1] not in SKIP
              and len(r) > 4 and r[4] in ("左", "右")]
        te = [(r[1], r[4]) for r in rows if r[0] >= CUT and r[1] not in SKIP
              and len(r) > 4 and r[4] in ("左", "右")]
        if len(tr) < 100 or len(te) < 20:
            continue
        ob_all = sum(1 for c, h in tr if c in ONB) / len(tr)
        for hand in ("左", "右"):
            trh = [(c, h) for c, h in tr if h == hand]
            teh = [c for c, h in te if h == hand]
            if not teh:
                continue
            n_h = len(trh)
            own = (sum(1 for c, h in trh if c in ONB) / n_h) if n_h else 0.0
            prior = min(0.6, max(0.15, ob_all * lg[hand] / max(1e-6, lg_all)))
            y1 = sum(1 for c in teh if c in ONB)
            y0 = len(teh) - y1
            for k in grid:
                w = n_h / (n_h + k)
                ph = min(0.97, max(0.03, w * own + (1 - w) * prior))
                loss[k] -= y1 * math.log(ph) + y0 * math.log(1 - ph)
            n_pts += len(teh)
    print(f"検証打席 {n_pts}(8/20以降・左右判明分)")
    base = loss[10**9]
    for k in grid:
        tag = "←スプリット無視" if k == 10**9 else ("←現行仮置き" if k == 100 else "")
        print(f"  K={'∞' if k == 10**9 else k:>4}: 対数損失 {loss[k]:.1f} "
              f"(無視比 {loss[k] - base:+.2f}) {tag}")
    best = min(grid, key=lambda k: loss[k])
    print(f"最良K = {'∞(個人スプリットに追加予測力なし)' if best == 10**9 else best}")


if __name__ == "__main__":
    main()
