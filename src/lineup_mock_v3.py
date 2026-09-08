# -*- coding: utf-8 -*-
"""打順カード デザイン華やか化モック(9/8社長「会社の資料みたい・目を引くカードに」)
A案=ナイター中継グラフィック風(ダーク+チームカラー発光) B案=チームカラー激突風
実データ(lineup_{gid}.json)から生成。採用案が決まったらlineup_card.pyへ移植する。
Usage: python src/lineup_mock_v3.py 0908 g-d-21
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_card2 import render, TEAMS, parse_meta  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

POSCHR = {"捕": "捕", "一": "一", "二": "二", "三": "三", "遊": "遊",
          "左": "左", "中": "中", "右": "右", "指": "DH", "投": "投"}


def pos_of(role):
    for ch in role or "":
        if ch in POSCHR:
            return POSCHR[ch]
    return ""


def rows_html(r, col, dark=True):
    field = [p for p in r["players"] if "投" not in p["role"]]
    mx = max(p["solo"] for p in field) or 1
    star_pid = max(field, key=lambda p: p["solo"])["pid"]
    out = []
    for p in r["players"]:
        is_p = "投" in p["role"]
        w = max(4, p["solo"] / mx * 100)
        star = '<span class="star">★</span>' if p["pid"] == star_pid else ""
        bcls = {"左": "l", "右": "r", "両": "s"}.get(p["bats"], "r")
        out.append(f'''
      <div class="prow">
        <div class="slot">{p["slot"]}</div>
        <div class="pn">{p["name"]}{star}<span class="role">{pos_of(p["role"])}</span></div>
        <div class="hand {bcls}">{p["bats"]}</div>
        <div class="pbar"><div class="pfill" style="width:{w:.0f}%;
             background:linear-gradient(90deg,{col},#fff);box-shadow:0 0 10px {col}"></div></div>
        <div class="pv">{'―' if is_p else f'{p["solo"]:.1f}'}</div>
      </div>''')
    return "".join(out)


def ladder_html(r):
    ev_a, ev_b, ev_m = r["ev_actual"], r["ev_best"], r.get("ev_bestmem")
    s = [f'<div class="lstep"><div class="lk">今日の並び</div><div class="lv">{ev_a:.2f}</div></div>',
         '<div class="larr">→</div>',
         f'<div class="lstep"><div class="lk">並べ替え最適</div><div class="lv">{ev_b:.2f}'
         f'<span class="lg2">+{max(0.0, ev_b - ev_a):.2f}</span></div></div>',
         '<div class="larr">→</div>']
    if ev_m:
        inn = "・".join(r.get("bestmem_in") or [])
        s.append(f'<div class="lstep gold"><div class="lk">ベストメンバー</div><div class="lv">{ev_m:.2f}'
                 f'<span class="lg2">+{ev_m - ev_a:.2f}</span></div><div class="lin">{inn} IN</div></div>')
    else:
        s.append('<div class="lstep gold"><div class="lk">ベストメンバー</div>'
                 '<div class="lv" style="font-size:15px;padding-top:8px">現メンバーがベスト</div></div>')
    return f'<div class="ladder">{"".join(s)}</div>'


def panel(r, side):
    t = TEAMS.get(r["team"], {})
    col, glow = t.get("color", "#888"), t.get("glow", "136,136,136")
    badge = ('<span class="badge ok">✓ ほぼ最適の並び</span>' if r["diff"] >= -0.05
             else f'<span class="badge amber">並び替え余地 {r["diff"]:+.2f}点</span>')
    return f'''
  <div class="panel" style="--tc:{col};--tg:{glow}">
    <div class="phead">
      <div class="mono" style="border-color:{col};color:{col};text-shadow:0 0 16px rgba({glow},.9)">{t.get("mono", "")}</div>
      <div><div class="ptm" style="color:{col};text-shadow:0 0 22px rgba({glow},.7)">{r["team"]}</div>{badge}</div>
      <div class="pev"><div class="pevl">この並びの得点期待値</div>
        <div class="pevv">{r["ev_actual"]:.2f}<span class="unit">点/試合</span></div></div>
    </div>
    <div class="phdr"><span style="width:34px">打順</span><span style="width:150px"></span><span style="width:30px">左右</span><span style="flex:1;text-align:center">打力(点/試合換算)</span></div>
    {rows_html(r, col)}
    {ladder_html(r)}
  </div>'''


def versus(res):
    a, h = res
    ta, th = TEAMS.get(a["team"], {}), TEAMS.get(h["team"], {})
    ca, ch = ta.get("color", "#888"), th.get("color", "#888")
    tot = a["ev_actual"] + h["ev_actual"]
    fa = a["ev_actual"] / tot * 100 if tot else 50
    lead = a if a["ev_actual"] >= h["ev_actual"] else h
    gap = abs(a["ev_actual"] - h["ev_actual"])
    return f'''
  <div class="vs">
    <div class="vsrow">
      <div class="vst" style="color:{ca};text-shadow:0 0 18px {ca}">{a["team"]} {a["ev_actual"]:.2f}</div>
      <div class="vsbar">
        <div style="position:absolute;left:0;top:0;bottom:0;width:{fa:.1f}%;
             background:linear-gradient(90deg,{ca},{ca}aa);box-shadow:0 0 18px {ca}"></div>
        <div style="position:absolute;right:0;top:0;bottom:0;width:{100 - fa:.1f}%;
             background:linear-gradient(90deg,{ch}aa,{ch});box-shadow:0 0 18px {ch}"></div>
        <div class="vszero"></div>
      </div>
      <div class="vst" style="color:{ch};text-align:right;text-shadow:0 0 18px {ch}">{h["ev_actual"]:.2f} {h["team"]}</div>
    </div>
    <div class="vssub">打線力バランス ─ {lead["team"]}の並びが <b>+{gap:.2f}点/試合</b> 上回る</div>
  </div>'''


CSS_COMMON = '''
  * { margin:0; padding:0; box-sizing:border-box; }
  .prow { display:flex; align-items:center; gap:8px; padding:4.5px 0; }
  .slot { width:30px; height:30px; border-radius:8px; flex:none; font-size:15px; font-weight:900;
          display:flex; align-items:center; justify-content:center; }
  .pn { width:150px; flex:none; font-size:19px; font-weight:900; white-space:nowrap; }
  .role { font-size:11px; font-weight:800; margin-left:5px; opacity:.55; }
  .star { color:#ffd34d; font-size:14px; margin-left:2px; text-shadow:0 0 12px rgba(255,211,77,1); }
  .hand { width:26px; height:20px; border-radius:6px; flex:none; font-size:11.5px; font-weight:900;
          display:flex; align-items:center; justify-content:center; }
  .pbar { flex:1; height:13px; border-radius:99px; overflow:hidden; position:relative; }
  .pfill { height:100%; border-radius:99px; }
  .pv { width:38px; flex:none; text-align:right; font-size:14.5px; font-weight:900; }
  .phdr { display:flex; gap:8px; font-size:10.5px; font-weight:800; letter-spacing:1px;
          padding-bottom:5px; margin-bottom:2px; }
  .ladder { display:flex; gap:8px; margin-top:12px; align-items:stretch; }
  .lstep { flex:1; border-radius:14px; padding:9px 12px; }
  .lk { font-size:11px; font-weight:900; letter-spacing:1px; opacity:.75; }
  .lv { font-size:24px; font-weight:900; }
  .lg2 { font-size:12.5px; font-weight:900; color:#2ee584; margin-left:5px; }
  .lin { font-size:11.5px; font-weight:900; margin-top:2px; }
  .larr { align-self:center; font-size:18px; font-weight:900; opacity:.5; }
  .badge { display:inline-block; border-radius:99px; font-size:12.5px; font-weight:900;
           padding:3px 12px; margin-top:5px; }
  .vsrow { display:flex; align-items:center; gap:14px; }
  .vst { width:190px; flex:none; font-size:23px; font-weight:900; }
  .vsbar { flex:1; height:20px; border-radius:99px; position:relative; overflow:hidden; }
  .vszero { position:absolute; left:50%; top:-3px; bottom:-3px; width:3px; background:#fff8; }
'''


def html_a(res, date, venue):
    a, h = res
    ga = TEAMS.get(a["team"], {}).get("glow", "120,120,120")
    gh = TEAMS.get(h["team"], {}).get("glow", "120,120,120")
    return f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>
{CSS_COMMON}
  body {{ width:1080px; height:1250px; color:#f2f5ff; padding:0;
         font-family:"Yu Gothic","Hiragino Sans","Noto Sans CJK JP",sans-serif;
         background:
           radial-gradient(900px 500px at 12% -6%, rgba({ga},.38), transparent 55%),
           radial-gradient(900px 500px at 88% -6%, rgba({gh},.38), transparent 55%),
           radial-gradient(1200px 700px at 50% 115%, rgba(47,111,224,.25), transparent 60%),
           repeating-linear-gradient(115deg, rgba(255,255,255,.022) 0 2px, transparent 2px 7px),
           #070b18; }}
  .accent {{ height:8px; background:linear-gradient(90deg, rgb({ga}), #ffd34d 50%, rgb({gh})); box-shadow:0 0 26px rgba(255,211,77,.55); }}
  .wrap {{ padding:26px 38px 0; }}
  .head {{ display:flex; align-items:center; gap:18px; }}
  .logo {{ width:64px; height:64px; border-radius:16px; font-size:34px; font-weight:900; color:#0b0f1e;
           background:linear-gradient(135deg,#ffd34d,#f5a623); display:flex; align-items:center;
           justify-content:center; box-shadow:0 0 30px rgba(245,197,24,.6); }}
  h1 {{ font-size:42px; font-weight:900; letter-spacing:6px;
       background:linear-gradient(180deg,#fff,#9fb7ff); -webkit-background-clip:text; color:transparent; }}
  .hsub {{ color:#8fa2cc; font-size:14.5px; font-weight:700; margin-top:2px; letter-spacing:1px; }}
  .chip {{ margin-left:auto; text-align:right; background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.14);
          border-radius:16px; padding:10px 18px; font-size:15.5px; font-weight:900; color:#dfe7ff;
          backdrop-filter:blur(4px); }}
  .beta {{ display:inline-block; background:rgba(255,211,77,.16); color:#ffd34d; border:1px solid #ffd34d66;
          border-radius:99px; font-size:12px; font-weight:900; padding:2px 12px; margin-top:6px; }}
  .cols {{ display:flex; gap:22px; margin-top:20px; }}
  .panel {{ flex:1; border-radius:22px; padding:18px 20px 16px;
           background:linear-gradient(180deg, rgba(255,255,255,.075), rgba(255,255,255,.028));
           border:1.5px solid rgba(var(--tg), .45); box-shadow:0 0 34px rgba(var(--tg), .22), inset 0 1px 0 rgba(255,255,255,.09); }}
  .phead {{ display:flex; gap:14px; align-items:center; margin-bottom:10px; }}
  .mono {{ width:54px; height:54px; border-radius:50%; border:2.5px solid; flex:none; font-size:18px; font-weight:900;
          display:flex; align-items:center; justify-content:center; background:rgba(255,255,255,.05); }}
  .ptm {{ font-size:25px; font-weight:900; }}
  .pev {{ margin-left:auto; text-align:right; }}
  .pevl {{ font-size:11px; font-weight:800; color:#8fa2cc; letter-spacing:1px; }}
  .pevv {{ font-size:40px; font-weight:900; color:#fff; text-shadow:0 0 26px rgba(var(--tg),.95); line-height:1.1; }}
  .unit {{ font-size:13px; color:#8fa2cc; margin-left:3px; }}
  .badge.ok {{ background:rgba(46,229,132,.14); color:#2ee584; border:1px solid #2ee58466; }}
  .badge.amber {{ background:rgba(255,196,66,.14); color:#ffc442; border:1px solid #ffc44266; }}
  .phdr {{ color:#7286b3; border-bottom:1.5px solid rgba(255,255,255,.1); }}
  .slot {{ background:rgba(255,255,255,.08); color:#dfe7ff; }}
  .pn {{ color:#fff; }}
  .hand.l {{ background:rgba(88,166,255,.18); color:#79b6ff; }}
  .hand.r {{ background:rgba(255,120,120,.16); color:#ff9d9d; }}
  .hand.s {{ background:rgba(196,140,255,.18); color:#d3a8ff; }}
  .pbar {{ background:rgba(255,255,255,.07); }}
  .pv {{ color:#dfe7ff; }}
  .lstep {{ background:rgba(255,255,255,.055); border:1px solid rgba(255,255,255,.12); }}
  .lstep.gold {{ background:linear-gradient(160deg, rgba(255,211,77,.2), rgba(255,211,77,.06));
               border:1.5px solid #ffd34d88; box-shadow:0 0 22px rgba(255,211,77,.28); }}
  .lv {{ color:#fff; }} .lin {{ color:#ffd34d; }} .lk {{ color:#9fb0d6; }}
  .vs {{ margin-top:20px; border-radius:20px; padding:16px 22px; background:rgba(255,255,255,.05);
        border:1px solid rgba(255,255,255,.12); }}
  .vssub {{ margin-top:9px; color:#aebada; font-size:14px; font-weight:800; text-align:center; }}
  .vssub b {{ color:#ffd34d; }}
  .note {{ margin-top:14px; border-radius:14px; padding:10px 16px; background:rgba(255,255,255,.04);
          color:#7286b3; font-size:12px; font-weight:700; line-height:1.65; }}
  .foot {{ margin-top:8px; text-align:center; color:#5d6c94; font-size:12.5px; font-weight:800; letter-spacing:1px; }}
</style></head><body>
<div class="accent"></div>
<div class="wrap">
  <div class="head">
    <div class="logo">采</div>
    <div><h1>打順診断</h1><div class="hsub">その日のスタメンで「何点取れる並びか」をデータで検証</div></div>
    <div class="chip">{date}&nbsp;&nbsp;◉ {venue}<br><span class="beta">β 試験運用</span></div>
  </div>
  <div class="cols">{panel(res[0], "away")}{panel(res[1], "home")}</div>
  {versus(res)}
  <div class="note">得点期待値=9イニング・中立環境換算(相手投手の質は含みません)。打力=その打者9人が並んだ場合の点/試合換算。
  ベストメンバーは同ポジション群内の入替のみの参考値で、守備力・休養・疲労は考慮していません。僅差は誤差の範囲です。</div>
  <div class="foot">@saihaiscore_lab(β試験運用)| 計算方法はnoteで全公開 | データ: NPB公式記録より自動集計</div>
</div>
</body></html>'''


def html_b(res, date, venue):
    a, h = res
    ca = TEAMS.get(a["team"], {}).get("color", "#888")
    ch = TEAMS.get(h["team"], {}).get("color", "#888")
    return f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>
{CSS_COMMON}
  body {{ width:1080px; height:1250px; color:#16213c; padding:0;
         font-family:"Yu Gothic","Hiragino Sans","Noto Sans CJK JP",sans-serif;
         background:linear-gradient(104deg, {ca} 0%, {ca} 44%, #10152b 49.5%, #10152b 50.5%, {ch} 56%, {ch} 100%); }}
  .wrap {{ padding:24px 36px 0; }}
  .head {{ display:flex; align-items:center; gap:16px; background:rgba(10,14,30,.85); border-radius:20px;
          padding:14px 22px; box-shadow:0 10px 40px rgba(0,0,0,.45); }}
  .logo {{ width:58px; height:58px; border-radius:14px; font-size:30px; font-weight:900; color:#0b0f1e;
          background:linear-gradient(135deg,#ffd34d,#f5a623); display:flex; align-items:center; justify-content:center; }}
  h1 {{ font-size:38px; font-weight:900; letter-spacing:5px; color:#fff; }}
  .hsub {{ color:#9fb0d6; font-size:13.5px; font-weight:700; }}
  .chip {{ margin-left:auto; text-align:right; color:#fff; font-size:15px; font-weight:900; }}
  .beta {{ display:inline-block; background:#ffd34d; color:#10152b; border-radius:99px; font-size:11.5px;
          font-weight:900; padding:2px 12px; margin-top:5px; }}
  .vsband {{ text-align:center; margin:14px 0 2px; }}
  .vsmark {{ display:inline-block; font-size:44px; font-weight:900; color:#fff; font-style:italic;
            text-shadow:0 4px 24px rgba(0,0,0,.6); letter-spacing:2px; }}
  .cols {{ display:flex; gap:26px; margin-top:12px; }}
  .panel {{ flex:1; border-radius:22px; padding:18px 20px 16px; background:rgba(255,255,255,.97);
           box-shadow:0 18px 50px rgba(0,0,0,.42); border-top:6px solid var(--tc); }}
  .phead {{ display:flex; gap:13px; align-items:center; margin-bottom:10px; }}
  .mono {{ width:52px; height:52px; border-radius:50%; border:3px solid; flex:none; font-size:17px;
          font-weight:900; display:flex; align-items:center; justify-content:center; }}
  .ptm {{ font-size:24px; font-weight:900; }}
  .pev {{ margin-left:auto; text-align:right; }}
  .pevl {{ font-size:11px; font-weight:800; color:#66718c; letter-spacing:1px; }}
  .pevv {{ font-size:38px; font-weight:900; color:var(--tc); line-height:1.1; }}
  .unit {{ font-size:13px; color:#66718c; }}
  .badge.ok {{ background:#e2f8ec; color:#0d9e55; }}
  .badge.amber {{ background:#fdf3dc; color:#9a7208; }}
  .phdr {{ color:#9fadcc; border-bottom:1.5px solid #e6ebf4; }}
  .slot {{ background:#eef2f9; color:#2c3a5c; }}
  .pn {{ color:#16213c; }}
  .hand.l {{ background:#e3efff; color:#2266cc; }}
  .hand.r {{ background:#ffe9e6; color:#cc4433; }}
  .hand.s {{ background:#f1e6ff; color:#7a3fc9; }}
  .pbar {{ background:#edf1f8; }}
  .pfill {{ box-shadow:none !important; background:linear-gradient(90deg,var(--tc),var(--tc)) !important; opacity:.92; }}
  .pv {{ color:#2c3a5c; }}
  .lstep {{ background:#f4f7fc; border:1px solid #e6ebf4; }}
  .lstep.gold {{ background:linear-gradient(160deg,#fff7dd,#fdeeb8); border:1.5px solid #f0c93f; }}
  .lv {{ color:#16213c; }} .lg2 {{ color:#0d9e55; }} .lin {{ color:#9a7208; }} .lk {{ color:#66718c; }}
  .vs {{ margin-top:18px; border-radius:20px; padding:16px 22px; background:rgba(10,14,30,.88);
        box-shadow:0 14px 44px rgba(0,0,0,.4); }}
  .vst {{ text-shadow:none !important; }}
  .vssub {{ margin-top:9px; color:#c6d0ea; font-size:14px; font-weight:800; text-align:center; }}
  .vssub b {{ color:#ffd34d; }}
  .note {{ margin-top:13px; border-radius:14px; padding:10px 16px; background:rgba(10,14,30,.6);
          color:#c6d0ea; font-size:12px; font-weight:700; line-height:1.65; }}
  .foot {{ margin-top:8px; text-align:center; color:#e6ebff; font-size:12.5px; font-weight:800;
          letter-spacing:1px; text-shadow:0 1px 6px rgba(0,0,0,.5); }}
</style></head><body>
<div class="wrap">
  <div class="head">
    <div class="logo">采</div>
    <div><h1>打順診断</h1><div class="hsub">その日のスタメンで「何点取れる並びか」をデータで検証</div></div>
    <div class="chip">{date}&nbsp;&nbsp;◉ {venue}<br><span class="beta">β 試験運用</span></div>
  </div>
  <div class="vsband"><span class="vsmark">{res[0]["team"]} <span style="color:#ffd34d">VS</span> {res[1]["team"]}</span></div>
  <div class="cols">{panel(res[0], "away")}{panel(res[1], "home")}</div>
  {versus(res)}
  <div class="note">得点期待値=9イニング・中立環境換算(相手投手の質は含みません)。ベストメンバーは同ポジション群内の
  入替のみの参考値で、守備力・休養・疲労は考慮していません。僅差は誤差の範囲です。</div>
  <div class="foot">@saihaiscore_lab(β試験運用)| 計算方法はnoteで全公開 | データ: NPB公式記録より自動集計</div>
</div>
</body></html>'''


def main():
    mmdd, gid = sys.argv[1], sys.argv[2]
    res = json.load(open(os.path.join(BASE, "data", "out", mmdd, f"lineup_{gid}.json"),
                         encoding="utf-8"))
    try:
        meta = parse_meta(mmdd, gid)
        date, venue = meta["date"], meta["venue"]
    except Exception:
        date, venue = f"{int(mmdd[:2])}月{int(mmdd[2:])}日", ""
    outdir = os.path.join(BASE, "data", "out", mmdd)
    for tag, fn in (("A", html_a), ("B", html_b)):
        hp = os.path.join(outdir, f"mock_v3{tag}_{gid}.html")
        open(hp, "w", encoding="utf-8").write(fn(res, date, venue))
        pp = hp.replace(".html", ".png")
        render(hp, pp, "1080,1250")
        print("png:", pp)


if __name__ == "__main__":
    main()
