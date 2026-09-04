# -*- coding: utf-8 -*-
"""代打ペナルティの当季実測較正(9/3社長指摘「代打打率は入ってるのか」→入れる)
同一選手内で「代打打席の被出塁」vs「通常打席」をMHオッズ比合成(選手の質の差を除去)。
出力: data/logs/ph_calib.json {"mult": 代打時の出塁オッズ乗数} → phase1が代打分布に適用
Usage: python src/ph_calib.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import parse_game, iter_games  # noqa
from palog import classify  # noqa
from fetch import RAW  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ONB = ("BB", "HBP", "1B", "2B", "3B", "HR")


def main():
    P = {}  # name -> {"ph": [ob,n], "norm": [ob,n]}
    games = 0
    for mmdd, gid in iter_games():
        if True:  # 旧2重ループのインデント維持
            try:
                events, _ = parse_game(mmdd, gid)
            except Exception:
                continue
            games += 1
            for e in events:
                if e["type"] != "pa":
                    continue
                cls = classify(e.get("result", ""))
                if cls in (None, "?", "SH") or "敬遠" in e.get("result", ""):
                    continue  # 敬遠は打力と無関係の出塁(代打ほど敬遠されやすく水増しになる)
                is_ph = e["batter"].startswith("代打")
                nm = e["batter"].replace("代打・", "").strip()
                if nm.startswith("（"):
                    continue
                b = P.setdefault(nm, {"ph": [0, 0], "norm": [0, 0]})
                k = "ph" if is_ph else "norm"
                b[k][0] += 1 if cls in ONB else 0
                b[k][1] += 1

    num = den = 0.0
    ph_ob = ph_n = no_ob = no_n = 0
    for b in P.values():
        (a, nb), (c, nr) = b["ph"], b["norm"]
        if nb == 0 or nr == 0:
            continue
        n = nb + nr
        num += a * (nr - c) / n
        den += c * (nb - a) / n
        ph_ob += a
        ph_n += nb
        no_ob += c
        no_n += nr
    mult = num / den if den else 1.0
    print(f"games={games} 代打打席n={ph_n} 代打被出塁{ph_ob/ph_n:.3f} 通常{no_ob/no_n:.3f} "
          f"同一選手内オッズ比(代打ペナルティ乗数)={mult:.3f}")
    with open(os.path.join(RAW, "..", "logs", "ph_calib.json"), "w", encoding="utf-8") as f:
        json.dump({"mult": round(mult, 4), "n_ph": ph_n,
                   "rate_ph": round(ph_ob / ph_n, 4), "rate_norm": round(no_ob / no_n, 4)}, f)
    print("saved: ph_calib.json")


if __name__ == "__main__":
    main()
