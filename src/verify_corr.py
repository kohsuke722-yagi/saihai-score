# -*- coding: utf-8 -*-
"""采配収支と勝敗の相関検証(9/3社長の疑問「良い采配側が勝ってるのは結果論では?」への答え)
decisionは未来不参照だが、相関自体はあるべき(弱く)。強すぎたら設計を疑うテスト。
Usage: python src/verify_corr.py [step]   # step=3なら3試合ごとにサンプル
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from phase1 import analyze_ph  # noqa
from build_card2 import parse_meta  # noqa
from fetch import RAW  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def game_nets(mmdd, gid):
    res = analyze_ph(mmdd, gid)
    nets = {}
    for r in res:
        if "error" in r or r.get("decision") is None:
            continue
        if r.get("kind") == "swing" and not r.get("counted"):
            continue
        team = r.get("def_team") if r.get("kind") in ("relief", "ibb") else r.get("team")
        v = r.get("decision_net", r["decision"]) if r.get("kind") == "relief" else r["decision"]
        nets[team] = nets.get(team, 0.0) + v
    return nets


def main():
    step = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    games = []
    for mmdd in sorted(os.listdir(RAW)):
        d = os.path.join(RAW, mmdd)
        if not (os.path.isdir(d) and mmdd.isdigit() and len(mmdd) == 4):
            continue
        for gid in sorted(os.listdir(d)):
            if os.path.exists(os.path.join(d, gid, "box.html")):
                games.append((mmdd, gid))
    games = games[::step]
    hi_win = decided = skipped = 0
    margin_w, margin_l = [], []
    for mmdd, gid in games:
        try:
            meta = parse_meta(mmdd, gid)
            nets = game_nets(mmdd, gid)
        except Exception:
            skipped += 1
            continue
        if meta["sc_away"] == meta["sc_home"]:
            continue
        winner = meta["away"] if meta["sc_away"] > meta["sc_home"] else meta["home"]
        loser = meta["home"] if winner == meta["away"] else meta["away"]
        nw, nl = nets.get(winner, 0.0), nets.get(loser, 0.0)
        if abs(nw - nl) < 1e-9:
            continue
        decided += 1
        if nw > nl:
            hi_win += 1
        margin_w.append(nw)
        margin_l.append(nl)
        if decided % 20 == 0:
            print(f"  ...{decided}試合 采配上位の勝率 {hi_win/decided:.1%}", flush=True)
    print(f"\n対象{decided}試合(スキップ{skipped}) 采配収支が上の側の勝率: {hi_win/decided:.1%}")
    print(f"勝者の平均収支 {sum(margin_w)/len(margin_w):+.3f} / 敗者 {sum(margin_l)/len(margin_l):+.3f}")
    print("目安: 50%=無関係(それも変) / 52-58%=健全な弱い相関 / 70%超=結果混入を疑うべき")


if __name__ == "__main__":
    main()
