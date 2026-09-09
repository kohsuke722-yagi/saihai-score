# -*- coding: utf-8 -*-
"""2025事前分布の構築(§7-c 4・9/9フェーズ4): 2025全季イベントから打者クラス分布を集計。
今季PA僅少の選手の縮小先を「リーグ平均」から「環境正規化した前季の本人+リーグ」へ改善する。
出力: data/logs/batters2025.json = {"league": 分布, "players": {pid: {"n": PA数, "d": 分布}}}
(静的データ=一度ビルドしてコミット。利用側=stats2.batter_dist2がシーズン跨ぎ減衰で混合)
Usage: python src/prior2025.py
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from palog import classify  # noqa
from stats2 import CLS, FOLD  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NONBAT = ("盗塁", "牽制", "暴投", "ワイルドピッチ", "ボーク", "パスボール", "途中")


def main():
    cnt = {}
    lg = {k: 0 for k in CLS}
    games = 0
    for f in glob.glob(os.path.join(BASE, "data", "events2025", "*", "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        events = d.get("events") or []
        ids, ids2 = d.get("ids") or {}, d.get("ids2") or {}
        if not events:
            continue
        games += 1
        for e in events:
            if e.get("type") != "pa":
                continue
            res = e.get("result", "")
            bat = e.get("batter", "")
            if "振り逃げ" not in res and (
                    not bat or bat.startswith("（")
                    or any(k in res for k in NONBAT)):
                continue
            cls = classify(res)
            cls = FOLD.get(cls, cls)
            if cls in (None, "?", "SH", "IBB") or cls not in lg:
                continue
            nm = bat.replace("代打・", "").strip()
            pid = (ids2.get(e.get("team")) or {}).get(nm) or ids.get(nm)
            if not pid:
                continue
            c = cnt.setdefault(pid, {k: 0 for k in CLS})
            c[cls] += 1
            lg[cls] += 1
    tot = sum(lg.values())
    out = {"league": {k: round(v / tot, 5) for k, v in lg.items()},
           "players": {}}
    for pid, c in cnt.items():
        n = sum(c.values())
        if n < 30:  # 事前分布として意味のあるサンプルのみ
            continue
        out["players"][pid] = {"n": n, "d": {k: round(v / n, 5) for k, v in c.items()}}
    outp = os.path.join(BASE, "data", "logs", "batters2025.json")
    json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"2025: {games}試合 打者{len(cnt)}人(30PA以上{len(out['players'])}人) → {outp}")
    print("2025リーグ分布:", out["league"])


if __name__ == "__main__":
    main()
