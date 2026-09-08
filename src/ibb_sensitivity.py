# -*- coding: utf-8 -*-
"""IBB浄化の感度分析(design-lineup-card.md §2「効果は感度分析で公開」・9/9)
申告敬遠をBBに算入した非浄化分布と現行(IBB除外)を同一手順で比較し、
打者OBP・チームEV・最適並びへの影響を定量化する。
Usage: python src/ibb_sensitivity.py 0905 c-g-19
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lineup_ev import game_ev, optimize  # noqa
from verify_lineup_search import load_teams, fmt_order  # noqa
from stats import PITCHER_BAT, LEAGUE, _blend, fetch_player  # noqa
from stats2 import (_load, _days, _w, _season_bat_counts, _norm, _self_w,  # noqa
                    FOLD, CLS, HALF_BAT, AGE_OUT)
from analyze import game_ids, game_ids2  # noqa
from phase1 import is_pitcher_bat  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def dist_variant(pid, P, asof, ibb_as_bb):
    """batter_dist2と同一手順。ibb_as_bb=TrueでIBBをBBに算入(非浄化)。
    returns (dist, 窓内IBB数)"""
    blog, _ = _load()
    b = P.get("bat")
    n_season = (b["PA"] - b["SH"]) if b else 0
    if P.get("pit") and n_season < 60:
        return dict(PITCHER_BAT), 0
    rows = blog.get(pid, [])
    sc, _sn = _season_bat_counts(b) if b else (None, 0)
    if sc is not None and asof < P.get("fetched", "0907"):
        sc = None
    if not rows and not b:
        return dict(LEAGUE), 0
    fold = dict(FOLD)
    if ibb_as_bb:
        fold["IBB"] = "BB"
    wc = {k: 0.0 for k in CLS}
    win = {k: 0 for k in CLS}
    n_ibb = 0
    for r in rows:
        d, o = r[0], fold.get(r[1], r[1])
        if _days(asof, d) <= 0:
            continue
        if r[1] == "IBB":
            n_ibb += 1
        if o not in wc:
            continue
        wc[o] += _w(asof, d, HALF_BAT)
        win[o] += 1
    n_eff = sum(wc.values())
    if sc is not None:
        w_out = 0.5 ** (AGE_OUT / HALF_BAT)
        n_out = 0.0
        for k in CLS:
            out_k = max(0.0, sc.get(k, 0.0) - win[k])
            wc[k] += w_out * out_k
            n_out += out_k
        n_eff += w_out * n_out
    return _blend(_norm(wc), _self_w(n_eff, "b")), n_ibb


def obp(d):
    return sum(d.get(k, 0.0) for k in ("BB", "HBP", "1B", "2B", "3B", "HR"))


def main():
    mmdd, gid = sys.argv[1], sys.argv[2]
    ids2 = game_ids2(mmdd, gid)
    ids = game_ids(mmdd, gid)
    for tm, names, dists, fixed in load_teams(mmdd, gid):
        print(f"\n══ {tm} ══")
        d_pure, d_ibb = [], []
        for i, nm in enumerate(names):
            pid = (ids2.get(tm) or {}).get(nm) or ids.get(nm)
            P = fetch_player(pid)
            dp, _ = dist_variant(pid, P, mmdd, False)
            di, n_ibb = dist_variant(pid, P, mmdd, True)
            d_pure.append(dp)
            d_ibb.append(di)
            dob = obp(di) - obp(dp)
            if abs(dob) > 0.0005 or n_ibb:
                print(f"  {i+1}番 {nm}: OBP {obp(dp):.3f} → 非浄化 {obp(di):.3f} "
                      f"({dob:+.4f}) 窓内IBB {n_ibb}件")
        ev_p = game_ev(d_pure)
        ev_i = game_ev(d_ibb)
        bo_p, ebest_p = optimize(d_pure, fixed=fixed, restarts=1)
        bo_i, ebest_i = optimize(d_ibb, fixed=fixed, restarts=1)
        print(f"  実際の並びEV: 浄化 {ev_p:.4f} vs 非浄化 {ev_i:.4f} ({ev_i-ev_p:+.4f})")
        print(f"  最適EV:       浄化 {ebest_p:.4f} vs 非浄化 {ebest_i:.4f} "
              f"({ebest_i-ebest_p:+.4f})")
        if bo_p != bo_i:
            print(f"  最適並びが変化: 浄化   {fmt_order(bo_p, names)}")
            print(f"                  非浄化 {fmt_order(bo_i, names)}")
        else:
            print("  最適並びは不変")


if __name__ == "__main__":
    main()
