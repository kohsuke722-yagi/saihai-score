# -*- coding: utf-8 -*-
"""Phase1 v3: 采配の指示評価エンジン(2026-09-03 走力・継投フル装備版)
  - 分布v2(stats2): 全打席を経過日数で指数減衰(半減期30日・較正予定)+
    投手は回別ブケット(1-3/4-6/7+)+直近減衰。少サンプルはリーグへ縮小
  - 2打席先読み: この打席の結果分布→「実際の次打者」の打席をその選手の分布で評価→以降実測RE表
  - バント4分岐: baseballdata当季実測較正+個人巧拙(縮小)+走者状況調整
  - 終盤確率判定: 7回以降2点差以内は必要点数kの確率(実測PS表)
  - 走力(9/3): 走者簿記(runners.py)で実走者を特定し、進塁率・盗塁環境・併殺回避を個人化
  - 継投: 巡目・左右・連投・明日の可用性コスト・ワンポイント・暴投項
  - 未来不参照: 当日以降の打席ログは使わない
Usage: python src/phase1.py 0902 g-db-21
"""
import sys, os, re, json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import RE, re_of, ps_of, HAS_RETAB  # noqa
from runners import annotate, parse_box_subs, REACH  # noqa
from stats import fetch_player, odds_combine, platoon_adjust, LEAGUE  # noqa
from stats2 import batter_dist2, pitcher_dist2, effective_n, league_meta, dp_prob  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 進塁パラメータ: 当季リーグ実測(palog meta.json・n付き)から取得 ──
_M = league_meta()
ADV_1B_R2SCORE = _M["adv_1b_r2"]["p"]        # 単打で二塁走者生還(実測)
ADV_1B_R1TO3 = _M["adv_1b_r1to3"]["p"]       # 単打で一塁走者三塁へ(実測)
ADV_2B_R1SCORE = _M["adv_2b_r1"]["p"]        # 二塁打で一塁走者生還(実測)
ADV_OUT_R3SCORE = (1 - _M["gb_share"]["p"]) * _M["adv_out_r3"]["p"]
LEAGUE_DP = _M["dp_given_out"]["p"]          # 併殺機会での併殺率(実測)

# ── バント分岐確率: baseballdata当季実測較正(bunt_calib.py出力・無ければ代表値) ──
BUNT_P = {
    True:  {"succ": 0.72, "hit": 0.03, "leadout": 0.14, "fail": 0.11},  # 投手打者
    False: {"succ": 0.80, "hit": 0.05, "leadout": 0.10, "fail": 0.05},  # 野手
}
_BC_PLAYERS = {}
try:
    with open(os.path.join(BASE, "data", "logs", "bunt_calib.json"), encoding="utf-8") as _f:
        _bcj = json.load(_f)
    BUNT_P = {True: _bcj["bunt_p"]["pitcher"], False: _bcj["bunt_p"]["fielder"]}
    _BC_PLAYERS = _bcj.get("players", {})
except Exception:
    pass

# 走者状況によるバント難度調整(代表値・較正予定): 1,2塁は三塁封殺があり成功率が下がる
BUNT_STATE_ADJ = {"12": 0.07, "2": 0.03}

# スクイズ分岐(代表値・実測較正不能=件数極少。走力実装後に3塁走者補正)
SQUEEZE_P = {
    True:  {"succ": 0.62, "hit": 0.03, "out3": 0.15, "fail": 0.20},  # 投手打者
    False: {"succ": 0.70, "hit": 0.05, "out3": 0.12, "fail": 0.13},  # 野手
}
SUCC = {"1": "2", "2": "3", "12": "23", "13": "13", "3": "3", "23": "23", "123": "123", "": ""}
HITST = {"1": "12", "2": "13", "12": "123", "13": "123", "23": "123", "123": "123", "3": "13", "": "1"}
LEADOUT = {"1": "1", "2": "1", "12": "12", "13": "13", "23": "12", "123": "123", "3": ""}

# ── 投手文脈補正(pitcher_ctx.py出力): 巡目・連投・可用性・暴投 ──
try:
    with open(os.path.join(BASE, "data", "logs", "pitcher_ctx.json"), encoding="utf-8") as _f:
        PCTX = json.load(_f)
except Exception:
    PCTX = {"tto": {}, "rest": {}, "appearances": {}}

# ── 走力データ(runpower.py出力): "チーム名:選手名" → 走塁カウント ──
try:
    with open(os.path.join(BASE, "data", "logs", "runpower.json"), encoding="utf-8") as _f:
        RP = json.load(_f)
except Exception:
    RP = {}
try:
    with open(os.path.join(BASE, "data", "logs", "handedness.json"), encoding="utf-8") as _f:
        _HAND = json.load(_f)
except Exception:
    _HAND = {}
_sb_att = sum(d["sb_att"] for d in RP.values())
_sb_opp = sum(d["sb_opp"] for d in RP.values())
_sb_succ = sum(d["sb_succ"] for d in RP.values())
LG_SB_ATT = _sb_att / (_sb_att + _sb_opp) if (_sb_att + _sb_opp) else 0.05
LG_SB_SUCC = _sb_succ / _sb_att if _sb_att else 0.7

ONBASE_KEYS = ("BB", "HBP", "1B", "2B", "3B", "HR")

TEAM_NAME2CODE = {"巨人": "g", "DeNA": "db", "阪神": "t", "広島": "c", "中日": "d",
                  "ヤクルト": "s", "ソフトバンク": "h", "日本ハム": "f", "ロッテ": "m",
                  "西武": "l", "オリックス": "b", "楽天": "e"}


def _shr(y, n, p0, k):
    """縮小推定: 機会nが少ないほどリーグ値p0へ寄せる"""
    return (y + k * p0) / (n + k) if (n + k) > 0 else p0


def ob_mult(dist, m):
    """被出塁オッズをm倍して分布を再正規化(巡目・連投補正の適用)"""
    if abs(m - 1.0) < 1e-9:
        return dist
    ob = sum(dist.get(x, 0.0) for x in ONBASE_KEYS)
    if not (0.0 < ob < 1.0):
        return dist
    odds = ob / (1 - ob) * m
    ob2 = odds / (1 + odds)
    fg, fb = ob2 / ob, (1 - ob2) / (1 - ob)
    return {x: p * (fg if x in ONBASE_KEYS else fb) for x, p in dist.items()}


def rest_streak(pid, asof):
    """asof前日から遡った連続登板日数(0=休養明け)。未来不参照"""
    import datetime as _dt
    dates = set(PCTX.get("appearances", {}).get(pid, []))
    d = _dt.date(2026, int(asof[:2]), int(asof[2:]))
    s = 0
    while (d - _dt.timedelta(days=s + 1)).strftime("%m%d") in dates:
        s += 1
    return s


def _has_game_tomorrow(team_name, asof):
    """明日その チームの試合があるか(移動日・休み前の連投はコストゼロ)。範囲外は保守的に有り"""
    import datetime as _dt
    td = PCTX.get("team_dates", {}).get(TEAM_NAME2CODE.get(team_name, ""), [])
    if not td:
        return True
    d = _dt.date(2026, int(asof[:2]), int(asof[2:]))
    tmr = d + _dt.timedelta(days=1)
    if tmr > _dt.date(2026, int(td[-1][:2]), int(td[-1][2:])):
        return True
    return tmr.strftime("%m%d") in td


def future_cost(dist_x, streak_before, team_name=None, asof=None):
    """リリーフ起用の将来コスト = 明日の可用性低下(実測)×平均リリーフ比の1登板価値"""
    av, ra = PCTX.get("avail", {}), PCTX.get("relief_avg")
    if not av or not ra:
        return 0.0
    if team_name and asof and not _has_game_tomorrow(team_name, asof):
        return 0.0
    p0 = av.get("0", {}).get("p")
    p1 = av.get(str(min(2, streak_before + 1)), {}).get("p")
    if p0 is None or p1 is None:
        return 0.0
    drop = max(0.0, p0 - p1)
    adv = max(0.0, (ev_state("", 0, ra) - ev_state("", 0, dist_x)) * 4.2)
    return drop * adv


def transitions(state, outs, dist, p_dp=None, adv=None):
    """打席1つ分の遷移列挙: (確率, この間の得点, 次状態, 次アウト数) のリスト。
    p_dp=併殺確率(1塁走者・2死未満)。adv=走者別進塁パラメータ上書き{a2h,a13,a1h,ao3}"""
    A = {"a2h": ADV_1B_R2SCORE, "a13": ADV_1B_R1TO3,
         "a1h": ADV_2B_R1SCORE, "ao3": ADV_OUT_R3SCORE}
    if adv:
        A.update({k: v for k, v in adv.items() if v is not None})
    r1, r2, r3 = ("1" in state), ("2" in state), ("3" in state)
    E = []

    def term(p, runs, n1, n2, n3, nouts):
        if p <= 0:
            return
        ns = ("1" if n1 else "") + ("2" if n2 else "") + ("3" if n3 else "")
        E.append((p, runs, ns, nouts))

    for o, p in dist.items():
        if p <= 0:
            continue
        if o in ("BB", "HBP"):
            runs = 1 if (r1 and r2 and r3) else 0
            n3 = r3 or (r1 and r2)
            term(p, runs, True, r2 or r1, n3 if not (r1 and r2 and r3) else True, outs)
        elif o == "K":
            term(p, 0, r1, r2, r3, outs + 1)
        elif o == "OUT":
            pd = (p_dp if p_dp is not None else LEAGUE_DP) if (r1 and outs < 2) else 0.0
            if pd > 0:
                # 併殺: 打者+一塁走者アウト。二塁走者は三塁へ・三塁走者は3アウト未満なら生還
                dp_runs = 1 if (r3 and outs + 2 < 3) else 0
                term(p * pd, dp_runs, False, False, r2, outs + 2)
                p = p * (1 - pd)
            if r3 and outs < 2:
                term(p * A["ao3"], 1, r1, r2, False, outs + 1)
                term(p * (1 - A["ao3"]), 0, r1, r2, r3, outs + 1)
            else:
                term(p, 0, r1, r2, r3, outs + 1)
        elif o == "1B":
            runs = 1 if r3 else 0
            if r2:
                for pr, sc in ((A["a2h"], True), (1 - A["a2h"], False)):
                    r2to3 = not sc
                    if r1:
                        p13 = A["a13"] if not r2to3 else 0.0
                        term(p * pr * p13, runs + (1 if sc else 0), True, False, True, outs)
                        term(p * pr * (1 - p13), runs + (1 if sc else 0), True, True, r2to3, outs)
                    else:
                        term(p * pr, runs + (1 if sc else 0), True, False, r2to3, outs)
            else:
                if r1:
                    term(p * A["a13"], runs, True, False, True, outs)
                    term(p * (1 - A["a13"]), runs, True, True, False, outs)
                else:
                    term(p, runs, True, False, False, outs)
        elif o == "2B":
            runs = (1 if r3 else 0) + (1 if r2 else 0)
            if r1:
                term(p * A["a1h"], runs + 1, False, True, False, outs)
                term(p * (1 - A["a1h"]), runs, False, True, True, outs)
            else:
                term(p, runs, False, True, False, outs)
        elif o == "3B":
            term(p, int(r1) + int(r2) + int(r3), False, False, True, outs)
        elif o == "HR":
            term(p, 1 + int(r1) + int(r2) + int(r3), False, False, False, outs)
    return E


def ev_state(state, outs, dist, cont=None, p_dp=None, adv=None):
    """この打席をdistで消化した後の期待得点。cont(state,outs)=打席後の継続評価(既定=実測RE表)"""
    if outs >= 3:
        return 0.0
    if cont is None:
        cont = lambda s, o: re_of(s, o)
    total = 0.0
    for p, runs, ns, nouts in transitions(state, outs, dist, p_dp, adv):
        total += p * runs
        if nouts < 3:
            total += p * cont(ns, nouts)
    return total


def ps_state(state, outs, dist, k, cont=None, p_dp=None, adv=None):
    """この打席をdistで消化した後、回終了までに「あとk点以上」入る確率(終盤判定用・k<=2)"""
    if k <= 0:
        return 1.0
    if outs >= 3:
        return 0.0
    if cont is None:
        cont = lambda s, o, kk: ps_of(s, o, kk)
    total = 0.0
    for p, runs, ns, nouts in transitions(state, outs, dist, p_dp, adv):
        if runs >= k:
            total += p
        elif nouts < 3:
            total += p * cont(ns, nouts, k - runs)
    return total


def _norm_name(nm):
    return re.sub(r"[\s　・]", "", nm or "")


def runner_ctx(team, bases, pid_b=None, P_b=None, pid_pi=None, asof=None):
    """塁上の実走者から (adv上書き, 併殺確率, 盗塁オプション) を作る(走力9/3)
    returns (adv dict, dp_mult, sb=(att,succ) or None)"""
    adv, dp_mult, sb = {}, 1.0, None
    if not bases:
        return adv, dp_mult, sb
    r2 = bases.get("2")
    if r2:
        d = RP.get(f"{team}:{r2}")
        if d:
            adv["a2h"] = _shr(d["a2h_y"], d["a2h_n"], ADV_1B_R2SCORE, 8)
    r1 = bases.get("1")
    if r1:
        d = RP.get(f"{team}:{r1}")
        if d:
            adv["a13"] = _shr(d["a13_y"], d["a13_n"], ADV_1B_R1TO3, 8)
            dp_rate = _shr(d["dp_y"], d["dp_n"], LEAGUE_DP, 12)
            dp_mult = dp_rate / LEAGUE_DP if LEAGUE_DP else 1.0
            att = _shr(d["sb_att"], d["sb_att"] + d["sb_opp"], LG_SB_ATT, 15)
            succ = _shr(d["sb_succ"], d["sb_att"], LG_SB_SUCC, 8)
            sb = (att, succ)
    return adv, dp_mult, sb


def sb_ev(st, outs, sb):
    """盗塁オプションの期待値(一塁走者・二塁空きのみ)。打たせる選択の価値に加算"""
    if not sb or "1" not in st or "2" in st or outs >= 3:
        return 0.0
    att, succ = sb
    st_adv = "".join(sorted(st.replace("1", "2")))
    st_out = st.replace("1", "")
    base = re_of(st, outs)
    gain = succ * (re_of(st_adv, outs) - base) + (1 - succ) * (re_of(st_out, outs + 1) - base)
    return att * max(-1.0, gain)


def personalize_bunt(bp, is_p, team, batter):
    """バント巧拙の個人化: baseballdata個人企図/成功をタイプ値へ縮小ブレンド(k=10企図)"""
    key = f"{TEAM_NAME2CODE.get(team, '')}:{_norm_name(batter)}"
    d = _BC_PLAYERS.get(key)
    if not d or d.get("att", 0) == 0:
        return bp
    hit = bp["hit"]
    s_base = bp["succ"] / (1 - hit) if hit < 1 else bp["succ"]
    s = _shr(d["succ"], d["att"], s_base, 10)
    rem = (1 - s) * (1 - hit)
    lo_ratio = bp["leadout"] / (bp["leadout"] + bp["fail"]) if (bp["leadout"] + bp["fail"]) else 0.6
    return {"succ": s * (1 - hit), "hit": hit,
            "leadout": rem * lo_ratio, "fail": rem * (1 - lo_ratio)}


def state_adjust_bunt(bp, st):
    """走者状況によるバント難度(1,2塁は三塁封殺があり難しい)。代表値・較正予定"""
    adj = BUNT_STATE_ADJ.get(st, 0.0)
    if adj <= 0:
        return bp
    s = max(0.3, bp["succ"] - adj)
    return {**bp, "succ": s, "leadout": bp["leadout"] + (bp["succ"] - s)}


def name_ids(mmdd, gid):
    html = open(os.path.join(BASE, "data", "raw", mmdd, gid, "playbyplay.html"), encoding="utf-8").read()
    mp = {}
    for pid, nm in re.findall(r'href="/bis/players/(\d+)\.html">([^<]+)</a>', html):
        mp[nm.strip()] = pid
    return mp


def is_pitcher_bat(P):
    return bool(P.get("pit")) and (not P.get("bat") or P["bat"]["PA"] < 60)


def analyze_ph(mmdd, gid):
    events, _ = annotate(mmdd, gid)  # 走者簿記付き(runners.py)
    ids = name_ids(mmdd, gid)
    subs = parse_box_subs(mmdd, gid)          # 元選手→代走
    subs_rev = {v: k for k, v in subs.items()}  # 代走→元選手
    asof = mmdd
    away = next(e["team"] for e in events if e["half"] == "表")
    home = next(e["team"] for e in events if e["half"] == "裏")

    cur_pitcher = {}
    slots = {away: {}, home: {}}
    seq = {away: 0, home: 0}
    score = {away: 0, home: 0}
    bf = {}               # 投手名→この試合の対戦打者数(巡目計算用)
    entry_inning = {}     # 投手名→登板した回
    half_pa = {}          # (回,表裏)→打席行数(回頭交代の判定用)
    pending_change = []
    pr_done = set()
    reached = set()       # この半回に自分の打撃で出塁した選手(代走誤検出の防止)
    cur_half_key = None
    results = []

    for e in events:
        team = e["team"]
        defense = home if e["half"] == "表" else away
        if e["type"] == "pitching":
            t = e["text"]
            m = re.search(r"先発投手[）)]?\s*(\S+)", t)
            if m:
                cur_pitcher[defense] = m.group(1)
                entry_inning[m.group(1)] = 1
            m = re.search(r"→\s*(\S+)", t)
            if m:
                old, new = cur_pitcher.get(defense), m.group(1)
                if old and old != new:
                    pending_change.append({"kind": "relief", "def_team": defense,
                                           "old": old, "new": new, "bf_old": bf.get(old, 0),
                                           "old_entry": entry_inning.get(old, 1),
                                           "at_head": half_pa.get((e["inning"], e["half"]), 0) == 0,
                                           "inning": e["inning"], "half": e["half"]})
                cur_pitcher[defense] = new
                entry_inning[new] = e["inning"]
            continue
        if e["type"] != "pa":
            continue
        bat = e["batter"]
        half_pa[(e["inning"], e["half"])] = half_pa.get((e["inning"], e["half"]), 0) + 1
        diff = score[team] - score[defense]  # 指示時点の点差(攻撃側視点)
        score[team] += e.get("runs", 0)
        if bat.startswith("（走者") or "盗塁" in e.get("result", ""):
            continue
        s = seq[team] % 9
        seq[team] += 1
        nxt = slots[team].get((s + 1) % 9)
        bf[cur_pitcher.get(defense, "")] = bf.get(cur_pitcher.get(defense, ""), 0) + 1
        while pending_change:
            pc_ = pending_change.pop(0)
            results.append({**pc_, "team": team, "outs": e["outs"], "state": e["runners"],
                            "batter": e["batter"], "next": nxt,
                            "next2": slots[team].get((s + 2) % 9), "diff": diff,
                            "bases": e.get("bases"), "pitcher": None})
        if cur_half_key != (e["inning"], e["half"]):
            cur_half_key = (e["inning"], e["half"])
            reached = set()
        # ⑤代走検出: 塁上に代走名が現れた最初の打席行(自分の打撃で出た選手は除外)
        for b in "123":
            nm = (e.get("bases") or {}).get(b)
            if nm and nm in subs_rev and nm not in pr_done and nm not in reached:
                pr_done.add(nm)
                s_orig = next((k for k, v in slots[team].items() if v == subs_rev[nm]), None)
                results.append({"kind": "pr", "inning": e["inning"], "half": e["half"],
                                "team": team, "outs": e["outs"], "state": e["runners"],
                                "sub": nm, "orig": subs_rev[nm], "base": b, "diff": diff,
                                "batter": bat, "next": nxt, "slot_orig": s_orig, "slot_cur": s,
                                "bases": e.get("bases"), "pitcher": cur_pitcher.get(defense)})
        res = e.get("result", "")
        if "敬遠" in res:  # NPB表記は「敬遠フォアボール」(申告敬遠含む)
            results.append({"kind": "ibb", "inning": e["inning"], "half": e["half"], "team": team,
                            "def_team": defense, "outs": e["outs"], "state": e["runners"],
                            "batter": bat, "next": nxt, "next2": slots[team].get((s + 2) % 9),
                            "diff": diff, "bases": e.get("bases"),
                            "pitcher": cur_pitcher.get(defense)})
        if ("犠牲バント" in res or "犠打" in res
                or "バントヒット" in res or "スリーバント" in res):
            results.append({"kind": "squeeze" if "3" in e["runners"] else "bunt",
                            "inning": e["inning"], "half": e["half"], "team": team,
                            "outs": e["outs"], "state": e["runners"], "batter": bat,
                            "diff": diff, "next": nxt, "bases": e.get("bases"),
                            "pitcher": cur_pitcher.get(defense)})
            slots[team][s] = bat
            continue
        if (e["outs"] <= 1 and e["runners"] in ("1", "2", "12")
                and "敬遠" not in res and not bat.startswith("代打")):
            # ③強攻: バント定石場面で打たせた選択(計上条件はEV側で判定)
            results.append({"kind": "swing", "inning": e["inning"], "half": e["half"], "team": team,
                            "outs": e["outs"], "state": e["runners"], "batter": bat,
                            "diff": diff, "next": nxt, "bases": e.get("bases"),
                            "pitcher": cur_pitcher.get(defense)})
        if any(kw in res for kw in REACH):
            reached.add(bat.replace("代打・", "").strip())
        if bat.startswith("代打"):
            ph_name = bat.replace("代打・", "").strip()
            results.append({"kind": "ph", "inning": e["inning"], "half": e["half"], "team": team,
                            "slot": s + 1, "outs": e["outs"], "state": e["runners"],
                            "ph": ph_name, "orig": slots[team].get(s), "next": nxt,
                            "diff": diff, "bases": e.get("bases"),
                            "pitcher": cur_pitcher.get(defense)})
            slots[team][s] = ph_name
        else:
            slots[team][s] = bat

    # ── EV計算 ──
    out = []
    for r in results:
        st, outs, inning = r["state"], r["outs"], r["inning"]
        pid_pi = ids.get(r["pitcher"]) if r.get("pitcher") else None
        P_pi = fetch_player(pid_pi) if pid_pi else None
        pdist = pitcher_dist2(pid_pi, P_pi, inning, asof) if P_pi else dict(LEAGUE)
        thr = P_pi["throws"] if P_pi else "右"

        def full(P_b, pid_b):
            return platoon_adjust(odds_combine(batter_dist2(pid_b, P_b, asof), pdist), P_b["bats"], thr)

        # 次打者の継続評価(実打順)。不明ならRE表=リーグ平均
        nxt_name = (r.get("next") or "").replace("代打・", "").strip()
        pid_n = ids.get(nxt_name) if nxt_name else None
        if pid_n:
            P_n = fetch_player(pid_n)
            dist_n = full(P_n, pid_n)
            cont = lambda s2, o2, _d=dist_n: ev_state(s2, o2, _d)
            next_used = f"{nxt_name}({'投' if is_pitcher_bat(P_n) else P_n['bats']+'打'})"
        else:
            cont = None
            dist_n = None
            next_used = "不明→リーグ平均"

        # 走力: 塁上の実走者に応じた進塁・併殺・盗塁パラメータ
        adv_r, dpm_r, sb_r = runner_ctx(r["team"], r.get("bases"))

        # 終盤確率判定: 7回以降・2点差以内 → 必要点数k=max(1,攻撃側ビハインド)。kは攻守対称
        def prob_ctx(d):
            if not HAS_RETAB or inning < 7 or d is None or abs(d) > 2:
                return None
            return max(1, -d)

        def mk_pc(dn):
            def pc(s2, o2, kk):
                if kk <= 0:
                    return 1.0
                if o2 >= 3:
                    return 0.0
                if dn is not None:
                    return ps_state(s2, o2, dn, kk)
                return ps_of(s2, o2, kk)
            return pc

        if r["kind"] == "pr":
            # ⑤代走: ΔEV(走塁) + 打順の機会費用(近似: 残りイニング×4.3打席/9スロット)
            tc_ = TEAM_NAME2CODE.get(r["team"], "")

            def fuzzy_id(nm):
                if not nm:
                    return None
                hit = ids.get(nm) or next((v for k2, v in ids.items()
                                           if k2.startswith(nm) or nm.startswith(k2)), None)
                if hit:
                    return hit
                # 打席が無い代走はplaybyplayにリンクが無い→全選手名簿(handedness)から補完
                n0 = _norm_name(nm)
                return next((pid0 for pid0, d0 in _HAND.items()
                             if d0.get("team") == tc_ and _norm_name(d0.get("name", "")).startswith(n0)),
                            None)
            pid_sub, pid_or = fuzzy_id(r["sub"]), fuzzy_id(r["orig"])
            pid_at = ids.get(r["batter"].replace("代打・", "").strip())
            if not pid_sub or not pid_at:
                out.append({**r, "error": f"ID不明 sub={pid_sub} bat={pid_at}"})
                continue
            P_at = fetch_player(pid_at)
            d_at = full(P_at, pid_at)
            pdp0 = dp_prob(pid_at, P_at, pid_pi, asof)
            b_sub = dict(r.get("bases") or {})
            b_org = {**b_sub, r["base"]: r["orig"]}
            a_s, dm_s, sb_s = runner_ctx(r["team"], b_sub)
            a_o, dm_o, sb_o = runner_ctx(r["team"], b_org)
            ev_s = ev_state(st, outs, d_at, cont, p_dp=pdp0 * dm_s, adv=a_s) + sb_ev(st, outs, sb_s)
            ev_o = ev_state(st, outs, d_at, cont, p_dp=pdp0 * dm_o, adv=a_o) + sb_ev(st, outs, sb_o)
            gain = ev_s - ev_o
            opp = 0.0
            if pid_or and r.get("slot_orig") is not None:
                P_or = fetch_player(pid_or)
                P_sub = fetch_player(pid_sub)
                d_or0, d_sub0 = batter_dist2(pid_or, P_or, asof), batter_dist2(pid_sub, P_sub, asof)
                rem = max(0, 9 - inning)
                ahead = (r["slot_orig"] - r["slot_cur"]) % 9
                exp_pa = max(0.0, (rem * 4.3 - ahead) / 9.0)
                opp = exp_pa * max(0.0, (ev_state("", 0, d_or0) - ev_state("", 0, d_sub0)))
            rec = {**r, "ev_run_gain": round(gain, 3), "opp_cost": round(opp, 3),
                   "judge": "RE", "decision": round(gain - opp, 3)}
            k = prob_ctx(r.get("diff"))
            if k:
                ps_s = ps_state(st, outs, d_at, k, cont=mk_pc(dist_n), p_dp=pdp0 * dm_s, adv=a_s)
                ps_o = ps_state(st, outs, d_at, k, cont=mk_pc(dist_n), p_dp=pdp0 * dm_o, adv=a_o)
                rec.update({"judge": f"P>={k}", "decision_prob": round(ps_s - ps_o, 3)})
            out.append(rec)
            continue

        if r["kind"] == "relief":
            # ⑨継投。回頭のリリーフ交代は記録のみ(9/3裁定: 続投は選択肢外)
            if r.get("old_entry", 1) > 1 and r.get("at_head"):
                rec0 = {**r, "judge": "none", "decision": None,
                        "note": "回頭リリーフ交代=記録のみ(実決断は「どのリリーフか」・将来課題)"}
                pid_nw = ids.get(r["new"])
                if pid_nw:
                    P_nw = fetch_player(pid_nw)
                    stk = rest_streak(pid_nw, asof)
                    rec0["streak_new"] = stk
                    rec0["usage_cost_new"] = round(
                        future_cost(pitcher_dist2(pid_nw, P_nw, inning, asof), stk,
                                    r["def_team"], asof), 3)
                out.append(rec0)
                continue
            pid_old, pid_new = ids.get(r["old"]), ids.get(r["new"])
            if not pid_old or not pid_new:
                out.append({**r, "error": f"投手ID不明 {r['old']}/{r['new']}"})
                continue
            P_old, P_new = fetch_player(pid_old), fetch_player(pid_new)
            pd_old = pitcher_dist2(pid_old, P_old, inning, asof)
            pd_new = pitcher_dist2(pid_new, P_new, inning, asof)
            streak = rest_streak(pid_new, asof)
            rk = "fresh" if streak == 0 else ("r1" if streak == 1 else "r2")
            pd_new_adj = ob_mult(pd_new, PCTX["rest"].get(rk, 1.0))
            bf0 = r.get("bf_old", 0)

            def opt_dists(pdist_fn, thr_x):
                ds = []
                for idx, nm in enumerate((r.get("batter"), r.get("next"), r.get("next2"))):
                    nm2 = (nm or "").replace("代打・", "").strip()
                    pidb = ids.get(nm2) if nm2 else None
                    if not pidb:
                        ds.append(None)
                        continue
                    Pb = fetch_player(pidb)
                    ds.append(platoon_adjust(odds_combine(batter_dist2(pidb, Pb, asof),
                                                          pdist_fn(idx)), Pb["bats"], thr_x))
                return ds

            def ev_chain(ds):
                if ds[0] is None:
                    return None
                c3 = (lambda s2, o2, _d=ds[2]: ev_state(s2, o2, _d)) if ds[2] is not None else None
                c2 = (lambda s2, o2, _d=ds[1], _c=c3: ev_state(s2, o2, _d, _c)) if ds[1] is not None else None
                return ev_state(st, outs, ds[0], c2, adv=adv_r)

            def ps_chain(ds, kk):
                def mkc(d, nxtc):
                    if d is None:
                        return None
                    def cfun(s2, o2, k2):
                        if k2 <= 0:
                            return 1.0
                        if o2 >= 3:
                            return 0.0
                        return ps_state(s2, o2, d, k2, cont=nxtc)
                    return cfun
                return ps_state(st, outs, ds[0], kk, cont=mkc(ds[1], mkc(ds[2], None)), adv=adv_r)

            # 続投側の劣化: 先発=巡目乗数(実測)。回中のリリーフ=同一回内なので補正なし
            def stay_mult(i2):
                if r.get("old_entry", 1) == 1:
                    return PCTX["tto"].get(str(min(3, (bf0 + i2) // 9 + 1)), 1.0)
                return 1.0
            ds_stay = opt_dists(lambda i2: ob_mult(pd_old, stay_mult(i2)),
                                P_old.get("throws", "右"))
            ds_new = opt_dists(lambda i2: pd_new_adj, P_new.get("throws", "右"))
            ev_stay, ev_new = ev_chain(ds_stay), ev_chain(ds_new)
            if ev_stay is None or ev_new is None:
                out.append({**r, "error": "先頭打者ID不明"})
                continue
            # 暴投リスク(投手別実測率×全走者1進塁の価値×約3打者)※率はスポナビ蓄積で本稼働
            _ADV1 = {"": ("", 0), "1": ("2", 0), "2": ("3", 0), "3": ("", 1), "12": ("23", 0),
                     "13": ("2", 1), "23": ("3", 1), "123": ("23", 1)}
            def wp_term(pid_x):
                rt = PCTX.get("wp_rate", {}).get(pid_x, PCTX.get("wp_league", 0.0))
                ns, rn = _ADV1.get(st, (st, 0))
                return rt * (rn + re_of(ns, outs) - re_of(st, outs)) * 3 if st else 0.0
            ev_stay += wp_term(pid_old)
            ev_new += wp_term(pid_new)
            # ワンポイント外形用の1打者評価
            ev1_stay = ev_state(st, outs, ds_stay[0], adv=adv_r)
            ev1_new = ev_state(st, outs, ds_new[0], adv=adv_r)
            fc_new = future_cost(pd_new, streak, r["def_team"], asof)
            rec = {**r, "judge": "RE", "streak_new": streak, "tto_old": min(3, bf0 // 9 + 1),
                   "old_throws": P_old.get("throws", "右"), "new_throws": P_new.get("throws", "右"),
                   "ev_stay": round(ev_stay, 3), "ev_new": round(ev_new, 3),
                   "future_cost_new": round(fc_new, 3),
                   "decision_1bat": round(ev1_stay - ev1_new, 3),
                   "decision": round(ev_stay - ev_new, 3),
                   "decision_net": round(ev_stay - ev_new - fc_new, 3)}
            # 左対左ワンポイント外形なら1打者評価を主に(NPBは3打者ルール無し)
            def bats_of(nm):
                pidb = ids.get((nm or "").replace("代打・", "").strip())
                return fetch_player(pidb).get("bats") if pidb else None
            if (not r.get("at_head") and P_new.get("throws") == "左"
                    and bats_of(r.get("batter")) == "左"):
                rec["one_point"] = True
                rec["decision_net"] = round(rec["decision_1bat"] - fc_new, 3)
            k = prob_ctx(r.get("diff"))
            if k:
                rec.update({"judge": f"P>={k}",
                            "ps_stay": round(ps_chain(ds_stay, k), 3),
                            "ps_new": round(ps_chain(ds_new, k), 3)})
                rec["decision_prob"] = round(rec["ps_stay"] - rec["ps_new"], 3)
            out.append(rec)
            continue

        if r["kind"] == "ibb":
            pid_b = ids.get(r["batter"].replace("代打・", "").strip())
            if not pid_b:
                out.append({**r, "error": "打者ID不明"})
                continue
            P_b = fetch_player(pid_b)
            d_b = full(P_b, pid_b)
            dp_b = dp_prob(pid_b, P_b, pid_pi, asof) * dpm_r
            ev_pitch = ev_state(st, outs, d_b, cont, p_dp=dp_b, adv=adv_r) + sb_ev(st, outs, sb_r)
            # 歩かせた後の状態(フォースで押し出される走者を進める)
            r1, r2, r3 = ("1" in st), ("2" in st), ("3" in st)
            walk_runs = 1 if (r1 and r2 and r3) else 0
            st2 = "1" + ("2" if (r2 or r1) else "") + ("3" if (r3 or (r1 and r2)) else "")
            nxt2_name = (r.get("next2") or "").replace("代打・", "").strip()
            pid_n2 = ids.get(nxt2_name) if nxt2_name else None
            d_n2 = full(fetch_player(pid_n2), pid_n2) if pid_n2 else None
            cont2 = (lambda s2, o2, _d=d_n2: ev_state(s2, o2, _d)) if d_n2 is not None else None
            if pid_n:
                dp_n = dp_prob(pid_n, P_n, pid_pi, asof)
                ev_walk = walk_runs + ev_state(st2, outs, dist_n, cont2, p_dp=dp_n)
            else:
                dp_n = None
                ev_walk = walk_runs + re_of(st2, outs)
            rec = {**r, "next_used": next_used, "judge": "RE",
                   "ev_pitch": round(ev_pitch, 3), "ev_walk": round(ev_walk, 3),
                   "decision": round(ev_pitch - ev_walk, 3)}
            k = prob_ctx(r.get("diff"))
            if k:
                ps_pitch = ps_state(st, outs, d_b, k, cont=mk_pc(dist_n), p_dp=dp_b, adv=adv_r)
                if walk_runs >= k:
                    ps_walk = 1.0
                elif pid_n:
                    ps_walk = ps_state(st2, outs, dist_n, k - walk_runs,
                                       cont=mk_pc(d_n2), p_dp=dp_n)
                else:
                    ps_walk = ps_of(st2, outs, k - walk_runs)
                rec.update({"judge": f"P>={k}", "ps_pitch": round(ps_pitch, 3),
                            "ps_walk": round(ps_walk, 3),
                            "decision_prob": round(ps_pitch - ps_walk, 3)})
            out.append(rec)
            continue

        if r["kind"] in ("bunt", "squeeze", "swing"):
            pid_b = ids.get(r["batter"].replace("代打・", "").strip())
            if not pid_b:
                out.append({**r, "error": "打者ID不明"})
                continue
            P_b = fetch_player(pid_b)
            is_p = is_pitcher_bat(P_b)
            pdp = dp_prob(pid_b, P_b, pid_pi, asof) * dpm_r
            d_b = full(P_b, pid_b)
            ev_swing = ev_state(st, outs, d_b, cont, p_dp=pdp, adv=adv_r) + sb_ev(st, outs, sb_r)
            c = cont if cont else (lambda s2, o2: re_of(s2, o2))
            k = prob_ctx(r.get("diff"))
            pc = mk_pc(dist_n)
            if r["kind"] == "squeeze":
                sp = SQUEEZE_P[is_p]
                # 3塁走者の走力で憤死率を補正(a2h=際どい生還の実績を速度代理に・±20%上限)
                r3n = (r.get("bases") or {}).get("3")
                d3 = RP.get(f"{r['team']}:{r3n}") if r3n else None
                if d3 and d3.get("a2h_n", 0) + 8 > 0:
                    spd = _shr(d3["a2h_y"], d3["a2h_n"], ADV_1B_R2SCORE, 8) / ADV_1B_R2SCORE
                    spd = max(0.8, min(1.2, spd))
                    sp = dict(sp)
                    out3_new = sp["out3"] * (2 - spd)
                    sp["succ"] += sp["out3"] - out3_new
                    sp["out3"] = out3_new
                rest = st.replace("3", "")
                run1 = 1 if outs + 1 < 3 else 0  # 2死スクイズ成功は得点無効(タイミングプレー近似)
                ev_b = (sp["succ"] * (run1 + c(SUCC.get(rest, rest), outs + 1))
                        + sp["hit"] * (1 + c(HITST.get(rest, rest), outs))
                        + sp["out3"] * c(HITST.get(rest, rest), outs + 1)
                        + sp["fail"] * c(st, outs + 1))
                bp_used = sp
            else:
                bp = state_adjust_bunt(personalize_bunt(BUNT_P[is_p], is_p, r["team"], r["batter"]), st)
                ev_b = (bp["succ"] * c(SUCC.get(st, st), outs + 1)
                        + bp["hit"] * c(HITST.get(st, st), outs)
                        + bp["leadout"] * c(LEADOUT.get(st, st), outs + 1)
                        + bp["fail"] * c(st, outs + 1))
                bp_used = bp
            rec = {**r, "batter_is_pitcher": is_p, "next_used": next_used,
                   "branch_p": {kk: round(vv, 4) for kk, vv in bp_used.items()},
                   "p_dp": round(pdp, 3), "judge": "RE",
                   "n_eff": round(effective_n(pid_b, "b", asof), 1),
                   "ev_swing": round(ev_swing, 3), "ev_bunt": round(ev_b, 3)}
            if r["kind"] == "swing":
                rec["decision"] = round(ev_swing - ev_b, 3)
                # ③計上条件: 投手打者は全件・野手はバントが現実的に迷える場面のみ
                rec["counted"] = bool(is_p or ev_b >= ev_swing - 0.02)
            else:
                rec["decision"] = round(ev_b - ev_swing, 3)
            if k:
                ps_swing = ps_state(st, outs, d_b, k, cont=pc, p_dp=pdp, adv=adv_r)
                if r["kind"] == "squeeze":
                    ps_b = (sp["succ"] * pc(SUCC.get(rest, rest), outs + 1, k - run1)
                            + sp["hit"] * pc(HITST.get(rest, rest), outs, k - 1)
                            + sp["out3"] * pc(HITST.get(rest, rest), outs + 1, k)
                            + sp["fail"] * pc(st, outs + 1, k))
                else:
                    ps_b = (bp["succ"] * pc(SUCC.get(st, st), outs + 1, k)
                            + bp["hit"] * pc(HITST.get(st, st), outs, k)
                            + bp["leadout"] * pc(LEADOUT.get(st, st), outs + 1, k)
                            + bp["fail"] * pc(st, outs + 1, k))
                dprob = (ps_swing - ps_b) if r["kind"] == "swing" else (ps_b - ps_swing)
                rec.update({"judge": f"P>={k}", "ps_swing": round(ps_swing, 3),
                            "ps_bunt": round(ps_b, 3), "decision_prob": round(dprob, 3)})
            out.append(rec)
            continue

        # 代打
        pid_ph, pid_or = ids.get(r["ph"]), ids.get(r["orig"]) if r["orig"] else None
        if not pid_ph or not pid_or:
            out.append({**r, "error": f"ID不明 ph={pid_ph} orig={pid_or}"})
            continue
        P_ph, P_or = fetch_player(pid_ph), fetch_player(pid_or)
        b_ph, b_or = batter_dist2(pid_ph, P_ph, asof), batter_dist2(pid_or, P_or, asof)

        def three_ev(bd, bats, pdp):
            e_base = ev_state(st, outs, bd, cont, p_dp=pdp, adv=adv_r)
            e_pit = ev_state(st, outs, odds_combine(bd, pdist), cont, p_dp=pdp, adv=adv_r)
            e_full = ev_state(st, outs, platoon_adjust(odds_combine(bd, pdist), bats, thr),
                              cont, p_dp=pdp, adv=adv_r)
            return e_base, e_pit, e_full

        dp_or = dp_prob(pid_or, P_or, pid_pi, asof) * dpm_r
        dp_ph = dp_prob(pid_ph, P_ph, pid_pi, asof) * dpm_r
        a1, b1, c1 = three_ev(b_or, P_or["bats"], dp_or)
        a2, b2, c2 = three_ev(b_ph, P_ph["bats"], dp_ph)
        rec = {**r,
               "orig_bats": P_or["bats"], "ph_bats": P_ph["bats"], "pitcher_throws": thr,
               "orig_is_pitcher": is_pitcher_bat(P_or), "next_used": next_used, "judge": "RE",
               "n_eff_ph": round(effective_n(pid_ph, "b", asof), 1),
               "n_eff_orig": round(effective_n(pid_or, "b", asof), 1),
               "ev_orig": round(c1, 3), "ev_ph": round(c2, 3), "decision": round(c2 - c1, 3),
               "bd_talent": round(a2 - a1, 3),
               "bd_pitcher": round((b2 - a2) - (b1 - a1), 3),
               "bd_platoon": round((c2 - b2) - (c1 - b1), 3)}
        k = prob_ctx(r.get("diff"))
        if k:
            pc = mk_pc(dist_n)
            d_or_f = platoon_adjust(odds_combine(b_or, pdist), P_or["bats"], thr)
            d_ph_f = platoon_adjust(odds_combine(b_ph, pdist), P_ph["bats"], thr)
            ps_or_v = ps_state(st, outs, d_or_f, k, cont=pc, p_dp=dp_or, adv=adv_r)
            ps_ph_v = ps_state(st, outs, d_ph_f, k, cont=pc, p_dp=dp_ph, adv=adv_r)
            rec.update({"judge": f"P>={k}", "ps_orig": round(ps_or_v, 3),
                        "ps_ph": round(ps_ph_v, 3),
                        "decision_prob": round(ps_ph_v - ps_or_v, 3)})
        out.append(rec)
    return out


if __name__ == "__main__":
    mmdd, gid = sys.argv[1], sys.argv[2]
    res = analyze_ph(mmdd, gid)
    outp = os.path.join(BASE, "data", "out", mmdd, f"{gid}_ph.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    json.dump(res, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in res:
        if "error" in r:
            print(f"  ! {r['inning']}回{r['half']}: {r.get('kind','')} {r['error']}")
            continue
        prob_note = ""
        if "decision_prob" in r:
            prob_note = f"  [{r['judge']}判定 {r['decision_prob']:+.1%}]"
        if r.get("kind") == "pr":
            print(f"{r['inning']}回{r['half']} {r['team']} {r['outs']}死{r['state'] or '走者無'} 代走:{r['orig']}→{r['sub']}({r['base']}塁)")
            print(f"   走塁ゲイン {r['ev_run_gain']:+.3f} − 機会費用 {r['opp_cost']:.3f}  指示 {r['decision']:+.3f}点")
            continue
        if r.get("kind") == "relief":
            if r.get("decision") is None:
                if r.get("usage_cost_new") is not None:
                    rest_s0 = ("休養明け", "連投", "3連投+")[min(2, r.get("streak_new", 0))]
                    print(f"{r['inning']}回{r['half']} {r['def_team']}守備 継投(回頭・記録のみ): {r['old']}→{r['new']}({rest_s0}) 起用の将来コスト −{r['usage_cost_new']:.3f}点")
                continue
            rest_s = ("休養明け", "連投", "3連投+")[min(2, r["streak_new"])]
            op = "・ワンポイント判定" if r.get("one_point") else ""
            print(f"{r['inning']}回{r['half']} {r['def_team']}守備 {r['outs']}死{r['state'] or '走者無'} 継投:{r['old']}({r['tto_old']}巡目)→{r['new']}({r['new_throws']}投・{rest_s}{op}) 先頭:{r['batter']}")
            print(f"   続投EV {r['ev_stay']:.3f} vs 交代EV {r['ev_new']:.3f} 将来コスト{r['future_cost_new']:.3f}  指示 {r['decision_net']:+.3f}点(守備側){prob_note}")
            continue
        if r.get("kind") == "ibb":
            print(f"{r['inning']}回{r['half']} {r['def_team']}守備 {r['outs']}死{r['state'] or '走者無'} 申告敬遠:{r['batter']} 次打者:{r['next_used']}")
            print(f"   勝負EV {r['ev_pitch']:.3f} vs 歩かせEV {r['ev_walk']:.3f}  指示 {r['decision']:+.3f}点(守備側){prob_note}")
            continue
        if r.get("kind") in ("bunt", "squeeze"):
            pb = "(投手)" if r.get("batter_is_pitcher") else "(野手)"
            nm = "スクイズ" if r["kind"] == "squeeze" else "バント"
            print(f"{r['inning']}回{r['half']} {r['team']} {r['outs']}死{r['state'] or '走者無'} {nm}:{r['batter']}{pb} 対{r['pitcher']} 次打者:{r['next_used']}")
            print(f"   強攻EV {r['ev_swing']:.3f} vs {nm}期待 {r['ev_bunt']:.3f}(成功{r['branch_p']['succ']:.0%}混合)  指示 {r['decision']:+.3f}点{prob_note}")
            continue
        if r.get("kind") == "swing":
            if not r.get("counted"):
                continue
            pb = "(投手)" if r.get("batter_is_pitcher") else "(野手)"
            print(f"{r['inning']}回{r['half']} {r['team']} {r['outs']}死{r['state']} 強攻:{r['batter']}{pb} 対{r['pitcher']} 次打者:{r['next_used']}")
            print(f"   強攻EV {r['ev_swing']:.3f} vs バント期待 {r['ev_bunt']:.3f}  指示 {r['decision']:+.3f}点{prob_note}")
            continue
        po = "(投手)" if r["orig_is_pitcher"] else f"({r['orig_bats']}打)"
        print(f"{r['inning']}回{r['half']} {r['team']} {r['outs']}死{r['state'] or '走者無'} 対{r['pitcher']}({r['pitcher_throws']}投) 次打者:{r['next_used']}")
        print(f"   元:{r['orig']}{po} EV {r['ev_orig']:.3f} → 代打:{r['ph']}({r['ph_bats']}打,有効n{r['n_eff_ph']}) EV {r['ev_ph']:.3f}"
              f"  指示 {r['decision']:+.3f}点  [打力{r['bd_talent']:+.3f} 投手{r['bd_pitcher']:+.3f} 左右{r['bd_platoon']:+.3f}]{prob_note}")
    print("saved:", outp)
