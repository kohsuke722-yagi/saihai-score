# -*- coding: utf-8 -*-
"""選手成績の取得・キャッシュ・分布化(NPB公式選手ページ)"""
import datetime
import os, re, json, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "data", "players")
UA = {"User-Agent": "Mozilla/5.0 (baseball-ev personal research)"}


def strip_tags(x):
    return re.sub(r"<[^>]+>", "", x).replace("&nbsp;", " ").strip()


def fetch_player(pid: str) -> dict:
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, f"{pid}.json")
    if os.path.exists(cp):
        return json.load(open(cp, encoding="utf-8"))
    url = f"https://npb.jp/bis/players/{pid}.html"
    html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf-8", "replace")
    time.sleep(1.0)
    name_m = re.search(r"<title>([^<|（(]+)", html)
    name = name_m.group(1).strip().replace("　", "") if name_m else pid
    hand = re.search(r"(右|左|両)投(右|左|両)打", html)
    throws, bats = (hand.group(1), hand.group(2)) if hand else ("右", "右")
    out = {"pid": pid, "name": name, "throws": throws, "bats": bats, "bat": None, "pit": None,
           "fetched": datetime.date.today().strftime("%m%d")}  # 未来参照遮断用(9/7監査#5)
    # 2026年行(寛容パース)。投手成績は2trに分割されているため後続行を連結する
    for mm in re.finditer(r'2026\s*</td>\s*<td class="team">[^<]*</td>((?:\s*<td[^>]*>.*?</td>)+?)\s*</tr>', html, re.S):
        cells = [strip_tags(c) for c in re.findall(r"(?s)<td[^>]*>(.*?)</td>", mm.group(1))]
        nums = len(cells)
        if nums == 21 and out["bat"] is None:  # 打撃: G,PA,AB,R,H,2B,3B,HR,TB,RBI,SB,CS,SH,SF,BB,HBP,SO,GIDP,AVG,SLG,OBP
            c = cells
            out["bat"] = {"G": int(c[0]), "PA": int(c[1]), "AB": int(c[2]), "H": int(c[4]),
                          "b2": int(c[5]), "b3": int(c[6]), "HR": int(c[7]),
                          "SH": int(c[12]), "SF": int(c[13]), "BB": int(c[14]),
                          "HBP": int(c[15]), "SO": int(c[16]), "GIDP": int(c[17])}
        elif nums == 12 and out["pit"] is None:
            # 投手行: 登板,勝,敗,S,HLD,HP,完投,完封,無四球,勝率,打者,回(入れ子表で行が分断される)
            # → 行の残り(被安打,被HR,与四球,与死球,奪三振,暴投,ボーク,失点,自責,防御率)を行末まで直接すくう
            c = cells
            row_end = html.find("</tr>", mm.end())
            tail = html[mm.end():row_end] if row_end != -1 else ""
            t = [strip_tags(x) for x in re.findall(r"(?s)<td[^>]*>(.*?)</td>", tail)]
            try:
                out["pit"] = {"TBF": int(c[10]), "IP": c[11].replace("\r", "").replace("\n", "").replace(" ", ""),
                              "H": int(t[0]), "HR": int(t[1]), "BB": int(t[2]), "IBB": 0,
                              "HBP": int(t[3]), "SO": int(t[4])}
            except (ValueError, IndexError):
                pass
    json.dump(out, open(cp, "w", encoding="utf-8"), ensure_ascii=False)
    return out


# ── リーグ基準分布: 当季実測(palogが毎晩meta.jsonへ)を正とし、無ければ代表値(9/8修正:
#    ハードコード値は実リーグよりOBPが1.2pt高い架空打者で、低n選手の縮小先として過大だった) ──
LEAGUE = {"BB": 0.085, "HBP": 0.010, "K": 0.215, "1B": 0.148,
          "2B": 0.042, "3B": 0.004, "HR": 0.026, "ROE": 0.009}
LEAGUE["OUT"] = 1.0 - sum(LEAGUE.values())
try:
    with open(os.path.join(BASE, "data", "logs", "meta.json"), encoding="utf-8") as _f:
        _ld = json.load(_f).get("league_dist")
    if (_ld and abs(sum(_ld.values()) - 1.0) < 0.02
            and all(k in _ld for k in ("BB", "K", "1B", "HR", "OUT"))):
        LEAGUE = {k: float(_ld.get(k, 0.0))
                  for k in ("BB", "HBP", "K", "1B", "2B", "3B", "HR", "OUT", "ROE")}
except Exception:
    pass

# 投手の打撃標準分布(セ・リーグ投手打席の代表値)。ROE=送りバント失敗(エラー)が主
PITCHER_BAT = {"BB": 0.03, "HBP": 0.004, "K": 0.42, "1B": 0.09,
               "2B": 0.012, "3B": 0.001, "HR": 0.002, "ROE": 0.010}
PITCHER_BAT["OUT"] = 1.0 - sum(PITCHER_BAT.values())


def batter_dist(p: dict) -> dict:
    """打者の1打席結果分布(犠打除外PAベース)。投手=投手標準分布/少サンプル=リーグへ縮小"""
    b = p.get("bat")
    n = (b["PA"] - b["SH"]) if b else 0
    if p.get("pit") and n < 60:
        return dict(PITCHER_BAT)  # 投手の打席は標準分布(個人の少サンプルは使わない)
    if not b or n < 30:
        base = batter_dist_raw(b) if b and n > 0 else dict(LEAGUE)
        return _blend(base, n / 120.0)
    if n < 120:
        return _blend(batter_dist_raw(b), n / 120.0)  # 縮小推定(120PAで自立)
    return batter_dist_raw(b)


def _blend(base, w):
    out = {k: w * base.get(k, 0) + (1 - w) * LEAGUE.get(k, 0.0)
           for k in ("BB", "HBP", "K", "1B", "2B", "3B", "HR", "ROE")}
    out["OUT"] = 1.0 - sum(out.values())
    return out


def batter_dist_raw(b: dict) -> dict:
    pa = max(1, b["PA"] - b["SH"])
    d = {"BB": b["BB"] / pa, "HBP": b["HBP"] / pa, "K": b["SO"] / pa,
         "1B": (b["H"] - b["b2"] - b["b3"] - b["HR"]) / pa,
         "2B": b["b2"] / pa, "3B": b["b3"] / pa, "HR": b["HR"] / pa}
    d["OUT"] = max(0.0, 1.0 - sum(d.values()))
    return d


def pitcher_dist(p: dict) -> dict:
    """投手の被打分布(打者換算)。非HR安打は1B/2B/3Bへリーグ比率で配分"""
    q = p.get("pit")
    if not q or q["TBF"] < 30:
        return dict(LEAGUE)
    tbf = q["TBF"]
    nonhr = max(0, q["H"] - q["HR"])
    share = LEAGUE["1B"] + LEAGUE["2B"] + LEAGUE["3B"]
    d = {"BB": (q["BB"]) / tbf, "HBP": q["HBP"] / tbf, "K": q["SO"] / tbf,
         "HR": q["HR"] / tbf,
         "1B": nonhr / tbf * (LEAGUE["1B"] / share),
         "2B": nonhr / tbf * (LEAGUE["2B"] / share),
         "3B": nonhr / tbf * (LEAGUE["3B"] / share)}
    d["OUT"] = max(0.0, 1.0 - sum(d.values()))
    return d


def odds_combine(b: dict, pch: dict) -> dict:
    """オッズ比法(log5系)で打者×投手を合成"""
    x = {}
    for k in b:
        l = max(LEAGUE.get(k, 1e-4), 1e-4)
        x[k] = max(1e-6, b[k]) * max(1e-6, pch.get(k, l)) / l
    s = sum(x.values())
    return {k: v / s for k, v in x.items()}


PLATOON = 0.04  # 旧・一律近似(実測が無い場合のフォールバック)
_PL_OR = None
_ONB_KEYS = ("BB", "HBP", "1B", "2B", "3B", "HR")


def _platoon_or():
    global _PL_OR
    if _PL_OR is None:
        try:
            with open(os.path.join(BASE, "data", "logs", "pitcher_ctx.json"), encoding="utf-8") as f:
                _PL_OR = json.load(f).get("platoon") or {}
        except Exception:
            _PL_OR = {}
    return _PL_OR


def platoon_adjust(d: dict, bats: str, throws: str) -> dict:
    """左右補正(9/7再設計): 一律±4%→実測の非対称オッズ比(同一打者内MH・毎晩再較正)。
    実測2026: 右打の利き手有利はほぼゼロ(OR1.01)・左打は明確(OR1.05)。
    有利/不利へsqrt(OR)ずつ振り分けて被出塁オッズをスケール"""
    if bats == "両":
        bats_eff = "左" if throws == "右" else "右"
    else:
        bats_eff = bats
    orv = _platoon_or().get(bats_eff, 1 + 2 * PLATOON)
    m = max(0.8, min(1.25, orv)) ** 0.5
    f = m if bats_eff != throws else 1.0 / m
    ob = sum(d.get(k, 0.0) for k in _ONB_KEYS)
    if not (0.0 < ob < 1.0) or abs(f - 1.0) < 1e-9:
        return dict(d)
    odds = ob / (1 - ob) * f
    ob2 = odds / (1 + odds)
    fg, fb = ob2 / ob, (1 - ob2) / (1 - ob)
    return {k: v * (fg if k in _ONB_KEYS else fb) for k, v in d.items()}
