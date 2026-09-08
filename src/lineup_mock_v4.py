# -*- coding: utf-8 -*-
"""打順カード華やか化モック第2弾(9/8社長「色替えだけに見える・模様や飾りを」)
C案=ダーク熱量系(集中線・縫い目モチーフ・金箔・斜めリボン) D案=ポップ祭り系(紙吹雪・ドット・スタンプ)
Usage: python src/lineup_mock_v4.py 0908 g-d-21
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


def seam_svg(color, op=".14"):
    """野球ボールの縫い目(2本の弧+ステッチ)を大きく敷く装飾SVG"""
    return f'''<svg viewBox="0 0 400 400" style="position:absolute;width:640px;height:640px;opacity:{op};pointer-events:none">
      <path d="M 60 -40 Q 250 200 60 440" fill="none" stroke="{color}" stroke-width="3"/>
      <path d="M 60 -40 Q 250 200 60 440" fill="none" stroke="{color}" stroke-width="14"
            stroke-dasharray="3 26" stroke-linecap="round" transform="translate(-14,0)"/>
      <path d="M 60 -40 Q 250 200 60 440" fill="none" stroke="{color}" stroke-width="14"
            stroke-dasharray="3 26" stroke-linecap="round" transform="translate(14,0)"/>
    </svg>'''


def rows_html(r, mode):
    field = [p for p in r["players"] if "投" not in p["role"]]
    mx = max(p["solo"] for p in field) or 1
    star_pid = max(field, key=lambda p: p["solo"])["pid"]
    out = []
    for p in r["players"]:
        is_p = "投" in p["role"]
        w = max(4, p["solo"] / mx * 100)
        star = '<span class="star">★</span>' if p["pid"] == star_pid else ""
        hot = ' hot' if p["pid"] == star_pid else ''
        bcls = {"左": "l", "右": "r", "両": "s"}.get(p["bats"], "r")
        out.append(f'''
      <div class="prow{hot}">
        <div class="slot">{p["slot"]}</div>
        <div class="pn">{p["name"]}{star}<span class="role">{pos_of(p["role"])}</span></div>
        <div class="hand {bcls}">{p["bats"]}</div>
        <div class="pbar"><div class="pfill" style="width:{w:.0f}%"></div><div class="sheen"></div></div>
        <div class="pv">{'―' if is_p else f'{p["solo"]:.1f}'}</div>
      </div>''')
    return "".join(out)


def ladder_html(r):
    ev_a, ev_b, ev_m = r["ev_actual"], r["ev_best"], r.get("ev_bestmem")
    s = [f'<div class="lstep"><div class="lk">今日の並び</div><div class="lv">{ev_a:.2f}</div></div>',
         '<div class="larr">▶</div>',
         f'<div class="lstep"><div class="lk">並べ替え最適</div><div class="lv">{ev_b:.2f}'
         f'<span class="lg2">+{max(0.0, ev_b - ev_a):.2f}</span></div></div>',
         '<div class="larr">▶</div>']
    if ev_m:
        inn = "・".join(r.get("bestmem_in") or [])
        s.append(f'<div class="lstep gold"><div class="spark"></div><div class="lk">ベストメンバー</div>'
                 f'<div class="lv">{ev_m:.2f}<span class="lg2">+{ev_m - ev_a:.2f}</span></div>'
                 f'<div class="lin">{inn} IN</div></div>')
    else:
        s.append('<div class="lstep gold"><div class="spark"></div><div class="lk">ベストメンバー</div>'
                 '<div class="lv" style="font-size:15px;padding-top:8px">現メンバーがベスト</div></div>')
    return f'<div class="ladder">{"".join(s)}</div>'


def panel(r, mode):
    t = TEAMS.get(r["team"], {})
    col, glow = t.get("color", "#888"), t.get("glow", "136,136,136")
    badge = ('<span class="badge ok">✔ ほぼ最適の並び</span>' if r["diff"] >= -0.05
             else f'<span class="badge amber">並び替え余地 {r["diff"]:+.2f}点</span>')
    return f'''
  <div class="panel" style="--tc:{col};--tg:{glow}">
    <div class="ribbon"><span class="rmono">{t.get("mono", "")}</span><span class="rteam">{r["team"]}</span>
      <span class="rev">{r["ev_actual"]:.2f}<small>点/試合</small></span></div>
    <div class="pbadge">{badge}</div>
    <div class="phdr"><span style="width:36px">打順</span><span style="width:148px"></span><span style="width:30px">左右</span><span style="flex:1;text-align:center">打力(点/試合換算)</span></div>
    {rows_html(r, mode)}
    {ladder_html(r)}
  </div>'''


def versus(res, mode):
    a, h = res
    ca = TEAMS.get(a["team"], {}).get("color", "#888")
    ch = TEAMS.get(h["team"], {}).get("color", "#888")
    tot = a["ev_actual"] + h["ev_actual"]
    fa = a["ev_actual"] / tot * 100 if tot else 50
    lead = a if a["ev_actual"] >= h["ev_actual"] else h
    gap = abs(a["ev_actual"] - h["ev_actual"])
    return f'''
  <div class="vs">
    <div class="rays"></div>
    <div class="vsrow">
      <div class="vst" style="color:{ca}">{a["team"]}<br><span class="vsn">{a["ev_actual"]:.2f}</span></div>
      <div class="vsbar">
        <div style="position:absolute;left:0;top:0;bottom:0;width:{fa:.1f}%;
             background:linear-gradient(90deg,{ca},{ca}cc);"></div>
        <div style="position:absolute;right:0;top:0;bottom:0;width:{100 - fa:.1f}%;
             background:linear-gradient(90deg,{ch}cc,{ch});"></div>
        <div class="vsstripe"></div><div class="vszero"></div>
      </div>
      <div class="vst" style="color:{ch};text-align:right">{h["team"]}<br><span class="vsn">{h["ev_actual"]:.2f}</span></div>
    </div>
    <div class="vssub">打線力バランス ─ {lead["team"]}の並びが <b>+{gap:.2f}点/試合</b> 上回る</div>
  </div>'''


CSS_BASE = '''
  * { margin:0; padding:0; box-sizing:border-box; }
  .prow { display:flex; align-items:center; gap:8px; padding:4px 6px; border-radius:10px; }
  .slot { width:31px; height:31px; flex:none; font-size:15.5px; font-weight:900;
          display:flex; align-items:center; justify-content:center;
          clip-path:polygon(50% 0, 100% 50%, 50% 100%, 0 50%); }
  .pn { width:148px; flex:none; font-size:19px; font-weight:900; white-space:nowrap; }
  .role { font-size:11px; font-weight:800; margin-left:5px; opacity:.55; }
  .star { color:#ffd34d; font-size:14px; margin-left:2px; text-shadow:0 0 12px rgba(255,211,77,1); }
  .hand { width:26px; height:20px; border-radius:6px; flex:none; font-size:11.5px; font-weight:900;
          display:flex; align-items:center; justify-content:center; }
  .pbar { flex:1; height:14px; border-radius:99px; overflow:hidden; position:relative; }
  .pfill { height:100%; border-radius:99px; background:linear-gradient(90deg,var(--tc),#fff); }
  .sheen { position:absolute; inset:0; border-radius:99px;
           background:repeating-linear-gradient(115deg, transparent 0 10px, rgba(255,255,255,.16) 10px 14px); }
  .pv { width:38px; flex:none; text-align:right; font-size:14.5px; font-weight:900; }
  .phdr { display:flex; gap:8px; font-size:10.5px; font-weight:800; letter-spacing:1px;
          padding:0 6px 5px; margin-bottom:2px; }
  .ladder { display:flex; gap:8px; margin-top:12px; align-items:stretch; }
  .lstep { flex:1; border-radius:14px; padding:9px 12px; position:relative; overflow:hidden; }
  .lk { font-size:11px; font-weight:900; letter-spacing:1px; opacity:.8; }
  .lv { font-size:24px; font-weight:900; }
  .lg2 { font-size:12.5px; font-weight:900; color:#17c46f; margin-left:5px; }
  .lin { font-size:11.5px; font-weight:900; margin-top:2px; }
  .larr { align-self:center; font-size:15px; font-weight:900; opacity:.6; }
  .badge { display:inline-block; border-radius:99px; font-size:12.5px; font-weight:900; padding:3px 14px; }
  .pbadge { margin:6px 0 8px; }
  .spark { position:absolute; inset:0; pointer-events:none;
    background:
      radial-gradient(circle at 12% 30%, rgba(255,255,255,.9) 0 1.5px, transparent 2.5px),
      radial-gradient(circle at 78% 18%, rgba(255,255,255,.8) 0 1.2px, transparent 2.2px),
      radial-gradient(circle at 90% 70%, rgba(255,255,255,.9) 0 1.8px, transparent 2.8px),
      radial-gradient(circle at 40% 80%, rgba(255,255,255,.7) 0 1.2px, transparent 2.2px); }
  .ribbon { display:flex; align-items:center; gap:12px; padding:10px 16px; margin:-18px -18px 0;
            clip-path:polygon(0 0, 100% 0, 97% 100%, 0 92%); }
  .rmono { width:46px; height:46px; border-radius:50%; border:2.5px solid #fff; flex:none;
           font-size:15px; font-weight:900; color:#fff; display:flex; align-items:center;
           justify-content:center; background:rgba(255,255,255,.14); }
  .rteam { font-size:26px; font-weight:900; color:#fff; letter-spacing:2px;
           text-shadow:0 2px 10px rgba(0,0,0,.35); }
  .rev { margin-left:auto; font-size:37px; font-weight:900; color:#fff;
         text-shadow:0 2px 14px rgba(0,0,0,.4); font-style:italic; }
  .rev small { font-size:13px; font-weight:800; margin-left:3px; font-style:normal; opacity:.85; }
  .vsrow { display:flex; align-items:center; gap:14px; position:relative; }
  .vst { width:150px; flex:none; font-size:20px; font-weight:900; line-height:1.1; }
  .vsn { font-size:27px; font-style:italic; }
  .vsbar { flex:1; height:22px; border-radius:99px; position:relative; overflow:hidden; }
  .vsstripe { position:absolute; inset:0;
    background:repeating-linear-gradient(115deg, transparent 0 14px, rgba(255,255,255,.13) 14px 19px); }
  .vszero { position:absolute; left:50%; top:-3px; bottom:-3px; width:3px; background:#fffc;
            box-shadow:0 0 10px #fff; }
'''


def html_c(res, date, venue):
    a, h = res
    ga = TEAMS.get(a["team"], {}).get("glow", "120,120,120")
    gh = TEAMS.get(h["team"], {}).get("glow", "120,120,120")
    ca = TEAMS.get(a["team"], {}).get("color", "#888")
    ch = TEAMS.get(h["team"], {}).get("color", "#888")
    return f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>
{CSS_BASE}
  body {{ width:1080px; height:1250px; color:#f2f5ff; overflow:hidden; position:relative;
         font-family:"Yu Gothic","Hiragino Sans","Noto Sans CJK JP",sans-serif;
         background:
           conic-gradient(from 200deg at 50% -20%, transparent 0 40%, rgba({ga},.16) 43%, transparent 46%,
                          rgba(255,211,77,.10) 49%, transparent 52%, rgba({gh},.16) 56%, transparent 60%),
           radial-gradient(1000px 560px at 8% -8%, rgba({ga},.5), transparent 55%),
           radial-gradient(1000px 560px at 92% -8%, rgba({gh},.5), transparent 55%),
           radial-gradient(1300px 720px at 50% 118%, rgba(255,187,32,.2), transparent 62%),
           repeating-linear-gradient(115deg, rgba(255,255,255,.03) 0 2px, transparent 2px 9px),
           linear-gradient(180deg,#0a0f22,#060913); }}
  body::after {{ content:""; position:absolute; inset:0; pointer-events:none;
    background:
      radial-gradient(circle at 6% 22%, rgba(255,255,255,.5) 0 2px, transparent 3px),
      radial-gradient(circle at 12% 60%, rgba(255,255,255,.35) 0 1.6px, transparent 2.6px),
      radial-gradient(circle at 90% 30%, rgba(255,255,255,.4) 0 2px, transparent 3px),
      radial-gradient(circle at 96% 64%, rgba(255,255,255,.3) 0 1.4px, transparent 2.4px),
      radial-gradient(circle at 50% 8%, rgba(255,255,255,.35) 0 1.6px, transparent 2.6px); }}
  .seamL {{ position:absolute; left:-260px; top:170px; transform:rotate(12deg); }}
  .seamR {{ position:absolute; right:-620px; top:560px; transform:scaleX(-1) rotate(12deg); }}
  .wrap {{ padding:24px 36px 0; position:relative; }}
  .head {{ display:flex; align-items:center; gap:18px; position:relative; }}
  .titlebox {{ position:relative; transform:skewX(-7deg); background:linear-gradient(100deg,#ffd34d,#ff9d2e);
              border-radius:8px; padding:8px 30px 10px 24px; box-shadow:0 10px 34px rgba(255,157,46,.45);
              clip-path:polygon(0 0, 100% 0, 96% 100%, 0 100%); }}
  .titlebox::before {{ content:""; position:absolute; inset:0;
     background:repeating-linear-gradient(-45deg, transparent 0 16px, rgba(255,255,255,.22) 16px 22px); }}
  h1 {{ font-size:46px; font-weight:900; letter-spacing:5px; color:#131313; position:relative;
       text-shadow:2px 2px 0 rgba(255,255,255,.55); }}
  .hsub {{ color:#a8b7dd; font-size:14.5px; font-weight:800; margin-top:8px; letter-spacing:1px; }}
  .chip {{ margin-left:auto; text-align:right; background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.18);
          border-radius:16px; padding:10px 18px; font-size:15.5px; font-weight:900; color:#eaf0ff; }}
  .beta {{ display:inline-block; background:#ffd34d; color:#131313; border-radius:99px; font-size:11.5px;
          font-weight:900; padding:2px 12px; margin-top:6px; }}
  .cols {{ display:flex; gap:22px; margin-top:18px; position:relative; }}
  .panel {{ flex:1; border-radius:20px; padding:18px 18px 16px; position:relative;
           background:linear-gradient(180deg, rgba(20,27,52,.92), rgba(13,18,38,.92));
           border:1.5px solid rgba(var(--tg), .55);
           box-shadow:0 0 40px rgba(var(--tg), .3), 0 18px 44px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.1); }}
  .ribbon {{ background:linear-gradient(100deg, var(--tc), rgba(var(--tg),.65)); position:relative; }}
  .ribbon::after {{ content:""; position:absolute; inset:0;
     background:repeating-linear-gradient(-55deg, transparent 0 22px, rgba(255,255,255,.12) 22px 30px); }}
  .phdr {{ color:#7286b3; border-bottom:1.5px solid rgba(255,255,255,.12); }}
  .prow.hot {{ background:linear-gradient(90deg, rgba(255,211,77,.14), transparent 70%);
              border-left:3px solid #ffd34d; }}
  .slot {{ background:linear-gradient(160deg, var(--tc), rgba(var(--tg),.5)); color:#fff;
          text-shadow:0 1px 4px rgba(0,0,0,.5); }}
  .pn {{ color:#fff; }}
  .hand.l {{ background:rgba(88,166,255,.2); color:#82bbff; }}
  .hand.r {{ background:rgba(255,120,120,.18); color:#ff9d9d; }}
  .hand.s {{ background:rgba(196,140,255,.2); color:#d3a8ff; }}
  .pbar {{ background:rgba(255,255,255,.08); box-shadow:inset 0 1px 3px rgba(0,0,0,.5); }}
  .pv {{ color:#eaf0ff; }}
  .badge.ok {{ background:rgba(46,229,132,.16); color:#2ee584; border:1px solid #2ee58466; }}
  .badge.amber {{ background:rgba(255,196,66,.16); color:#ffc442; border:1px solid #ffc44266; }}
  .lstep {{ background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.14); }}
  .lstep.gold {{ background:linear-gradient(110deg,#8a6a12,#c9a53a 30%,#8a6a12 55%,#e0bc55 80%,#9a7a1e);
               border:1.5px solid #ffd34d; box-shadow:0 0 26px rgba(255,211,77,.4); }}
  .lstep.gold .lk {{ color:#fff3cf; }} .lstep.gold .lv {{ color:#fff; text-shadow:0 1px 6px rgba(0,0,0,.4); }}
  .lstep.gold .lg2 {{ color:#c9ffdf; }} .lstep.gold .lin {{ color:#fff3cf; }}
  .lv {{ color:#fff; }} .lk {{ color:#9fb0d6; }}
  .vs {{ margin-top:18px; border-radius:20px; padding:16px 22px; position:relative; overflow:hidden;
        background:linear-gradient(180deg, rgba(20,27,52,.92), rgba(13,18,38,.92));
        border:1px solid rgba(255,255,255,.14); box-shadow:0 14px 40px rgba(0,0,0,.45); }}
  .rays {{ position:absolute; inset:-40%; pointer-events:none; opacity:.5;
    background:conic-gradient(from 0deg at 50% 50%,
      transparent 0 14deg, rgba(255,211,77,.08) 14deg 18deg, transparent 18deg 32deg,
      rgba({ga},.09) 32deg 36deg, transparent 36deg 50deg, rgba({gh},.09) 50deg 54deg,
      transparent 54deg 68deg, rgba(255,211,77,.08) 68deg 72deg, transparent 72deg 90deg); }}
  .vssub {{ margin-top:9px; color:#aebada; font-size:14px; font-weight:800; text-align:center; position:relative; }}
  .vssub b {{ color:#ffd34d; }}
  .note {{ margin-top:13px; border-radius:14px; padding:9px 16px; background:rgba(255,255,255,.05);
          color:#7286b3; font-size:11.5px; font-weight:700; line-height:1.6; position:relative; }}
  .foot {{ margin-top:7px; text-align:center; color:#5d6c94; font-size:12.5px; font-weight:800; letter-spacing:1px; }}
</style></head><body>
<div class="seamL">{seam_svg(f"rgb({ga})", ".18")}</div>
<div class="seamR">{seam_svg(f"rgb({gh})", ".18")}</div>
<div class="wrap">
  <div class="head">
    <div><div class="titlebox"><h1>⚡ 打順診断</h1></div>
      <div class="hsub">その日のスタメンで「何点取れる並びか」をデータで検証</div></div>
    <div class="chip">{date}&nbsp;&nbsp;◉ {venue}<br><span class="beta">β 試験運用</span></div>
  </div>
  <div class="cols">{panel(res[0], "c")}{panel(res[1], "c")}</div>
  {versus(res, "c")}
  <div class="note">得点期待値=9イニング・中立環境換算(相手投手の質は含みません)。ベストメンバーは同ポジション群内の
  入替のみの参考値・守備力/休養/疲労は考慮外。僅差は誤差の範囲です。</div>
  <div class="foot">@saihaiscore_lab(β試験運用)| 計算方法はnoteで全公開 | データ: NPB公式記録より自動集計</div>
</div>
</body></html>'''


def html_d(res, date, venue):
    a, h = res
    ca = TEAMS.get(a["team"], {}).get("color", "#888")
    ch = TEAMS.get(h["team"], {}).get("color", "#888")
    ga = TEAMS.get(a["team"], {}).get("glow", "120,120,120")
    gh = TEAMS.get(h["team"], {}).get("glow", "120,120,120")
    return f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>
{CSS_BASE}
  body {{ width:1080px; height:1250px; color:#1c2340; overflow:hidden; position:relative;
         font-family:"Yu Gothic","Hiragino Sans","Noto Sans CJK JP",sans-serif;
         background:
           radial-gradient(circle at 7% 12%, {ca}33 0 90px, transparent 91px),
           radial-gradient(circle at 94% 16%, {ch}33 0 110px, transparent 111px),
           radial-gradient(circle at 88% 88%, {ca}26 0 80px, transparent 81px),
           radial-gradient(circle at 10% 84%, {ch}26 0 95px, transparent 96px),
           linear-gradient(160deg, #fff6df 0%, #ffe9ee 30%, #e8f4ff 65%, #f3ecff 100%); }}
  body::before {{ content:""; position:absolute; inset:0; pointer-events:none; opacity:.55;
    background-image:
      radial-gradient(circle, {ca}55 0 3px, transparent 4px),
      radial-gradient(circle, {ch}55 0 3px, transparent 4px),
      radial-gradient(circle, #ffd34d88 0 2.5px, transparent 3.5px);
    background-size: 90px 120px, 110px 140px, 70px 100px;
    background-position: 0 0, 40px 60px, 20px 30px; }}
  body::after {{ content:""; position:absolute; inset:0; pointer-events:none;
    background:repeating-linear-gradient(125deg, transparent 0 60px, rgba(255,255,255,.5) 60px 62px); }}
  .wrap {{ padding:24px 36px 0; position:relative; z-index:2; }}
  .head {{ display:flex; align-items:center; gap:18px; }}
  .titlebox {{ position:relative; transform:rotate(-2deg); background:#1c2340; border-radius:14px;
              padding:10px 30px; box-shadow:8px 8px 0 #ffd34d, 0 16px 40px rgba(28,35,64,.3); }}
  h1 {{ font-size:44px; font-weight:900; letter-spacing:5px;
       background:linear-gradient(90deg,#ffd34d,#ff9d6c,#ff7ab8,#7ab9ff); -webkit-background-clip:text; color:transparent; }}
  .hsub {{ color:#525f8a; font-size:14.5px; font-weight:800; margin-top:10px; }}
  .chip {{ margin-left:auto; text-align:right; background:#fff; border:2.5px solid #1c2340; border-radius:16px;
          padding:10px 18px; font-size:15.5px; font-weight:900; color:#1c2340;
          box-shadow:5px 5px 0 rgba(28,35,64,.15); }}
  .beta {{ display:inline-block; background:#1c2340; color:#ffd34d; border-radius:99px; font-size:11.5px;
          font-weight:900; padding:2px 12px; margin-top:6px; }}
  .cols {{ display:flex; gap:24px; margin-top:18px; }}
  .panel {{ flex:1; border-radius:22px; padding:18px 18px 16px; background:#fff; position:relative;
           border:2.5px solid #1c2340; box-shadow:9px 9px 0 rgba(var(--tg), .5), 0 20px 46px rgba(28,35,64,.18); }}
  .ribbon {{ background:linear-gradient(100deg, var(--tc), rgba(var(--tg),.75)); border-radius:14px 14px 0 0; }}
  .ribbon::after {{ content:""; position:absolute; inset:0;
     background:repeating-linear-gradient(-55deg, transparent 0 20px, rgba(255,255,255,.17) 20px 28px); }}
  .phdr {{ color:#9fadcc; border-bottom:2px solid #eef1f8; }}
  .prow.hot {{ background:linear-gradient(90deg, #fff3c8, transparent 75%); border-left:4px solid #ffbe0b; }}
  .prow:nth-child(even) {{ }}
  .slot {{ background:linear-gradient(160deg, var(--tc), rgba(var(--tg),.65)); color:#fff; }}
  .pn {{ color:#1c2340; }}
  .hand.l {{ background:#e3efff; color:#2266cc; }}
  .hand.r {{ background:#ffe9e6; color:#cc4433; }}
  .hand.s {{ background:#f1e6ff; color:#7a3fc9; }}
  .pbar {{ background:#eef1f8; border:1px solid #dde4f2; }}
  .pfill {{ background:linear-gradient(90deg, var(--tc), rgba(var(--tg),.75)); }}
  .pv {{ color:#1c2340; }}
  .badge.ok {{ background:#dcf7e9; color:#0d9e55; border:1.5px solid #0d9e5544; }}
  .badge.amber {{ background:#fdf3d4; color:#9a7208; border:1.5px solid #9a720844; }}
  .lstep {{ background:#f5f7fc; border:2px solid #e3e9f5; }}
  .lstep.gold {{ background:linear-gradient(110deg,#ffe9a3,#fff7dd 40%,#ffd34d); border:2px solid #d9a514;
               box-shadow:4px 4px 0 rgba(217,165,20,.35); }}
  .lv {{ color:#1c2340; }} .lk {{ color:#66718c; }} .lin {{ color:#8a6a12; }}
  .vs {{ margin-top:18px; border-radius:22px; padding:16px 22px; background:#1c2340; position:relative;
        overflow:hidden; border:2.5px solid #1c2340; box-shadow:8px 8px 0 rgba(255,211,77,.7); }}
  .rays {{ position:absolute; inset:-45%; pointer-events:none; opacity:.75;
    background:conic-gradient(from 0deg at 50% 50%,
      transparent 0 12deg, rgba(255,255,255,.06) 12deg 17deg, transparent 17deg 30deg,
      rgba({ga},.14) 30deg 35deg, transparent 35deg 47deg, rgba({gh},.14) 47deg 52deg,
      transparent 52deg 64deg, rgba(255,211,77,.12) 64deg 69deg, transparent 69deg 84deg); }}
  .vst {{ color:#fff !important; }}
  .vssub {{ margin-top:9px; color:#c6d0ea; font-size:14px; font-weight:800; text-align:center; position:relative; }}
  .vssub b {{ color:#ffd34d; }}
  .note {{ margin-top:13px; border-radius:14px; padding:9px 16px; background:rgba(255,255,255,.75);
          border:1.5px solid #dde4f2; color:#525f8a; font-size:11.5px; font-weight:700; line-height:1.6; }}
  .foot {{ margin-top:7px; text-align:center; color:#525f8a; font-size:12.5px; font-weight:800; letter-spacing:1px; }}
</style></head><body>
<div class="wrap">
  <div class="head">
    <div><div class="titlebox"><h1>⚾ 打順診断</h1></div>
      <div class="hsub">その日のスタメンで「何点取れる並びか」をデータで検証</div></div>
    <div class="chip">{date}&nbsp;&nbsp;◉ {venue}<br><span class="beta">β 試験運用</span></div>
  </div>
  <div class="cols">{panel(res[0], "d")}{panel(res[1], "d")}</div>
  {versus(res, "d")}
  <div class="note">得点期待値=9イニング・中立環境換算(相手投手の質は含みません)。ベストメンバーは同ポジション群内の
  入替のみの参考値・守備力/休養/疲労は考慮外。僅差は誤差の範囲です。</div>
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
    for tag, fn in (("C", html_c), ("D", html_d)):
        hp = os.path.join(outdir, f"mock_v4{tag}_{gid}.html")
        open(hp, "w", encoding="utf-8").write(fn(res, date, venue))
        pp = hp.replace(".html", ".png")
        render(hp, pp, "1080,1250")
        print("png:", pp)


if __name__ == "__main__":
    main()
