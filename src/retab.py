# -*- coding: utf-8 -*-
"""当季NPB実測のRE表+得点確率表を全取得済み試合から集計(2026-09-03裁定: 借り物RE表の置換)
- re: その(塁,アウト)状態から回終了までの平均得点
- ps: 同・1点以上入る確率(終盤判定「7回以降2点差以内は得点確率」用)
方針: 1-8回のみ使用(9回以降はサヨナラ打ち切り・戦術歪みで censored のため除外=標準的作法)
出力: data/logs/retable.json {"<state>|<outs>": {"n", "re", "ps"}} state空は"-"
Usage: python src/retab.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import parse_game, re_of, iter_games  # noqa
from fetch import RAW  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGS = os.path.join(os.path.dirname(RAW), "logs")


def main():
    agg = {}  # key -> [n, sum_runs, n_scored]
    games = 0
    for mmdd, gid in iter_games():
        if True:  # 旧2重ループのインデント維持
            try:
                events, _ = parse_game(mmdd, gid)
            except Exception as e:
                print(f"skip {mmdd}/{gid}: {e}")
                continue
            games += 1
            # (回,表裏)ごとに末尾からの累積得点を付けて集計
            halves = {}
            for e in events:
                if e["type"] == "pa" and e["inning"] <= 8:
                    halves.setdefault((e["inning"], e["half"]), []).append(e)
            for pas in halves.values():
                future = 0
                fut = [0] * len(pas)
                for i in range(len(pas) - 1, -1, -1):
                    future += pas[i].get("runs", 0)
                    fut[i] = future
                for pa, f in zip(pas, fut):
                    key = f"{pa['runners'] or '-'}|{pa['outs']}"
                    a = agg.setdefault(key, [0, 0.0, 0, 0])
                    a[0] += 1
                    a[1] += f
                    a[2] += 1 if f >= 1 else 0
                    a[3] += 1 if f >= 2 else 0
    table = {k: {"n": n, "re": round(s / n, 4), "ps": round(c / n, 4), "ps2": round(c2 / n, 4)}
             for k, (n, s, c, c2) in sorted(agg.items())}
    out = os.path.join(LOGS, "retable.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"games": games, "note": "1-8回のみ・当季実測", "table": table}, f,
                  ensure_ascii=False, indent=1)
    print(f"games={games}  states={len(table)}  saved: {out}")
    print(f"{'状態':<8}{'n':>7}{'実測RE':>8}{'借り物RE':>9}{'得点確率':>9}")
    for st in ("-", "1", "2", "3", "12", "13", "23", "123"):
        for o in (0, 1, 2):
            t = table.get(f"{st}|{o}")
            if t:
                old = re_of("" if st == "-" else st, o)
                print(f"{o}死{st:<6}{t['n']:>7}{t['re']:>8.3f}{old:>9.3f}{t['ps']:>8.1%}")


if __name__ == "__main__":
    main()
