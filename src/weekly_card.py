# -*- coding: utf-8 -*-
"""週間監督通信簿カード(月曜・試合なし日用)モックv2・豪華版(2026-09-08)
- 采配王メダル・好手/悪手リング・順位メダル・塁状況ダイヤ・グロー等、試合カードと同級の作り込み
Usage: python src/weekly_card.py 0901 0906 [--png]
"""
import glob
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_card2 import render, TEAMS  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CENTRAL = ("巨人", "DeNA", "阪神", "広島", "中日", "ヤクルト")
PACIFIC = ("ソフトバンク", "日本ハム", "ロッテ", "西武", "オリックス", "楽天")


def collect(d0, d1):
    agg = {}
    best = worst = None
    n_pos = n_neg = n_all = 0
    for f in glob.glob(os.path.join(BASE, "data", "out", "*", "*_ph.json")):
        mmdd = os.path.basename(os.path.dirname(f))
        if not (d0 <= mmdd <= d1):
            continue
        try:
            recs = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        gid = os.path.basename(f).replace("_ph.json", "")
        for r in recs:
            if "error" in r:
                continue
            k = r.get("kind")
            tm = r.get("def_team") if k in ("relief", "ibb") else r.get("team")
            if not tm:
                continue
            a = agg.setdefault(tm, {"atk": 0.0, "miss": 0.0, "games": set()})
            a["games"].add(f"{mmdd}/{gid}")
            if r.get("decision") is not None:
                if k == "swing" and not r.get("counted"):
                    continue
                w = r.get("decision_wp_net", r.get("decision_wp"))
                if w is None:
                    continue
                a["atk"] += w * 100
                n_all += 1
                if w >= 0:
                    n_pos += 1
                else:
                    n_neg += 1
                lab = f"{int(mmdd[:2])}/{int(mmdd[2:])} {r['inning']}回 {tm}"
                if best is None or w * 100 > best[0]:
                    best = (w * 100, lab, r)
                if worst is None or w * 100 < worst[0]:
                    worst = (w * 100, lab, r)
            elif r.get("decision_head_wp") is not None:
                a["miss"] += r["decision_head_wp"] * 100
            elif r.get("engine_loss_wp"):
                a["miss"] -= r["engine_loss_wp"] * 100
    return agg, best, worst, (n_pos, n_neg, n_all)


def desc_of(r):
    k = r.get("kind")
    if k in ("bunt", "squeeze"):
        return f"{r.get('batter','')}の{'スクイズ' if k=='squeeze' else '送りバント'}"
    if k == "swing":
        return f"{r.get('batter','')}に強攻"
    if k == "ph":
        return f"代打・{r.get('ph','')}(元:{r.get('orig','')})"
    if k == "pr":
        return f"代走 {r.get('orig','')}→{r.get('sub','')}"
    if k == "ibb":
        return f"{r.get('batter','')}への申告敬遠"
    if k == "relief":
        return f"継投 {r.get('old','')}→{r.get('new','')}"
    return ""


def situ_svg(state, outs, scale=1.15):
    state = state or ""
    def dia(cx, cy, b):
        filled = b in state
        fill = "#f5c518" if filled else "#dde4f0"
        glow = ' style="filter:drop-shadow(0 0 5px rgba(245,197,24,.85))"' if filled else ""
        return (f'<rect x="{cx-6}" y="{cy-6}" width="12" height="12" rx="1.8" '
                f'transform="rotate(45 {cx} {cy})" fill="{fill}" '
                f'stroke="{"#e0a90f" if filled else "#b9c4d8"}" stroke-width="1.3"{glow}/>')
    lamps = "".join(
        f'<circle cx="{18 + i * 13}" cy="37" r="3.8" '
        f'fill="{"#dd3d35" if i < outs else "#dde4f0"}" '
        f'stroke="{"#dd3d35" if i < outs else "#b9c4d8"}" stroke-width="1.2"/>'
        for i in range(2))
    w, h = int(52 * scale), int(44 * scale)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 52 44" style="flex:none">'
            f'{dia(26, 9, "2")}{dia(38, 21, "1")}{dia(14, 21, "3")}{lamps}</svg>')


def medal(tm, size=54, fs=19):
    t = TEAMS.get(tm, {})
    col = t.get("color", "#888")
    mono = t.get("mono", tm[:1])
    return (f'<div style="width:{size}px;height:{size}px;border-radius:50%;flex:none;'
            f'background:radial-gradient(circle at 32% 28%, #ffffff, #eef2f9);'
            f'border:2.5px solid {col};color:{col};font-size:{fs}px;font-weight:900;'
            f'display:flex;align-items:center;justify-content:center;'
            f'box-shadow:0 0 14px {col}55, inset 0 0 8px {col}22">{mono}</div>')


def rank_rows(agg, teams):
    rows = []
    for tm in teams:
        a = agg.get(tm)
        if not a or not a["games"]:
            continue
        g = len(a["games"])
        rows.append((tm, (a["atk"] + a["miss"]) / g, a["atk"] / g, a["miss"] / g, g))
    rows.sort(key=lambda x: -x[1])
    return rows


RANK_BG = ("linear-gradient(135deg,#f7d774,#e0a90f)", "linear-gradient(135deg,#e8edf5,#b9c4d8)",
           "linear-gradient(135deg,#e8c39a,#c08552)")


def bar_rows(rows, mx):
    out = []
    for i, (tm, net, atk, miss, g) in enumerate(rows):
        t = TEAMS.get(tm, {})
        col = t.get("color", "#888")
        w = min(100.0, abs(net) / mx * 100)
        cls = "pos" if net >= 0 else "neg"
        side = "left:50%" if net >= 0 else "right:50%"
        rbg = RANK_BG[i] if i < 3 else "#f0f3f9"
        rcol = "#fff" if i < 3 else "#9fadcc"
        first = ' style="background:rgba(47,111,224,.05);border-radius:12px"' if i == 0 else ""
        out.append(f'''
      <div class="rrow"{first}>
        <div class="rk" style="background:{rbg};color:{rcol}">{i + 1}</div>
        {medal(tm, 40, 14)}
        <div class="tmw"><div class="tm" style="color:{col}">{tm}</div>
          <div class="sub">攻め<b class="{ 'sg' if atk>=0 else 'sr'}">{atk:+.1f}</b> 見逃し<b class="sr">{miss:+.1f}</b><span class="gg"> / {g}試合</span></div></div>
        <div class="barwrap"><div class="bar {cls}" style="width:{w / 2:.1f}%;{side}"></div></div>
        <div class="val {cls}">{net:+.1f}<span class="pct">%</span></div>
      </div>''')
    return "".join(out)


def hero_card(title, tm, val, sub, good=True):
    t = TEAMS.get(tm, {})
    col = "#0d9e55" if good else "#dd3d35"
    return f'''
    <div class="hero {'hg' if good else 'hr'}">
      <div class="htitle">{title}</div>
      <div class="hbody">{medal(tm, 62, 22)}
        <div><div class="hteam" style="color:{t.get('color','#333')}">{tm}</div>
        <div class="hval" style="color:{col};text-shadow:0 0 18px {col}66">{val}</div></div></div>
      <div class="hsub">{sub}</div>
    </div>'''


def build(d0, d1, png=False):
    agg, best, worst, (n_pos, n_neg, n_all) = collect(d0, d1)
    ce, pa = rank_rows(agg, CENTRAL), rank_rows(agg, PACIFIC)
    mx = max([abs(r[1]) for r in ce + pa] or [1.0])
    period = f"{int(d0[:2])}/{int(d0[2:])}（火）− {int(d1[:2])}/{int(d1[2:])}（日）"
    king = max(ce + pa, key=lambda r: r[1])
    dunce = min(ce + pa, key=lambda r: r[1])
    C = 2 * math.pi * 74
    fpos = n_pos / max(1, n_pos + n_neg)
    glen = max(4, C * fpos - 6)
    rlen = max(4, C * (1 - fpos) - 6)
    rrot = -90 + 360 * fpos + 2

    def bw_card(x, kind):
        v, lab, r = x
        col = "#0d9e55" if v >= 0 else "#dd3d35"
        pill = ("good", "今週のベスト采配") if kind == "b" else ("bad", "今週のワースト采配")
        return f'''
      <div class="bcard {'g' if kind == 'b' else 'r'}">
        <div class="pill {pill[0]}">{pill[1]}</div>
        <div class="brow">{situ_svg(r.get('state'), r.get('outs', 0))}
          <div><div class="pl0">{lab} {r.get('outs',0)}死{r.get('state') or '走者無'}</div>
          <div class="pl1">{desc_of(r)}</div></div></div>
        <div class="pv" style="color:{col};text-shadow:0 0 16px {col}66">勝率 {v:+.1f}%</div>
        <div class="mag" style="background:linear-gradient(90deg,{col},{col}66);width:{min(100, abs(v) * 12):.0f}%"></div>
      </div>'''

    html = f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1080px; height:1250px; color:#16213c; padding:0; overflow:hidden; position:relative;
         font-family:"Yu Gothic","Hiragino Sans","Noto Sans CJK JP",sans-serif;
         background:
           conic-gradient(from 178deg at 50% -14%, transparent 0 34%, rgba(255,255,255,.13) 37%,
             transparent 40%, rgba(255,255,255,.09) 45%, transparent 48%, rgba(255,255,255,.13) 53%,
             transparent 56%, rgba(255,255,255,.09) 61%, transparent 64%),
           linear-gradient(135deg, #29b7ff 0%, #6d5dff 34%, #ff5fa8 68%, #ffb703 100%); }}
  body::before {{ content:""; position:absolute; inset:0; pointer-events:none; opacity:.5; z-index:0;
    background-image:
      radial-gradient(circle, rgba(255,255,255,.85) 0 2.4px, transparent 3.4px),
      radial-gradient(circle, rgba(255,230,109,.8) 0 2px, transparent 3px);
    background-size: 130px 170px, 150px 190px;
    background-position: 10px 20px, 70px 90px; }}
  .accent {{ height:9px; background:linear-gradient(90deg,#00e5ff,#6d5dff,#ff5fa8,#ffd166,#06d6a0);
            position:relative; z-index:2; }}
  .wrap {{ padding:26px 40px 0; position:relative; z-index:2; }}
  .head {{ display:flex; align-items:center; gap:18px; }}
  .logo {{ width:64px; height:64px; border-radius:16px; color:#fff; font-size:34px; font-weight:900;
          background:linear-gradient(135deg,#ffd34d,#f5a623); color:#131313;
          display:flex; align-items:center; justify-content:center;
          box-shadow:6px 6px 0 rgba(28,35,64,.3); transform:rotate(-2deg); }}
  h1 {{ font-size:38px; font-weight:900; letter-spacing:3px; display:inline-block;
       background:#fff; border-radius:14px; padding:4px 20px; transform:rotate(-1.2deg);
       box-shadow:6px 6px 0 rgba(28,35,64,.3); }}
  h1 span, h1 {{ background-clip:padding-box; }}
  .hsub2 {{ color:#fff; font-size:15px; font-weight:800; margin-top:8px;
           text-shadow:0 2px 10px rgba(28,35,64,.5); }}
  .chip {{ margin-left:auto; text-align:right; }}
  .period {{ background:#fff; border:1.5px solid #dde4f0; border-radius:12px; padding:8px 16px;
            font-size:16.5px; font-weight:900; color:#2c3a5c; box-shadow:0 4px 14px rgba(22,33,60,.06); }}
  .beta {{ display:inline-block; background:#fff; border:1.5px solid #1673c9; color:#1673c9;
          border-radius:99px; font-size:12px; font-weight:900; padding:2px 12px; margin-top:6px; }}
  .heroband {{ display:flex; gap:20px; margin:18px 0 16px; align-items:stretch; }}
  .hero {{ flex:1; background:rgba(255,255,255,.94); border-radius:20px; padding:16px 20px 14px;
          box-shadow:0 10px 28px rgba(22,33,60,.09); }}
  .hero.hg {{ border:1.5px solid rgba(13,158,85,.4); }}
  .hero.hr {{ border:1.5px solid rgba(221,61,53,.4); }}
  .htitle {{ font-size:13.5px; font-weight:900; letter-spacing:2px; color:#66718c; margin-bottom:8px; }}
  .hbody {{ display:flex; align-items:center; gap:14px; }}
  .hteam {{ font-size:21px; font-weight:900; }}
  .hval {{ font-size:34px; font-weight:900; line-height:1.1; }}
  .hsub {{ color:#66718c; font-size:12.5px; font-weight:700; margin-top:8px; }}
  .ringbox {{ width:230px; background:rgba(255,255,255,.94); border-radius:20px; padding:12px;
             box-shadow:0 10px 28px rgba(22,33,60,.09); display:flex; flex-direction:column; align-items:center; }}
  .ringlbl {{ font-size:13px; font-weight:900; letter-spacing:2px; color:#66718c; margin-bottom:2px; }}
  .cols {{ display:flex; gap:20px; }}
  .col {{ flex:1; background:rgba(255,255,255,.94); border-radius:20px; padding:18px 20px 10px;
         box-shadow:0 10px 28px rgba(22,33,60,.09); }}
  .lg {{ font-size:19px; font-weight:900; letter-spacing:3px; margin-bottom:10px;
        display:flex; align-items:center; gap:10px; }}
  .dot {{ width:12px; height:12px; border-radius:4px; background:#1673c9;
         box-shadow:0 0 10px rgba(22,115,201,.6); }}
  .rrow {{ display:flex; align-items:center; gap:10px; padding:8px 6px; border-top:1px solid #e6ebf4; }}
  .rk {{ width:30px; height:30px; border-radius:50%; flex:none; font-size:15px; font-weight:900;
        display:flex; align-items:center; justify-content:center;
        box-shadow:0 3px 8px rgba(22,33,60,.15); }}
  .tmw {{ width:150px; flex:none; }}
  .tm {{ font-size:17.5px; font-weight:900; white-space:nowrap; letter-spacing:-0.5px; }}
  .sub {{ color:#66718c; font-size:11.5px; font-weight:700; margin-top:1px; white-space:nowrap; }}
  .sub b.sg {{ color:#0d9e55; }} .sub b.sr {{ color:#dd3d35; }}
  .gg {{ color:#9fadcc; }}
  .barwrap {{ position:relative; flex:1; height:18px; background:#f0f3f9; border-radius:9px;
             overflow:hidden; border:1px solid #e6ebf4; }}
  .barwrap::after {{ content:""; position:absolute; left:50%; top:0; bottom:0; width:1.5px; background:#b9c4d8; }}
  .bar {{ position:absolute; top:2.5px; bottom:2.5px; border-radius:6px; }}
  .bar.pos {{ background:linear-gradient(90deg,#0d9e55,#35c97e); box-shadow:0 0 12px rgba(13,158,85,.55); }}
  .bar.neg {{ background:linear-gradient(90deg,#f0837d,#dd3d35); box-shadow:0 0 12px rgba(221,61,53,.5); }}
  .val {{ width:88px; flex:none; text-align:right; font-size:21px; font-weight:900; }}
  .val .pct {{ font-size:13px; }}
  .val.pos {{ color:#0d9e55; text-shadow:0 0 12px rgba(13,158,85,.45); }}
  .val.neg {{ color:#dd3d35; text-shadow:0 0 12px rgba(221,61,53,.4); }}
  .band {{ display:flex; gap:20px; margin-top:16px; }}
  .bcard {{ flex:1; background:rgba(255,255,255,.94); border-radius:20px; padding:16px 20px;
           box-shadow:0 10px 28px rgba(22,33,60,.09); position:relative; overflow:hidden; }}
  .bcard.g {{ border:1.5px solid rgba(13,158,85,.4); }}
  .bcard.r {{ border:1.5px solid rgba(221,61,53,.4); }}
  .pill {{ display:inline-block; border-radius:99px; font-size:12.5px; font-weight:900;
          padding:3px 14px; margin-bottom:10px; letter-spacing:1px; }}
  .pill.good {{ background:rgba(13,158,85,.12); color:#0a7f45; }}
  .pill.bad {{ background:rgba(221,61,53,.12); color:#b8302a; }}
  .brow {{ display:flex; gap:12px; align-items:center; }}
  .pl0 {{ color:#66718c; font-size:13px; font-weight:800; }}
  .pl1 {{ font-size:20px; font-weight:900; line-height:1.4; }}
  .pv {{ font-size:29px; font-weight:900; margin-top:8px; }}
  .mag {{ height:6px; border-radius:3px; margin-top:8px; }}
  .note {{ margin-top:14px; background:rgba(255,255,255,.72); border-radius:14px; padding:12px 18px;
          color:#5d6a86; font-size:13px; font-weight:700; line-height:1.7; }}
  .foot {{ margin-top:10px; text-align:center; color:#8b96ab; font-size:12.5px; font-weight:700;
          letter-spacing:1px; }}
</style></head><body>
<div class="accent"></div>
<div class="wrap">
  <div class="head">
    <div class="logo">采</div>
    <div><h1>週間 監督通信簿</h1>
      <div class="hsub2">NPB全試合の監督采配を勝率換算で自動採点 ─ 週間収支ランキング</div></div>
    <div class="chip"><div class="period">{period}</div><br><span class="beta">β 試験運用</span></div>
  </div>
  <div class="heroband">
    {hero_card("👑 今週の采配王", king[0], f"{king[1]:+.1f}%", f"攻め{king[2]:+.1f} / 見逃し{king[3]:+.1f}(勝率換算・週平均)", True)}
    <div class="ringbox">
      <div class="ringlbl">今週の全采配</div>
      <svg width="170" height="170" viewBox="0 0 170 170">
        <circle cx="85" cy="85" r="74" fill="none" stroke="#eef1f7" stroke-width="15"/>
        <circle cx="85" cy="85" r="74" fill="none" stroke="#0d9e55" stroke-width="15"
          stroke-linecap="round" stroke-dasharray="{glen:.0f} {C - glen:.0f}"
          transform="rotate(-90 85 85)" style="filter:drop-shadow(0 0 8px rgba(13,158,85,.6))"/>
        <circle cx="85" cy="85" r="74" fill="none" stroke="#dd3d35" stroke-width="15"
          stroke-linecap="round" stroke-dasharray="{rlen:.0f} {C - rlen:.0f}"
          transform="rotate({rrot:.0f} 85 85)" style="filter:drop-shadow(0 0 8px rgba(221,61,53,.5))"/>
        <text x="85" y="76" text-anchor="middle" font-size="34" font-weight="900" fill="#16213c">{n_all}</text>
        <text x="85" y="99" text-anchor="middle" font-size="13" font-weight="800" fill="#66718c">采配を採点</text>
        <text x="85" y="120" text-anchor="middle" font-size="12" font-weight="900">
          <tspan fill="#0d9e55">好手{fpos:.0%}</tspan><tspan fill="#9fadcc"> / </tspan><tspan fill="#dd3d35">悪手{1 - fpos:.0%}</tspan></text>
      </svg>
    </div>
    {hero_card("⚠ 今週のワースト", dunce[0], f"{dunce[1]:+.1f}%", f"攻め{dunce[2]:+.1f} / 見逃し{dunce[3]:+.1f}(勝率換算・週平均)", False)}
  </div>
  <div class="cols">
    <div class="col"><div class="lg"><span class="dot"></span>セ・リーグ</div>{bar_rows(ce, mx)}</div>
    <div class="col"><div class="lg"><span class="dot" style="background:#f5c518;box-shadow:0 0 10px rgba(245,197,24,.7)"></span>パ・リーグ</div>{bar_rows(pa, mx)}</div>
  </div>
  <div class="band">{bw_card(best, "b")}{bw_card(worst, "w")}</div>
  <div class="note">数値=勝率換算の采配収支(%/試合・週平均)。攻め=実行した采配の合計/見逃し=最善を選ばなかった機会損失。
  指示の瞬間の期待値で採点し結果は使いません。負傷交代・選択肢のない場面は採点対象外。僅差の順位差は誤差の範囲です。</div>
  <div class="foot">@saihaiscore_lab(β試験運用)| 計算方法はnoteで全公開 | データ: NPB公式記録より自動集計</div>
</div>
</body></html>'''
    outdir = os.path.join(BASE, "data", "out", "weekly")
    os.makedirs(outdir, exist_ok=True)
    hp = os.path.join(outdir, f"tsushinbo_{d0}_{d1}.html")
    open(hp, "w", encoding="utf-8").write(html)
    print("html:", hp)
    if png:
        pp = hp.replace(".html", ".png")
        render(hp, pp, "1080,1250")
        print("png:", pp)
        return pp
    return hp


if __name__ == "__main__":
    d0, d1 = sys.argv[1], sys.argv[2]
    build(d0, d1, "--png" in sys.argv)
