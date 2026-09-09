# -*- coding: utf-8 -*-
"""終盤の代打ブレンド係数の実測(design-lineup-card §4・9/9フェーズ2)
w(スロット種別, イニング) = そのスロットの打席にスタメン以外が立っている確率
(代打+その後の守備固め等の残留込み=「今日の並びのEV」の反実仮想として正しい定義)。
- スロット推定: チーム別PA列は打順を巡回する(イベント列のインデックス%9)
- 投手スロット(セ)と野手スロット(打順位置別)で層別・延長は9回に折込
- 出力: data/logs/ph_blend.json(毎晩nightlyで再計測)
Usage: python src/ph_blend.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import iter_games, parse_game  # noqa
from runners import parse_box_lineup  # noqa
from phase1 import _norm_name  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build():
    # cnt[kind][inning][slot] = PA数, sub[...] = スタメン以外が立った数
    cnt = {"p": {}, "f": {}}
    sub = {"p": {}, "f": {}}
    games = 0
    for mmdd, gid in iter_games():
        try:
            lu = parse_box_lineup(mmdd, gid)
            events, _ = parse_game(mmdd, gid)
        except Exception:
            continue
        if not lu or len(lu) < 2 or not events:
            continue
        away = next((e["team"] for e in events if e.get("half") == "表"), None)
        home = next((e["team"] for e in events if e.get("half") == "裏"), None)
        if not away or not home:
            continue
        games += 1
        for tm, l in ((away, lu[0]), (home, lu[1])):
            starters = {s: _norm_name(l.get(s, ("", ""))[1]) for s in range(9)}
            roles = {s: (l.get(s, ("", ""))[0] or "") for s in range(9)}
            idx = 0
            for e in events:
                if e.get("type") != "pa" or e.get("team") != tm:
                    continue
                # 打席でない行の除外(phase1と同一・9/7監査#3: 盗塁/牽制等が巡回を壊す)
                res_row = e.get("result", "")
                bat = e.get("batter", "")
                if "振り逃げ" not in res_row and (
                        not bat or bat.startswith("（")
                        or any(k in res_row for k in
                               ("盗塁", "牽制", "暴投", "ワイルドピッチ",
                                "ボーク", "パスボール", "途中"))):
                    continue
                s = idx % 9
                idx += 1
                inn = int(e.get("inning", 1))
                if inn > 9:  # 延長は9回モデルの外(交代が濃く混ざるため除外)
                    continue
                kind = "p" if "投" in roles[s] else "f"
                key = s if kind == "f" else 0
                c = cnt[kind].setdefault(inn, {})
                c[key] = c.get(key, 0) + 1
                if _norm_name(bat) != starters[s]:
                    m = sub[kind].setdefault(inn, {})
                    m[key] = m.get(key, 0) + 1
    out = {"games": games, "pitcher": {}, "field": {}, "n_pitcher": {}, "n_field": {}}
    for inn in range(1, 10):
        c = sum(cnt["p"].get(inn, {}).values())
        s = sum(sub["p"].get(inn, {}).values())
        if c:
            out["pitcher"][str(inn)] = round(s / c, 4)
            out["n_pitcher"][str(inn)] = c
    for slot in range(9):
        row, nrow = {}, {}
        for inn in range(1, 10):
            c = cnt["f"].get(inn, {}).get(slot, 0)
            s = sub["f"].get(inn, {}).get(slot, 0)
            if c:
                row[str(inn)] = round(s / c, 4)
                nrow[str(inn)] = c
        out["field"][str(slot)] = row
        out["n_field"][str(slot)] = nrow
    outp = os.path.join(BASE, "data", "logs", "ph_blend.json")
    json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"ph_blend: {games}試合から実測 → {outp}")
    print("投手スロットの非スタメン率:",
          {k: out["pitcher"][k] for k in sorted(out["pitcher"], key=int)})
    fs = {s: out["field"][s].get("9") for s in out["field"]}
    print("野手スロット9回の非スタメン率:", fs)
    return out


if __name__ == "__main__":
    build()
