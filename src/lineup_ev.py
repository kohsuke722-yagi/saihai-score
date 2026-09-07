# -*- coding: utf-8 -*-
"""打順の得点期待値カード(9/7社長発案・設計⑯の商品化)
- その日のスタメン9人の分布(直近減衰・当日以前のみ=未来不参照)でマルコフ全イニングDPを回し、
  実際の打順のEV(点/試合)と最適並び(局所探索・セは投手スロット固定)のEVを比較
- ベンチ野手に「スタメンを明確に上回る打者」がいれば注記(守備制約は判定不能なので事実表示のみ)
Usage: python src/lineup_ev.py 0905 c-g-19          # 両チーム分を計算・表示
       python src/lineup_ev.py 0905 c-g-19 --card   # カードHTML+PNGも生成
"""
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import game_ids, game_ids2  # noqa
from runners import parse_box_lineup  # noqa
from stats import fetch_player, PITCHER_BAT  # noqa
from stats2 import batter_dist2  # noqa
from phase1 import transitions, bench_roster, is_pitcher_bat, _norm_name, _HAND, TEAM_NAME2CODE  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_PA_INN = 24  # 1イニングの打席打ち切り(確率質量はほぼ残らない)


def _trans_table(dists):
    """打者別×全(塁,アウト)の遷移リストを前計算"""
    T = []
    for d in dists:
        t = {}
        for st in ("", "1", "2", "3", "12", "13", "23", "123"):
            for o in (0, 1, 2):
                t[(st, o)] = transitions(st, o, d)
        T.append(t)
    return T


def _inning(T, lead):
    """先頭打者leadで始まる1イニングの(期待得点, 次イニング先頭の分布)"""
    frontier = {("", 0, lead): 1.0}
    runs = 0.0
    nxt = defaultdict(float)
    for _ in range(MAX_PA_INN):
        new = {}
        for (st, o, bi), p in frontier.items():
            for pr, rn, ns, no in T[bi % 9][(st, o)]:
                q = p * pr
                runs += q * rn
                if no >= 3:
                    nxt[(bi + 1) % 9] += q
                else:
                    k = (ns, no, (bi + 1) % 9)
                    new[k] = new.get(k, 0.0) + q
        frontier = new
        if not frontier:
            break
    for (st, o, bi), p in frontier.items():
        nxt[(bi + 1) % 9] += p
    return runs, dict(nxt)


def game_ev(dists):
    """この並びの期待得点(9イニング・先頭打者の持ち越し込み)"""
    T = _trans_table(dists)
    inn = [_inning(T, i) for i in range(9)]
    lead = {0: 1.0}
    total = 0.0
    for _ in range(9):
        nl = defaultdict(float)
        for li, p in lead.items():
            r, nd = inn[li]
            total += p * r
            for j, q in nd.items():
                nl[j] += p * q
        lead = dict(nl)
    return total


def game_ev_from(T, order):
    """前計算済み遷移表Tと並びorderでのEV(総当り用の高速版)"""
    To = [T[i] for i in order]
    inn = []
    for lead in range(9):
        frontier = {("", 0, lead): 1.0}
        runs = 0.0
        nxt = defaultdict(float)
        for _ in range(MAX_PA_INN):
            new = {}
            for (st, o, bi), p in frontier.items():
                for pr, rn, ns, no in To[bi % 9][(st, o)]:
                    q = p * pr
                    runs += q * rn
                    if no >= 3:
                        nxt[(bi + 1) % 9] += q
                    else:
                        k = (ns, no, (bi + 1) % 9)
                        new[k] = new.get(k, 0.0) + q
            frontier = new
            if not frontier:
                break
        for (st, o, bi), p in frontier.items():
            nxt[(bi + 1) % 9] += p
        inn.append((runs, dict(nxt)))
    lead = {0: 1.0}
    total = 0.0
    for _ in range(9):
        nl = defaultdict(float)
        for li, p in lead.items():
            r, nd = inn[li]
            total += p * r
            for j, q in nd.items():
                nl[j] += p * q
        lead = dict(nl)
    return total


def full_search(dists, fixed=None, topk=200):
    """総当り(9/8社長要望): 投手固定なら8!=40,320通りを全評価。
    returns (best_order, best_ev, top_orders[(ev, order)降順])"""
    import heapq
    import itertools
    T = _trans_table(dists)
    free = [i for i in range(9) if i != fixed]
    heap = []
    best_ev, best_order = -1.0, list(range(9))
    for perm in itertools.permutations(free):
        it = iter(perm)
        order = [fixed if i == fixed else next(it) for i in range(9)]
        ev = game_ev_from(T, order)
        if ev > best_ev:
            best_ev, best_order = ev, order
        if len(heap) < topk:
            heapq.heappush(heap, (ev, order))
        elif ev > heap[0][0]:
            heapq.heapreplace(heap, (ev, order))
    return best_order, best_ev, sorted(heap, reverse=True)


def speed_params(tm, players):
    """スロットごとの走力(runpower実測・縮小つき): 進塁a2h/a13・併殺回避・盗塁(att,succ)"""
    try:
        RP = json.load(open(os.path.join(BASE, "data", "logs", "runpower.json"),
                            encoding="utf-8"))
    except Exception:
        RP = {}
    from phase1 import (_shr, ADV_1B_R2SCORE, ADV_1B_R1TO3, LEAGUE_DP,
                        LG_SB_ATT, LG_SB_SUCC)
    out = []
    for p in players:
        d = RP.get(f"{tm}:{p['name']}")
        if d:
            out.append({"a2h": _shr(d["a2h_y"], d["a2h_n"], ADV_1B_R2SCORE, 8),
                        "a13": _shr(d["a13_y"], d["a13_n"], ADV_1B_R1TO3, 8),
                        "dp": _shr(d["dp_y"], d["dp_n"], LEAGUE_DP, 12) / LEAGUE_DP,
                        "att": _shr(d["sb_att"], d["sb_att"] + d["sb_opp"], LG_SB_ATT, 15),
                        "succ": _shr(d["sb_succ"], d["sb_att"], LG_SB_SUCC, 8)})
        else:
            out.append({"a2h": ADV_1B_R2SCORE, "a13": ADV_1B_R1TO3, "dp": 1.0,
                        "att": LG_SB_ATT, "succ": LG_SB_SUCC})
    return out


def transitions_id(rid, outs, dist, sp):
    """走者ID付き遷移(設計P3のスロット占有DP): rid=(r1,r2,r3)=スロットidx or None。
    進塁確率・併殺回避を塁上の走者本人の実測値で評価。分岐構造はphase1.transitions()と同一"""
    from phase1 import (ADV_1B_R2SCORE, ADV_1B_R1TO3, ADV_2B_R1SCORE,
                        ADV_OUT_R3SCORE, LEAGUE_DP)
    r1, r2, r3 = rid
    a2h = sp[r2]["a2h"] if r2 is not None else ADV_1B_R2SCORE
    a13 = sp[r1]["a13"] if r1 is not None else ADV_1B_R1TO3
    a1h = ADV_2B_R1SCORE
    ao3 = ADV_OUT_R3SCORE
    p_dp = LEAGUE_DP * (sp[r1]["dp"] if r1 is not None else 1.0)
    E = []

    def term(p, runs, n1, n2, n3, no):
        if p > 0:
            E.append((p, runs, (n1, n2, n3), no))
    b = "B"  # 打者マーカー(呼び出し側でスロットidxに置換)
    for o, p in dist.items():
        if p <= 0:
            continue
        if o in ("BB", "HBP"):
            if r1 is not None:
                if r2 is not None:
                    term(p, 1 if r3 is not None else 0, b, r1, r2, outs)
                else:
                    term(p, 0, b, r1, r3, outs)
            else:
                term(p, 0, b, r2, r3, outs)
        elif o == "K":
            term(p, 0, r1, r2, r3, outs + 1)
        elif o == "OUT":
            pp = p
            if r1 is not None and outs < 2:
                dp_runs = 1 if (r3 is not None and outs + 2 < 3) else 0
                term(p * p_dp, dp_runs, None, None, r2, outs + 2)
                pp = p * (1 - p_dp)
            if r3 is not None and outs < 2:
                term(pp * ao3, 1, r1, r2, None, outs + 1)
                term(pp * (1 - ao3), 0, r1, r2, r3, outs + 1)
            else:
                term(pp, 0, r1, r2, r3, outs + 1)
        elif o == "1B":
            base = 1 if r3 is not None else 0
            if r2 is not None:
                for pr, sc in ((a2h, True), (1 - a2h, False)):
                    if r1 is not None:
                        p13 = a13 if sc else 0.0
                        term(p * pr * p13, base + (1 if sc else 0), b, None, r1, outs)
                        term(p * pr * (1 - p13), base + (1 if sc else 0), b, r1,
                             None if sc else r2, outs)
                    else:
                        term(p * pr, base + (1 if sc else 0), b, None,
                             None if sc else r2, outs)
            else:
                if r1 is not None:
                    term(p * a13, base, b, None, r1, outs)
                    term(p * (1 - a13), base, b, r1, None, outs)
                else:
                    term(p, base, b, None, None, outs)
        elif o == "2B":
            base = (1 if r3 is not None else 0) + (1 if r2 is not None else 0)
            if r1 is not None:
                term(p * a1h, base + 1, None, b, None, outs)
                term(p * (1 - a1h), base, None, b, r1, outs)
            else:
                term(p, base, None, b, None, outs)
        elif o == "3B":
            n = sum(1 for x in rid if x is not None)
            term(p, n, None, None, b, outs)
        elif o == "HR":
            n = sum(1 for x in rid if x is not None)
            term(p, n + 1, None, None, None, outs)
    return E


def game_ev_speed(dists, sp, order):
    """走力込みの精密EV(2段階探索の決勝用): 走者の身元を追跡し盗塁も遷移として挿入"""
    d9 = [dists[i] for i in order]
    s9 = [sp[i] for i in order]
    inn = []
    for lead in range(9):
        frontier = {((None, None, None), 0, lead): 1.0}
        runs = 0.0
        nxt = defaultdict(float)
        for _ in range(MAX_PA_INN):
            new = {}

            def add(rid, o, bi, q):
                if o >= 3:
                    nxt[bi % 9] += q
                else:
                    k = (rid, o, bi)
                    new[k] = new.get(k, 0.0) + q
            for (rid, o, bi), p in frontier.items():
                b = bi % 9
                # 盗塁オプション(一塁走者・二塁空き): 走者本人のatt/succ
                branches = [(rid, o, p)]
                r1, r2, r3 = rid
                if r1 is not None and r2 is None and o < 3:
                    att, succ = s9[r1]["att"], s9[r1]["succ"]
                    branches = [((None, r1, r3), o, p * att * succ),
                                ((None, None, r3), o + 1, p * att * (1 - succ)),
                                (rid, o, p * (1 - att))]
                for rid0, o0, p0 in branches:
                    if p0 <= 0:
                        continue
                    if o0 >= 3:
                        nxt[b] += p0  # 盗塁死で3アウト: 次の回は同じ打者から
                        continue
                    for pr, rn, nr, no in transitions_id(rid0, o0, d9[b], s9):
                        q = p0 * pr
                        runs += q * rn
                        nr2 = tuple(b if x == "B" else x for x in nr)
                        add(nr2, no, bi + 1, q)
            frontier = new
            if not frontier:
                break
        for (rid, o, bi), p in frontier.items():
            nxt[bi % 9] += p
        inn.append((runs, dict(nxt)))
    lead = {0: 1.0}
    total = 0.0
    for _ in range(9):
        nl = defaultdict(float)
        for li, p in lead.items():
            r, nd = inn[li]
            total += p * r
            for j, q in nd.items():
                nl[j] += p * q
        lead = dict(nl)
    return total


def optimize(dists, fixed=None, restarts=3, seed_orders=None):
    """並びの局所探索(全ペア交換の山登り+再出発)。fixed=固定スロット(投手)。
    returns (best_order(индексы元スロット), best_ev)"""
    import itertools
    n = 9
    free = [i for i in range(n) if i != fixed]

    def ev_of(order):
        return game_ev([dists[i] for i in order])

    def climb(order):
        cur = list(order)
        cur_ev = ev_of(cur)
        improved = True
        while improved:
            improved = False
            for a, b in itertools.combinations(range(n), 2):
                if fixed is not None and (cur[a] == fixed or cur[b] == fixed):
                    continue
                cand = list(cur)
                cand[a], cand[b] = cand[b], cand[a]
                e = ev_of(cand)
                if e > cur_ev + 1e-9:
                    cur, cur_ev = cand, e
                    improved = True
        return cur, cur_ev

    best, best_ev = climb(list(range(n)))
    orders = list(seed_orders or [])
    # 再出発: 打力降順(定石: 強い順に前へ)+回転
    strength = sorted(free, key=lambda i: -game_ev([dists[i]] * 9))
    for r in range(restarts):
        rot = strength[r:] + strength[:r]
        cand = [None] * n
        if fixed is not None:
            cand[fixed] = fixed
        it = iter(rot)
        for j in range(n):
            if cand[j] is None:
                cand[j] = next(it)
        orders.append(cand)
    for od in orders:
        o2, e2 = climb(od)
        if e2 > best_ev:
            best, best_ev = o2, e2
    return best, best_ev


def analyze_lineup(mmdd, gid):
    """両チームの打順評価。returns [{team, players, ev_actual, ev_best, best_order, bench_note}]"""
    lineup = parse_box_lineup(mmdd, gid)
    if not lineup:
        return []
    ids2 = game_ids2(mmdd, gid)
    ids = game_ids(mmdd, gid)
    import re as _re
    # away/homeのチーム名はids2のキー順でなくlineupの並び(先攻/後攻)に対応させる必要がある
    # → box打撃成績もplaybyplayも先攻が先。ids2キーはdict順不定のためeventsから取る
    from analyze import parse_game
    events, _ = parse_game(mmdd, gid)
    away = next((e["team"] for e in events if e["half"] == "表"), None)
    home = next((e["team"] for e in events if e["half"] == "裏"), None)
    if not away or not home:
        return []
    _, bench_bat = bench_roster(mmdd, gid)
    out = []
    for tm, lu in ((away, lineup[0]), (home, lineup[1])):
        players, dists, fixed = [], [], None
        ok = True
        for s0 in range(9):
            role, nm = lu.get(s0, ("", ""))
            pid = (ids2.get(tm) or {}).get(nm) or ids.get(nm)
            if not pid:
                ok = False
                break
            P = fetch_player(pid)
            if is_pitcher_bat(P):
                d = dict(PITCHER_BAT)
                fixed = s0
            else:
                d = batter_dist2(pid, P, mmdd)
            obp = sum(d.get(k, 0.0) for k in ("BB", "HBP", "1B", "2B", "3B", "HR"))
            players.append({"slot": s0 + 1, "name": nm, "role": role, "pid": pid,
                            "bats": P.get("bats", "右"), "obp": round(obp, 3),
                            "solo": round(game_ev([d] * 9), 2)})
            dists.append(d)
        if not ok or len(dists) != 9:
            continue
        ev_act = game_ev(dists)
        best, ev_best = optimize(dists, fixed=fixed)
        # ベンチ注記: スタメン野手最弱よりsolo EVが高いベンチ野手(上位1名)
        tc = TEAM_NAME2CODE.get(tm, "")
        starters_pid = {p["pid"] for p in players}
        cands, bench_best = [], None
        for nm, grp in (bench_bat.get(tm) or []):
            n0 = _norm_name(nm)
            hits = [p for p, dd in _HAND.items() if dd.get("team") == tc
                    and _norm_name(dd.get("name", "")).startswith(n0)]
            pid = hits[0] if len(hits) == 1 else None
            if not pid or pid in starters_pid:
                continue
            P = fetch_player(pid)
            if is_pitcher_bat(P) or not (P.get("bat") and P["bat"].get("PA", 0) >= 60):
                continue
            dc = batter_dist2(pid, P, mmdd)
            solo = game_ev([dc] * 9)
            cands.append((nm, grp, pid, dc, solo))
            if bench_best is None or solo > bench_best[1]:
                bench_best = (nm, solo)

        # ベストメンバー探索(9/8社長要望→9/8丸指摘で強化): 入替候補は「守備起用実績」で適格性判定
        # (今季その正確なポジションで3先発以上かつ直近30日以内=球団が実際に守備で使っている事実)。
        # 最大2枚・貪欲→最終並べ替え。守備範囲・年齢負担は実績で代理、休養・疲労は考慮外(免責)
        try:
            DEF = json.load(open(os.path.join(BASE, "data", "logs", "defense_starts.json"),
                                 encoding="utf-8"))
        except Exception:
            DEF = {}
        import datetime as _dt

        def exact_pos(role):
            for ch in role or "":
                if ch in "捕一二三遊左中右指投":
                    return ch
            return None

        def can_play(nm, pc):
            if pc == "指":
                return True
            d = DEF.get(f"{tm}|{nm}", {}).get(pc)
            if not d or d["n"] < 3:
                return False
            a = _dt.date(2026, int(mmdd[:2]), int(mmdd[2:]))
            l = _dt.date(2026, int(d["last"][:2]), int(d["last"][2:]))
            return (a - l).days <= 30

        cur_d = list(dists)
        swaps_in, used_b = [], set()
        for _ in range(2):
            base_ev0 = game_ev(cur_d)
            best_gain, best_swap = 0.05, None  # 微差の入替提案はしない
            for si, p in enumerate(players):
                pc = exact_pos(p["role"])
                if pc in (None, "投"):
                    continue
                for nm, grp, pidc, dc, solo in cands:
                    if nm in used_b or not can_play(nm, pc):
                        continue
                    trial = list(cur_d)
                    trial[si] = dc
                    gain = game_ev(trial) - base_ev0
                    if gain > best_gain:
                        best_gain, best_swap = gain, (si, nm, pc, dc)
            if not best_swap:
                break
            si, nm, pc, dc = best_swap
            cur_d[si] = dc
            used_b.add(nm)
            swaps_in.append((nm, pc))
        ev_bm = None
        if swaps_in:
            _, ev_bm = optimize(cur_d, fixed=fixed, restarts=1)
        # ベンチ最強打者がどの守備位置にも適格でない=代打専任(丸型)の判定 → カードで役割として尊重
        pinch_ace = None
        if bench_best:
            slots_pos = [exact_pos(p["role"]) for p in players]
            if not any(can_play(bench_best[0], pc) for pc in slots_pos if pc not in (None, "投")):
                pinch_ace = bench_best[0]
        out.append({"team": tm, "players": players, "fixed": fixed,
                    "ev_actual": round(ev_act, 3), "ev_best": round(ev_best, 3),
                    "diff": round(ev_act - ev_best, 3),
                    "best_order": [players[i]["name"] for i in best],
                    "ev_bestmem": round(ev_bm, 3) if ev_bm else None,
                    "bestmem_in": [f"{nm}({g})" for nm, g in swaps_in],
                    "pinch_ace": pinch_ace,
                    "bench_best": list(bench_best) if bench_best else None})
    return out


def main():
    mmdd, gid = sys.argv[1], sys.argv[2]
    res = analyze_lineup(mmdd, gid)
    for r in res:
        print(f"── {r['team']} 実際の打順EV {r['ev_actual']:.2f}点/試合 "
              f"vs 最適並び {r['ev_best']:.2f}点 (差 {r['diff']:+.2f}点 "
              f"= シーズン換算 {r['diff'] * 143:+.0f}点)")
        act = "".join(f"{p['slot']}{p['name']} " for p in r["players"])
        print(f"   実際: {act}")
        print(f"   最適: {' '.join(f'{i+1}{nm}' for i, nm in enumerate(r['best_order']))}")
        if r.get("ev_bestmem"):
            print(f"   ベストメンバー(同ポジ制約): {'+'.join(r['bestmem_in'])}IN → {r['ev_bestmem']:.2f}点")
    outp = os.path.join(BASE, "data", "out", mmdd, f"lineup_{gid}.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    json.dump(res, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved:", outp)


if __name__ == "__main__":
    main()
