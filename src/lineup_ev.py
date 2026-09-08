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

# バント方策の対象状態(3塁走者ありはスクイズ=別物・2死は非合理でDPも選ばない)
BUNT_STATES = ("1", "2", "12")


def bunt_options(tm, names, dists, pitcher_flags):
    """規範方策(9/9裁定A=規範で探索・B=野手も対象): リーグRE基準でev_bunt>ev_swingとなる
    (塁,アウト)だけバント4分岐(個人巧拙・状況難度込み)へ差し替える方策表。
    returns [dict{(st,o): bp4分岐dict}] — 静的判定なので遷移表の前計算と互換
    (真の逐次最適は後ろ向き帰納が要るが打順文脈での判定反転は二次効果・plan-bunt-dp.md)"""
    from phase1 import BUNT_P, personalize_bunt, state_adjust_bunt, ev_state, \
        SUCC, HITST, LEADOUT
    from analyze import re_of
    out = []
    for nm, d, is_p in zip(names, dists, pitcher_flags):
        opt = {}
        for st in BUNT_STATES:
            bp = state_adjust_bunt(personalize_bunt(BUNT_P[is_p], is_p, tm, nm), st)
            for o in (0, 1):
                ev_b = (bp["succ"] * re_of(SUCC[st], o + 1)
                        + bp["hit"] * re_of(HITST[st], o)
                        + bp["leadout"] * re_of(LEADOUT[st], o + 1)
                        + bp["fail"] * re_of(st, o + 1))
                if ev_b > ev_state(st, o, d):
                    opt[(st, o)] = (bp, None)  # None=規範(純バント遷移)
        out.append(opt)
    return out


def bunt_options_desc(tm, names, dists, pitcher_flags):
    """記述方策(実際の監督文化): 実測企図率π(bunt_calib.pi・タイプ合算率へ縮小k=15)で
    π×バント4分岐+(1-π)×打撃分布の混合遷移にする方策表。「実際の打順EV」用。
    野手はリーグ一律だと主砲に幻のバントを課すため、個人の季節企図数で傾向スケール
    (企図0の強打者→π≈0.2倍・常連→上振れ。cap3倍・縮小c=2)"""
    from phase1 import (BUNT_P, personalize_bunt, state_adjust_bunt, _shr,
                        _BC_PLAYERS, TEAM_NAME2CODE, _norm_name)
    try:
        cal = json.load(open(os.path.join(BASE, "data", "logs", "bunt_calib.json"),
                             encoding="utf-8"))
    except Exception:
        cal = {}
    PI = cal.get("pi", {})
    # 野手の平均季節企図数(傾向スケールの基準): リーグ全野手企図÷レギュラー枠96
    f_att = (cal.get("stats", {}).get("fielder", {}).get("att", 0)) / 96.0 or 7.0
    tc = TEAM_NAME2CODE.get(tm, "")
    out = []
    for nm, d, is_p in zip(names, dists, pitcher_flags):
        tbl = PI.get("pitcher" if is_p else "fielder", {})
        pool_a = sum(v["att"] for v in tbl.values())
        pool_n = sum(v["opp"] for v in tbl.values())
        pool = pool_a / pool_n if pool_n else 0.0
        prop = 1.0
        if not is_p:
            my_att = (_BC_PLAYERS.get(f"{tc}:{_norm_name(nm)}") or {}).get("att", 0)
            prop = min(3.0, (my_att + 2.0) / (f_att + 2.0))
        opt = {}
        for st in BUNT_STATES:
            bp = state_adjust_bunt(personalize_bunt(BUNT_P[is_p], is_p, tm, nm), st)
            for o in (0, 1):
                c = tbl.get(f"{st}:{o}")
                if not c:
                    continue
                pi = min(0.97, _shr(c["att"], c["opp"], pool, 15) * prop)
                if pi > 0.005:
                    opt[(st, o)] = (bp, pi)
        out.append(opt)
    return out


def _bunt_branches(st, o, bp):
    """バント4分岐を素DPの遷移形式(p, runs, 次状態, 次アウト)に(対象状態は得点枝なし)"""
    from phase1 import SUCC, HITST, LEADOUT
    return [(bp["succ"], 0, SUCC[st], o + 1), (bp["hit"], 0, HITST[st], o),
            (bp["leadout"], 0, LEADOUT[st], o + 1), (bp["fail"], 0, st, o + 1)]


def _trans_table(dists, bunts=None):
    """打者別×全(塁,アウト)の遷移リストを前計算。bunts=方策表
    {(st,o): (bp, π)} — π=None:規範(純バント) / π=float:記述(π混合)"""
    T = []
    for i, d in enumerate(dists):
        bo = bunts[i] if bunts else {}
        t = {}
        for st in ("", "1", "2", "3", "12", "13", "23", "123"):
            for o in (0, 1, 2):
                ent = bo.get((st, o))
                if not ent:
                    t[(st, o)] = transitions(st, o, d)
                    continue
                bp, pi = ent
                bb = _bunt_branches(st, o, bp)
                if pi is None:
                    t[(st, o)] = bb
                else:
                    t[(st, o)] = [(p * pi, r, ns, no) for p, r, ns, no in bb] + \
                                 [(p * (1 - pi), r, ns, no)
                                  for p, r, ns, no in transitions(st, o, d)]
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


def game_ev(dists, bunts=None):
    """この並びの期待得点(9イニング・先頭打者の持ち越し込み)"""
    T = _trans_table(dists, bunts)
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


def full_search(dists, fixed=None, topk=200, bunts=None):
    """総当り(9/8社長要望): 投手固定なら8!=40,320通りを全評価。
    returns (best_order, best_ev, top_orders[(ev, order)降順])"""
    import heapq
    import itertools
    T = _trans_table(dists, bunts)
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


def dist_short(pid, asof, half=15.0):
    """短期記憶(半減期15日)の打者分布 — ベストメンバー候補の頑健性チェック用。
    母体の較正半減期(batter_dist2)には触らない(9/8社長「減衰率おかしいのでは」への
    二重時計ルール: 長短両方の記憶で上回る候補のみ提案)"""
    from stats2 import _load, _decayed, _season_bat_counts, _self_w
    from stats import fetch_player, LEAGUE, _blend
    P = fetch_player(pid)
    b = P.get("bat")
    if P.get("pit") and ((b["PA"] - b["SH"]) if b else 0) < 60:
        return dict(PITCHER_BAT)
    blog, _ = _load()
    rows = blog.get(pid, [])
    sc, sn = _season_bat_counts(b) if b else (None, 0)
    if sc is not None and asof < P.get("fetched", "0907"):
        sc, sn = None, 0
    if not rows and not b:
        return dict(LEAGUE)
    d, ne = _decayed(rows, asof, sc, sn, half)
    return _blend(d, _self_w(ne, "b"))


def recent_form(pid, asof, days=14):
    """直近days日の実出塁率(SH除外・10打席未満はNone)。フォーム注記用(9/8社長指摘)"""
    from stats2 import _load, _days
    blog, _ = _load()
    rows = [r for r in blog.get(pid, []) if 0 < _days(asof, r[0]) <= days]
    pa = [r for r in rows if r[1] != "SH"]
    if len(pa) < 10:
        return None
    ob = sum(1 for r in pa if r[1] in ("BB", "HBP", "1B", "2B", "3B", "HR"))
    return ob / len(pa)


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


def _bunt_branches_id(rid, o, bp, b):
    """バント4分岐の走者ID版(対象状態は3塁走者なし=r3はNone)。bは打者のスロットidx"""
    r1, r2, _ = rid
    succ = (None, r1, r2)  # 全走者1つ進塁・打者アウト("1"→2塁,"2"→3塁,"12"→2,3塁)
    if r1 is not None and r2 is not None:
        hit, lead = (b, r1, r2), (b, r1, None)   # leadout=先頭走者(r2)が三塁封殺
    elif r1 is not None:
        hit, lead = (b, r1, None), (b, None, None)
    else:
        hit, lead = (b, None, r2), (b, None, None)
    return [(bp["succ"], 0, succ, o + 1), (bp["hit"], 0, hit, o),
            (bp["leadout"], 0, lead, o + 1), (bp["fail"], 0, rid, o + 1)]


def game_ev_speed(dists, sp, order, bunts=None):
    """走力込みの精密EV(2段階探索の決勝用): 走者の身元を追跡し盗塁も遷移として挿入"""
    d9 = [dists[i] for i in order]
    s9 = [sp[i] for i in order]
    b9 = [bunts[i] for i in order] if bunts else None
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
                    ent = None
                    if b9:
                        stc = ("1" if rid0[0] is not None else "") + \
                              ("2" if rid0[1] is not None else "") + \
                              ("3" if rid0[2] is not None else "")
                        ent = b9[b].get((stc, o0))
                    if not ent:
                        trans = transitions_id(rid0, o0, d9[b], s9)
                    else:
                        bp_pol, pi = ent
                        bb = _bunt_branches_id(rid0, o0, bp_pol, b)
                        if pi is None:
                            trans = bb
                        else:
                            trans = [(p * pi, r, ns, no) for p, r, ns, no in bb] + \
                                    [(p * (1 - pi), r, ns, no) for p, r, ns, no
                                     in transitions_id(rid0, o0, d9[b], s9)]
                    for pr, rn, nr, no in trans:
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


def optimize(dists, fixed=None, restarts=3, seed_orders=None, bunts=None):
    """並びの局所探索(全ペア交換の山登り+再出発)。fixed=固定スロット(投手)。
    returns (best_order(индексы元スロット), best_ev)"""
    import itertools
    n = 9
    free = [i for i in range(n) if i != fixed]

    def ev_of(order):
        return game_ev([dists[i] for i in order],
                       [bunts[i] for i in order] if bunts else None)

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
        out.append(analyze_team(tm, mmdd, players, dists, fixed, bench_bat))
    return out


def analyze_team(tm, mmdd, players, dists, fixed, bench_bat):
    """1チーム分のエンジン評価(analyze_lineupから抽出・9/8試合前カード対応)。
    players/dists=スタメン9人(打順順)・fixed=投手スロット・bench_bat=bench_roster野手側"""
    # 9/9裁定: 探索は局所探索(素DP・数秒)・表示EVは走力込みDPで統一通貨に
    # (検証: 走力は並びを±0.001級しか動かさないがEV水準を+0.3%上げる → 表示のみ精密化)
    # バント方策(9/9裁定A): 実際EV=記述方策(実測π=監督文化の混合)・探索/最適EV=規範方策
    if True:  # 抽出時のインデント維持
        tc = TEAM_NAME2CODE.get(tm, "")
        sp = speed_params(tc, players)
        pf = [i == fixed for i in range(9)]
        nms = [p["name"] for p in players]
        b_desc = bunt_options_desc(tm, nms, dists, pf)
        b_norm = bunt_options(tm, nms, dists, pf)
        ev_act_plain = game_ev(dists, b_desc)
        ev_act = game_ev_speed(dists, sp, list(range(9)), b_desc)
        best, ev_best_plain = optimize(dists, fixed=fixed, bunts=b_norm)
        ev_best = game_ev_speed(dists, sp, best, b_norm)
        if ev_best < ev_act:  # 通貨差で最適が逆転する稀ケース: 実際の並びが最適
            best, ev_best = list(range(9)), ev_act
        # ベンチ注記: スタメン野手最弱よりsolo EVが高いベンチ野手(上位1名)
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

        # ベストメンバー: 組み合わせ+再配置込み(9/8社長「噛み合いも考慮して」)。
        # 「打者集合を選ぶ(打撃EV)+守備は適格割当が存在するか(Kuhn法マッチング)」に定式化。
        # スターターの守備位置シャッフル(ダルベック一塁IN→玉突きで三塁に別の人等)も許容
        import itertools as _it
        field_slots = [i for i in range(9) if i != fixed]
        POSL = [exact_pos(players[i]["role"]) for i in field_slots]

        def elig(nm, pos, own=None):
            return pos == "指" or pos == own or can_play(nm, pos)

        def assignment(team_list):
            """team_list=[(名前, 現ポジorNone)] を POSL へ全員割当できれば pos_idx->player_idx"""
            adj = [[j for j, pos in enumerate(POSL) if elig(nm, pos, own)]
                   for nm, own in team_list]
            mp = [-1] * len(POSL)

            def aug(i, vis):
                for j in adj[i]:
                    if j in vis:
                        continue
                    vis.add(j)
                    if mp[j] < 0 or aug(mp[j], vis):
                        mp[j] = i
                        return True
                return False
            for i in range(len(team_list)):
                if not aug(i, set()):
                    return None
            return mp

        base_ev0 = game_ev(dists)
        # 二重時計ルール(9/8社長): 短期記憶(h=15日)の分布でもゲインが正の案のみ提案
        dists_s = [dists[i] if i == fixed else dist_short(players[i]["pid"], mmdd)
                   for i in range(9)]
        base_s = game_ev(dists_s)
        cands_s = {c[0]: dist_short(c[2], mmdd) for c in cands}
        sols = []
        for k in (1, 2):
            for ins in _it.combinations(cands, k):
                for outs in _it.combinations(range(len(field_slots)), k):
                    team_list = [(players[si]["name"], POSL[ii])
                                 for ii, si in enumerate(field_slots) if ii not in outs]
                    team_list += [(c[0], None) for c in ins]
                    mp = assignment(team_list)
                    if mp is None:
                        continue
                    trial = list(dists)
                    trial_s = list(dists_s)
                    for c, oi in zip(ins, outs):
                        trial[field_slots[oi]] = c[3]
                        trial_s[field_slots[oi]] = cands_s[c[0]]
                    gain = game_ev(trial) - base_ev0
                    if gain <= 0.05:  # 微差の入替提案はしない
                        continue
                    if game_ev(trial_s) - base_s <= 0:  # 短期記憶で負→頑健でない
                        continue
                    # IN選手の割当先ポジ(表示用)と本職度(タイブレーク用)
                    in_pos, fam = {}, 0
                    n_stay = len(field_slots) - k
                    for j, pi in enumerate(mp):
                        if pi >= n_stay:
                            nm_in = team_list[pi][0]
                            in_pos[nm_in] = POSL[j]
                            fam += DEF.get(f"{tm}|{nm_in}", {}).get(POSL[j], {}).get("n", 0)
                    sols.append((gain, fam, ins, outs, in_pos))
        swaps_in, swap_slots = [], {}
        cur_d = list(dists)
        if sols:
            # 最良ゲイン±0.02の帯内では本職度(IN選手の割当ポジ先発数合計)を優先
            # (9/8社長「3Bより1Bでは」— 守備の質は起用実績で代理)
            gmax = max(s[0] for s in sols)
            gain, fam, ins, outs, in_pos = max(
                (s for s in sols if s[0] >= gmax - 0.02), key=lambda s: s[1])
            for c, oi in zip(ins, outs):
                nm, _grp, pidc, dc, _solo = c
                si = field_slots[oi]
                cur_d[si] = dc
                swap_slots[si] = nm
                # 直近フォーム注記(9/8社長「ダルベックは直近落ちてる」→総合力評価だと明示)
                fr = recent_form(pidc, mmdd)
                ob_dc = sum(dc.get(k2, 0.0) for k2 in ("BB", "HBP", "1B", "2B", "3B", "HR"))
                tag = ""
                if fr is not None and fr <= ob_dc - 0.06:
                    tag = "・直近▼"
                elif fr is not None and fr >= ob_dc + 0.06:
                    tag = "・直近▲"
                swaps_in.append((nm, in_pos.get(nm, "?") + tag))
        ev_bm = None
        if swaps_in:
            nms_bm = [swap_slots.get(i, nms[i]) for i in range(9)]
            b_norm_bm = bunt_options(tm, nms_bm, cur_d, pf)
            o_bm, _ = optimize(cur_d, fixed=fixed, restarts=1, bunts=b_norm_bm)
            sp_bm = speed_params(tc, [{"name": n} for n in nms_bm])
            ev_bm = max(game_ev_speed(cur_d, sp_bm, o_bm, b_norm_bm), ev_best)
        # ベンチ最強打者がどの守備位置にも適格でない=代打専任(丸型)の判定 → カードで役割として尊重
        pinch_ace = None
        if bench_best:
            slots_pos = [exact_pos(p["role"]) for p in players]
            if not any(can_play(bench_best[0], pc) for pc in slots_pos if pc not in (None, "投")):
                pinch_ace = bench_best[0]
        # 主砲の置き場注記(9/8社長「佐々木はもっと前では」・§7-dの傾向表示/P4ゲート通過済み)
        star_note = None
        field_i = [i for i in range(9) if i != fixed]
        star_i = max(field_i, key=lambda i: players[i]["solo"])
        rest_i = [i for i in range(9) if i not in (star_i, fixed)]
        curve = {}
        for s in range(9):
            if s == fixed:
                continue
            o = [None] * 9
            if fixed is not None:
                o[fixed] = fixed
            o[s] = star_i
            it = iter(rest_i)
            for j in range(9):
                if o[j] is None:
                    o[j] = next(it)
            curve[s] = game_ev([dists[i] for i in o], [b_norm[i] for i in o])
        smax = max(curve, key=curve.get)
        band_s = [s for s in curve if curve[smax] - curve[s] <= 0.003]
        gain_s = curve[smax] - curve[star_i]
        if star_i not in band_s and gain_s >= 0.01:
            lo, hi = min(band_s) + 1, max(band_s) + 1
            rng = f"{lo}番" if lo == hi else f"{lo}〜{hi}番"
            star_note = (f"★{players[star_i]['name']}は{rng}配置が良さそう"
                         f"(現{star_i + 1}番・+{gain_s:.2f}点の傾向)")
        return {"team": tm, "players": players, "fixed": fixed,
                "star_note": star_note,
                "ev_actual": round(ev_act, 3), "ev_best": round(ev_best, 3),
                "diff": round(ev_act - ev_best, 3),
                "ev_actual_plain": round(ev_act_plain, 3),
                "ev_best_plain": round(ev_best_plain, 3),
                "best_order": [players[i]["name"] for i in best],
                "ev_bestmem": round(ev_bm, 3) if ev_bm else None,
                "bestmem_in": [f"{nm}({g})" for nm, g in swaps_in],
                "pinch_ace": pinch_ace,
                "bench_best": list(bench_best) if bench_best else None}


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
