# -*- coding: utf-8 -*-
"""総当り+走力込み2段階探索の実戦検証(9/9計画①②・next-session-0909.md)
①full_search(8!)と局所探索optimize()の一致確認・上位K件のEV密集度実測
②総当り上位200件(δバンド)をgame_ev_speedで決勝評価 — 走力寄与の定量化・実行時間実測
Usage: python src/verify_lineup_search.py 0905 c-g-19
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lineup_ev import (game_ev, full_search, optimize, speed_params,
                       game_ev_speed)  # noqa
from runners import parse_box_lineup  # noqa
from analyze import game_ids, game_ids2, parse_game  # noqa
from stats import fetch_player, PITCHER_BAT  # noqa
from stats2 import batter_dist2  # noqa
from phase1 import is_pitcher_bat, TEAM_NAME2CODE  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_teams(mmdd, gid):
    """analyze_lineup()の読み込み部と同一手順で(team, names, dists, fixed)を返す"""
    lineup = parse_box_lineup(mmdd, gid)
    ids2 = game_ids2(mmdd, gid)
    ids = game_ids(mmdd, gid)
    events, _ = parse_game(mmdd, gid)
    away = next(e["team"] for e in events if e["half"] == "表")
    home = next(e["team"] for e in events if e["half"] == "裏")
    out = []
    for tm, lu in ((away, lineup[0]), (home, lineup[1])):
        names, dists, fixed = [], [], None
        for s0 in range(9):
            role, nm = lu.get(s0, ("", ""))
            pid = (ids2.get(tm) or {}).get(nm) or ids.get(nm)
            if not pid:
                raise RuntimeError(f"pid不明: {tm} {nm}")
            P = fetch_player(pid)
            if is_pitcher_bat(P):
                d = dict(PITCHER_BAT)
                fixed = s0
            else:
                d = batter_dist2(pid, P, mmdd)
            names.append(nm)
            dists.append(d)
        out.append((tm, names, dists, fixed))
    return out


def fmt_order(order, names):
    return " ".join(f"{i+1}{names[j]}" for i, j in enumerate(order))


def main():
    mmdd, gid = sys.argv[1], sys.argv[2]
    report = {"mmdd": mmdd, "gid": gid, "teams": []}
    for tm, names, dists, fixed in load_teams(mmdd, gid):
        print(f"\n══ {tm} (投手スロット={None if fixed is None else fixed+1}番) ══")
        R = {"team": tm, "fixed": fixed, "names": names}

        # ① 局所探索 vs 総当り
        t0 = time.perf_counter()
        lo_order, lo_ev = optimize(dists, fixed=fixed)
        t_lo = time.perf_counter() - t0
        print(f"[局所探索] EV={lo_ev:.4f} ({t_lo:.1f}s)  {fmt_order(lo_order, names)}")

        t0 = time.perf_counter()
        fs_order, fs_ev, top = full_search(dists, fixed=fixed, topk=200)
        t_fs = time.perf_counter() - t0
        print(f"[総当り8!] EV={fs_ev:.4f} ({t_fs:.1f}s)  {fmt_order(fs_order, names)}")
        gap = fs_ev - lo_ev
        match = "一致" if gap < 1e-6 and lo_order == fs_order else \
                ("EV一致・並び別" if gap < 1e-6 else f"局所探索が劣後 {gap:+.4f}")
        print(f"→ 検証①: {match}")
        R["local"] = {"ev": lo_ev, "order": lo_order, "sec": round(t_lo, 1)}
        R["full"] = {"ev": fs_ev, "order": fs_order, "sec": round(t_fs, 1),
                     "verdict": match}

        # 上位K件の密集度(δバンドの実測)
        evs = [e for e, _ in top]
        print("上位密集度: " + "  ".join(
            f"#{k}:-{fs_ev - evs[k-1]:.4f}" for k in (2, 5, 10, 25, 50, 100, 200)
            if k <= len(evs)))
        bands = {d: sum(1 for e in evs if fs_ev - e <= d)
                 for d in (0.005, 0.01, 0.02, 0.05)}
        print("δバンド内の並び数: " + "  ".join(
            f"δ={d}: {n}件{'+' if n == len(evs) else ''}" for d, n in bands.items()))
        R["density"] = {"gaps": {k: round(fs_ev - evs[k-1], 4)
                                 for k in (2, 5, 10, 25, 50, 100, 200) if k <= len(evs)},
                        "bands": {str(d): n for d, n in bands.items()}}

        # ② 走力込み決勝評価(上位200件+実際の並び)
        sp = speed_params(TEAM_NAME2CODE.get(tm, tm), [{"name": n} for n in names])
        t0 = time.perf_counter()
        _ = game_ev_speed(dists, sp, top[0][1])
        t_one = time.perf_counter() - t0
        print(f"[走力DP] 1件 {t_one:.2f}s → 200件推定 {t_one*200:.0f}s")
        t0 = time.perf_counter()
        sp_ranked = sorted(((game_ev_speed(dists, sp, od), ev0, od)
                            for ev0, od in top), reverse=True)
        t_sp = time.perf_counter() - t0
        sp_best_ev, sp_best_ev0, sp_best = sp_ranked[0]
        # 素の総当り1位が走力込みで何位に落ちるか
        rank_of_plain = next(i + 1 for i, (_, _, od) in enumerate(sp_ranked)
                             if od == fs_order)
        ev_speed_plain = next(e for e, _, od in sp_ranked if od == fs_order)
        print(f"[走力200件] {t_sp:.0f}s  決勝1位 EV={sp_best_ev:.4f}"
              f" (素EV{sp_best_ev0:.4f}・素順位{[od for _, od in top].index(sp_best)+1}位)")
        print(f"   {fmt_order(sp_best, names)}")
        print(f"   素の1位は走力込みで{rank_of_plain}位 (EV={ev_speed_plain:.4f}"
              f"・決勝1位との差 {sp_best_ev - ev_speed_plain:+.4f})")
        moved = [(names[j], sp_best.index(j) + 1, fs_order.index(j) + 1)
                 for j in range(9) if sp_best.index(j) != fs_order.index(j)]
        if moved:
            print("   動いた選手: " + "  ".join(
                f"{n} {b}→{a}番" for n, a, b in moved))
        else:
            print("   並びは不変(走力を入れても最適は同じ)")
        R["speed"] = {"sec": round(t_sp, 1), "sec_per": round(t_one, 2),
                      "best_ev": sp_best_ev, "best_order": list(sp_best),
                      "plain_best_rank": rank_of_plain,
                      "delta_vs_plain": round(sp_best_ev - ev_speed_plain, 4),
                      "moved": moved}
        report["teams"].append(R)

    outp = os.path.join(BASE, "data", "out", mmdd, f"verify_search_{gid}.json")
    json.dump(report, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nsaved:", outp)


if __name__ == "__main__":
    main()
