# -*- coding: utf-8 -*-
"""カード生成v1(汎用): box.htmlメタ自動解析+phase1 v3全采配+監督名(2026-09-03)
Usage: python src/build_card2.py 0902 g-db-21 [--png]
出力: data/out/{mmdd}/card_{gid}.html (+ --png でEdgeヘッドレス2倍レンダ)
"""
import json
import math
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEAMS = {  # 権利クリーンな近似カラー・モノグラムはイニシャル
    "巨人": {"name": "読売<br>ジャイアンツ", "mono": "YG", "color": "#f97709", "glow": "249,119,9"},
    "DeNA": {"name": "横浜DeNA<br>ベイスターズ", "mono": "DB", "color": "#2266cc", "glow": "34,102,204"},
    "阪神": {"name": "阪神<br>タイガース", "mono": "HT", "color": "#ffd23f", "glow": "255,210,63"},
    "広島": {"name": "広島東洋<br>カープ", "mono": "C", "color": "#ff3b30", "glow": "255,59,48"},
    "中日": {"name": "中日<br>ドラゴンズ", "mono": "D", "color": "#2b6bd7", "glow": "43,107,215"},
    "ヤクルト": {"name": "東京ヤクルト<br>スワローズ", "mono": "YS", "color": "#12b886", "glow": "18,184,134"},
    "ソフトバンク": {"name": "福岡ソフトバンク<br>ホークス", "mono": "H", "color": "#f5c518", "glow": "245,197,24"},
    "日本ハム": {"name": "北海道日本ハム<br>ファイターズ", "mono": "F", "color": "#58a6d6", "glow": "88,166,214"},
    "ロッテ": {"name": "千葉ロッテ<br>マリーンズ", "mono": "M", "color": "#aab4c4", "glow": "170,180,196"},
    "西武": {"name": "埼玉西武<br>ライオンズ", "mono": "L", "color": "#3f6ad8", "glow": "63,106,216"},
    "オリックス": {"name": "オリックス<br>バファローズ", "mono": "B", "color": "#c9a24a", "glow": "201,162,74"},
    "楽天": {"name": "東北楽天<br>ゴールデンイーグルス", "mono": "E", "color": "#c3002f", "glow": "195,0,47"},
}
FULL2SHORT = {"読売ジャイアンツ": "巨人", "横浜DeNAベイスターズ": "DeNA", "阪神タイガース": "阪神",
              "広島東洋カープ": "広島", "中日ドラゴンズ": "中日", "東京ヤクルトスワローズ": "ヤクルト",
              "福岡ソフトバンクホークス": "ソフトバンク", "北海道日本ハムファイターズ": "日本ハム",
              "千葉ロッテマリーンズ": "ロッテ", "埼玉西武ライオンズ": "西武",
              "オリックス・バファローズ": "オリックス", "東北楽天ゴールデンイーグルス": "楽天"}
CODE = {"巨人": "g", "DeNA": "db", "阪神": "t", "広島": "c", "中日": "d", "ヤクルト": "s",
        "ソフトバンク": "h", "日本ハム": "f", "ロッテ": "m", "西武": "l", "オリックス": "b", "楽天": "e"}
CATLABEL = {"bunt": "バント", "squeeze": "スクイズ", "ph": "代打", "ibb": "申告敬遠",
            "relief": "継投", "pr": "代走", "swing": "強攻"}
HASHTAG = {"巨人": "読売ジャイアンツ", "DeNA": "横浜DeNAベイスターズ", "阪神": "阪神タイガース",
           "広島": "広島カープ", "中日": "中日ドラゴンズ", "ヤクルト": "ヤクルトスワローズ",
           "ソフトバンク": "ソフトバンクホークス", "日本ハム": "日本ハムファイターズ",
           "ロッテ": "ロッテマリーンズ", "西武": "西武ライオンズ",
           "オリックス": "オリックスバファローズ", "楽天": "楽天イーグルス"}


def parse_meta(mmdd, gid):
    """box.htmlヘッダ: 日付・球場・両チーム・開始/試合時間・最終スコア"""
    html = open(os.path.join(BASE, "data", "raw", mmdd, gid, "box.html"), encoding="utf-8").read()
    plain = re.sub(r"<[^>]+>", " ", html)
    plain = re.sub(r"[\s ]+", " ", plain.replace("&nbsp;", " "))
    m = re.search(r"(\d{4})年(\d+)月(\d+)日（(.)） (.+?) 【", plain)
    date = f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日({m.group(4)})" if m else ""
    venue = m.group(5).replace(" ", "") if m else ""  # 「神 宮」等のスペース入り表記対応
    mt = re.search(r"】 (\S+?) vs (\S+?) \d+回戦", plain)
    home_full, away_full = mt.group(1), mt.group(2)
    ms = re.search(r"◇開始 (\S+?) ◇.*?◇試合時間 (\d+)時間(\d+)分", plain)
    gametime = f"{ms.group(1)} / {ms.group(2)}:{ms.group(3)}" if ms else ""
    home, away = FULL2SHORT[home_full], FULL2SHORT[away_full]

    def final_score(full):
        i = plain.index(full + " ", plain.index("計 H E"))
        seg = plain[i + len(full):].split()
        toks = []
        for t in seg[:22]:
            if re.fullmatch(r"\d+|x|X", t):
                toks.append(t)
            elif toks:
                break
        return int(toks[-3])  # [...イニング, 計, H, E]
    try:
        sc_away, sc_home = final_score(away_full), final_score(home_full)
    except Exception:
        sc_away = sc_home = 0
    return {"date": date, "venue": venue, "gametime": gametime,
            "away": away, "home": home, "sc_away": sc_away, "sc_home": sc_home}


def collect_vals(mmdd, gid, away, home):
    """phase1 v3出力→カード用の采配リスト(decisionのみ・裁定準拠)"""
    ph = json.load(open(os.path.join(BASE, "data", "out", mmdd, f"{gid}_ph.json"), encoding="utf-8"))
    vals = []
    for r in ph:
        if "error" in r or r.get("decision") is None:
            continue
        k = r.get("kind", "ph")
        team, v = r.get("team"), r["decision"]
        if k in ("bunt", "squeeze"):
            pb = "投手" if r.get("batter_is_pitcher") else ""
            desc = f"{r['batter']}{pb and '(投手)'}の{'スクイズ' if k == 'squeeze' else '送りバント'}"
        elif k == "ph":
            desc = f"代打・{r['ph']}(元:{r['orig']}{'=投手' if r.get('orig_is_pitcher') else ''})"
        elif k == "ibb":
            team, desc = r["def_team"], f"{r['batter']}への申告敬遠"
        elif k == "relief":
            team, v = r["def_team"], r.get("decision_net", r["decision"])
            desc = f"継投 {r['old']}→{r['new']}"
        elif k == "pr":
            desc = f"代走 {r['orig']}→{r['sub']}"
        elif k == "swing":
            if not r.get("counted"):
                continue  # ③裁定: 強打者に打たせた等は「采配」でない(誤帰属防止・表示もしない 9/3社長指摘)
            desc = f"{r['batter']}に強攻(バント回避)"
        else:
            continue
        note = f" [{r['judge']}]" if str(r.get("judge", "RE")).startswith("P") else ""
        ref = bool(k == "swing" and not r.get("counted"))
        # 期待値の推移(対抗手→選んだ手)。9/3社長指示でl2に表示
        FT = {"bunt": ("ev_swing", "ev_bunt"), "squeeze": ("ev_swing", "ev_bunt"),
              "swing": ("ev_bunt", "ev_swing"), "ph": ("ev_orig", "ev_ph"),
              "ibb": ("ev_pitch", "ev_walk"), "relief": ("ev_stay", "ev_new")}
        ef = et = None
        if k in FT:
            ef, et = r.get(FT[k][0]), r.get(FT[k][1])
        vals.append({"team": team, "inning": r["inning"], "cat": CATLABEL.get(k, k) + ("(参考)" if ref else ""),
                     "desc": desc, "v": round(v, 2), "note": note, "ref": ref,
                     "ev_from": ef, "ev_to": et, "def_side": k in ("relief", "ibb"),
                     "state": r.get("state", "") or "", "outs": r.get("outs", 0)})
    return vals


# 白基調モード(9/3社長「見比べたい」): ダーク配色→ライト配色の置換マップ
LIGHT_MAP = [
    ("--txt:#f2f6ff", "--txt:#16213c"), ("--mut:#7e8db0", "--mut:#5d6a86"),
    ("--mut2:#aab8da", "--mut2:#4d5a78"),
    ("background:#060a18", "background:#eef1f7"),
    ("#0c1734", "#ffffff"), ("#081024", "#f7f9fd"), ("#070c1c", "#f0f3f9"),
    ("rgba(16,26,54,.80)", "rgba(255,255,255,.92)"), ("rgba(16,26,54,.82)", "rgba(255,255,255,.92)"),
    ("rgba(16,26,54,.84)", "rgba(255,255,255,.92)"),
    ("rgba(9,15,32,.84)", "rgba(244,247,252,.95)"), ("rgba(10,17,36,.86)", "rgba(244,247,252,.95)"),
    ("rgba(9,15,34,.88)", "rgba(244,247,252,.95)"), ("rgba(9,15,34,.84)", "rgba(244,247,252,.95)"),
    ("rgba(10,17,36,.95)", "rgba(247,249,253,.96)"), ("rgba(12,20,44,.94)", "rgba(255,255,255,.94)"),
    ("#101b33", "#ffffff"), ("#182746", "#dde4f0"), ("#41598f", "#9fadcc"),
    ("#5d70a0", "#5d6a86"), ("#1d2c4e", "#d5dcea"), ("#7e8db0", "#5d6a86"),
    ("#31e981", "#0d9e55"), ("rgba(49,233,129", "rgba(13,158,85"), ("#7df5b0", "#0a7f45"),
    ("#ff5d54", "#dd3d35"), ("rgba(255,93,84", "rgba(221,61,53"), ("#ff9d97", "#b8302a"),
    ("#1a2743", "#e6ebf4"), ("#233250", "#e6ebf4"), ("#33456e", "#b9c4d8"),
    ("rgba(150,195,255,.10)", "rgba(47,111,224,.06)"),
    ("rgba(190,220,255,.13)", "rgba(47,111,224,.05)"),
    ("rgba(255,225,140,.10)", "rgba(245,197,24,.07)"),
    # 白文字系(スコア数字・チーム名・リング中央・ラベル・透かし)を濃紺へ
    ("color:#fff; text-shadow:0 0 24px rgba(255,255,255,.4);", "color:#16213c;"),
    ("font-size:21px; font-weight:900; color:#fff;", "font-size:21px; font-weight:900; color:#16213c;"),
    ("font-size:60px; font-weight:900; line-height:1; color:#fff;",
     "font-size:60px; font-weight:900; line-height:1; color:#16213c;"),
    ("#cfe2ff", "#46557a"),
    ("rgba(255,255,255,.04)", "rgba(22,33,60,.05)"),
    # 中央リング: 濃紺の円盤→ごく薄い青地、黒影→淡影
    ("rgba(20,38,80,.35)", "rgba(47,111,224,.08)"),
    ("rgba(120,160,255,.14)", "rgba(47,111,224,.20)"),
    ("0 2px 6px rgba(0,0,0,.6)", "0 1px 3px rgba(0,0,0,.15)"),
    # 見出し・チップの白飛び対策(白基調本採用時の仕上げ)
    ("#dbe7ff", "#2c3a5c"),
    ("#8b96ab", "#66718c"),
    ("--cyan:#4fd8ff", "--cyan:#1673c9"),
    ("rgba(79,216,255,.5)", "rgba(22,115,201,.2)"),
]


def build(mmdd, gid, render_png=False, light=False):
    meta = parse_meta(mmdd, gid)
    AWAY = {**TEAMS[meta["away"]], "short": meta["away"]}
    HOME = {**TEAMS[meta["home"]], "short": meta["home"]}
    WINNER = "away" if meta["sc_away"] > meta["sc_home"] else "home"
    try:
        mgr = json.load(open(os.path.join(BASE, "data", "logs", "managers.json"), encoding="utf-8"))
    except Exception:
        mgr = {}
    try:
        mgr_ov = json.load(open(os.path.join(BASE, "data", "logs", "managers_override.json"), encoding="utf-8"))
    except Exception:
        mgr_ov = {}

    def mgr_label(short):
        """表示用監督名。途中交代はoverride優先(例: 橋上監督代行・ロスター欄は更新が遅い)"""
        code = CODE.get(short, "")
        if code in mgr_ov:
            return mgr_ov[code]
        nm = mgr.get(code, "")
        base = nm.split("　")[0].split()[0] if nm else short
        return f"{base}監督"

    vals = collect_vals(mmdd, gid, AWAY["short"], HOME["short"])
    tpl = open(os.path.join(BASE, "src", "card_template.html"), encoding="utf-8").read()

    def teamvals(short):
        return [x for x in vals if x["team"] == short and not x.get("ref")]

    def teamrefs(short):
        return [x for x in vals if x["team"] == short and x.get("ref")]

    def net(short):
        return round(sum(x["v"] for x in teamvals(short)), 2)

    win = AWAY if WINNER == "away" else HOME
    lose = HOME if WINNER == "away" else AWAY
    w_plus = round(sum(x["v"] for x in teamvals(win["short"]) if x["v"] > 0), 2)
    l_minus = round(sum(x["v"] for x in teamvals(lose["short"]) if x["v"] < 0), 2)
    center = round(net(win["short"]) - net(lose["short"]), 2)

    def fmt(v, pt=True):
        return f"{v:+.2f}" + ("点" if pt else "")

    def situ_svg(state, outs):
        """TV風の場面表示: 塁ダイヤ(占有=黄)+アウトランプ(9/3社長指示)"""
        def dia(cx, cy, b):
            filled = b in state
            fill = "#f5c518" if filled else "#1a2743"
            glow = ' style="filter:drop-shadow(0 0 4px rgba(245,197,24,.8))"' if filled else ""
            return (f'<rect x="{cx-5.5}" y="{cy-5.5}" width="11" height="11" rx="1.5" '
                    f'transform="rotate(45 {cx} {cy})" fill="{fill}" '
                    f'stroke="{"#f5c518" if filled else "#33456e"}" stroke-width="1.2"{glow}/>')
        lamps = "".join(
            f'<circle cx="{17 + i * 12}" cy="34" r="3.4" '
            f'fill="{"#ff5d54" if i < outs else "#1a2743"}" '
            f'stroke="{"#ff5d54" if i < outs else "#33456e"}" stroke-width="1.1"/>'
            for i in range(2))
        return (f'<svg width="46" height="40" viewBox="0 0 46 40" '
                f'style="flex:none;opacity:.95">{dia(23, 8, "2")}{dia(34, 19, "1")}'
                f'{dia(12, 19, "3")}{lamps}</svg>')

    def top3_html(short):
        evs = sorted(teamvals(short), key=lambda x: -abs(x["v"]))[:3]
        crowns = ["1", "2", "3"]  # 王冠廃止: 「良い順」でなく「影響の大きい順」なので(9/3社長指示)
        rk = ["rk1", "rk2", "rk3"]
        outl = []
        maxv = max((abs(x["v"]) for x in evs), default=1) or 1
        for i, e in enumerate(evs):
            cls = "g" if e["v"] > 0 else "r"
            first = (" first-g" if e["v"] > 0 else " first-r") if i == 0 else ""
            w = int(abs(e["v"]) / maxv * 100)
            ev_txt = ""
            if e.get("ev_from") is not None and e.get("ev_to") is not None:
                # 攻守で推移の向きが逆に見える混乱を主語で解消(9/3社長指摘)
                word = "失点期待" if e.get("def_side") else "得点期待"
                ev_txt = f' ・ {word} {e["ev_from"]:.2f} → {e["ev_to"]:.2f}点'
            outl.append(
                f'<div class="item{first}">'
                f'<div class="rankb {rk[i]}">{crowns[i]}</div>'
                f'<div class="itx"><div class="l1">{e["inning"]}回 {e["desc"][:26]}</div>'
                f'<div class="l2">{e["cat"]}{ev_txt}</div></div>'
                f'{situ_svg(e["state"], e["outs"])}'
                f'<div style="text-align:center;flex:none">'
                f'<div class="ival {cls}">{fmt(e["v"], False)}</div>'
                f'<div style="font-size:11.5px;font-weight:900;letter-spacing:2px;opacity:.8" class="ival {cls}">'
                f'{("失点減" if e["v"] >= 0 else "失点増") if e.get("def_side") else ("得点増" if e["v"] >= 0 else "得点減")}</div></div>'
                f'<div class="mag {cls}" style="width:{w}%"></div></div>')
        if len(evs) < 3:  # 少ない試合は正直に表示(穴埋めしない・9/3社長指摘)
            outl.append(
                '<div class="item"><div class="itx">'
                f'<div class="l1" style="color:#5d70a0">評価対象の采配は{len(evs)}件'
                '(動きの少ない試合)</div></div></div>')
        return "\n".join(outl)

    def cum(short, mx):
        c, o = 0.0, [0.0]
        for i in range(1, mx + 1):
            c += sum(x["v"] for x in teamvals(short) if x["inning"] == i)
            o.append(round(c, 2))
        return o

    vals_main = [x for x in vals if not x.get("ref")]
    max_inn = max((x["inning"] for x in vals_main), default=9)
    ac, hc = cum(AWAY["short"], max_inn), cum(HOME["short"], max_inn)
    lim = max(0.5, max(abs(v) for v in ac + hc))
    X0, X1, BASEY = 44, 856, 118
    SCALE = 88 / lim

    def pts(c):
        n = len(c)
        return [(X0 + (X1 - X0) * i / (n - 1), BASEY - v * SCALE) for i, v in enumerate(c)]

    def smoothd(p):
        """単調性を保つ緩やかな曲線(Catmull-Rom→ベジェ・制御点を区間内にクランプ)"""
        if len(p) < 3:
            return f"M{p[0][0]:.1f},{p[0][1]:.1f} L{p[-1][0]:.1f},{p[-1][1]:.1f} "
        d = f"M{p[0][0]:.1f},{p[0][1]:.1f} "
        for i in range(len(p) - 1):
            p0, p1, p2, p3 = p[max(0, i - 1)], p[i], p[i + 1], p[min(len(p) - 1, i + 2)]
            lo, hi = min(p1[1], p2[1]), max(p1[1], p2[1])
            c1 = (p1[0] + (p2[0] - p0[0]) / 6, min(hi, max(lo, p1[1] + (p2[1] - p0[1]) / 6)))
            c2 = (p2[0] - (p3[0] - p1[0]) / 6, min(hi, max(lo, p2[1] - (p3[1] - p1[1]) / 6)))
            d += f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} "
        return d

    pa, phh = pts(ac), pts(hc)
    da, dh = smoothd(pa), smoothd(phh)
    area_a = da + f"L{X1},{BASEY} L{X0},{BASEY} Z"
    area_h = dh + f"L{X1},{BASEY} L{X0},{BASEY} Z"
    top_all = sorted(vals_main, key=lambda x: -abs(x["v"]))[:3]
    # 注釈: |0.10|以上を最大4件(なければ最大の1件)。起きた回の位置に置き、該当点へ引き出し線
    notable = sorted([e for e in vals_main if abs(e["v"]) >= 0.10], key=lambda x: -abs(x["v"]))[:4]
    if not notable and top_all:
        notable = top_all[:1]
    notable.sort(key=lambda e: e["inning"])
    callouts = []
    used = []  # (x, row) 衝突回避
    BW, BH = 172, 40
    for e in notable:
        team_pts = pa if e["team"] == AWAY["short"] else phh
        px, py = team_pts[min(e["inning"], len(team_pts) - 1)]
        top_side = py >= BASEY  # 線が下(マイナス側)なら箱は上に
        rows = ([8, 52] if top_side else [156, 200])
        bx = max(X0, min(X1 - BW - 4, px - BW / 2))
        row_y = rows[0]
        for ux, uy in used:
            if abs(bx - ux) < BW + 10 and row_y == uy:
                row_y = rows[1]
        used.append((bx, row_y))
        col = "49,233,129" if e["v"] > 0 else "255,93,84"
        tcol = "#7df5b0" if e["v"] > 0 else "#ff9d97"
        ly0 = row_y + BH if top_side else row_y  # 引き出し線の起点(箱の下端/上端)
        callouts.append(
            f'<line x1="{px:.0f}" y1="{py:.0f}" x2="{bx + BW/2:.0f}" y2="{ly0}" stroke="rgba({col},.55)" stroke-width="1.3"/>'
            f'<circle cx="{px:.0f}" cy="{py:.0f}" r="4.5" fill="none" stroke="rgba({col},.9)" stroke-width="1.6"/>'
            f'<rect x="{bx:.0f}" y="{row_y}" rx="6" width="{BW}" height="{BH}" fill="#101b33" stroke="rgba({col},.65)" stroke-width="1.2"/>'
            f'<text x="{bx+10:.0f}" y="{row_y+16}" fill="#7e8db0" font-size="11.5" font-weight="bold">{e["inning"]}回 {e["cat"]}</text>'
            f'<text x="{bx+10:.0f}" y="{row_y+32}" fill="{tcol}" font-size="13" font-weight="900">{e["desc"][:13]} {fmt(e["v"], False)}</text>')
    g1 = round(lim, 1)
    xlabels = "".join(f'<text x="{X0 + (X1-X0)*i/max_inn:.0f}" y="252">{i}回</text>' for i in range(1, max_inn + 1))
    chart = f'''<svg width="976" height="265" viewBox="0 0 976 265">
  <defs>
    <linearGradient id="ga" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%" stop-color="{AWAY['color']}" stop-opacity=".30"/><stop offset="100%" stop-color="{AWAY['color']}" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="gh" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{HOME['color']}" stop-opacity=".30"/><stop offset="100%" stop-color="{HOME['color']}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <g stroke="#182746" stroke-width="1">
    <line x1="{X0}" y1="30" x2="{X1}" y2="30"/><line x1="{X0}" y1="74" x2="{X1}" y2="74"/>
    <line x1="{X0}" y1="162" x2="{X1}" y2="162"/><line x1="{X0}" y1="206" x2="{X1}" y2="206"/>
  </g>
  <line x1="{X0}" y1="{BASEY}" x2="{X1}" y2="{BASEY}" stroke="#41598f" stroke-width="1.8" stroke-dasharray="2 4"/>
  <g fill="#5d70a0" font-size="12.5" font-weight="bold">
    <text x="8" y="35">+{g1}</text><text x="14" y="122">0.0</text><text x="8" y="211">-{g1}</text>
  </g>
  <path fill="url(#ga)" d="{area_a}"/><path fill="url(#gh)" d="{area_h}"/>
  <path fill="none" stroke="{HOME['color']}" stroke-width="3.4" stroke-linejoin="round"
        style="filter:drop-shadow(0 0 6px rgba({HOME['glow']},.85))" d="{dh}"/>
  <path fill="none" stroke="{AWAY['color']}" stroke-width="3.4" stroke-linejoin="round"
        style="filter:drop-shadow(0 0 6px rgba({AWAY['glow']},.9))" d="{da}"/>
  <circle cx="{pa[-1][0]:.0f}" cy="{pa[-1][1]:.0f}" r="6" fill="{AWAY['color']}" style="filter:drop-shadow(0 0 8px rgba({AWAY['glow']},1))"/>
  <circle cx="{phh[-1][0]:.0f}" cy="{phh[-1][1]:.0f}" r="6" fill="{HOME['color']}" style="filter:drop-shadow(0 0 8px rgba({HOME['glow']},1))"/>
  <g>{''.join(callouts)}</g>
  <g>
    <line x1="868" y1="14" x2="868" y2="210" stroke="#1d2c4e" stroke-width="1.5"/>
    <text x="880" y="30" fill="#7e8db0" font-size="13" font-weight="bold" letter-spacing="2">最終インパクト</text>
    <text x="878" y="72" fill="#31e981" font-size="36" font-weight="900"
          style="filter:drop-shadow(0 0 14px rgba(49,233,129,.8))">{fmt(center)}</text>
    <line x1="878" y1="92" x2="962" y2="92" stroke="#1d2c4e" stroke-width="1.2"/>
    <text x="880" y="116" fill="{AWAY['color']}" font-size="16" font-weight="900">{AWAY['short']}</text>
    <text x="880" y="138" fill="{'#31e981' if net(AWAY['short'])>=0 else '#ff5d54'}" font-size="21" font-weight="900">{fmt(net(AWAY['short']))}</text>
    <text x="880" y="168" fill="{HOME['color']}" font-size="16" font-weight="900">{HOME['short']}</text>
    <text x="880" y="190" fill="{'#31e981' if net(HOME['short'])>=0 else '#ff5d54'}" font-size="21" font-weight="900">{fmt(net(HOME['short']))}</text>
  </g>
  <g font-size="13" fill="#5d70a0" text-anchor="middle" font-weight="bold">{xlabels}</g>
</svg>'''

    C = 2 * math.pi * 94
    fplus = abs(w_plus) / max(abs(w_plus) + abs(l_minus), 0.01)
    blue_len = max(4, C * fplus - 8)
    red_len = max(4, C * (1 - fplus) - 8)
    red_rot = -90 + 360 * fplus + 3

    # 上下矢印スウッシュSVGをテンプレから捕獲(符号に応じて左右へ配置し直す)
    i1 = tpl.index('<svg class="swoosh"')
    e1 = tpl.index('</svg>', i1) + 6
    i2 = tpl.index('<svg class="swoosh"', e1)
    e2 = tpl.index('</svg>', i2) + 6
    SW_UP, SW_DOWN = tpl[i1:e1], tpl[i2:e2]

    s = tpl
    # チーム名はトークン2段置換(対戦カードがサンプルのヤクルト/阪神と被ると連鎖置換で壊れるため)
    s = s.replace("東京ヤクルト<br>スワローズ", "@@AN@@").replace("阪神<br>タイガース", "@@HN@@")
    s = s.replace('class="medal m-yk">YS<', f'class="medal m-yk">{AWAY["mono"]}<')
    s = s.replace('class="medal m-hs">HT<', f'class="medal m-hs">{HOME["mono"]}<')
    s = s.replace('<div class="snum">1</div>', f'<div class="snum">{meta["sc_away"]}</div>', 1)
    s = s.replace('<div class="snum">9</div>', f'<div class="snum">{meta["sc_home"]}</div>', 1)
    s = s.replace('<span class="losechip">LOSE</span>', "@@AC@@").replace('<span class="winchip">WIN</span>', "@@HC@@")
    if meta["sc_away"] == meta["sc_home"]:  # 引き分け
        s = s.replace("@@AC@@", '<span class="losechip">DRAW</span>')
        s = s.replace("@@HC@@", '<span class="losechip">DRAW</span>')
    else:
        s = s.replace("@@AC@@", '<span class="winchip">WIN</span>' if WINNER == "away" else '<span class="losechip">LOSE</span>')
        s = s.replace("@@HC@@", '<span class="losechip">LOSE</span>' if WINNER == "away" else '<span class="winchip">WIN</span>')
    s = s.replace("2026年9月2日(火)<br>◉ 神宮球場", f"{meta['date']}<br>◉ {meta['venue']}")
    s = s.replace("2026.9.2(火)&nbsp;&nbsp;神宮球場", f"{meta['date']}&nbsp;&nbsp;{meta['venue']}")
    # チームカラー連動(9/3社長指示): ヘッダー帯の左右・上部バー・ロゴメダルを対戦カードの色に
    s = s.replace("rgba(42,79,158,.55)", f"rgba({AWAY['glow']},.30)")
    s = s.replace("rgba(158,128,12,.45)", f"rgba({HOME['glow']},.30)")
    s = s.replace("linear-gradient(90deg,#2f6fe0,#4fd8ff 35%,#f5c518 70%,#e0a90f)",
                  f"linear-gradient(90deg,{AWAY['color']},{AWAY['color']} 38%,{HOME['color']} 62%,{HOME['color']})")
    s = s.replace("</style>",
                  f".medal.m-yk {{ background:radial-gradient(circle at 30% 28%, #262e47, #121728) !important;"
                  f" border-color:{AWAY['color']} !important; color:{AWAY['color']} !important; }}\n"
                  f".medal.m-hs {{ background:radial-gradient(circle at 30% 28%, #262e47, #121728) !important;"
                  f" border-color:{HOME['color']} !important; color:{HOME['color']} !important; }}\n</style>")
    s = s.replace('style="background:#4e8df5"', f'style="background:{AWAY["color"]}"')
    s = s.replace('style="background:#f5c518"', f'style="background:{HOME["color"]}"')
    # 収支ボックスはヘッダーと同じ並び(左=先攻・右=後攻)、符号でプラス/マイナス表示と矢印を切替
    # (9/3社長指摘: 勝者左固定だと上のスコアと逆になる)
    def metric(team_d, net_v):
        word = "プラス効果" if net_v >= 0 else "マイナス効果"
        cls = "pos" if net_v >= 0 else "neg"
        sw = SW_UP if net_v >= 0 else SW_DOWN
        return (f'<div class="lb c-yk">{team_d["short"]}の{word}</div>',
                f'<div class="numw {cls}">{fmt(net_v, False)}<span class="pt">点</span></div>', sw)
    la, na, swa = metric(AWAY, net(AWAY["short"]))
    lh, nh, swh = metric(HOME, net(HOME["short"]))
    s = s.replace('<div class="lb c-hs">阪神のプラス効果</div>', la)
    s = s.replace('<div class="numw pos">+2.8<span class="pt">点</span></div>', na)
    s = s.replace(SW_UP, "@@SWA@@", 1)
    s = s.replace('<div class="lb c-yk">ヤクルトのマイナス効果</div>', lh)
    s = s.replace('<div class="numw neg">-1.1<span class="pt">点</span></div>', nh)
    s = s.replace(SW_DOWN, "@@SWH@@", 1)
    s = s.replace("@@SWA@@", swa).replace("@@SWH@@", swh)
    s = s.replace('<div class="cnum">+1.7<span class="pt">点</span></div>',
                  f'<div class="cnum">{fmt(center, False)}<span class="pt">点</span></div>')
    # 勝者の采配が下回る試合ではラベルを反転(固定「WINに貢献」だと嘘になる)
    s = s.replace('<div class="cwin">WIN に貢献</div>',
                  '<div class="cwin">WIN側の采配が上</div>' if center >= 0
                  else '<div class="cwin" style="color:#dd3d35">LOSE側の采配が上</div>')
    s = s.replace('stroke-dasharray="412 178.6" transform="rotate(-90 109 109)"',
                  f'stroke-dasharray="{blue_len:.0f} {C - blue_len:.0f}" transform="rotate(-90 109 109)"')
    s = s.replace('stroke-dasharray="152 438.6" transform="rotate(172 109 109)"',
                  f'stroke-dasharray="{red_len:.0f} {C - red_len:.0f}" transform="rotate({red_rot:.0f} 109 109)"')
    s = re.sub(r'<div class="chd"><div class="cdot2"[^>]*></div>ヤクルトの采配 TOP 3</div>.*?(?=</div>\s*<div class="col">)',
               f'<div class="chd"><div class="cdot2" style="background:{AWAY["color"]}"></div>{AWAY["short"]}の注目采配'
               f'<span style="font-size:12.5px;font-weight:700;opacity:.6;margin-left:7px">影響の大きい順</span></div>\n'
               + top3_html(AWAY["short"]) + "\n",
               s, flags=re.S)
    h2 = s.index("阪神の采配 TOP 3")
    col2_start = s.rindex('<div class="chd">', 0, h2)
    sec_pos = s.index('<div class="chart">', h2)
    s = (s[:col2_start]
         + f'<div class="chd"><div class="cdot2" style="background:{HOME["color"]}"></div>{HOME["short"]}の注目采配'
         + '<span style="font-size:12.5px;font-weight:700;opacity:.6;margin-left:7px">影響の大きい順</span></div>\n'
         + top3_html(HOME["short"]) + '\n    </div>\n  </div>\n\n  ' + s[sec_pos:])
    s = s.replace(">ヤクルト</div>", ">@@ALG@@</div>").replace(">阪神</div>", ">@@HLG@@</div>")
    s = s.replace("@@ALG@@", AWAY["short"]).replace("@@HLG@@", HOME["short"])
    s = s.replace("@@AN@@", AWAY["name"]).replace("@@HN@@", HOME["name"])
    s = s.replace("最終インパクト +1.7点", f"最終インパクト {fmt(center)}")
    c0 = s.index('<svg width="976"')
    c1 = s.index("</svg>", c0) + 6
    s = s[:c0] + chart + s[c1:]
    counts = {}
    for x in vals_main:
        counts[x["cat"]] = counts.get(x["cat"], 0) + 1
    cstr = "・".join(f"{k}{v}" for k, v in counts.items())
    s = s.replace("<b>18:00 / 3:28</b>", f"<b>{meta['gametime']}</b>")
    s = s.replace("<b>10件</b>", f"<b>{len(vals_main)}件</b>")
    s = s.replace("<b>バント3・継投4・代打3</b>", f"<b>{cstr}</b>")
    if top_all:
        s = re.sub(r'<div class="row"><span>最大インパクト</span><b>[^<]*</b></div>',
                   f'<div class="row"><span>最大インパクト</span><b>{top_all[0]["inning"]}回 {top_all[0]["cat"]} {fmt(top_all[0]["v"])}</b></div>', s)
    s = re.sub(r"塁・アウト状況の得点期待値\(RE24\)で「指示の瞬間」を採点。結果論ではなく、\s*選手の実行\(成否\)と分離した監督の判断そのものの評価です。",
               "指示の瞬間の期待値差で採点(結果は使わない)。当季実測RE表×直近重み(バックテスト較正済み)×相手投手×左右×走者の走力。7回以降の接戦は得点確率でも判定。", s)
    s = s.replace('>SAMPLE<', '><')
    s = s.replace('<h1>采配の<span class="em">勝敗インパクト</span>分析</h1>', '')  # 9/3社長指示: タイトル文字削除
    s = s.replace("@saihaiscore_lab|計算方法はnoteで全公開|データ: NPB公式記録より自動集計",
                  "@saihaiscore_lab(β試験運用)|計算方法はnoteで全公開|データ: NPB公式記録より自動集計")

    if light:
        for a, b in LIGHT_MAP:
            s = s.replace(a, b)
    sfx = "" if light else "_dark"  # 白基調が本番(9/3社長裁定)
    outp = os.path.join(BASE, "data", "out", mmdd, f"card_{gid}{sfx}.html")
    open(outp, "w", encoding="utf-8").write(s)
    print(f"{gid}: {AWAY['short']}{meta['sc_away']}-{meta['sc_home']}{HOME['short']} {meta['venue']} "
          f"采配{len(vals)}件 {win['short']}+{w_plus} {lose['short']}{l_minus} → {outp}")

    # 投稿文の自動生成(9/3社長確定フォーマット: 日付スコア/ベストと悪手の1文/ハッシュタグ)
    def play_str(e):
        d = re.sub(r"（[^）]*）|\([^)]*\)", "", e["desc"]).replace("・", "").strip()
        return f"{e['inning']}回の{e['team']}・{d}"
    m2 = re.search(r"(\d+)月(\d+)日", meta["date"])
    dstr = f"{m2.group(1)}月{m2.group(2)}日" if m2 else meta["date"]
    line1 = f"{dstr} {AWAY['short']} {meta['sc_away']}-{meta['sc_home']} {HOME['short']}"
    best = max(vals_main, key=lambda x: x["v"], default=None)
    worst = min(vals_main, key=lambda x: x["v"], default=None)
    if best and best["v"] >= 0.05:
        line2 = f"采配では{play_str(best)}が一番のプラス({fmt(best['v'], False)})"
        if worst and worst["v"] <= -0.05:
            line2 += f"で、逆に{play_str(worst)}({fmt(worst['v'], False)})が悪手だった。"
        else:
            line2 += "で、逆に目立った悪手のない試合だった。"
    elif worst and worst["v"] <= -0.05:
        line2 = f"采配では目立ったプラスがなく、{play_str(worst)}({fmt(worst['v'], False)})が悪手だった。"
    else:
        line2 = "采配では大きな動きのない試合だった。"
    line3 = f"#NPB #{HASHTAG.get(AWAY['short'], AWAY['short'])} #{HASHTAG.get(HOME['short'], HOME['short'])}"
    post = f"{line1}\n{line2}\n{line3}"
    with open(os.path.join(BASE, "data", "out", mmdd, f"card_{gid}.txt"), "w", encoding="utf-8") as f:
        f.write(post)
    print("--- 投稿文 ---")
    print(post)
    if render_png:
        png = os.path.join(BASE, "data", "out", mmdd, f"card_{gid}{sfx}.png")
        render(outp, png, "1080,1250")
        print("png:", png)
    return outp


def browser_bin():
    """ヘッドレスブラウザ: ローカル=Edge / GitHub Actions等=BROWSER_BINかchrome系を自動検出"""
    cands = [os.environ.get("BROWSER_BIN"),
             r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             "/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise RuntimeError("ヘッドレスブラウザ無し(環境変数BROWSER_BINで指定)")


def render(html_path, png_path, size, scale=3):
    args = [browser_bin(), "--headless=new", f"--screenshot={png_path}",
            f"--window-size={size}", f"--force-device-scale-factor={scale}",
            "--hide-scrollbars", "file:///" + html_path.replace(os.sep, "/")]
    if os.name != "nt":
        args[1:1] = ["--no-sandbox", "--disable-gpu"]  # CIランナー用
    subprocess.run(args, capture_output=True, timeout=90)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], "--png" in sys.argv, "--dark" not in sys.argv)
