# -*- coding: utf-8 -*-
"""結果文の全種類を分類器に通して集計(分類器の穴を探す)"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import parse_game
from palog import classify

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "raw")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

cnt = collections.Counter()
samples = {}
for mmdd in sorted(os.listdir(RAW)):
    day = os.path.join(RAW, mmdd)
    if not os.path.isdir(day):
        continue
    for gid in os.listdir(day):
        if not os.path.exists(os.path.join(day, gid, "playbyplay.html")):
            continue
        try:
            events, _ = parse_game(mmdd, gid)
        except Exception:
            continue
        for e in events:
            if e["type"] != "pa":
                continue
            c = classify(e.get("result", ""))
            cnt[c] += 1
            samples.setdefault(c, collections.Counter())[e["result"][:30]] += 1

total = sum(v for k, v in cnt.items() if k)
print("クラス分布:", dict(cnt))
for c in ("?",):
    if c in samples:
        print(f"--- {c} 上位 ---")
        for s, n in samples[c].most_common(25):
            print(f"  {n:4d}  {s}")
# 各クラスの代表例(誤分類チェック)
for c in ("HR", "3B", "2B", "1B", "K", "BB", "HBP", "SH", "OUT"):
    if c in samples:
        print(f"--- {c} 例 ---")
        for s, n in samples[c].most_common(5):
            print(f"  {n:4d}  {s}")
