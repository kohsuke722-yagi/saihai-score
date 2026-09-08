# -*- coding: utf-8 -*-
"""守備起用実績DB(9/8社長指摘「スタメンは打力だけじゃない・丸は守備がきつい」への実装)
- 全試合のスタメン表から (チーム|選手) → {ポジション: {先発数, 最終先発日}} を構築
- ベストメンバー候補の適格性フィルタに使う(球団が実際にそのポジで使っている事実=観測可能な守備力の代理)
出力: data/logs/defense_starts.json
Usage: python src/defense_log.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import iter_games, parse_game  # noqa
from runners import parse_box_lineup  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

POS = "捕一二三遊左中右指投"


def pos_of(role):
    for ch in role or "":
        if ch in POS:
            return ch
    return None


def main():
    db = {}
    games = 0
    for mmdd, gid in iter_games():
        lu = parse_box_lineup(mmdd, gid)
        if not lu:
            continue
        try:
            events, _ = parse_game(mmdd, gid)
        except Exception:
            continue
        away = next((e["team"] for e in events if e.get("half") == "表"), None)
        home = next((e["team"] for e in events if e.get("half") == "裏"), None)
        if not away or not home:
            continue
        games += 1
        for tm, slots in ((away, lu[0]), (home, lu[1])):
            for s0, (role, nm) in slots.items():
                p = pos_of(role)
                if not p:
                    continue
                d = db.setdefault(f"{tm}|{nm}", {}).setdefault(p, {"n": 0, "last": "0000"})
                d["n"] += 1
                d["last"] = max(d["last"], mmdd)
    out = os.path.join(BASE, "data", "logs", "defense_starts.json")
    # 空上書きガード(9/8実害: raw無しのActionsランナーが空dictで上書き→ベストメンバー全滅)
    if not db and os.path.exists(out):
        try:
            old = json.load(open(out, encoding="utf-8"))
        except Exception:
            old = {}
        if old:
            print(f"WARN: 今回の集計が空(games={games})・既存{len(old)}件を保持して上書きしない")
            return
    json.dump(db, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"games={games} 選手×チーム={len(db)} saved: defense_starts.json")


if __name__ == "__main__":
    main()
