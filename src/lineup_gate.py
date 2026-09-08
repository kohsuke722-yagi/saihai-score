# -*- coding: utf-8 -*-
"""統計ゲートP4(design-lineup-card.md §1・9/9実装): 打順diffの統計的成立性
- ブートストラップ: 減衰済み生カウント(PA原子)を再抽選→縮小を再適用(縮小後の再抽選は帯過小)
- 共通乱数で実際/最適を対に・レプリケートごとに帯内再最適化(総当り上位K帯=検証①の密集実測が根拠)
- optimism補正: 完璧監督(真の最適並び)の幻の見逃しphantomの平均を控除(Efron流のこの問題への翻案)
- **判定線は帰無分布で較正(9/9裁定)**: 固定線「帯<0」は完璧監督の~27%を誤有罪にした
  (平均補正では勝者の呪いの分散成分が残る)→ 完璧監督シミュM本の帯上端の帰無分布に対する
  p値で有罪判定(p≤0.05)。FP≤5%は構成上保証・検出力は実測公開
- 三値判定: 有意な見逃し(p≤0.05)/最適域(補正後点推定≥-0.02)/判定不能
- 偽陽性テスト--fp: 三重ブートストラップで較正済み手続き自体のFPを検証(重い・夜間用)
Usage: python src/lineup_gate.py 0905 c-g-19 [--b 400] [--k 200] [--mnull 40]
       python src/lineup_gate.py 0905 c-g-19 --fp [--m 20] [--mnull 20] [--b 200]
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


def gate_stat(atoms9, fixed9, actual, band, B, rng):
    """検定統計量の計算(判定はしない)。atoms9=打者別原子(固定はNone,dist)・
    band=候補並び(actualを含む前提)。returns dict(diff_hat, optimism, point_corr,
    band95, istar=このデータが信じる最適並びのband内idx)"""
    d0 = [dist_of(a) if a else f for a, f in zip(atoms9, fixed9)]
    ia = band.index(actual)
    evs0 = ev_orders(_trans_table(d0), band)
    diff_hat = float(evs0[ia] - evs0.max())
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
    return {"diff_hat": round(diff_hat, 4), "optimism": round(opt_bias, 4),
            "point_corr": round(diff_hat - opt_bias, 4),
            "band95": [round(lo, 4), round(hi, 4)], "istar": istar, "B": B}


DELTA_BAND = 0.005  # 帯メンバーの資格(首位との差)。argmax不安定スケールの実測(検証①)に整合


def null_band_his(atoms9, fixed9, band, B, m_null, rng, delta=DELTA_BAND):
    """帯内H0の帰無分布(9/9裁定#2): 「THE最適を打ったか」は頂上が平坦すぎて検定不能
    (診断: 真実のargmaxは1回の再抽選で98〜197位に大シャッフル・帰無の勝者だけ首位差が
    水増しされFP30%)→ 帰無の監督=真実の帯内(首位とδ以内)の一様ランダムメンバーに変更。
    有罪=「帯のどのメンバーとしても説明不能な並び」。完璧監督FP<5%は保守側で保証"""
    d0 = [dist_of(a) if a else f for a, f in zip(atoms9, fixed9)]
    evs0 = ev_orders(_trans_table(d0), band)
    mx = evs0.max()
    members = [i for i in range(len(band)) if mx - evs0[i] <= delta]
    his = []
    for _ in range(m_null):
        ai = members[rng.randrange(len(members))]
        atoms_j = [resample(a, rng) if a else None for a in atoms9]
        his.append(gate_stat(atoms_j, fixed9, band[ai], band, B, rng)["band95"][1])
    return his


def verdict_of(stat, his):
    """帰無分布に対するp値で三値判定。p=(1+#{null帯上端≤観測帯上端})/(M+1)"""
    p = (1 + sum(1 for h in his if h <= stat["band95"][1])) / (len(his) + 1)
    if p <= 0.05:
        v = "有意な見逃し"
    elif stat["point_corr"] >= -OPT_ZONE:
        v = "最適域"
    else:
        v = "判定不能"
    return v, round(p, 3)


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
    B = arg("--b", 400)
    K = arg("--k", 200)
    M = arg("--m", 20)
    MN = arg("--mnull", 40 if not fp_mode else 20)
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
            st = gate_stat(atoms9, fixed9, actual, band, B, rng)
            his = null_band_his(atoms9, fixed9, band, B, MN, rng)
            v, p = verdict_of(st, his)
            c5 = sorted(his)[int(0.05 * len(his))]
            sec = time.perf_counter() - t0
            print(f"── {tm} ({sec:.0f}s) 素diff {st['diff_hat']:+.3f} "
                  f"optimism {st['optimism']:+.3f} → 補正後 {st['point_corr']:+.3f} "
                  f"帯95% [{st['band95'][0]:+.3f}, {st['band95'][1]:+.3f}]")
            print(f"   帰無5%線 {c5:+.3f} (M_null={MN}) p={p} → 判定: {v}")
            results.append({**st, "team": tm, "p": p, "null_c5": round(c5, 4),
                            "verdict": v})
        else:
            # 偽陽性テスト(三重ブートストラップ): 完璧監督=o_best(真の最適)。
            # 外側M個の観測データセットそれぞれに較正済み手続き(統計量+帰無較正)を適用
            fp = 0
            for m in range(M):
                atoms_m = [resample(a, rng) if a else None for a in atoms9]
                st = gate_stat(atoms_m, fixed9, o_best, band, B, rng)
                his = null_band_his(atoms_m, fixed9, band, B, MN, rng)
                v, _p = verdict_of(st, his)
                if v == "有意な見逃し":
                    fp += 1
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
