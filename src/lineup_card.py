# -*- coding: utf-8 -*-
"""打順診断カード モックv1(2026-09-08・design-lineup-card.md v2の表示原則準拠)
- 実名は上げのみ/名前入り最適打順は出さない/三値判定(v0は統計ゲート前のため
  「最適域/並び替え余地」の2値+誤差注記)/構造の事実表示(出塁配置・左右並び)
Usage: python src/lineup_card.py 0905 c-g-19 [--png]
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_card2 import render, TEAMS, parse_meta  # noqa
from lineup_ev import analyze_lineup  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def medal(tm, size=52, fs=18):
    t = TEAMS.get(tm, {})
    col = t.get("color", "#888")
    mono = t.get("mono", tm[:1])
    return (f'<div style="width:{size}px;height:{size}px;border-radius:50%;flex:none;'
            f'background:radial-gradient(circle at 32% 28%, #ffffff, #eef2f9);'
            f'border:2.5px solid {col};color:{col};font-size:{fs}px;font-weight:900;'
            f'display:flex;align-items:center;justify-content:center;'
            f'box-shadow:0 0 14px {col}55">{mono}</div>')


def insights(r):
    ps = r["players"]
    out = []
    bats = [p["bats"] for p in ps]
    runL = mx = 0
    for b in bats:
        runL = runL + 1 if b == "左" else 0
        mx = max(mx, runL)
    if mx >= 3:
        out.append(("warn", f"左打者{mx}連続 ─ 終盤の左ワンポイントに要注意"))
    else:
        out.append(("good", "左右ジグザグ配置 ─ ワンポイント耐性◎"))
    field = [p for p in ps if "投" not in p["role"]]
    top_obp = sorted(field, key=lambda p: -p["obp"])[:3]
    avg_slot = sum(p["slot"] for p in top_obp) / 3
    if avg_slot <= 3.4:
        out.append(("good", f"出塁率上位3人を上位打順に集約(平均{avg_slot:.1f}番)"))
    else:
        out.append(("info", f"出塁率上位3人の平均打順は{avg_slot:.1f}番"))
    if r.get("fixed") is not None:
        out.append(("info", f"{r['fixed'] + 1}番投手(セ方式)"))
    return out


POSCHR = {"捕": "捕", "一": "一", "二": "二", "三": "三", "遊": "遊",
          "左": "左", "中": "中", "右": "右", "指": "DH", "投": "投"}


def pos_of(role):
    for ch in role or "":
        if ch in POSCHR:
            return POSCHR[ch]
    return ""


def team_panel(r, meta_side):
    t = TEAMS.get(r["team"], {})
    col = t.get("color", "#333")
    diff = r["diff"]
    if diff >= -0.05:
        badge = '<span class="badge ok">✓ ほぼ最適の並び</span>'
    else:
        badge = f'<span class="badge amber">並び替え余地 {diff:+.2f}点</span>'
    field = [p for p in r["players"] if "投" not in p["role"]]
    mx_solo = max(p["solo"] for p in field) or 1
    star_pid = max(field, key=lambda p: p["solo"])["pid"]
    rows = []
    for p in r["players"]:
        is_p = "投" in p["role"]
        w = max(4, p["solo"] / mx_solo * 100)
        bchip = {"左": "l", "右": "r", "両": "s"}.get(p["bats"], "r")
        star = '<span class="star">★</span>' if p["pid"] == star_pid else ""
        rows.append(f'''
      <div class="prow">
        <div class="slot">{p["slot"]}</div>
        <div class="pn">{p["name"]}{star}<span class="role">{pos_of(p["role"])}</span></div>
        <div class="hand {bchip}">{p["bats"]}</div>
        <div class="pbar"><div class="pfill" style="width:{w:.0f}%;background:linear-gradient(90deg,{col},{col}88)"></div></div>
        <div class="pv">{'―' if is_p else f'{p["solo"]:.1f}'}</div>
      </div>''')
    ins = "".join(f'<div class="ins {c}">{txt}</div>' for c, txt in insights(r))
    # EVラダー: 今日の並び → 並べ替え → ベストメンバー(同ポジ制約・IN選手のみ実名)
    ev_a, ev_b, ev_m = r["ev_actual"], r["ev_best"], r.get("ev_bestmem")
    steps = [f'<div class="lstep"><div class="lk">今日の並び</div><div class="lv">{ev_a:.2f}</div></div>',
             f'<div class="larr">→</div>',
             f'<div class="lstep"><div class="lk">並べ替え最適</div><div class="lv">{ev_b:.2f}'
             f'<span class="lg2">+{max(0.0, ev_b - ev_a):.2f}</span></div></div>']
    if ev_m:
        inn = "・".join(r.get("bestmem_in") or [])
        steps += [f'<div class="larr">→</div>',
                  f'<div class="lstep gold"><div class="lk">ベストメンバー</div><div class="lv">{ev_m:.2f}'
                  f'<span class="lg2">+{ev_m - ev_a:.2f}</span></div>'
                  f'<div class="lin">{inn} IN</div></div>']
    else:
        steps += [f'<div class="larr">→</div>',
                  f'<div class="lstep gold"><div class="lk">ベストメンバー</div>'
                  f'<div class="lv" style="font-size:15px;padding-top:6px">現メンバーがベスト</div></div>']
    ladder = f'<div class="ladder">{"".join(steps)}</div>'
    return f'''
  <div class="panel">
    <div class="phead">{medal(r["team"])}
      <div><div class="ptm" style="color:{col}">{r["team"]}</div>{badge}</div>
      <div class="pev"><div class="pevl">この並びの得点期待値</div>
        <div class="pevv">{r["ev_actual"]:.2f}<span class="unit">点/試合</span></div></div>
    </div>
    <div class="phdr"><span>打順</span><span style="margin-left:126px">左右</span><span style="margin-left:36px">打力(点/試合換算)</span></div>
    {"".join(rows)}
    {ladder}
    {ins}
  </div>'''


def versus(res):
    a, h = res[0], res[1]
    ca = TEAMS.get(a["team"], {}).get("color", "#4e8df5")
    ch = TEAMS.get(h["team"], {}).get("color", "#f5c518")
    tot = a["ev_actual"] + h["ev_actual"]
    fa = a["ev_actual"] / tot * 100 if tot else 50
    lead = a if a["ev_actual"] >= h["ev_actual"] else h
    gap = abs(a["ev_actual"] - h["ev_actual"])
    return f'''
  <div class="vs">
    <div class="vslbl">打線力バランス(この並び同士・中立環境)</div>
    <div class="vsrow">
      <div class="vst" style="color:{ca}">{a["team"]} {a["ev_actual"]:.2f}</div>
      <div class="vsbar">
        <div style="position:absolute;left:0;top:0;bottom:0;width:{fa:.1f}%;
             background:linear-gradient(90deg,{ca},{ca}99);box-shadow:0 0 12px {ca}66"></div>
        <div style="position:absolute;right:0;top:0;bottom:0;width:{100 - fa:.1f}%;
             background:linear-gradient(90deg,{ch}99,{ch});box-shadow:0 0 12px {ch}66"></div>
        <div class="vszero"></div>
      </div>
      <div class="vst" style="color:{ch};text-align:right">{h["ev_actual"]:.2f} {h["team"]}</div>
    </div>
    <div class="vssub">{lead["team"]}の並びが +{gap:.2f}点/試合 上回る</div>
  </div>'''


def build(mmdd, gid, png=False):
    res = analyze_lineup(mmdd, gid)
    if len(res) < 2:
        print("lineup解析不能")
        return
    try:
        meta = parse_meta(mmdd, gid)
        date, venue = meta["date"], meta["venue"]
    except Exception:
        date, venue = f"{int(mmdd[:2])}月{int(mmdd[2:])}日", ""
    html = f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1080px; height:1250px; color:#16213c; padding:0;
         font-family:"Yu Gothic","Hiragino Sans","Noto Sans CJK JP",sans-serif;
         background:
           radial-gradient(1100px 540px at 88% -8%, rgba(47,111,224,.13), transparent 60%),
           radial-gradient(900px 520px at -8% 108%, rgba(245,197,24,.13), transparent 60%),
           #eef1f7; }}
  .accent {{ height:7px; background:linear-gradient(90deg,#2f6fe0,#4fd8ff 35%,#f5c518 70%,#e0a90f); }}
  .wrap {{ padding:24px 38px 0; }}
  .head {{ display:flex; align-items:center; gap:18px; margin-bottom:16px; }}
  .logo {{ width:60px; height:60px; border-radius:15px; color:#fff; font-size:32px; font-weight:900;
          background:linear-gradient(135deg,#2f6fe0,#12408a);
          display:flex; align-items:center; justify-content:center;
          box-shadow:0 8px 22px rgba(47,111,224,.45); }}
  h1 {{ font-size:36px; font-weight:900; letter-spacing:3px; }}
  .hsub {{ color:#5d6a86; font-size:14.5px; font-weight:700; margin-top:2px; }}
  .chip {{ margin-left:auto; text-align:right; }}
  .period {{ background:#fff; border:1.5px solid #dde4f0; border-radius:12px; padding:8px 16px;
            font-size:15.5px; font-weight:900; color:#2c3a5c; box-shadow:0 4px 14px rgba(22,33,60,.06); }}
  .beta {{ display:inline-block; background:#fff; border:1.5px solid #1673c9; color:#1673c9;
          border-radius:99px; font-size:12px; font-weight:900; padding:2px 12px; margin-top:6px; }}
  .cols {{ display:flex; gap:20px; }}
  .panel {{ flex:1; background:rgba(255,255,255,.94); border-radius:20px; padding:18px 20px 14px;
           box-shadow:0 10px 28px rgba(22,33,60,.09); }}
  .phead {{ display:flex; gap:12px; align-items:center; margin-bottom:10px; }}
  .ptm {{ font-size:22px; font-weight:900; }}
  .badge {{ display:inline-block; border-radius:99px; font-size:12.5px; font-weight:900; padding:3px 12px; margin-top:4px; }}
  .badge.ok {{ background:rgba(13,158,85,.12); color:#0a7f45; }}
  .badge.amber {{ background:rgba(224,169,15,.15); color:#9a7208; }}
  .pev {{ margin-left:auto; text-align:right; }}
  .pevl {{ font-size:11.5px; font-weight:800; color:#66718c; letter-spacing:1px; }}
  .pevv {{ font-size:31px; font-weight:900; color:#1673c9; text-shadow:0 0 14px rgba(22,115,201,.35); line-height:1.15; }}
  .unit {{ font-size:13px; color:#5d6a86; margin-left:2px; }}
  .pevb {{ font-size:11.5px; font-weight:700; color:#9fadcc; }}
  .phdr {{ color:#9fadcc; font-size:11px; font-weight:800; letter-spacing:1px; border-bottom:1.5px solid #e6ebf4; padding-bottom:4px; }}
  .prow {{ display:flex; align-items:center; gap:8px; padding:8px 0; border-bottom:1px solid #f0f3f9; }}
  .slot {{ width:26px; height:26px; border-radius:8px; background:#f0f3f9; color:#46557a; flex:none;
          font-size:14px; font-weight:900; display:flex; align-items:center; justify-content:center; }}
  .pn {{ width:126px; flex:none; font-size:17.5px; font-weight:900; white-space:nowrap; }}
  .role {{ color:#9fadcc; font-size:11px; font-weight:800; margin-left:5px; }}
  .star {{ color:#e0a90f; font-size:13px; margin-left:2px; text-shadow:0 0 8px rgba(245,197,24,.8); }}
  .hand {{ width:26px; height:20px; border-radius:6px; flex:none; font-size:11.5px; font-weight:900;
          display:flex; align-items:center; justify-content:center; }}
  .hand.l {{ background:rgba(221,61,53,.1); color:#b8302a; }}
  .hand.r {{ background:rgba(22,115,201,.1); color:#1673c9; }}
  .hand.s {{ background:rgba(13,158,85,.1); color:#0a7f45; }}
  .pbar {{ flex:1; height:12px; background:#f0f3f9; border-radius:6px; overflow:hidden; }}
  .pfill {{ height:100%; border-radius:6px; box-shadow:0 0 8px rgba(22,33,60,.15); }}
  .pv {{ width:36px; flex:none; text-align:right; font-size:14px; font-weight:900; color:#2c3a5c; }}
  .ladder {{ display:flex; align-items:stretch; gap:8px; margin:12px 0 4px; }}
  .lstep {{ flex:1; background:#f7f9fd; border:1.5px solid #e6ebf4; border-radius:12px;
           padding:8px 10px; text-align:center; }}
  .lstep.gold {{ background:rgba(245,197,24,.08); border-color:rgba(224,169,15,.5);
                box-shadow:0 0 14px rgba(245,197,24,.25); }}
  .lk {{ font-size:11px; font-weight:900; color:#66718c; letter-spacing:1px; }}
  .lv {{ font-size:22px; font-weight:900; color:#16213c; }}
  .lg2 {{ font-size:12px; font-weight:900; color:#0d9e55; margin-left:4px; }}
  .lin {{ font-size:11.5px; font-weight:900; color:#9a7208; margin-top:2px; }}
  .larr {{ align-self:center; color:#9fadcc; font-size:18px; font-weight:900; }}
  .ins {{ margin-top:7px; border-radius:10px; padding:7px 12px; font-size:13px; font-weight:800; }}
  .ins.good {{ background:rgba(13,158,85,.08); color:#0a7f45; }}
  .ins.warn {{ background:rgba(221,61,53,.08); color:#b8302a; }}
  .ins.info {{ background:rgba(22,115,201,.07); color:#2c5a9c; }}
  .bench {{ margin-top:8px; border-top:1.5px dashed #e6ebf4; padding-top:8px; color:#5d6a86;
           font-size:13.5px; font-weight:700; }}
  .bench b {{ color:#16213c; }}
  .vs {{ margin-top:18px; background:rgba(255,255,255,.94); border-radius:20px; padding:16px 24px;
        box-shadow:0 10px 28px rgba(22,33,60,.09); }}
  .vslbl {{ font-size:13px; font-weight:900; letter-spacing:2px; color:#66718c; margin-bottom:10px; }}
  .vsrow {{ display:flex; align-items:center; gap:14px; }}
  .vst {{ width:170px; flex:none; font-size:20px; font-weight:900; }}
  .vsbar {{ position:relative; flex:1; height:22px; border-radius:11px; overflow:hidden;
           background:#f0f3f9; }}
  .vszero {{ position:absolute; left:50%; top:0; bottom:0; width:2px; background:rgba(255,255,255,.85); }}
  .vssub {{ margin-top:8px; color:#5d6a86; font-size:13.5px; font-weight:800; text-align:center; }}
  .note {{ margin-top:14px; background:rgba(255,255,255,.72); border-radius:14px; padding:12px 18px;
          color:#5d6a86; font-size:12.5px; font-weight:700; line-height:1.7; }}
  .foot {{ margin-top:10px; text-align:center; color:#8b96ab; font-size:12.5px; font-weight:700; letter-spacing:1px; }}
</style></head><body>
<div class="accent"></div>
<div class="wrap">
  <div class="head">
    <div class="logo">采</div>
    <div><h1>打順診断</h1>
      <div class="hsub">その日のスタメンで「何点取れる並びか」をデータで検証</div></div>
    <div class="chip"><div class="period">{date}&nbsp;&nbsp;◉ {venue}</div><br><span class="beta">β 試験運用</span></div>
  </div>
  <div class="cols">{team_panel(res[0], "away")}{team_panel(res[1], "home")}</div>
  {versus(res)}
  <div class="note">得点期待値=9イニング・中立環境換算(相手投手の質は含みません)。打力=その打者9人が並んだ場合の
  点/試合換算。ベストメンバーは同ポジション群(捕手/内野/外野)内の入替のみの参考値で、守備力・休養・疲労は
  考慮していません。僅差は誤差の範囲です。計算方法はnoteで全公開。</div>
  <div class="foot">@saihaiscore_lab(β試験運用)| 計算方法はnoteで全公開 | データ: NPB公式記録より自動集計</div>
</div>
</body></html>'''
    outdir = os.path.join(BASE, "data", "out", mmdd)
    os.makedirs(outdir, exist_ok=True)
    hp = os.path.join(outdir, f"lineup_{gid}.html")
    open(hp, "w", encoding="utf-8").write(html)
    print("html:", hp)
    if png:
        pp = hp.replace(".html", ".png")
        render(hp, pp, "1080,1250")
        print("png:", pp)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], "--png" in sys.argv)
