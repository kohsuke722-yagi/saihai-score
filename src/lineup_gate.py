# -*- coding: utf-8 -*-
"""統計ゲートP4(design-lineup-card.md §1・9/9実装): 打順diffの統計的成立性
- ブートストラップ: 減衰済み生カウント(PA原子)を再抽選→縮小を再適用(縮小後の再抽選は帯過小)
- 通貨統一(9/10): 原子合成にλ_bat追い縮小+2025事前分布を再適用=batter_dist2と機械精度で
  同一(表示・探索・検定の通貨一致)。λ・priorは決定的成分(リーグ縮小と同じ扱い)
- 共通乱数で実際/最適を対に・レプリケートごとに帯内再最適化(総当り上位K帯=検証①の密集実測が根拠)
- optimism補正: 完璧監督(真の最適並び)の幻の見逃しphantomの平均を控除(Efron流のこの問題への翻案)
- **判定線は帰無分布で較正(9/9裁定)**: 固定線「帯<0」は完璧監督の~27%を誤有罪にした
  (平均補正では勝者の呪いの分散成分が残る)→ 完璧監督シミュM本の帯上端の帰無分布に対する
  p値で有罪判定(p≤0.05)。FP≤5%は構成上保証・検出力は実測公開
- 三値判定: 有意な見逃し(p≤0.05)/最適域(補正後点推定≥-0.02)/判定不能
- 偽陽性テスト--fp: 三重ブートストラップで較正済み手続き自体のFPを検証(重い・夜間用)
- 運用(9/9フェーズ1): 判定JSONは data/gates/{mmdd}/ へ(コミット対象・カードが読む)。
  --pregame=試合前モード(rawのbox/rosterから読む・軽量設定でカード配達前に実行)、
  省略=夜間本走({gid}_final.json・本走設定B400/MN40)
- 検出力実測--power(9/9フェーズ2): 合成オフェンダー(真のEVからdだけ劣る並び)への
  有罪判定率をFPテストと同じ三重ブートストラップで測る。既定は試合前運用設定(B200/MN20)
  =配達実物の検出力。「どのくらいの見逃しなら一晩で捕まえられるか」のnote公開用
Usage: python src/lineup_gate.py 0905 c-g-19 [--b 400] [--k 200] [--mnull 40] [--pregame]
       python src/lineup_gate.py 0905 c-g-19 --fp [--m 20] [--mnull 20] [--b 200]
       python src/lineup_gate.py 0905 c-g-19 --power [--m 12] [--levels 0.02,0.03,0.05]
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
                    FOLD, CLS, HALF_BAT, AGE_OUT, LAMBDA_BAT, _prior25,
                    batter_dist2)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OPT_ZONE = 0.02  # 最適域の閾値(補正後点推定・optimismと同桁=帯の分解能。裁定余地あり)
# δ_null拡幅のスケール。env GATE_DSCALEで全実行点(cloud_pregame・gate_batch・CLI)一括設定
DSCALE = float(os.environ.get("GATE_DSCALE", "1.0"))


def batter_atoms(pid, P, asof):
    """batter_dist2と同一手順のPA原子リスト[(重み, クラス)]と2025事前分布(n25, d25)。
    固定分布なら(None, dist, None)。通貨統一(9/10): 固定分布もbatter_dist2の実物を使う"""
    blog, _ = _load()
    b = P.get("bat")
    n_season = (b["PA"] - b["SH"]) if b else 0
    if P.get("pit") and n_season < 60:
        return None, dict(PITCHER_BAT), None
    rows = blog.get(pid, [])
    sc, _sn = _season_bat_counts(b) if b else (None, 0)
    if sc is not None and asof < P.get("fetched", "0907"):
        sc = None
    if not rows and not b:
        return None, batter_dist2(pid, P, asof), None
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
        return None, batter_dist2(pid, P, asof), None
    return atoms, None, _prior25(pid)


def dist_of(atoms, prior=None):
    """原子集合→分布。縮小・2025事前分布混合・λ追い縮小の再適用込み
    =batter_dist2と同一の合成(通貨統一9/10: λ・priorは決定的成分として再適用。
    ブートストラップが揺らすのは今季PA原子のみ=リーグ縮小と同じ扱い)"""
    wc = {k: 0.0 for k in CLS}
    for w, k in atoms:
        wc[k] += w
    n_eff = sum(wc.values())
    d = _norm(wc)
    if prior:
        n25, d25 = prior
        d = {k: (n_eff * d.get(k, 0.0) + n25 * d25.get(k, 0.0)) / (n_eff + n25)
             for k in CLS}
        n_eff += n25
    return _blend(_blend(d, _self_w(n_eff, "b")), LAMBDA_BAT)


def resample(atoms, rng):
    return rng.choices(atoms, k=len(atoms))


def gate_stat(atoms9, fixed9, prior9, actual, band, B, rng):
    """検定統計量の計算(判定はしない)。atoms9=打者別原子(固定はNone,dist)・
    band=候補並び(actualを含む前提)。returns dict(diff_hat, optimism, point_corr,
    band95, istar=このデータが信じる最適並びのband内idx)"""
    d0 = [dist_of(a, pr) if a else f
          for a, f, pr in zip(atoms9, fixed9, prior9)]
    ia = band.index(actual)
    evs0 = ev_orders(_trans_table(d0), band)
    diff_hat = float(evs0[ia] - evs0.max())
    istar = int(evs0.argmax())
    diffs, phantoms = [], []
    for _ in range(B):
        db = [dist_of(resample(a, rng), pr) if a else f
              for a, f, pr in zip(atoms9, fixed9, prior9)]
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


def null_band_his(atoms9, fixed9, prior9, band, B, m_null, rng, delta=DELTA_BAND):
    """帯内H0の帰無分布(9/9裁定#2): 「THE最適を打ったか」は頂上が平坦すぎて検定不能
    (診断: 真実のargmaxは1回の再抽選で98〜197位に大シャッフル・帰無の勝者だけ首位差が
    水増しされFP30%)→ 帰無の監督=真実の帯内(首位とδ以内)の一様ランダムメンバーに変更。
    有罪=「帯のどのメンバーとしても説明不能な並び」。完璧監督FP<5%は保守側で保証"""
    d0 = [dist_of(a, pr) if a else f
          for a, f, pr in zip(atoms9, fixed9, prior9)]
    evs0 = ev_orders(_trans_table(d0), band)
    mx = evs0.max()
    members = [i for i in range(len(band)) if mx - evs0[i] <= delta]
    his = []
    for _ in range(m_null):
        ai = members[rng.randrange(len(members))]
        atoms_j = [resample(a, rng) if a else None for a in atoms9]
        his.append(gate_stat(atoms_j, fixed9, prior9, band[ai], band, B,
                             rng)["band95"][1])
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
    from verify_lineup_search import resolve_pid
    ids2 = game_ids2(mmdd, gid)
    ids = game_ids(mmdd, gid)
    out = []
    for tm, names, dists, fixed in load_teams(mmdd, gid):
        atoms9, fixed9, prior9 = [], [], []
        for i, nm in enumerate(names):
            pid = resolve_pid(mmdd, gid, tm, nm, ids2, ids)
            a, f, pr = batter_atoms(pid, fetch_player(pid), mmdd)
            atoms9.append(a)
            fixed9.append(f)
            prior9.append(pr)
        out.append((tm, names, dists, fixed, atoms9, fixed9, prior9))
    return out


def load_atoms_pregame(mmdd, gid):
    """試合前用ローダー: イベント(playbyplay)が無くてもbox/rosterから読む。
    pid解決・投手判定はpregame_card.build_gameと同一手順(カードとの通貨統一)。
    分布はゲート通貨=素DP(相手先発補正なし・9/9実務近似②の根拠のまま)"""
    from pregame_card import roster_ids, resolve_pid_fallback, CODE2NAME
    from runners import parse_box_lineup
    from stats import fetch_player
    from stats2 import batter_dist2
    from phase1 import is_pitcher_bat, TEAM_NAME2CODE, _norm_name
    lu = parse_box_lineup(mmdd, gid)
    if not lu or len(lu) < 2:
        raise RuntimeError("スタメン未発表")
    home = CODE2NAME.get(gid.split("-")[0])
    away = CODE2NAME.get(gid.split("-")[1])
    if not home or not away:
        raise RuntimeError(f"チームコード不明: {gid}")
    rids = roster_ids(mmdd, gid)
    out = []
    for tm, l in ((away, lu[0]), (home, lu[1])):
        tc = TEAM_NAME2CODE[tm]
        names, dists, fixed = [], [], None
        atoms9, fixed9, prior9 = [], [], []
        for s0 in range(9):
            role, nm = l.get(s0, ("", ""))
            pid = (rids.get(tm) or {}).get(_norm_name(nm)) or resolve_pid_fallback(tc, nm)
            if not pid:
                raise RuntimeError(f"pid不明: {tm} {nm}")
            P = fetch_player(pid)
            if is_pitcher_bat(P) or "投" in (role or ""):
                d, fixed = dict(PITCHER_BAT), s0
                a, f, pr = None, dict(PITCHER_BAT), None
            else:
                d = batter_dist2(pid, P, mmdd)
                a, f, pr = batter_atoms(pid, P, mmdd)
            names.append(nm)
            dists.append(d)
            atoms9.append(a)
            fixed9.append(f)
            prior9.append(pr)
        out.append((tm, names, dists, fixed, atoms9, fixed9, prior9))
    return out


def gate_one(tm, dists, fixed, atoms9, fixed9, prior9, B, K, MN, rng,
             verbose=True, dscale=1.0):
    """1チームの三値判定(帯内H0+optimism補正+帰無較正p値+δ拡幅=9/9最終形)"""
    t0 = time.perf_counter()
    o_best, _, top = fast_full_search(dists, fixed=fixed, topk=K)
    band = [o for _, o in sorted(top, reverse=True)]
    actual = list(range(9))
    if actual not in band:
        band.append(actual)
    st = gate_stat(atoms9, fixed9, prior9, actual, band, B, rng)
    # δ拡幅(9/9裁定#4): 帰無の帯資格は水増しされた首位から測るため、実測optimism分
    # 広げて対称化(FP実測8%>5%の残滓対策)
    dl = DELTA_BAND + dscale * abs(st["optimism"])
    his = null_band_his(atoms9, fixed9, prior9, band, B, MN, rng, delta=dl)
    v, p = verdict_of(st, his)
    c5 = sorted(his)[int(0.05 * len(his))]
    sec = time.perf_counter() - t0
    if verbose:
        print(f"── {tm} ({sec:.0f}s) 素diff {st['diff_hat']:+.3f} "
              f"optimism {st['optimism']:+.3f} → 補正後 {st['point_corr']:+.3f} "
              f"帯95% [{st['band95'][0]:+.3f}, {st['band95'][1]:+.3f}]", flush=True)
        print(f"   帰無5%線 {c5:+.3f} (M_null={MN}) p={p} → 判定: {v}", flush=True)
    return {**st, "team": tm, "p": p, "null_c5": round(c5, 4),
            "verdict": v, "sec": round(sec)}


def gates_path(mmdd, gid, final=False):
    return os.path.join(BASE, "data", "gates", mmdd,
                        f"{gid}{'_final' if final else ''}.json")


def run_gate(mmdd, gid, B=400, K=200, MN=40, pregame=False, team=None):
    """1試合の三値判定を実行し data/gates/{mmdd}/ へ保存。returns 結果list"""
    rng = random.Random(20260909)
    loader = load_atoms_pregame if pregame else load_atoms
    results = [gate_one(tm, dists, fixed, atoms9, fixed9, prior9, B, K, MN,
                        rng, dscale=DSCALE)
               for tm, names, dists, fixed, atoms9, fixed9, prior9
               in loader(mmdd, gid) if not (team and tm != team)]
    outp = gates_path(mmdd, gid, final=not pregame)
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    payload = {"mmdd": mmdd, "gid": gid, "mode": "pregame" if pregame else "nightly",
               "settings": {"B": B, "K": K, "M_null": MN,
                            "delta": DELTA_BAND, "opt_zone": OPT_ZONE,
                            "dscale": DSCALE, "lam_bat": LAMBDA_BAT},
               "teams": results}
    json.dump(payload, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved:", outp)
    return results


def power_run(mmdd, gid, B, K, MN, M, levels, team=None, pregame=False):
    """検出力の実測: 各水準dごとに「真のEV(観測分布d0上)からd劣る並び」を実際の並びとして
    較正済み手続きにかけ、『有意な見逃し』が出る率を測る。FPテスト(d=0)の一般化。
    オフェンダーは総当り全件から目標EV差に最近接の並びを採用(達成値achievedを併記)"""
    rng = random.Random(20260909)
    loader = load_atoms_pregame if pregame else load_atoms
    out = []
    for tm, names, dists, fixed, atoms9, fixed9, prior9 in loader(mmdd, gid):
        if team and tm != team:
            continue
        _, best_ev, pool = fast_full_search(dists, fixed=fixed, topk=40320)
        pool_sorted = sorted(pool, reverse=True)
        band = [o for _, o in pool_sorted[:K]]
        res_t = {"team": tm, "levels": []}
        for d in levels:
            ev_o, off = min(pool_sorted, key=lambda t: abs(t[0] - (best_ev - d)))
            achieved = float(best_ev - ev_o)
            band_l = band if off in band else band + [off]
            det = 0
            t0 = time.perf_counter()
            for m in range(M):
                atoms_m = [resample(a, rng) if a else None for a in atoms9]
                st = gate_stat(atoms_m, fixed9, prior9, off, band_l, B, rng)
                dl = DELTA_BAND + DSCALE * abs(st["optimism"])
                his = null_band_his(atoms_m, fixed9, prior9, band_l, B, MN,
                                    rng, delta=dl)
                v, _p = verdict_of(st, his)
                det += (v == "有意な見逃し")
                print(f"   {tm} d={achieved:.3f}: {m + 1}/{M} 済 (検出{det})", flush=True)
            sec = time.perf_counter() - t0
            print(f"── {tm} 真の見逃し {achieved:+.3f}点/試合 → 検出率 {det}/{M}"
                  f" = {det / M:.0%} ({sec:.0f}s)", flush=True)
            res_t["levels"].append({"level": d, "achieved": round(achieved, 4),
                                    "detect": det, "M": M,
                                    "rate": round(det / M, 3)})
        out.append(res_t)
    outp = os.path.join(BASE, "data", "out", mmdd, f"power_{gid}.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    json.dump({"mmdd": mmdd, "gid": gid,
               "settings": {"B": B, "K": K, "M_null": MN, "M": M,
                            "delta": DELTA_BAND, "opt_zone": OPT_ZONE,
                            "dscale": DSCALE, "lam_bat": LAMBDA_BAT},
               "teams": out}, open(outp, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("saved:", outp)
    return out


def main():
    mmdd, gid = sys.argv[1], sys.argv[2]
    args = sys.argv[3:]

    def arg(k, dv):
        return int(args[args.index(k) + 1]) if k in args else dv
    fp_mode = "--fp" in args
    power_mode = "--power" in args
    pregame = "--pregame" in args
    B = arg("--b", 200 if power_mode else 400)
    K = arg("--k", 200)
    M = arg("--m", 12 if power_mode else 20)
    MN = arg("--mnull", 20 if (fp_mode or power_mode) else 40)
    tgt = args[args.index("--team") + 1] if "--team" in args else None
    global DSCALE
    if "--dscale" in args:  # 省略時はenv GATE_DSCALE既定を維持(全実行点の一貫性)
        DSCALE = float(args[args.index("--dscale") + 1])
    if power_mode:
        levels = [float(x) for x in
                  (args[args.index("--levels") + 1] if "--levels" in args
                   else "0.02,0.03,0.05").split(",")]
        power_run(mmdd, gid, B=B, K=K, MN=MN, M=M, levels=levels,
                  team=tgt, pregame=pregame)
        return
    if not fp_mode:
        run_gate(mmdd, gid, B=B, K=K, MN=MN, pregame=pregame, team=tgt)
        return
    rng = random.Random(20260909)
    results = []
    for tm, names, dists, fixed, atoms9, fixed9, prior9 in load_atoms(mmdd, gid):
        if tgt and tm != tgt:
            continue
        t0 = time.perf_counter()
        o_best, _, top = fast_full_search(dists, fixed=fixed, topk=K)
        band = [o for _, o in sorted(top, reverse=True)]
        actual = list(range(9))
        if actual not in band:
            band.append(actual)
        # 偽陽性テスト(三重ブートストラップ): 完璧監督=o_best(真の最適)。
        # 外側M個の観測データセットそれぞれに較正済み手続き(統計量+帰無較正)を適用
        fp = 0
        for m in range(M):
            atoms_m = [resample(a, rng) if a else None for a in atoms9]
            st = gate_stat(atoms_m, fixed9, prior9, o_best, band, B, rng)
            dl = DELTA_BAND + DSCALE * abs(st["optimism"])
            his = null_band_his(atoms_m, fixed9, prior9, band, B, MN, rng,
                                delta=dl)
            v, _p = verdict_of(st, his)
            if v == "有意な見逃し":
                fp += 1
            print(f"   {tm}: {m+1}/{M} 済 (FP {fp})", flush=True)
        rate = fp / M
        sec = time.perf_counter() - t0
        print(f"── {tm} 偽陽性率 {rate:.1%} ({fp}/{M}) "
              f"{'合格(≤5%)' if rate <= 0.05 else '不合格'} ({sec:.0f}s)")
        results.append({"team": tm, "fp": fp, "M": M, "rate": rate,
                        "B": B, "MN": MN, "dscale": DSCALE,
                        "lam_bat": LAMBDA_BAT})
    outp = os.path.join(BASE, "data", "out", mmdd,
                        f"gate_fp_{gid}{('_' + tgt) if tgt else ''}"
                        f"_d{DSCALE:g}.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    json.dump(results, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved:", outp)


if __name__ == "__main__":
    main()
