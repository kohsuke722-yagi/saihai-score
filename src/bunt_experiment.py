# -*- coding: utf-8 -*-
"""バント方策DPの検品(plan-bunt-dp.md 検証2・3/9/9裁定A=規範方策・B=野手込み)
- 検証3: 規範方策のバント選択マップ(誰がどの塁×アウトで振るか)の野球的妥当性
- 検証2: 8番投手vs9番投手のEV比較(方策込みで初めて公平になる比較)
Usage: python src/bunt_experiment.py 0905 c-g-19
"""
import sys
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lineup_ev import game_ev, optimize, bunt_options  # noqa
from verify_lineup_search import load_teams, fmt_order  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ST_LABEL = {"1": "一塁", "2": "二塁", "12": "一二塁"}


def pin_pitcher(dists, bunts, pi, slot):
    """投手(元idx=pi)を打順slot(0-based)に置いた並び替えリストを作る"""
    rest_d = [d for i, d in enumerate(dists) if i != pi]
    rest_b = [b for i, b in enumerate(bunts) if i != pi]
    nd = rest_d[:slot] + [dists[pi]] + rest_d[slot:]
    nb = rest_b[:slot] + [bunts[pi]] + rest_b[slot:]
    return nd, nb


def main():
    mmdd, gid = sys.argv[1], sys.argv[2]
    for tm, names, dists, fixed in load_teams(mmdd, gid):
        print(f"\n══ {tm} ══")
        bunts = bunt_options(tm, names, dists,
                             [i == fixed for i in range(9)])
        # 検証3: バント選択マップ
        print("[規範方策の選択マップ] (リーグRE基準でバント優位の局面)")
        any_b = False
        for i, (nm, bo) in enumerate(zip(names, bunts)):
            if bo:
                any_b = True
                sits = " ".join(f"{ST_LABEL[st]}{o}死" for (st, o) in sorted(bo))
                print(f"  {nm}{'(投)' if i == fixed else ''}: {sits}")
        if not any_b:
            print("  (バントを選ぶ打者なし)")
        # 方策ON/OFFのEV差(実際の並びで)
        ev_off = game_ev(dists)
        ev_on = game_ev(dists, bunts)
        print(f"[実際の並び] 方策OFF {ev_off:.4f} → ON {ev_on:.4f} ({ev_on-ev_off:+.4f})")
        # 検証2: 8番投手 vs 9番投手(方策ON/OFF×最適化)
        if fixed is None:
            print("  (DH・投手打席なし → 8番投手比較は対象外)")
            continue
        for label, bts in (("方策OFF", None), ("方策ON ", bunts)):
            evs = {}
            for slot in (7, 8):
                nd, nb = pin_pitcher(dists, bunts, fixed, slot)
                _, ev = optimize(nd, fixed=slot, restarts=2,
                                 bunts=nb if bts else None)
                evs[slot] = ev
            d = evs[7] - evs[8]
            better = "8番優位" if d > 0 else "9番優位"
            print(f"[{label}] 投手8番 {evs[7]:.4f} vs 9番 {evs[8]:.4f} "
                  f"→ {better} ({d:+.4f}点/試合)")


if __name__ == "__main__":
    main()
