# -*- coding: utf-8 -*-
"""分布v2: 打席ログDB(palog)による直近減衰重み付け+投手の回別ブケット
設計(docs/model-spec.md v1.1):
  - 全打席に経過日数の指数減衰重み w=0.5^(日数/HALFLIFE) を付ける
  - ログ窓(8/1〜)より古いシーズン打席は「シーズン合計−窓内」で正確に枚数を出し、
    平均経過日数AGE_OUTの一括重みで混ぜる(全打席がちょうど1回ずつ入る)
  - 未来不参照: asof当日以降のログ打席は使わない
  - 少サンプルはリーグへ縮小(有効打席数ベース)
  - 投手は回別(1-3/4-6/7+)の窓内成績を有効TBFで全体へブレンド
定数は全て較正予定(バックテストで半減期等を決める)と明示。
"""
import os, json, datetime
from stats import (LEAGUE, PITCHER_BAT, batter_dist_raw, pitcher_dist,  # noqa
                   batter_dist, _blend)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(BASE, "data", "logs")

HALFLIFE = 30.0   # 既定(calib.jsonで上書き)
AGE_OUT = 75.0    # ログ窓外打席の平均経過日数(フルバックフィル後はほぼ不使用)
SELF_PA = 120.0   # cap形の既定(calib.jsonで上書き)
INN_TBF = 60.0    # 回別ブケットの自立TBF(較正予定)

# ── バックテスト較正値(backtest.py出力・2026-09-03): 半減期と縮小はデータで決める ──
HALF_BAT = HALF_PIT = HALFLIFE
_SHRINK = {"b": ("cap", SELF_PA), "p": ("cap", SELF_PA)}
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "data", "logs", "calib.json"), encoding="utf-8") as _cf:
        _cal = json.load(_cf)
    HALF_BAT = _cal["bat"]["halflife"]
    HALF_PIT = _cal["pit"]["halflife"]
    _SHRINK = {"b": (_cal["bat"]["form"], _cal["bat"]["param"]),
               "p": (_cal["pit"]["form"], _cal["pit"]["param"])}
except Exception:
    pass


def _self_w(n_eff, kind):
    form, prm = _SHRINK[kind]
    return min(1.0, n_eff / prm) if form == "cap" else n_eff / (n_eff + prm)
CLS = ("BB", "HBP", "K", "1B", "2B", "3B", "HR", "OUT", "ROE")  # ROE=失策出塁(9/9フェーズ2)
FOLD = {"OUT_G": "OUT", "OUT_A": "OUT", "DP": "OUT"}  # 分布上はアウトに畳む(併殺・ゴロ率は別関数で使う)

_blog = _plog = _meta = None


def _load():
    global _blog, _plog, _meta
    if _blog is None:
        _blog = json.load(open(os.path.join(LOGS, "batters.json"), encoding="utf-8"))
        _plog = json.load(open(os.path.join(LOGS, "pitchers.json"), encoding="utf-8"))
        _meta = json.load(open(os.path.join(LOGS, "meta.json"), encoding="utf-8"))
    return _blog, _plog


def league_meta():
    _load()
    return _meta


def _days(asof, d):
    a = datetime.date(2026, int(asof[:2]), int(asof[2:]))
    b = datetime.date(2026, int(d[:2]), int(d[2:]))
    return (a - b).days


def _w(asof, d, half=None):
    return 0.5 ** (max(0, _days(asof, d)) / (half or HALFLIFE))


def _norm(c):
    s = sum(c.values())
    if s <= 0:
        return dict(LEAGUE)
    return {k: c.get(k, 0.0) / s for k in CLS}


def _season_bat_counts(b):
    """選手ページのシーズン打撃行→クラス別回数(SH除外分母)"""
    n = max(0, b["PA"] - b["SH"])
    c = {"BB": b["BB"], "HBP": b["HBP"], "K": b["SO"],
         "1B": max(0, b["H"] - b["b2"] - b["b3"] - b["HR"]),
         "2B": b["b2"], "3B": b["b3"], "HR": b["HR"]}
    c["OUT"] = max(0.0, n - sum(c.values()))
    return c, n


def _season_pit_counts(q):
    tbf = q["TBF"]
    nonhr = max(0, q["H"] - q["HR"])
    share = LEAGUE["1B"] + LEAGUE["2B"] + LEAGUE["3B"]
    c = {"BB": q["BB"], "HBP": q["HBP"], "K": q["SO"], "HR": q["HR"],
         "1B": nonhr * LEAGUE["1B"] / share, "2B": nonhr * LEAGUE["2B"] / share,
         "3B": nonhr * LEAGUE["3B"] / share}
    c["OUT"] = max(0.0, tbf - sum(c.values()))
    return c, tbf


def _decayed(rows, asof, season_counts, season_n, half=None, row_w=None):
    """窓内=個別減衰重み + 窓外=(シーズン−窓内)を一括重みで合算。
    row_w=行別の追加重み関数(役割変換②-c等・Noneで従来と同一)"""
    h = half or HALFLIFE
    wc = {k: 0.0 for k in CLS}
    win = {k: 0 for k in CLS}
    n_win = 0
    for r in rows:
        d, o = r[0], FOLD.get(r[1], r[1])
        if o not in wc or _days(asof, d) <= 0:  # 未来不参照(当日含む)
            continue
        wc[o] += _w(asof, d, h) * (row_w(r) if row_w else 1.0)
        win[o] += 1
        n_win += 1
    n_eff = sum(wc.values())
    if season_counts is not None:
        w_out = 0.5 ** (AGE_OUT / h)
        n_out = 0.0
        for k in CLS:
            out_k = max(0.0, season_counts.get(k, 0.0) - win[k])
            wc[k] += w_out * out_k
            n_out += out_k
        n_eff += w_out * n_out
    return _norm(wc), n_eff


W_2025 = 0.5 ** (350.0 / 90.0)  # シーズン跨ぎ減衰(前季打席の一括重み≈0.067・半減期90日)
_P25 = {}


def _prior25(pid):
    """2025本人分布(環境正規化済み)を(有効打席数, 分布)で返す。無ければNone(9/9フェーズ4)"""
    if "data" not in _P25:
        try:
            _P25["data"] = json.load(open(os.path.join(LOGS, "batters2025.json"),
                                          encoding="utf-8"))
        except Exception:
            _P25["data"] = {"players": {}, "league": {}}
    p = _P25["data"]["players"].get(pid)
    if not p:
        return None
    L25 = _P25["data"].get("league") or {}
    adj = {k: max(1e-9, p["d"].get(k, 0.0)) * max(1e-9, LEAGUE.get(k, 1e-9))
           / max(1e-9, L25.get(k, 1e-9)) for k in CLS}
    ssum = sum(adj.values())
    return p["n"] * W_2025, {k: v / ssum for k, v in adj.items()}


def batter_dist2(pid, P, asof):
    """打者分布v2。投手打席=標準分布。減衰重み+縮小。
    今季サンプル僅少の選手は2025本人分布(環境正規化・シーズン跨ぎ減衰)を混合(§7-c 4)"""
    blog, _ = _load()
    b = P.get("bat")
    n_season = (b["PA"] - b["SH"]) if b else 0
    if P.get("pit") and n_season < 60:
        return dict(PITCHER_BAT)
    rows = blog.get(pid, [])
    sc, sn = _season_bat_counts(b) if b else (None, 0)
    if sc is not None and asof < P.get("fetched", "0907"):
        sc, sn = None, 0  # スナップショットにasof以降の未来打席が混入するため不使用(9/7監査#5)
    if not rows and not b:
        pr = _prior25(pid)
        if pr:
            n25, d25 = pr
            return _blend(_blend(d25, _self_w(n25, "b")), LAMBDA_BAT)
        return dict(LEAGUE)
    d, n_eff = _decayed(rows, asof, sc, sn, HALF_BAT)
    pr = _prior25(pid)
    if pr:
        n25, d25 = pr
        d = {k: (n_eff * d.get(k, 0.0) + n25 * d25.get(k, 0.0)) / (n_eff + n25)
             for k in CLS}
        n_eff += n25
    # 追い縮小λ(9/9フェーズ4較正): 予測OBPの較正勾配を4カット日で実測→0.56〜0.70で一貫
    # =現行縮小は不足(上位帯過大・下位帯過小の両端が実測)。偏差を0.65倍に圧縮。
    # ゲート原子(lineup_gate.dist_of)にも9/10適用済み(通貨統一・FP再検証とセット)
    return _blend(_blend(d, _self_w(n_eff, "b")), LAMBDA_BAT)


K_CROSS_ROLE = 0.5  # 役割変換(②-c・9/9): 直近と異なる役割で投げた打席の重み(仮置き・較正課題)
_ROLE = {}


def _role_sets():
    """pitcher_ctxの登板記録から役割判定素材(先発日set・全登板list)を読む(キャッシュ)"""
    if "starts" not in _ROLE:
        try:
            pc = json.load(open(os.path.join(LOGS, "pitcher_ctx.json"), encoding="utf-8"))
            _ROLE["starts"] = {p: set(v) for p, v in (pc.get("starts") or {}).items()}
            _ROLE["apps"] = {p: sorted(v) for p, v in (pc.get("appearances") or {}).items()}
        except Exception:
            _ROLE["starts"], _ROLE["apps"] = {}, {}
    return _ROLE["starts"], _ROLE["apps"]


def pitcher_dist2(pid, P, inning, asof):
    """投手被打分布v2。全体(減衰)に回別ブケット(窓内)を有効TBFでブレンド。
    役割変換バイアス対策(②-c・9/9): 先発⇔救援の転向者は、直近役割(asof前の最終登板)と
    異なる役割で投げた打席をK_CROSS_ROLE倍に減重(66/371人が両役割経験の実態への対処。
    シーズン簿の残差は役割を分離できないため従来どおり=近似と明記)"""
    _, plog = _load()
    q = P.get("pit")
    rows = plog.get(pid, [])
    sc, sn = _season_pit_counts(q) if q and q["TBF"] >= 20 else (None, 0)
    if sc is not None and asof < P.get("fetched", "0907"):
        sc, sn = None, 0  # 未来参照遮断(9/7監査#5)
    if not rows and not sc:
        return dict(LEAGUE)
    starts, apps = _role_sets()
    stt = starts.get(pid) or set()
    row_w = None
    ap = [d0 for d0 in (apps.get(pid) or []) if d0 < asof] or (apps.get(pid) or [])
    if stt and ap:
        cur_sp = ap[-1] in stt
        if any((d0 in stt) != cur_sp for d0 in ap):  # 両役割が混在する転向者のみ発動
            row_w = (lambda r, _s=stt, _c=cur_sp:
                     1.0 if ((r[0] in _s) == _c) else K_CROSS_ROLE)
    overall, n_eff = _decayed(rows, asof, sc, sn, HALF_PIT, row_w)
    overall = _blend(overall, _self_w(n_eff, "p"))
    # 回別ブケット(窓内ログのみ・シーズンページに回別は無い)
    lo, hi = (1, 3) if inning <= 3 else (4, 6) if inning <= 6 else (7, 99)
    brows = [r for r in rows if len(r) > 2 and lo <= r[2] <= hi]
    bd, bn = _decayed(brows, asof, None, 0, HALF_PIT, row_w)
    wb = bn / (bn + INN_TBF)
    mix = {k: wb * bd[k] + (1 - wb) * overall[k] for k in CLS}
    s = sum(mix.values())
    mix = {k: v / s for k, v in mix.items()}
    # 追い縮小λ_pit(9/9フェーズ4=log5強度検証の実測回答): 短ホライズン(12-20日)の
    # 較正勾配0.88-0.93→0.90を採用。長ホライズンでは0.4-0.6まで落ちる(投手フォームの
    # ドリフト=ホライズン依存減衰の課題として記録)。エース級-1.3点の振れは概ね正・1割減衰
    return _blend(mix, LAMBDA_PIT)


LAMBDA_BAT = 0.65  # 打者分布の追い縮小(9/9較正・batter_dist2の注記参照)
LAMBDA_PIT = 0.90  # 投手分布の追い縮小(9/9較正・pitcher_dist2の注記参照)
K_SPLIT = 400.0  # 9/9較正: 検証5,100打席でK=400≒スプリット無視が最良。個人の左右差は
# 今季サンプルではほぼノイズ=信号はリーグ左右比(事前分布)が担う(The Bookの追認)


def batter_dist2_vs(pid, P, asof, vs_hand):
    """対左/対右スプリット分布(9/8左右対応): 窓内の該当打席(減衰)を
    「総合分布×リーグ左右係数」の事前分布へ縮小ブレンド(k=K_SPLIT)。
    利き腕不明・リーグ係数未整備ならNone(呼び出し側で総合分布を使う)"""
    if vs_hand not in ("左", "右"):
        return None
    blog, _ = _load()
    Lh = _meta.get(f"league_dist_vs{vs_hand}")
    L = _meta.get("league_dist")
    if not Lh or not L:
        return None
    base = batter_dist2(pid, P, asof)
    pri = {k: max(1e-9, base.get(k, 0.0)) * max(1e-9, Lh.get(k, 0.0))
           / max(1e-6, L.get(k, 1e-6)) for k in CLS}
    s = sum(pri.values())
    pri = {k: v / s for k, v in pri.items()}
    wc = {k: 0.0 for k in CLS}
    for r in blog.get(pid, []):
        if len(r) < 5 or r[4] != vs_hand:
            continue
        o = FOLD.get(r[1], r[1])
        if o not in wc or _days(asof, r[0]) <= 0:
            continue
        wc[o] += _w(asof, r[0], HALF_BAT)
    n_eff = sum(wc.values())
    w = n_eff / (n_eff + K_SPLIT)
    d = {k: w * (wc[k] / n_eff if n_eff else 0.0) + (1 - w) * pri[k] for k in CLS}
    s = sum(d.values())
    return {k: v / s for k, v in d.items()}


def effective_n(pid, kind, asof):
    """説明用: その選手の有効サンプル数(較正済み半減期を使用・9/7監査#27)"""
    blog, plog = _load()
    rows = (blog if kind == "b" else plog).get(pid, [])
    h = HALF_BAT if kind == "b" else HALF_PIT
    return sum(_w(asof, r[0], h) for r in rows if _days(asof, r[0]) > 0)


GB_SHRINK = 40.0        # ゴロ率の自立インプレーアウト数(較正予定)
PITCHER_GB_TILT = 1.10  # 投手打者のゴロ率係数(較正予定)


def _gb_share(rows, asof, is_batter=True):
    """窓内ログからゴロ率(インプレーアウト中)をリーグへ縮小して返す"""
    _load()
    gL = _meta["gb_share"]["p"]
    g = a = 0.0
    for r in rows:
        if _days(asof, r[0]) <= 0:
            continue
        c = r[1]
        if c in ("OUT_G", "DP"):
            g += 1
        elif c == "OUT_A":
            a += 1
    n = g + a
    if n <= 0:
        return gL
    w = n / (n + GB_SHRINK)
    return w * (g / n) + (1 - w) * gL


def dp_prob(pid_b, P_b, pid_p, asof):
    """併殺確率 P(併殺|インプレーアウト, 1塁走者・2死未満)
    = リーグ実測 × 打者ゴロ率×投手ゴロ率のオッズ合成による傾き"""
    blog, plog = _load()
    gL = _meta["gb_share"]["p"]
    dpL = _meta["dp_given_out"]["p"]
    if P_b.get("pit") and (not P_b.get("bat") or P_b["bat"]["PA"] < 60):
        gb = min(0.75, gL * PITCHER_GB_TILT)
    else:
        gb = _gb_share(blog.get(pid_b, []), asof)
    gp = _gb_share(plog.get(pid_p, []), asof, False) if pid_p else gL
    # オッズ合成(log5系)
    num = gb * gp / gL
    den = num + (1 - gb) * (1 - gp) / (1 - gL)
    gb_eff = num / den
    return max(0.05, min(0.45, dpL * gb_eff / gL))
