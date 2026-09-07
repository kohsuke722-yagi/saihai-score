# -*- coding: utf-8 -*-
"""週間監督通信簿カード(月曜・試合なし日用)モックv1(2026-09-08・design-weekly.md準拠)
- 火〜日の_ph.jsonを集計: 攻めの収支(実行采配のWP合計)と見逃しの損(回頭起用差+代打見逃し)を分離
- リーグ別ランキング・%/試合正規化・週間ベスト/ワースト采配つき
Usage: python src/weekly_card.py 0901 0906 [--png]
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_card2 import render, TEAMS  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CENTRAL = ("巨人", "DeNA", "阪神", "広島", "中日", "ヤクルト")
PACIFIC = ("ソフトバンク", "日本ハム", "ロッテ", "西武", "オリックス", "楽天")
KINDLABEL = {"bunt": "送りバント", "squeeze": "スクイズ", "swing": "強攻", "ph": "代打",
             "pr": "代走", "ibb": "申告敬遠", "relief": "継投"}


def collect(d0, d1):
    agg = {}  # team -> {"atk": x, "miss": x, "games": set}
    best = worst = None
    for f in glob.glob(os.path.join(BASE, "data", "out", "*", "*_ph.json")):
        mmdd = os.path.basename(os.path.dirname(f))
        if not (d0 <= mmdd <= d1):
            continue
        gid = os.path.basename(f).replace("_ph.json", "")
        try:
            recs = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
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
                lab = f"{int(mmdd[:2])}/{int(mmdd[2:])} {r['inning']}回 {tm}"
                if best is None or w * 100 > best[0]:
                    best = (w * 100, lab, r)
                if worst is None or w * 100 < worst[0]:
                    worst = (w * 100, lab, r)
            elif r.get("decision_head_wp") is not None:
                a["miss"] += r["decision_head_wp"] * 100
            elif r.get("engine_loss_wp"):
                a["miss"] -= r["engine_loss_wp"] * 100
    return agg, best, worst


def desc_of(r):
    k = r.get("kind")
    if k in ("bunt", "squeeze"):
        return f"{r.get('batter','')}の{'スクイズ' if k=='squeeze' else '送りバント'}"
    if k == "swing":
        return f"{r.get('batter','')}に強攻"
    if k == "ph":
        return f"代打・{r.get('ph','')}"
    if k == "pr":
        return f"代走 {r.get('orig','')}→{r.get('sub','')}"
    if k == "ibb":
        return f"{r.get('batter','')}への申告敬遠"
    if k == "relief":
        return f"継投 {r.get('old','')}→{r.get('new','')}"
    return ""


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


def bar_html(rows):
    mx = max((abs(r[1]) for r in rows), default=1) or 1
    out = []
    for i, (tm, net, atk, miss, g) in enumerate(rows):
        col = TEAMS.get(tm, {}).get("color", "#888")
        w = abs(net) / mx * 100
        cls = "pos" if net >= 0 else "neg"
        side = "left:50%" if net >= 0 else f"right:50%"
        out.append(f'''
      <div class="rrow">
        <div class="rk">{i + 1}</div>
        <div class="tm" style="color:{col}">{tm}</div>
        <div class="barwrap">
          <div class="bar {cls}" style="width:{w / 2:.1f}%;{side}"></div>
        </div>
        <div class="val {cls}">{net:+.1f}%</div>
        <div class="sub">攻め{atk:+.1f} 見逃し{miss:+.1f}<span class="gg">・{g}試合</span></div>
      </div>''')
    return "".join(out)


def build(d0, d1, png=False):
    agg, best, worst = collect(d0, d1)
    ce, pa = rank_rows(agg, CENTRAL), rank_rows(agg, PACIFIC)
    period = f"{int(d0[:2])}/{int(d0[2:])} − {int(d1[:2])}/{int(d1[2:])}"
    b_html = w_html = ""
    if best:
        b_html = (f'<div class="pill good">今週のベスト采配</div>'
                  f'<div class="pl1">{best[1]} {desc_of(best[2])}</div>'
                  f'<div class="pv good">勝率 {best[0]:+.1f}%</div>')
    if worst:
        w_html = (f'<div class="pill bad">今週のワースト采配</div>'
                  f'<div class="pl1">{worst[1]} {desc_of(worst[2])}</div>'
                  f'<div class="pv bad">勝率 {worst[0]:+.1f}%</div>')
    html = f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1080px; height:1250px; background:#eef1f7; color:#16213c;
         font-family:"Yu Gothic","Hiragino Sans","Noto Sans CJK JP",sans-serif; padding:34px 40px; }}
  .head {{ display:flex; align-items:center; gap:16px; margin-bottom:6px; }}
  .logo {{ width:56px; height:56px; border-radius:14px; background:linear-gradient(135deg,#1673c9,#12408a);
          color:#fff; font-size:30px; font-weight:900; display:flex; align-items:center; justify-content:center; }}
  h1 {{ font-size:34px; font-weight:900; letter-spacing:2px; }}
  .period {{ margin-left:auto; text-align:right; color:#5d6a86; font-size:16px; font-weight:700; }}
  .beta {{ display:inline-block; background:#fff; border:1.5px solid #1673c9; color:#1673c9;
          border-radius:99px; font-size:12.5px; font-weight:900; padding:2px 12px; margin-top:4px; }}
  .lede {{ color:#5d6a86; font-size:15.5px; font-weight:700; margin:2px 0 18px 72px; }}
  .cols {{ display:flex; gap:22px; }}
  .col {{ flex:1; background:#fff; border-radius:18px; padding:20px 22px 14px;
         box-shadow:0 8px 24px rgba(22,33,60,.07); }}
  .lg {{ font-size:19px; font-weight:900; letter-spacing:3px; margin-bottom:12px;
        display:flex; align-items:center; gap:9px; }}
  .dot {{ width:10px; height:10px; border-radius:3px; background:#1673c9; }}
  .rrow {{ display:grid; grid-template-columns:30px 118px 1fr 86px; grid-template-rows:auto auto;
          align-items:center; column-gap:10px; padding:7px 0 6px; border-top:1px solid #e6ebf4; }}
  .rk {{ font-size:17px; font-weight:900; color:#9fadcc; text-align:center; }}
  .tm {{ font-size:17.5px; font-weight:900; white-space:nowrap; letter-spacing:-0.5px; }}
  .barwrap {{ position:relative; height:14px; background:#f0f3f9; border-radius:7px; overflow:hidden; }}
  .barwrap::after {{ content:""; position:absolute; left:50%; top:0; bottom:0; width:1.5px; background:#b9c4d8; }}
  .bar {{ position:absolute; top:2px; bottom:2px; border-radius:5px; }}
  .bar.pos {{ background:linear-gradient(90deg,#0d9e55,#35c97e); }}
  .bar.neg {{ background:linear-gradient(90deg,#f0837d,#dd3d35); }}
  .val {{ font-size:19px; font-weight:900; text-align:right; }}
  .val.pos {{ color:#0d9e55; }} .val.neg {{ color:#dd3d35; }}
  .sub {{ grid-column:2 / 5; color:#66718c; font-size:12.5px; font-weight:700; padding-left:2px; }}
  .gg {{ color:#9fadcc; }}
  .band {{ display:flex; gap:22px; margin-top:20px; }}
  .bcard {{ flex:1; background:#fff; border-radius:18px; padding:18px 22px;
           box-shadow:0 8px 24px rgba(22,33,60,.07); }}
  .bcard.g {{ border:1.5px solid rgba(13,158,85,.35); }}
  .bcard.r {{ border:1.5px solid rgba(221,61,53,.35); }}
  .pill {{ display:inline-block; border-radius:99px; font-size:13px; font-weight:900;
          padding:3px 14px; margin-bottom:10px; }}
  .pill.good {{ background:rgba(13,158,85,.1); color:#0a7f45; }}
  .pill.bad {{ background:rgba(221,61,53,.1); color:#b8302a; }}
  .pl1 {{ font-size:19px; font-weight:900; line-height:1.45; }}
  .pv {{ font-size:30px; font-weight:900; margin-top:8px; }}
  .pv.good {{ color:#0d9e55; }} .pv.bad {{ color:#dd3d35; }}
  .note {{ margin-top:18px; background:rgba(255,255,255,.7); border-radius:14px; padding:14px 18px;
          color:#5d6a86; font-size:13.5px; font-weight:700; line-height:1.75; }}
  .foot {{ margin-top:14px; text-align:center; color:#8b96ab; font-size:13px; font-weight:700;
          letter-spacing:1px; }}
</style></head><body>
  <div class="head">
    <div class="logo">采</div>
    <div><h1>週間 監督通信簿</h1><span class="beta">β 試験運用</span></div>
    <div class="period">{period}<br>全采配をWP(勝率換算)で自動採点</div>
  </div>
  <div class="lede">攻めの収支=実行した采配の合計 / 見逃し=最善を選ばなかった機会損失(0が満点)</div>
  <div class="cols">
    <div class="col"><div class="lg"><span class="dot"></span>セ・リーグ</div>{bar_html(ce)}</div>
    <div class="col"><div class="lg"><span class="dot" style="background:#f5c518"></span>パ・リーグ</div>{bar_html(pa)}</div>
  </div>
  <div class="band">
    <div class="bcard g">{b_html}</div>
    <div class="bcard r">{w_html}</div>
  </div>
  <div class="note">数値=勝率換算の采配収支(%/試合・週平均)。指示の瞬間の期待値で採点し結果は使いません。
  負傷交代・選択肢のない場面は採点対象外。僅差の順位差は誤差の範囲です。計算方法はnoteで全公開。</div>
  <div class="foot">@saihaiscore_lab(β試験運用)| 計算方法はnoteで全公開 | データ: NPB公式記録より自動集計</div>
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
