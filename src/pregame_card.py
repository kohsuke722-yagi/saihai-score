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
from lineup_ev import analyze_team, game_ev, make_adjuster  # noqa
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


def starters_today(mmdd):
    """予告先発ページから {チーム名: (pid, 表示名)}。ページの日付がmmddと一致する時のみ
    (夜間は翌日分に切り替わるため空を返す。セは相手打順の投手スロットからも取れる)"""
    import re as _re
    from fetch import get
    try:
        h = get("https://npb.jp/announcement/starter/")
    except Exception:
        return {}
    m = _re.search(r"<h4>(\d+)月(\d+)日の予告先発投手</h4>", h)
    if not m or f"{int(m.group(1)):02d}{int(m.group(2)):02d}" != mmdd:
        return {}
    out = {}
    for c, pid, nm in _re.findall(
            r'logo_(\w+)_m\.gif.*?players/(\d+)\.html">\s*<span>([^<]+)</span>', h, _re.S):
        tm = CODE2NAME.get(c)
        if tm:
            out[tm] = (pid, _norm_name(nm).replace("　", ""))
    return out


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
    st_page = starters_today(mmdd)

    def starter_of(tm, l):
        """そのチームの先発: セ=打順の投手スロット/パ=予告先発ページ"""
        for s0 in range(9):
            role, nm = l.get(s0, ("", ""))
            if "投" in (role or ""):
                pid = (rids.get(tm) or {}).get(_norm_name(nm)) \
                    or resolve_pid_fallback(TEAM_NAME2CODE[tm], nm)
                if pid:
                    return pid, nm
        return st_page.get(tm) or (None, "")
    stt = {away: starter_of(away, lu[0]), home: starter_of(home, lu[1])}
    res = []
    for tm, opp, l in ((away, home, lu[0]), (home, away, lu[1])):
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
        # 相手先発込み補正(§6 v1): 打力バー(solo)は素の実力・EVは対戦文脈込み
        adj, sp_name = None, ""
        opp_pid, opp_nm = stt.get(opp) or (None, "")
        if opp_pid:
            adj, sp_name, w_sp = make_adjuster(opp_pid, mmdd, name_hint=opp_nm)
            dists = [adj(d) for d in dists]
        r = analyze_team(tm, mmdd, players, dists, fixed, bench_bat, adj=adj)
        r["matchup"] = sp_name or None
        res.append(r)
    for r in res:
        print(f"  {r['team']}: 実際 {r['ev_actual']:.2f} → 最適 {r['ev_best']:.2f} "
              f"(差 {r['diff']:+.2f})"
              + (f" → ベストメンバー {r['ev_bestmem']:.2f}" if r.get("ev_bestmem") else ""))
    build_from_results(res, mmdd, gid, png)
    # Discord配達用の本文とJSON(cloud_pregame.pyが読む)
    import json
    outdir = os.path.join(BASE, "data", "out", mmdd)
    json.dump(res, open(os.path.join(outdir, f"lineup_{gid}.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        from build_card2 import parse_meta
        venue = parse_meta(mmdd, gid).get("venue", "")
    except Exception:
        venue = ""
    a, h = res
    lines = [f"⚾ スタメン発表|{a['team']} × {h['team']}"
             + (f"({venue})" if venue else ""),
             f"並びの得点期待値: {a['team']} {a['ev_actual']:.2f}"
             f" vs {h['team']} {h['ev_actual']:.2f}(9回換算・中立環境)"]
    for r in res:
        note = []
        if r["diff"] <= -0.05:
            note.append(f"並べ替え余地{-r['diff']:.2f}点")
        if r.get("ev_bestmem") and r["ev_bestmem"] - r["ev_actual"] >= 0.1:
            note.append(f"ベストメンバーなら+{r['ev_bestmem'] - r['ev_actual']:.2f}点"
                        f"({'・'.join(r['bestmem_in'])} IN)")
        if note:
            lines.append(f"・{r['team']}: {'/'.join(note)}")
    lines.append("※試験運用β・計算方法はnoteで公開")
    open(os.path.join(outdir, f"lineup_{gid}.txt"), "w",
         encoding="utf-8").write("\n".join(lines))
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
