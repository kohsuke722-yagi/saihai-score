# -*- coding: utf-8 -*-
"""バックテスト較正(plan-backtest.md B・2026-09-03): 半減期・縮小の全定数を予測誤差で決める
方式: 選手ごとに日付順ストリーミングで減衰サムを更新し、テスト期間(8/1以降)の各打席を
     「前日までのデータのみ」で予測(未来不参照が構造的に保証)。誤差=マルチクラス対数損失。
縮小2方式を比較: cap形 w=min(1,n/CAP) (現行) vs ディリクレ形 w=n/(n+K)
出力: data/logs/calib.json(stats2が起動時に読む)+較正曲線(予測出塁率10分位vs実測)
Usage: python src/backtest.py
"""
import json
import math
import os
import sys
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(BASE, "data", "logs")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLS = ("BB", "HBP", "K", "1B", "2B", "3B", "HR", "OUT")
FOLD = {"OUT_G": "OUT", "OUT_A": "OUT", "DP": "OUT"}
HALVES = (15.0, 30.0, 45.0, 60.0, 90.0, 100000.0)
CAPS = (60.0, 120.0, 240.0)          # cap形: w=min(1, n/CAP)
KS = (30.0, 60.0, 120.0, 240.0)      # ディリクレ形: w=n/(n+K)
TEST_START = "0801"
ONB = ("BB", "HBP", "1B", "2B", "3B", "HR")


def d_ord(mmdd):
    return datetime.date(2026, int(mmdd[:2]), int(mmdd[2:])).toordinal()


def run_side(log, label):
    # リーグ分布
    lg = {k: 0 for k in CLS}
    for rows in log.values():
        for r in rows:
            c = FOLD.get(r[1], r[1])
            if c in lg:
                lg[c] += 1
    tot = sum(lg.values())
    L = {k: v / tot for k, v in lg.items()}
    t0 = d_ord(TEST_START)

    res = {}  # (half, form, param) -> [sum_ll, n]
    curve = None  # 最良組合せ用は後で再走査
    for half in HALVES:
        acc = {("cap", c): [0.0, 0] for c in CAPS}
        acc.update({("dir", k): [0.0, 0] for k in KS})
        for pid, rows in log.items():
            byd = {}
            for r in rows:
                c = FOLD.get(r[1], r[1])
                if c in lg:
                    byd.setdefault(r[0], []).append(c)
            S = {k: 0.0 for k in CLS}
            W = 0.0
            last = None
            for d in sorted(byd, key=d_ord):
                od = d_ord(d)
                if last is not None:
                    f = 0.5 ** ((od - last) / half)
                    W *= f
                    for k in CLS:
                        S[k] *= f
                last = od
                if od >= t0 and W >= 0:
                    for (form, prm), a in acc.items():
                        if form == "cap":
                            w = min(1.0, W / prm)
                        else:
                            w = W / (W + prm)
                        for c in byd[d]:
                            p = w * (S[c] / W if W > 0 else 0.0) + (1 - w) * L[c]
                            a[0] += -math.log(max(p, 1e-9))
                            a[1] += 1
                for c in byd[d]:
                    S[c] += 1.0
                    W += 1.0
        for key, a in acc.items():
            res[(half,) + key] = a[0] / a[1] if a[1] else 9.9
    best = min(res, key=res.get)
    print(f"── {label}: テスト打席={next(iter([0])) or ''}{[a for a in [1]] and ''}")
    tbl = sorted(res.items(), key=lambda kv: kv[1])[:6]
    for (h, form, prm), ll in tbl:
        hh = "なし" if h > 9999 else f"{h:.0f}日"
        print(f"  半減期{hh:>5} {form}{prm:.0f}: logloss {ll:.5f}")
    bh, bform, bprm = best
    print(f"  → 最良: 半減期{'なし' if bh > 9999 else str(int(bh)) + '日'} {bform} {bprm:.0f}")

    # 較正曲線(最良組合せ・予測出塁率10分位)
    dec = [[0.0, 0.0, 0] for _ in range(10)]
    for pid, rows in log.items():
        byd = {}
        for r in rows:
            c = FOLD.get(r[1], r[1])
            if c in lg:
                byd.setdefault(r[0], []).append(c)
        S = {k: 0.0 for k in CLS}
        W = 0.0
        last = None
        for d in sorted(byd, key=d_ord):
            od = d_ord(d)
            if last is not None:
                f = 0.5 ** ((od - last) / bh)
                W *= f
                for k in CLS:
                    S[k] *= f
            last = od
            if od >= t0:
                w = min(1.0, W / bprm) if bform == "cap" else W / (W + bprm)
                p_ob = sum(w * (S[c] / W if W > 0 else 0.0) + (1 - w) * L[c] for c in ONB)
                i = min(9, int(p_ob * 25))  # だいたい.20-.60に分布するので25倍で分位化
                for c in byd[d]:
                    dec[i][0] += p_ob
                    dec[i][1] += 1 if c in ONB else 0
                    dec[i][2] += 1
            for c in byd[d]:
                S[c] += 1.0
                W += 1.0
    print("  較正曲線(予測出塁率帯: 予測平均 vs 実測):")
    for i, (sp, so, n) in enumerate(dec):
        if n >= 200:
            print(f"    帯{i}: 予測{sp / n:.3f} 実測{so / n:.3f} (n={n})")
    return {"halflife": bh, "form": bform, "param": bprm,
            "logloss": round(res[best], 5),
            "table": {f"{int(h)}|{f2}|{int(p)}": round(v, 5) for (h, f2, p), v in res.items()}}


def main():
    blog = json.load(open(os.path.join(LOGS, "batters.json"), encoding="utf-8"))
    plog = json.load(open(os.path.join(LOGS, "pitchers.json"), encoding="utf-8"))
    out = {"bat": run_side(blog, "打者(自分の打席結果を予測)"),
           "pit": run_side(plog, "投手(被打結果を予測)")}
    with open(os.path.join(LOGS, "calib.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved: calib.json")


if __name__ == "__main__":
    main()
