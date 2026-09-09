# -*- coding: utf-8 -*-
"""K_DAY較正(9/9フェーズ3・9/7残穴#3): 継投判断の「当日の出来」ブレンド強度K=45(仮置き)を
実データで較正する。方法: 全投手の登板内シーケンスで「ここまでの当日被打」から
「次の打者の被出塁」を予測し、K別の対数損失を比較(leave-one-day-outの季節基準率にブレンド)
Usage: python src/calib_kday.py
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


def main():
    plog = json.load(open(os.path.join(BASE, "data", "logs", "pitchers.json"),
                          encoding="utf-8"))
    grid = [10, 20, 30, 45, 70, 100, 200, 10**9]
    loss = {k: 0.0 for k in grid}
    n_pts = 0
    for pid, rows in plog.items():
        # 日別に分け、季節全体の出塁率(その日を除く)を基準率に
        by_day = {}
        for r in rows:
            if r[1] in SKIP:
                continue
            by_day.setdefault(r[0], []).append(1 if r[1] in ONB else 0)
        tot_ob = sum(sum(v) for v in by_day.values())
        tot_n = sum(len(v) for v in by_day.values())
        if tot_n < 60:
            continue
        for d, seq in by_day.items():
            n_d = len(seq)
            ob_d = sum(seq)
            p0 = (tot_ob - ob_d + 1.0) / (tot_n - n_d + 3.0)  # 弱事前つきLODO基準率
            cum = 0
            for i, y in enumerate(seq):
                if i >= 2:  # 当日情報が2打者以上ある点だけ評価
                    for k in grid:
                        w = i / (i + k)
                        ph = min(0.98, max(0.02, (1 - w) * p0 + w * cum / i))
                        loss[k] -= y * math.log(ph) + (1 - y) * math.log(1 - ph)
                    n_pts += 1
                cum += y
    print(f"評価点 {n_pts}打席(当日3打者目以降・投手{sum(1 for p, r in plog.items())}人中の適格分)")
    base = loss[10**9]
    for k in grid:
        tag = "←当日無視" if k == 10**9 else ("←現行仮置き" if k == 45 else "")
        print(f"  K={'∞' if k == 10**9 else k:>4}: 対数損失 {loss[k]:.1f} "
              f"(当日無視比 {loss[k] - base:+.2f}) {tag}")
    best = min(grid, key=lambda k: loss[k])
    print(f"最良K = {'∞(当日の出来に予測力なし)' if best == 10**9 else best}")


if __name__ == "__main__":
    main()
