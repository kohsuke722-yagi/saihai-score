# -*- coding: utf-8 -*-
"""チーム文脈依存の実証(9/8夜社長の宿題・next-session-0909タスク3)
「出塁の脇役が多いチームは主砲4番でも良いが、いないなら主砲は前に」を同一主砲で実証する。
脇役7人の分布をOUT↔BBの質量移動でOBPだけ±δ動かし(長打力・単打力は不変)、
各文脈で主砲を各スロットに置いたときのベストレスポンスEV(残り8人は8!全列挙の最良)を比較。
Usage: python src/context_curve.py 0905 c-g-19 巨人 佐々木
"""
import itertools
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lineup_ev import game_ev, game_ev_from, _trans_table  # noqa
from verify_lineup_search import load_teams  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DELTAS = [("出塁低い脇役(-30pt)", -0.03), ("実際の打線", 0.0), ("出塁高い脇役(+30pt)", +0.03)]


def shift_obp(d, delta):
    """OUT↔BBの質量移動でOBPをdeltaだけ動かす。他の事象(安打・長打)は不変"""
    d2 = dict(d)
    if delta >= 0:
        mv = min(delta, max(0.0, d2.get("OUT", 0.0) - 0.05))
    else:
        mv = -min(-delta, max(0.0, d2.get("BB", 0.0) - 0.005))
    d2["BB"] = d2.get("BB", 0.0) + mv
    d2["OUT"] = d2.get("OUT", 0.0) - mv
    return d2


def obp_of(d):
    return sum(d.get(k, 0.0) for k in ("BB", "HBP", "1B", "2B", "3B", "HR"))


def best_curve(dists, star, fixed):
    """8!全列挙しながら主砲スロット別の最良EVを抽出(ベストレスポンスカーブ)"""
    T = _trans_table(dists)
    free = [i for i in range(9) if i != fixed]
    best, bestord = {}, {}
    for perm in itertools.permutations(free):
        it = iter(perm)
        order = [fixed if i == fixed else next(it) for i in range(9)]
        ev = game_ev_from(T, order)
        s = order.index(star)
        if ev > best.get(s, -1.0):
            best[s], bestord[s] = ev, order
    return best, bestord


def keep_order_curve(dists, star, fixed):
    """主砲だけ動かし残りは実際の相対順(前回9/5佐々木カーブと同方式)"""
    rest = [i for i in range(9) if i not in (star, fixed)]
    out = {}
    for s in range(9):
        if s == fixed:
            continue
        order = [None] * 9
        order[fixed] = fixed
        order[s] = star
        it = iter(rest)
        for j in range(9):
            if order[j] is None:
                order[j] = next(it)
        out[s] = game_ev([dists[i] for i in order])
    return out


def main():
    mmdd, gid, tgt_team, star_name = sys.argv[1:5]
    team = next(t for t in load_teams(mmdd, gid) if t[0] == tgt_team)
    tm, names, dists, fixed = team
    star = names.index(star_name)
    support = [i for i in range(9) if i not in (star, fixed)]
    print(f"主砲={star_name}(実際{star+1}番) 投手={names[fixed]}({fixed+1}番固定) "
          f"脇役7人={' '.join(names[i] for i in support)}")
    report = {"mmdd": mmdd, "gid": gid, "team": tm, "star": star_name,
              "star_slot_actual": star + 1, "contexts": []}
    for label, delta in DELTAS:
        dd = [shift_obp(d, delta) if i in support else d
              for i, d in enumerate(dists)]
        sup_obp = sum(obp_of(dd[i]) for i in support) / len(support)
        t0 = time.perf_counter()
        best, bestord = best_curve(dd, star, fixed)
        sec = time.perf_counter() - t0
        ko = keep_order_curve(dd, star, fixed)
        peak = max(best, key=best.get)
        print(f"\n── {label}: 脇役平均OBP={sup_obp:.3f} ({sec:.0f}s)")
        print("  slot :  " + "  ".join(f"{s+1}番" for s in sorted(best)))
        print("  BR   :  " + "  ".join(f"{best[s]-best[peak]:+.3f}" for s in sorted(best)))
        kpk = max(ko, key=ko.get)
        print("  実順 :  " + "  ".join(f"{ko[s]-ko[kpk]:+.3f}" for s in sorted(ko)))
        print(f"  → 最適スロット: BR={peak+1}番 / 実順維持={kpk+1}番  "
              f"(BRピークEV={best[peak]:.3f})")
        print(f"  BRピーク並び: " + " ".join(
            f"{i+1}{names[j]}" for i, j in enumerate(bestord[peak])))
        report["contexts"].append({
            "label": label, "delta": delta, "support_obp": round(sup_obp, 3),
            "curve_br": {s + 1: round(best[s], 4) for s in sorted(best)},
            "curve_keep": {s + 1: round(ko[s], 4) for s in sorted(ko)},
            "peak_br": peak + 1, "peak_keep": kpk + 1,
            "peak_order": [names[j] for j in bestord[peak]], "sec": round(sec)})
    outp = os.path.join(BASE, "data", "out", mmdd, f"context_curve_{gid}.json")
    json.dump(report, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nsaved:", outp)


if __name__ == "__main__":
    main()
