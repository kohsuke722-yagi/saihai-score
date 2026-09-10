# -*- coding: utf-8 -*-
"""打順診断カード v3・華やか版(2026-09-08社長「カラフルで目を引く・ゴージャスではなく」)
- 表示原則は据え置き: 実名は上げのみ/名前入り最適打順は出さない/構造の事実表示
- デザイン: 鮮やかなマルチカラー背景+放射光+紙吹雪・チームカラーのリボン見出し・
  ダイヤ型打順・主砲行フレア・ポップなオフセット影(金の重厚系は不採用)
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


def insights(r):
    ps = r["players"]
    out = []
    if r.get("matchup"):
        out.append(("info", f"⚔ 本日の相手先発 {r['matchup']} 込みで換算 ─ 打者ごとの対左/対右実績も反映(残りは相手ブルペンの実測)"))
    elif "matchup" in r:
        out.append(("info", "相手先発 未反映(中立環境換算)"))
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
    if r.get("star_note"):
        out.append(("good", r["star_note"]))
    if r.get("pinch_ace"):
        out.append(("info", f"ベンチに代打の切り札: {r['pinch_ace']}(直近は守備起用なし・温存が合理的)"))
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


GUILTY_BADGE = True  # 9/10復帰: 通貨統一(λ追い縮小+2025事前分布をゲート原子へ)後の
# FP再検証=3/120=2.5%≤5%で余裕合格(巨人3/60・広島0/60・B200/MN20/dscale=1.0)。
# 経緯: 9/9夜ROE通貨で7.5%不合格→一時停止。掟: 通貨を変えたら余裕をもって再合格まで停止


def badge_of(r):
    """判定バッジ=P4統計ゲートの三値のみ(9/9フェーズ1配線)。
    v0固定閾値の「ほぼ最適」断定は廃止 — ゲート未実施なら断定しない(検定中)"""
    g = r.get("gate") or {}
    v = g.get("verdict")
    if v == "最適域":
        return '<span class="badge ok">✔ 最適域の並び</span>'
    if v == "有意な見逃し":
        if GUILTY_BADGE:
            return '<span class="badge amber">⚠ 並び替え余地(統計的に有意)</span>'
        return '<span class="badge gray">並び差は判定不能(検定較正中)</span>'
    if v == "判定不能":
        return '<span class="badge gray">並び差は判定不能(僅差)</span>'
    return '<span class="badge gray">⏳ 並び判定は検定中</span>'


def team_panel(r, side):
    t = TEAMS.get(r["team"], {})
    col, glow = t.get("color", "#333"), t.get("glow", "60,60,60")
    badge = badge_of(r)
    field = [p for p in r["players"] if "投" not in p["role"]]
    mx_solo = max(p["solo"] for p in field) or 1
    star_pid = max(field, key=lambda p: p["solo"])["pid"]
    rows = []
    for p in r["players"]:
        is_p = "投" in p["role"]
        w = max(4, p["solo"] / mx_solo * 100)
        bchip = {"左": "l", "右": "r", "両": "s"}.get(p["bats"], "r")
        star = '<span class="star">★</span>' if p["pid"] == star_pid else ""
        hot = " hot" if p["pid"] == star_pid else ""
        rows.append(f'''
      <div class="prow{hot}">
        <div class="slot">{p["slot"]}</div>
        <div class="pn">{p["name"]}{star}<span class="role">{pos_of(p["role"])}</span></div>
        <div class="hand {bchip}">{p["bats"]}</div>
        <div class="pbar"><div class="pfill" style="width:{w:.0f}%;
             background:linear-gradient(90deg,{col},rgba({glow},.55))"></div><div class="sheen"></div></div>
        <div class="pv">{'―' if is_p else f'{p["solo"]:.1f}'}</div>
      </div>''')
    ins = "".join(f'<div class="ins {c}">{txt}</div>' for c, txt in insights(r))
    # EVラダー: 今日の並び → 並べ替え → ベストメンバー(同ポジ群制約・IN選手のみ実名)
    # ラダー: 一番目立つ箱には常に「到達できるベストの数字」(9/8社長指摘の誤読解消)。
    # 空白が多い=しょぼい指摘→数字大型化・チーム色グラデ枠・矢印に+チップでリッチに
    ev_a, ev_b, ev_m = r["ev_actual"], r["ev_best"], r.get("ev_bestmem")

    def chain(d):
        chip = f'<span class="dchip">+{d:.2f}</span>' if d > 0.004 else ""
        return f'<div class="lchain">{chip}<span class="lar">▶</span></div>'
    # 常に2箱(9/8社長「2つの方が見やすい」): 右箱=到達ベスト。入替提案は添え書きに畳む
    steps = [f'<div class="lstep now"><div class="lk">今日の並び</div>'
             f'<div class="lv">{ev_a:.2f}<span class="unit2">点/試合</span></div>'
             f'<div class="lin">発表スタメンの得点期待値</div></div>']
    if ev_m:
        inn = "・".join(r.get("bestmem_in") or [])
        steps += [chain(ev_m - ev_a),
                  f'<div class="lstep best"><div class="lk">ベストメンバー(並べ替え込み)</div>'
                  f'<div class="lv">{ev_m:.2f}<span class="lg2">+{ev_m - ev_a:.2f}</span></div>'
                  f'<div class="lin">{inn} IN ─ 並べ替えのみなら{ev_b:.2f}</div></div>']
    else:
        steps += [chain(max(0.0, ev_b - ev_a)),
                  f'<div class="lstep best"><div class="lk">この9人のベスト</div>'
                  f'<div class="lv">{ev_b:.2f}<span class="lg2">+{max(0.0, ev_b - ev_a):.2f}</span></div>'
                  f'<div class="lin">並べ替えで到達 ─ メンバー入替の提案なし</div></div>']
    ladder = f'<div class="ladder">{"".join(steps)}</div>'
    rows_html = "".join(rows)
    return f'''
  <div class="panel" style="--tc:{col};--tg:{glow}">
    <div class="ribbon"><span class="rmono">{t.get("mono", "")}</span>
      <span class="rteam">{r["team"]}</span>{badge}
      <span class="rev">{ev_a:.2f}<small>点/試合</small></span></div>
    <div class="phdr"><span style="width:34px">打順</span><span style="width:146px"></span><span style="width:30px">左右</span><span style="flex:1;text-align:center">打力(点/試合換算)</span></div>
    {rows_html}
    {ladder}
    {ins}
  </div>'''


def versus(res):
    a, h = res
    ca = TEAMS.get(a["team"], {}).get("color", "#888")
    ch = TEAMS.get(h["team"], {}).get("color", "#888")
    tot = a["ev_actual"] + h["ev_actual"]
    fa = a["ev_actual"] / tot * 100 if tot else 50
    lead = a if a["ev_actual"] >= h["ev_actual"] else h
    gap = abs(a["ev_actual"] - h["ev_actual"])
    return f'''
  <div class="vs">
    <div class="vslbl">⚡ 打線力バランス({'今日の対戦条件込み' if a.get("matchup") and h.get("matchup") else 'この並び同士・中立環境'})</div>
    <div class="vsrow">
      <div class="vst" style="color:{ca}">{a["team"]} {a["ev_actual"]:.2f}</div>
      <div class="vsbar">
        <div style="position:absolute;left:0;top:0;bottom:0;width:{fa:.1f}%;
             background:linear-gradient(90deg,{ca},{ca}bb)"></div>
        <div style="position:absolute;right:0;top:0;bottom:0;width:{100 - fa:.1f}%;
             background:linear-gradient(90deg,{ch}bb,{ch})"></div>
        <div class="vsstripe"></div><div class="vszero"></div>
      </div>
      <div class="vst" style="color:{ch};text-align:right">{h["ev_actual"]:.2f} {h["team"]}</div>
    </div>
    <div class="vssub">{lead["team"]}の並びが <b>+{gap:.2f}点/試合</b> 上回る</div>
  </div>'''


def build(mmdd, gid, png=False):
    res = analyze_lineup(mmdd, gid)
    if len(res) < 2:
        print("lineup解析不能")
        return
    build_from_results(res, mmdd, gid, png)


def load_gate(mmdd, gid):
    """P4ゲート判定JSON: 試合前版({gid}.json=配達時の判定)を優先し、
    無ければ夜間本走版({gid}_final.json)。どちらも無ければ{}"""
    import json
    gdir = os.path.join(BASE, "data", "gates", mmdd)
    for fn in (f"{gid}.json", f"{gid}_final.json"):
        p = os.path.join(gdir, fn)
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                return {t["team"]: t for t in d.get("teams", [])}
            except Exception:
                pass
    return {}


def build_from_results(res, mmdd, gid, png=False):
    """結果dict列(先攻,後攻)からカード生成(試合前カード9/8対応で分離)"""
    gate = load_gate(mmdd, gid)
    for r in res:
        r.setdefault("gate", gate.get(r["team"]))
    try:
        meta = parse_meta(mmdd, gid)
        date, venue = meta["date"], meta["venue"]
    except Exception:
        date, venue = f"{int(mmdd[:2])}月{int(mmdd[2:])}日", ""
    ga = TEAMS.get(res[0]["team"], {}).get("glow", "41,183,255")
    gh = TEAMS.get(res[1]["team"], {}).get("glow", "255,183,3")
    ev_note = ("得点期待値=9イニング換算・本日の相手先発込み(打者ごとの対左/対右実績を縮小つきで反映・"
               "残りイニングは相手ブルペンの実測被打で想定)。" if all(r.get("matchup") for r in res) else
               "得点期待値=9イニング・中立環境換算(相手投手の質は含みません)。")
    if all(r.get("blend") for r in res):
        ev_note += ("終盤の交代文化込み(スタメン以外が打席に立つ確率をイニング×打順で実測しブレンド)・"
                    "盗塁と進塁打も実測値で反映。")
    html = f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1080px; height:1250px; color:#1c2340; overflow:hidden; position:relative;
         font-family:"Yu Gothic","Hiragino Sans","Noto Sans CJK JP",sans-serif;
         background:
           conic-gradient(from 178deg at 50% -14%, transparent 0 34%, rgba(255,255,255,.14) 37%,
             transparent 40%, rgba(255,255,255,.1) 45%, transparent 48%, rgba(255,255,255,.14) 53%,
             transparent 56%, rgba(255,255,255,.1) 61%, transparent 64%),
           radial-gradient(880px 620px at -4% 30%, rgba({ga},.55), transparent 62%),
           radial-gradient(880px 620px at 104% 30%, rgba({gh},.55), transparent 62%),
           linear-gradient(135deg, #29b7ff 0%, #6d5dff 34%, #ff5fa8 68%, #ffb703 100%); }}
  body::before {{ content:""; position:absolute; inset:0; pointer-events:none; opacity:.5;
    background-image:
      radial-gradient(circle, rgba(255,255,255,.85) 0 2.6px, transparent 3.6px),
      radial-gradient(circle, rgba(255,230,109,.8) 0 2.2px, transparent 3.2px),
      radial-gradient(circle, rgba(255,255,255,.55) 0 1.8px, transparent 2.8px);
    background-size: 130px 170px, 150px 190px, 90px 120px;
    background-position: 10px 20px, 70px 90px, 40px 50px; }}
  body::after {{ content:""; position:absolute; inset:0; pointer-events:none;
    background:
      radial-gradient(circle at 90% 6%, rgba(255,255,255,.22) 0 120px, transparent 121px),
      radial-gradient(circle at 4% 40%, rgba(255,255,255,.14) 0 90px, transparent 91px),
      radial-gradient(circle at 96% 78%, rgba(255,255,255,.12) 0 110px, transparent 111px); }}
  .accent {{ height:9px; background:linear-gradient(90deg,#00e5ff,#6d5dff,#ff5fa8,#ffd166,#06d6a0);
            position:relative; z-index:2; }}
  .wrap {{ padding:22px 34px 0; position:relative; z-index:2; }}
  .head {{ display:flex; align-items:center; gap:18px; margin-bottom:14px; }}
  .titlebox {{ transform:rotate(-1.6deg); background:#fff; border-radius:16px; padding:8px 26px 10px;
              box-shadow:7px 7px 0 rgba(28,35,64,.35), 0 14px 40px rgba(28,35,64,.25); position:relative; }}
  .titlebox::after {{ content:"✦"; position:absolute; right:-14px; top:-16px; font-size:30px; color:#fff;
              text-shadow:0 0 14px rgba(255,255,255,.95); }}
  h1 {{ font-size:44px; font-weight:900; letter-spacing:4px;
       background:linear-gradient(95deg,#1d9bf0,#6d5dff 40%,#ff2e88 75%,#ff8a00);
       -webkit-background-clip:text; color:transparent; }}
  .hsub {{ color:#fff; font-size:14.5px; font-weight:800; margin-top:9px; letter-spacing:1px;
          text-shadow:0 2px 10px rgba(28,35,64,.5); }}
  .chip {{ margin-left:auto; text-align:right; background:#fff; border-radius:16px; padding:10px 18px;
          font-size:15.5px; font-weight:900; color:#1c2340; box-shadow:6px 6px 0 rgba(28,35,64,.28); }}
  .beta {{ display:inline-block; background:linear-gradient(90deg,#ff5fa8,#ff8a00); color:#fff;
          border-radius:99px; font-size:11.5px; font-weight:900; padding:2px 12px; margin-top:6px; }}
  .cols {{ display:flex; gap:22px; }}
  .panel {{ flex:1; border-radius:22px; padding:0 16px 14px; background:#fff; position:relative;
           box-shadow:9px 9px 0 rgba(var(--tg), .55), 0 22px 50px rgba(28,35,64,.3); }}
  .ribbon {{ display:flex; align-items:center; gap:10px; padding:12px 16px; margin:0 -16px 8px;
            border-radius:22px 22px 0 0; position:relative; overflow:hidden;
            background:linear-gradient(100deg, var(--tc), rgba(var(--tg),.72)); }}
  .ribbon::after {{ content:""; position:absolute; inset:0;
     background:repeating-linear-gradient(-55deg, transparent 0 20px, rgba(255,255,255,.16) 20px 28px); }}
  .rmono {{ width:44px; height:44px; border-radius:50%; border:2.5px solid #fff; flex:none; z-index:1;
           font-size:14px; font-weight:900; color:#fff; display:flex; align-items:center;
           justify-content:center; background:rgba(255,255,255,.16); }}
  .rteam {{ font-size:24px; font-weight:900; color:#fff; letter-spacing:2px; z-index:1;
           text-shadow:0 2px 10px rgba(0,0,0,.3); }}
  .rev {{ margin-left:auto; font-size:34px; font-weight:900; color:#fff; font-style:italic; z-index:1;
         text-shadow:0 2px 12px rgba(0,0,0,.35); }}
  .rev small {{ font-size:12px; font-weight:800; margin-left:3px; font-style:normal; opacity:.9; }}
  .badge {{ display:inline-block; border-radius:99px; font-size:11.5px; font-weight:900;
           padding:3px 11px; z-index:1; }}
  .badge.ok {{ background:#fff; color:#0d9e55; }}
  .badge.amber {{ background:#fff; color:#c98a00; }}
  .badge.gray {{ background:rgba(255,255,255,.82); color:#5f6f99; }}
  .phdr {{ display:flex; gap:8px; color:#5f6f99; font-size:10.5px; font-weight:900; letter-spacing:1px;
          border-bottom:2px solid #e3e9f5; padding-bottom:4px; margin-bottom:2px; }}
  .prow {{ display:flex; align-items:center; gap:8px; padding:3.5px 4px; border-radius:10px; }}
  .prow.hot {{ background:linear-gradient(90deg,#fff3c8,transparent 75%); border-left:4px solid #ffbe0b; }}
  .slot {{ width:30px; height:30px; flex:none; font-size:15px; font-weight:900; color:#fff;
          display:flex; align-items:center; justify-content:center;
          clip-path:polygon(50% 0, 100% 50%, 50% 100%, 0 50%);
          background:linear-gradient(160deg, var(--tc), rgba(var(--tg),.6)); }}
  .pn {{ width:146px; flex:none; font-size:18.5px; font-weight:900; white-space:nowrap; color:#1c2340; }}
  .role {{ color:#6b7ba5; font-size:11px; font-weight:900; margin-left:5px; }}
  .star {{ color:#f5a300; font-size:13px; margin-left:2px; text-shadow:0 0 10px rgba(255,190,11,.9); }}
  .hand {{ width:26px; height:20px; border-radius:6px; flex:none; font-size:11.5px; font-weight:900;
          display:flex; align-items:center; justify-content:center; }}
  .hand.l {{ background:#e3efff; color:#2266cc; }}
  .hand.r {{ background:#ffe9e6; color:#cc4433; }}
  .hand.s {{ background:#f1e6ff; color:#7a3fc9; }}
  .pbar {{ flex:1; height:13px; border-radius:99px; background:#eef1f8; overflow:hidden; position:relative; }}
  .pfill {{ height:100%; border-radius:99px; }}
  .sheen {{ position:absolute; inset:0; border-radius:99px;
           background:repeating-linear-gradient(115deg, transparent 0 10px, rgba(255,255,255,.28) 10px 14px); }}
  .pv {{ width:36px; flex:none; text-align:right; font-size:14px; font-weight:900; color:#1c2340; }}
  .ladder {{ display:flex; gap:4px; margin-top:11px; align-items:stretch; }}
  .lstep {{ flex:1; border-radius:14px; padding:9px 13px; position:relative; overflow:hidden; }}
  .lstep.now {{ background:linear-gradient(135deg, rgba(var(--tg),.2), #f2f5fb 75%);
              border:2px solid rgba(var(--tg),.6); }}
  .lstep.now .lv {{ color:var(--tc); }}
  .lstep.now::after {{ content:""; position:absolute; right:-18px; top:-18px; width:64px; height:64px;
              border-radius:50%; background:rgba(var(--tg),.16); }}
  .lstep.mid {{ background:#f5f7fc; border:2px solid #e3e9f5; }}
  .lstep.best {{ background:linear-gradient(120deg,#ffd166,#ff9770); border:2px solid #ff7b54;
               box-shadow:4px 4px 0 rgba(255,123,84,.35); }}
  .lstep.best::after {{ content:""; position:absolute; inset:0;
     background:repeating-linear-gradient(-55deg, transparent 0 16px, rgba(255,255,255,.18) 16px 22px); }}
  .lstep.best .lk {{ color:#7c2d12; }} .lstep.best .lv {{ color:#4a1c06; }}
  .lstep.best .lg2 {{ color:#0b6e3a; }} .lstep.best .lin {{ color:#7c2d12; }}
  .lk {{ font-size:10.5px; font-weight:900; letter-spacing:1px; color:#3d4d78; }}
  .lv {{ font-size:27px; font-weight:900; color:#1c2340; font-style:italic; line-height:1.15;
        position:relative; z-index:1; }}
  .unit2 {{ font-size:11px; font-weight:800; font-style:normal; color:#5f6f99; margin-left:3px; }}
  .lg2 {{ font-size:12.5px; font-weight:900; color:#0d9e55; margin-left:5px; }}
  .lin {{ font-size:10.5px; font-weight:900; color:#54648e; margin-top:1px; position:relative; z-index:1; }}
  .ladder.l3 .lv {{ font-size:23px; }}
  .ladder.l3 .lstep {{ padding:8px 10px; }}
  .ladder.l3 .lchain {{ width:44px; }}
  .lchain {{ display:flex; flex-direction:column; align-items:center; justify-content:center;
            width:52px; flex:none; gap:2px; }}
  .dchip {{ background:#0d9e55; color:#fff; border-radius:99px; font-size:11.5px; font-weight:900;
           padding:1px 9px; box-shadow:0 3px 8px rgba(13,158,85,.45); }}
  .lar {{ color:#c3cce4; font-size:15px; font-weight:900; }}
  .ins {{ margin-top:6px; border-radius:10px; padding:6px 11px; font-size:12.5px; font-weight:800; }}
  .ins.good {{ background:#dcf7e9; color:#0b7a42; }}
  .ins.warn {{ background:#ffe8e0; color:#b4432a; }}
  .ins.info {{ background:#e8eefb; color:#3d5588; }}
  .vs {{ margin-top:16px; border-radius:20px; padding:14px 22px; background:#fff;
        box-shadow:8px 8px 0 rgba(28,35,64,.3), 0 18px 44px rgba(28,35,64,.25); }}
  .vslbl {{ font-size:12.5px; font-weight:900; letter-spacing:2px; color:#3d4d78; margin-bottom:8px; }}
  .vsrow {{ display:flex; align-items:center; gap:14px; }}
  .vst {{ width:170px; flex:none; font-size:20px; font-weight:900; }}
  .vsbar {{ flex:1; height:20px; border-radius:99px; position:relative; overflow:hidden; background:#eef1f8; }}
  .vsstripe {{ position:absolute; inset:0;
    background:repeating-linear-gradient(115deg, transparent 0 14px, rgba(255,255,255,.2) 14px 19px); }}
  .vszero {{ position:absolute; left:50%; top:-3px; bottom:-3px; width:3px; background:#fff;
            box-shadow:0 0 8px rgba(28,35,64,.4); }}
  .vssub {{ margin-top:8px; color:#39496f; font-size:13.5px; font-weight:800; text-align:center; }}
  .vssub b {{ color:#e0447a; }}
  .note {{ margin-top:12px; border-radius:14px; padding:9px 16px; background:rgba(255,255,255,.9);
          color:#3d4d78; font-size:11.5px; font-weight:700; line-height:1.65; }}
  .foot {{ margin-top:7px; text-align:center; color:#fff; font-size:12.5px; font-weight:800;
          letter-spacing:1px; text-shadow:0 2px 8px rgba(28,35,64,.55); }}
</style></head><body>
<div class="accent"></div>
<div class="wrap">
  <div class="head">
    <div><div class="titlebox"><h1>⚾ 打順診断</h1></div>
      <div class="hsub">その日のスタメンで「何点取れる並びか」をデータで検証</div></div>
    <div class="chip">{date}&nbsp;&nbsp;◉ {venue}<br><span class="beta">β 試験運用</span></div>
  </div>
  <div class="cols">{team_panel(res[0], "away")}{team_panel(res[1], "home")}</div>
  {versus(res)}
  <div class="note">{ev_note} 打力=その打者9人が並んだ場合の点/試合換算(素の実力・対戦補正なし)。
  ベストメンバーは同ポジション群内の入替+守備再配置の参考値で、守備力・休養・疲労は
  考慮していません(候補は減衰込み総合力と短期2週評価の両方で上回る場合のみ提案。▼▲=直近2週の実出塁との乖離)。
  並びの判定バッジは統計検定(ブートストラップ・偽陽性率5%以下に較正済み)の三値表示
  【最適域/判定不能/有意な並び替え余地】。僅差は誤差の範囲です。計算方法はnoteで全公開。</div>
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
