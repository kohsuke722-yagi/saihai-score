# -*- coding: utf-8 -*-
"""試合前スタメン発表→打順診断カード(9/8社長「今日から打順カードを上げたい」)
NPB公式はスタメン発表後、試合前でもbox.html(打順)とroster.html(ベンチ)を掲載する。
試合前ページに選手IDリンクが無いため、ロスター辞書(_HAND)でチーム内名前解決する。
Usage: python src/pregame_card.py 0908 [gid...] [--png] [--fetch]
       (gid省略で当日全試合・未発表はスキップ。--fetchで最新ページを再取得)
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runners import parse_box_lineup  # noqa
from stats import fetch_player, PITCHER_BAT  # noqa
from stats2 import batter_dist2  # noqa
from phase1 import (is_pitcher_bat, bench_roster, _HAND, _norm_name,  # noqa
                    TEAM_NAME2CODE, _FULL2SHORT_T)
from lineup_ev import analyze_team, game_ev  # noqa
from lineup_card import build_from_results  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CODE2NAME = {v: k for k, v in TEAM_NAME2CODE.items()}


def roster_ids(mmdd, gid):
    """試合前roster.htmlの選手リンクからチーム別 name→pid(box短縮名と同一表記・最良の解決源)"""
    path = os.path.join(BASE, "data", "raw", mmdd, gid, "roster.html")
    if not os.path.exists(path):
        return {}
    html = open(path, encoding="utf-8").read()
    heads = sorted((m.start(), short) for full, short in _FULL2SHORT_T.items()
                   for m in re.finditer(re.escape(full), html))
    out = {}
    for m in re.finditer(r'players/(\d+)\.html"[^>]*>([^<]+)<', html):
        tm = None
        for hpos, short in heads:
            if hpos < m.start():
                tm = short
        if tm:
            out.setdefault(tm, {})[_norm_name(m.group(2))] = m.group(1)
    return out


def resolve_pid_fallback(tc, nm):
    """ロスター辞書(_HAND)での名前解決(roster.htmlに無い場合の保険)。
    姓の完全一致優先→前方一致・チーム内限定。曖昧ならNone"""
    n0 = _norm_name(nm)
    exact = [p for p, d in _HAND.items() if d.get("team") == tc
             and (_norm_name(d.get("name", "")) == n0
                  or _norm_name(d.get("name", "")).split("　")[0] == n0)]
    if len(exact) == 1:
        return exact[0]
    hits = [p for p, d in _HAND.items()
            if d.get("team") == tc and _norm_name(d.get("name", "")).startswith(n0)]
    return hits[0] if len(hits) == 1 else None


def build_game(mmdd, gid, png=False):
    lu = parse_box_lineup(mmdd, gid)
    if not lu or len(lu) < 2:
        print(f"{gid}: スタメン未発表")
        return False
    home = CODE2NAME.get(gid.split("-")[0])
    away = CODE2NAME.get(gid.split("-")[1])
    if not home or not away:
        print(f"{gid}: チームコード不明")
        return False
    _, bench_bat = bench_roster(mmdd, gid)
    rids = roster_ids(mmdd, gid)
    res = []
    for tm, l in ((away, lu[0]), (home, lu[1])):
        tc = TEAM_NAME2CODE[tm]
        players, dists, fixed = [], [], None
        for s0 in range(9):
            role, nm = l.get(s0, ("", ""))
            pid = (rids.get(tm) or {}).get(_norm_name(nm)) or resolve_pid_fallback(tc, nm)
            if not pid:
                print(f"{gid}: ID解決失敗 {tm}「{nm}」→ この試合はスキップ")
                return False
            P = fetch_player(pid)
            if is_pitcher_bat(P) or "投" in (role or ""):
                d = dict(PITCHER_BAT)
                fixed = s0
            else:
                d = batter_dist2(pid, P, mmdd)
            obp = sum(d.get(k, 0.0) for k in ("BB", "HBP", "1B", "2B", "3B", "HR"))
            players.append({"slot": s0 + 1, "name": nm, "role": role, "pid": pid,
                            "bats": P.get("bats", "右"), "obp": round(obp, 3),
                            "solo": round(game_ev([d] * 9), 2)})
            dists.append(d)
        res.append(analyze_team(tm, mmdd, players, dists, fixed, bench_bat))
    for r in res:
        print(f"  {r['team']}: 実際 {r['ev_actual']:.2f} → 最適 {r['ev_best']:.2f} "
              f"(差 {r['diff']:+.2f})"
              + (f" → ベストメンバー {r['ev_bestmem']:.2f}" if r.get("ev_bestmem") else ""))
    build_from_results(res, mmdd, gid, png)
    return True


def main():
    mmdd = sys.argv[1]
    args = sys.argv[2:]
    png = "--png" in args
    gids = [a for a in args if not a.startswith("--")]
    if "--fetch" in args:
        from fetch import fetch_pbp
        fetch_pbp(mmdd)
    if not gids:
        from fetch import game_urls
        gids = [u.rstrip("/").split("/")[-1] for u in game_urls(mmdd)]
    ok = 0
    for gid in gids:
        print(f"── {gid}")
        try:
            ok += 1 if build_game(mmdd, gid, png) else 0
        except Exception as e:
            print(f"{gid}: ERROR {e}")
    print(f"カード生成 {ok}/{len(gids)}試合")


if __name__ == "__main__":
    main()
