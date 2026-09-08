# -*- coding: utf-8 -*-
"""統計ゲートP4(design-lineup-card.md §1・9/9実装): 打順diffの統計的成立性
- ブートストラップ: 減衰済み生カウント(PA原子)を再抽選→縮小を再適用(縮小後の再抽選は帯過小)
- 共通乱数で実際/最適を対に・レプリケートごとに帯内再最適化(総当り上位K帯=検証①の密集実測が根拠)
- optimism補正: 完璧監督(真の最適並び)の幻の見逃しphantomの平均を控除(Efron流のこの問題への翻案)
- 三値判定: 有意な見逃し(補正後帯<0)/最適域(補正後点推定≥-0.02)/判定不能
- 偽陽性テスト: 二重ブートストラップで「完璧監督に有罪を出す率」を実測(ゲート≤5%)
Usage: python src/lineup_gate.py 0905 c-g-19 [--b 400] [--k 200]
       python src/lineup_gate.py 0905 c-g-19 --fp [--m 40] [--b 120] [--k 50]
"""
import json
import os
import random
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lineup_ev import _trans_table, game_ev_from  # noqa
from lineup_fast import ev_orders, fast_full_search  # noqa
from verify_lineup_search import load_teams  # noqa
from stats import PITCHER_BAT, LEAGUE, _blend  # noqa
from stats2 import (_load, _days, _season_bat_counts, _norm, _self_w,  # noqa
                    FOLD, CLS, HALF_BAT, AGE_OUT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OPT_ZONE = 0.02  # 最適域の閾値(補正後点推定・optimismと同桁=帯の分解能。裁定余地あり)


def batter_atoms(pid, P, asof):
    """batter_dist2と同一手順のPA原子リスト[(重み, クラス)]。固定分布ならNoneを返す"""
    blog, _ = _load()
    b = P.get("bat")
    n_season = (b["PA"] - b["SH"]) if b else 0
    if P.get("pit") and n_season < 60:
        return None, dict(PITCHER_BAT)
    rows = blog.get(pid, [])
    sc, _sn = _season_bat_counts(b) if b else (None, 0)
    if sc is not None and asof < P.get("fetched", "0907"):
        sc = None
    if not rows and not b:
        return None, dict(LEAGUE)
    atoms, win = [], {k: 0 for k in CLS}
    for r in rows:
        d, o = r[0], FOLD.get(r[1], r[1])
        if o not in win or _days(asof, d) <= 0:
            continue
        atoms.append((0.5 ** (max(0, _days(asof, d)) / HALF_BAT), o))
        win[o] += 1
    if sc is not None:
        w_out = 0.5 ** (AGE_OUT / HALF_BAT)
        for k in CLS:
            for _ in range(int(round(max(0.0, sc.get(k, 0.0) - win[k])))):
                atoms.append((w_out, k))
    if not atoms:
        return None, dict(LEAGUE)
    return atoms, None


def dist_of(atoms):
    """原子集合→分布(縮小の再適用込み・batter_dist2と同一の合成)"""
    wc = {k: 0.0 for k in CLS}
    for w, k in atoms:
        wc[k] += w
    n_eff = sum(wc.values())
    return _blend(_norm(wc), _self_w(n_eff, "b"))


def resample(atoms, rng):
    return rng.choices(atoms, k=len(atoms))


def gate_one(atoms9, fixed9, actual, band, B, rng, label=""):
    """1チームのゲート判定。atoms9=打者別原子(固定はNone,dist)・band=候補並び(先頭=点推定最適)
    returns dict(diff_hat, optimism, band95, verdict, ...)"""
    d0 = [dist_of(a) if a else f for a, f in zip(atoms9, fixed9)]
    ia = band.index(actual)  # bandはactualを含む前提(main側で保証)
    evs0 = ev_orders(_trans_table(d0), band)
    ev0_act = evs0[ia]
    diff_hat = float(ev0_act - evs0.max())
    istar = int(evs0.argmax())
    diffs, phantoms = [], []
    for _ in range(B):
        db = [dist_of(resample(a, rng)) if a else f
              for a, f in zip(atoms9, fixed9)]
        evs = ev_orders(_trans_table(db), band)
        mx = evs.max()
        diffs.append(float(evs[ia] - mx))
        phantoms.append(float(evs[istar] - mx))
    opt_bias = sum(phantoms) / len(phantoms)
    corr = sorted(d - opt_bias for d in diffs)
    lo = corr[int(0.025 * len(corr))]
    hi = corr[min(len(corr) - 1, int(0.975 * len(corr)))]
    point = diff_hat - opt_bias
    if hi < 0:
        verdict = "有意な見逃し"
    elif point >= -OPT_ZONE:
        verdict = "最適域"
    else:
        verdict = "判定不能"
    return {"label": label, "diff_hat": round(diff_hat, 4),
            "optimism": round(opt_bias, 4), "point_corr": round(point, 4),
            "band95": [round(lo, 4), round(hi, 4)], "verdict": verdict, "B": B}


def load_atoms(mmdd, gid):
    """load_teamsと同一の対応でチームごとの(atoms9, fixed9, names, dists0, fixed)を返す"""
    from analyze import game_ids, game_ids2
    from runners import parse_box_lineup
    from stats import fetch_player
    ids2 = game_ids2(mmdd, gid)
    ids = game_ids(mmdd, gid)
    out = []
    for tm, names, dists, fixed in load_teams(mmdd, gid):
        atoms9, fixed9 = [], []
        for i, nm in enumerate(names):
            pid = (ids2.get(tm) or {}).get(nm) or ids.get(nm)
            a, f = batter_atoms(pid, fetch_player(pid), mmdd)
            atoms9.append(a)
            fixed9.append(f)
        out.append((tm, names, dists, fixed, atoms9, fixed9))
    return out


def main():
    mmdd, gid = sys.argv[1], sys.argv[2]
    args = sys.argv[3:]

    def arg(k, dv):
        return int(args[args.index(k) + 1]) if k in args else dv
    fp_mode = "--fp" in args
    B = arg("--b", 400)  # 高速化(lineup_fast)によりFPも本番設定で回す
    K = arg("--k", 200)
    M = arg("--m", 100)
    rng = random.Random(20260909)
    results = []
    for tm, names, dists, fixed, atoms9, fixed9 in load_atoms(mmdd, gid):
        t0 = time.perf_counter()
        o_best, _, top = fast_full_search(dists, fixed=fixed, topk=K)
        band = [o for _, o in sorted(top, reverse=True)]
        actual = list(range(9))
        if actual not in band:
            band.append(actual)
        if not fp_mode:
            r = gate_one(atoms9, fixed9, actual, band, B, rng, tm)
            sec = time.perf_counter() - t0
            print(f"── {tm} ({sec:.0f}s) 素diff {r['diff_hat']:+.3f} "
                  f"optimism {r['optimism']:+.3f} → 補正後 {r['point_corr']:+.3f} "
                  f"帯95% [{r['band95'][0]:+.3f}, {r['band95'][1]:+.3f}]")
            print(f"   判定: {r['verdict']}")
            results.append(r)
        else:
            # 偽陽性テスト: 真の分布=点推定・完璧監督=o_best。外側M個の観測データセットを生成し
            # それぞれに内側ゲートを回して「有意な見逃し」率を実測
            fp = 0
            for m in range(M):
                atoms_m = [resample(a, rng) if a else None for a in atoms9]
                r = gate_one(atoms_m, fixed9, o_best, band, B, rng)
                if r["verdict"] == "有意な見逃し":
                    fp += 1
                if (m + 1) % 10 == 0:
                    print(f"   {tm}: {m+1}/{M} 済 (FP {fp})")
            rate = fp / M
            sec = time.perf_counter() - t0
            print(f"── {tm} 偽陽性率 {rate:.1%} ({fp}/{M}) "
                  f"{'合格(≤5%)' if rate <= 0.05 else '不合格'} ({sec:.0f}s)")
            results.append({"team": tm, "fp": fp, "M": M, "rate": rate})
    outp = os.path.join(BASE, "data", "out", mmdd,
                        f"gate_{'fp_' if fp_mode else ''}{gid}.json")
    json.dump(results, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved:", outp)


if __name__ == "__main__":
    main()
