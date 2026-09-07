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
