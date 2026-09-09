# -*- coding: utf-8 -*-
"""采配ペナントレースカード(design-weekly 2節・9/9フェーズ4モック)
チーム別「采配収支の累計」折れ線(シーズン・週間通信簿と同じ集計の積算)。
注意書き: 過去分は現行モデルでのバックフィル値(モデル改定の度に再計算)と明記
Usage: python src/pennant_card.py [--png]
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_card2 import render, TEAMS  # noqa
from weekly_card import CENTRAL, PACIFIC, medal  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def collect_daily():
    """日付×チームの采配収支(%WP・週間通信簿と同じ定義)"""
    daily = {}
    dates = set()
    for f in glob.glob(os.path.join(BASE, "data", "out", "*", "*_ph.json")):
        mmdd = os.path.basename(os.path.dirname(f))
        if not mmdd.isdigit():
            continue
        try:
            recs = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for r in recs:
            if "error" in r:
                continue
            k = r.get("kind")
            tm = r.get("def_team") if k in ("relief", "ibb", "relief_scan") else r.get("team")
            if not tm:
                continue
            v = 0.0
            if r.get("decision") is not None:
                if k == "swing" and not r.get("counted"):
                    continue
                w = r.get("decision_wp_net", r.get("decision_wp"))
                v = (w or 0.0) * 100
            elif r.get("decision_head_wp") is not None:
                v = r["decision_head_wp"] * 100
            elif r.get("engine_loss_wp"):
                v = -r["engine_loss_wp"] * 100
            else:
                continue
            daily.setdefault(tm, {}).setdefault(mmdd, 0.0)
            daily[tm][mmdd] += v
            dates.add(mmdd)
    return daily, sorted(dates)


def chart(teams, daily, dates, w=470, h=300):
    """1リーグ分のSVG折れ線(累計・リーグ平均比)。
    絶対値だとセ(投手代打=ほぼ常に正の収支)とパ(DH)で系統オフセットが出るため、
    リーグ内の相対収支で表示(週間通信簿のリーグ別ランキングと同じ理屈)"""
    raw = {}
    for tm in teams:
        cum, ys = 0.0, []
        for d in dates:
            cum += daily.get(tm, {}).get(d, 0.0)
            ys.append(cum)
        raw[tm] = ys
    series = {}
    lo = hi = 0.0
    n_d = len(dates)
    means = [sum(raw[tm][i] for tm in teams) / len(teams) for i in range(n_d)]
    for tm in teams:
        ys = [raw[tm][i] - means[i] for i in range(n_d)]
        series[tm] = ys
        lo, hi = min([lo] + ys), max([hi] + ys)
    pad = (hi - lo) * 0.08 + 1e-6
    lo, hi = lo - pad, hi + pad
    n = len(dates)

    def xy(i, v):
        x = 8 + i / max(1, n - 1) * (w - 90)
        y = (h - 24) * (1 - (v - lo) / (hi - lo)) + 8
        return x, y
    y0 = xy(0, 0.0)[1]
    parts = [f'<line x1="8" y1="{y0:.0f}" x2="{w-82}" y2="{y0:.0f}" '
             f'stroke="#b9c4d8" stroke-width="1.2" stroke-dasharray="4 4"/>']
    order = sorted(teams, key=lambda t: -series.get(t, [0])[-1])
    for tm in teams:
        col = TEAMS.get(tm, {}).get("color", "#888")
        pts = " ".join(f"{xy(i, v)[0]:.1f},{xy(i, v)[1]:.1f}"
                       for i, v in enumerate(series[tm]))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" '
                     f'stroke-width="2.6" stroke-linejoin="round" '
                     f'style="filter:drop-shadow(0 0 3px {col}66)"/>')
    labs = []
    for rank, tm in enumerate(order):
        col = TEAMS.get(tm, {}).get("color", "#888")
        v = series[tm][-1]
        ly = min(h - 16, max(12, xy(n - 1, v)[1]))
        labs.append((ly, tm, col, v))
    labs.sort()
    for j in range(1, len(labs)):  # ラベルの重なり回避(最低18px間隔)
        if labs[j][0] - labs[j - 1][0] < 19:
            labs[j] = (labs[j - 1][0] + 19, *labs[j][1:])
    for ly, tm, col, v in labs:
        parts.append(f'<text x="{w-78}" y="{ly:.0f}" font-size="12.5" '
                     f'font-weight="900" fill="{col}">{tm} {v:+.0f}</text>')
    lab_d = [dates[0], dates[len(dates) // 2], dates[-1]]
    for d in lab_d:
        i = dates.index(d)
        parts.append(f'<text x="{xy(i, lo)[0]:.0f}" y="{h-2}" font-size="10" '
                     f'font-weight="800" fill="#8b96ab" text-anchor="middle">'
                     f'{int(d[:2])}/{int(d[2:])}</text>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">{"".join(parts)}</svg>'


def build(png=False):
    daily, dates = collect_daily()
    if not dates:
        print("データ無し")
        return None
    period = f"{int(dates[0][:2])}/{int(dates[0][2:])} − {int(dates[-1][:2])}/{int(dates[-1][2:])}"
    html = f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1080px; height:1250px; color:#16213c; overflow:hidden; position:relative;
         font-family:"Yu Gothic","Hiragino Sans","Noto Sans CJK JP",sans-serif;
         background:
           conic-gradient(from 178deg at 50% -14%, transparent 0 34%, rgba(255,255,255,.13) 37%,
             transparent 40%, rgba(255,255,255,.09) 45%, transparent 48%, rgba(255,255,255,.13) 53%,
             transparent 56%, rgba(255,255,255,.09) 61%, transparent 64%),
           linear-gradient(135deg, #29b7ff 0%, #6d5dff 34%, #ff5fa8 68%, #ffb703 100%); }}
  .accent {{ height:9px; background:linear-gradient(90deg,#00e5ff,#6d5dff,#ff5fa8,#ffd166,#06d6a0); }}
  .wrap {{ padding:26px 40px 0; position:relative; z-index:2; }}
  .head {{ display:flex; align-items:center; gap:18px; }}
  .logo {{ width:64px; height:64px; border-radius:16px; font-size:34px; font-weight:900;
          background:linear-gradient(135deg,#ffd34d,#f5a623); color:#131313;
          display:flex; align-items:center; justify-content:center;
          box-shadow:6px 6px 0 rgba(28,35,64,.3); transform:rotate(-2deg); }}
  h1 {{ font-size:38px; font-weight:900; letter-spacing:3px; display:inline-block;
       background:#fff; border-radius:14px; padding:4px 20px; transform:rotate(-1.2deg);
       box-shadow:6px 6px 0 rgba(28,35,64,.3); }}
  .hsub2 {{ color:#fff; font-size:15px; font-weight:800; margin-top:8px;
           text-shadow:0 2px 10px rgba(28,35,64,.5); }}
  .chip {{ margin-left:auto; background:#fff; border-radius:12px; padding:8px 16px;
          font-size:16.5px; font-weight:900; color:#2c3a5c; box-shadow:0 4px 14px rgba(22,33,60,.1); }}
  .cols {{ display:flex; flex-direction:column; gap:18px; margin-top:18px; }}
  .col {{ background:rgba(255,255,255,.95); border-radius:20px; padding:16px 20px 10px;
         box-shadow:0 10px 28px rgba(22,33,60,.1); }}
  .lg {{ font-size:19px; font-weight:900; letter-spacing:3px; margin-bottom:6px;
        display:flex; align-items:center; gap:10px; }}
  .dot {{ width:12px; height:12px; border-radius:4px; background:#1673c9;
         box-shadow:0 0 10px rgba(22,115,201,.6); }}
  .note {{ margin-top:14px; background:rgba(255,255,255,.75); border-radius:14px; padding:12px 18px;
          color:#5d6a86; font-size:13px; font-weight:700; line-height:1.7; }}
  .foot {{ margin-top:10px; text-align:center; color:#fff; font-size:12.5px; font-weight:800;
          letter-spacing:1px; text-shadow:0 2px 8px rgba(28,35,64,.5); }}
</style></head><body>
<div class="accent"></div>
<div class="wrap">
  <div class="head">
    <div class="logo">采</div>
    <div><h1>采配ペナントレース</h1>
      <div class="hsub2">監督采配の勝率収支・シーズン累計 ─ 全試合自動採点の積み上げ</div></div>
    <div class="chip">{period}</div>
  </div>
  <div class="cols">
    <div class="col"><div class="lg"><span class="dot"></span>セ・リーグ</div>
      {chart(CENTRAL, daily, dates)}</div>
    <div class="col"><div class="lg"><span class="dot" style="background:#f5c518"></span>パ・リーグ</div>
      {chart(PACIFIC, daily, dates)}</div>
  </div>
  <div class="note">数値=勝率換算の采配収支(%)の累計・リーグ平均比(リーグ内の相対収支。
  セ・パでは投手打席の有無により収支の絶対水準が構造的に違うため)。攻めの采配(実行)と見逃しの損の合算。
  指示の瞬間の期待値で採点し結果は使いません。過去分は現行モデルでのバックフィル値のため、
  モデル改定のたびに再計算されます(改定履歴はnoteで公開)。僅差は誤差の範囲です。</div>
  <div class="foot">@saihaiscore_lab(β試験運用)| 計算方法はnoteで全公開 | データ: NPB公式記録より自動集計</div>
</div>
</body></html>'''
    outdir = os.path.join(BASE, "data", "out", "weekly")
    os.makedirs(outdir, exist_ok=True)
    hp = os.path.join(outdir, "pennant.html")
    open(hp, "w", encoding="utf-8").write(html)
    print("html:", hp)
    if png:
        pp = hp.replace(".html", ".png")
        render(hp, pp, "1080,1250")
        print("png:", pp)
        return pp
    return hp


if __name__ == "__main__":
    build("--png" in sys.argv)
