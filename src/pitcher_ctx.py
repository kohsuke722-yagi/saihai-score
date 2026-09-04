# -*- coding: utf-8 -*-
"""投手の文脈補正の当季実測較正(⑨継投・2026-09-03)
- 巡目(TTO): 先発の被出塁率を1巡/2巡/3巡+で集計→オッズ比の乗数
- 連投: リリーフの被出塁率を 休養明け/連投(昨日投げた)/3連投+ で集計→乗数
- 出力: data/logs/pitcher_ctx.json {"tto":…, "rest":…, "appearances": pid→登板日list}
Usage: python src/pitcher_ctx.py
※ 球数カーブは毎日のスポナビ取得で実データが貯まり次第追加(9/3社長裁定: 過去分の大規模取得はしない)
"""
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(BASE, "data", "logs")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ONBASE = ("BB", "HBP", "1B", "2B", "3B", "HR")


def d_of(mmdd):
    return datetime.date(2026, int(mmdd[:2]), int(mmdd[2:]))


def rate(counts):
    ob, n = counts
    return ob / n if n else None


def odds_mult(bucket, base):
    rb, r0 = rate(bucket), rate(base)
    if rb is None or r0 in (None, 0.0, 1.0):
        return 1.0
    return (rb / (1 - rb)) / (r0 / (1 - r0))


def main():
    with open(os.path.join(LOGS, "pitchers.json"), encoding="utf-8") as f:
        pitchers = json.load(f)
    try:
        with open(os.path.join(LOGS, "handedness.json"), encoding="utf-8") as f:
            hand = json.load(f)
    except Exception:
        hand = {}
    # チーム→試合日(gid=home-away-NN から。raw∪イベントキャッシュ)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from analyze import iter_games, game_ids  # noqa
    team_dates = {}
    for mmdd, gid in iter_games():
        parts = gid.split("-")
        if len(parts) == 3:
            team_dates.setdefault(parts[0], set()).add(mmdd)
            team_dates.setdefault(parts[1], set()).add(mmdd)

    # 層別(同一投手内)集計: 「良い投手ほど3巡目まで投げる/連投させられる」選択バイアスを除去
    tto_p = {}    # pid -> {bucket: [ob, n]} 先発のみ
    rest_p = {}   # pid -> {bucket: [ob, n]} リリーフのみ
    cross_p = {}  # pid -> {in1/inx: [ob, n]} リリーフの回またぎ
    appearances = {}

    for pid, rows in pitchers.items():
        by_date = {}
        for mmdd, cls, inning, st, outs in rows:
            by_date.setdefault(mmdd, []).append((cls, inning))
        dates = sorted(by_date, key=d_of)
        appearances[pid] = dates
        for i, mmdd in enumerate(dates):
            clss = by_date[mmdd]
            is_starter = clss[0][1] == 1
            # 連投streak: 昨日から遡って連続登板日数
            streak = 0
            d = d_of(mmdd)
            prev = set(d_of(x) for x in dates[:i])
            while (d - datetime.timedelta(days=streak + 1)) in prev:
                streak += 1
            entry_inn = clss[0][1]
            for j, (cls, inn) in enumerate(clss):
                if cls == "SH":
                    continue
                ob = 1 if cls in ONBASE else 0
                if is_starter:
                    b = str(min(3, j // 9 + 1))
                    tto_p.setdefault(pid, {}).setdefault(b, [0, 0])
                    tto_p[pid][b][0] += ob
                    tto_p[pid][b][1] += 1
                else:
                    k = "fresh" if streak == 0 else ("r1" if streak == 1 else "r2")
                    rest_p.setdefault(pid, {}).setdefault(k, [0, 0])
                    rest_p[pid][k][0] += ob
                    rest_p[pid][k][1] += 1
                    # 回またぎ: 登板した回(in1) vs 2イニング目以降(inx)
                    cx = "in1" if inn == entry_inn else "inx"
                    cross_p.setdefault(pid, {}).setdefault(cx, [0, 0])
                    cross_p[pid][cx][0] += ob
                    cross_p[pid][cx][1] += 1

    def mh_or(strata, bucket, ref):
        """Mantel-Haenszel: 同一投手内で bucket vs ref のオッズ比を層別合成"""
        num = den = 0.0
        n_b = n_r = 0
        for d in strata.values():
            if bucket not in d or ref not in d:
                continue
            a, nb = d[bucket]
            c, nr = d[ref]
            n = nb + nr
            if n == 0:
                continue
            num += a * (nr - c) / n
            den += c * (nb - a) / n
            n_b += nb
            n_r += nr
        return (num / den if den else 1.0), n_b

    def pooled(strata, bucket):
        ob = n = 0
        for d in strata.values():
            if bucket in d:
                ob += d[bucket][0]
                n += d[bucket][1]
        return (ob / n if n else None), n

    out = {"tto": {}, "rest": {}, "appearances": appearances}
    print("巡目(先発・同一投手内MHオッズ比・基準=1巡):")
    for b in ("1", "2", "3"):
        m, nb = (1.0, pooled(tto_p, b)[1]) if b == "1" else mh_or(tto_p, b, "1")
        out["tto"][b] = round(m, 4)
        r, n = pooled(tto_p, b)
        print(f"  {b}巡{'+' if b == '3' else ''}: 被出塁{r:.3f} (n={n}) 乗数{m:.3f}")
    print("連投(リリーフ・同一投手内MHオッズ比・基準=休養明け):")
    for k, label in (("fresh", "休養明け"), ("r1", "連投"), ("r2", "3連投+")):
        m, nb = (1.0, pooled(rest_p, k)[1]) if k == "fresh" else mh_or(rest_p, k, "fresh")
        out["rest"][k] = round(m, 4)
        r, n = pooled(rest_p, k)
        print(f"  {label}: 被出塁{r:.3f} (n={n}) 乗数{m:.3f}")
    # ── 翌日可用性(リリーフ): 今日投げると明日(翌チーム試合日が連日の場合)投げる確率がどれだけ落ちるか
    # +リーグ平均リリーフ被打分布(起用価値の基準)
    avail = {}
    relief_avg = {}
    for pid, rows in pitchers.items():
        dates = appearances[pid]
        if not dates:
            continue
        first_inns = {}
        for mmdd, cls, inning, st, outs in rows:
            first_inns.setdefault(mmdd, inning)
        relief_days = {d for d in dates if first_inns[d] > 1}
        if len(relief_days) < len(dates) * 0.5:
            continue  # 主に先発の投手は除外
        for mmdd, cls, inning, st, outs in rows:
            if mmdd in relief_days and cls != "SH":
                k = cls if cls in ("BB", "HBP", "K", "1B", "2B", "3B", "HR") else "OUT"
                relief_avg[k] = relief_avg.get(k, 0) + 1
        # 主力リリーフ(登板15日+)に限定=使用頻度バイアスを抑えて「連投状況→翌日登板率」を測る
        if len(relief_days) < 15:
            continue
        tc = hand.get(pid, {}).get("team")
        tdates = sorted(team_dates.get(tc, ()), key=d_of) if tc else []
        pitched = set(dates)
        for i in range(len(tdates) - 1):
            d0, d1 = tdates[i], tdates[i + 1]
            if (d_of(d1) - d_of(d0)).days != 1:
                continue  # 連日の試合のみ(移動日を挟むと可用性の意味が変わる)
            # d0終了時点の連投数(d0含む・0=今日投げてない)
            s = 0
            while (d_of(d0) - datetime.timedelta(days=s)).strftime("%m%d") in pitched:
                s += 1
            b = str(min(2, s))
            avail.setdefault(b, [0, 0])
            avail[b][0] += 1 if d1 in pitched else 0
            avail[b][1] += 1
    tot_ra = sum(relief_avg.values())
    out["avail"] = {b: {"p": round(rate(v), 4), "n": v[1]} for b, v in sorted(avail.items())
                    if b in ("0", "1", "2")}
    out["relief_avg"] = {k: round(v / tot_ra, 5) for k, v in relief_avg.items()}
    out["team_dates"] = {tc: sorted(ds, key=d_of) for tc, ds in team_dates.items()}
    print("翌日登板率(主力リリーフ・連日試合・今日までの連投数別):")
    for b, label in (("0", "今日投げてない"), ("1", "今日1日目"), ("2", "今日で2連投+")):
        if b in out["avail"]:
            a = out["avail"][b]
            print(f"  {label}: {a['p']:.1%} (n={a['n']})")

    # ── 投手別の暴投率・盗塁許容(9/3社長指示): raw全試合を走査してマウンド上の投手に帰属 ──
    import re as _re  # noqa: F401 (下の走査で使用)
    from analyze import parse_game  # noqa
    wp_c, sb_c, pa_c = {}, {}, {}
    for mmdd, gid in iter_games():
        if True:  # 旧2重ループのインデント維持
            try:
                events, _ = parse_game(mmdd, gid)
            except Exception:
                continue
            ids = game_ids(mmdd, gid)
            away = next((e["team"] for e in events if e["half"] == "表"), None)
            home = next((e["team"] for e in events if e["half"] == "裏"), None)
            cur = {}
            for e in events:
                dfs = home if e["half"] == "表" else away
                if e["type"] == "pitching":
                    m = _re.search(r"先発投手[）)]?\s*(\S+)", e["text"]) or _re.search(r"→\s*(\S+)", e["text"])
                    if m:
                        cur[dfs] = ids.get(m.group(1))
                    continue
                if e["type"] != "pa" or not cur.get(dfs):
                    continue
                pid = cur[dfs]
                res = e.get("result", "")
                if "暴投" in res or "ワイルドピッチ" in res:
                    wp_c[pid] = wp_c.get(pid, 0) + 1
                elif "盗塁" in res:
                    a, s2 = sb_c.get(pid, (0, 0))
                    sb_c[pid] = (a + 1, s2 + (0 if ("盗塁死" in res or "盗塁刺" in res) else 1))
                else:
                    pa_c[pid] = pa_c.get(pid, 0) + 1
    tot_wp, tot_pa = sum(wp_c.values()), sum(pa_c.values())
    lg_wp = tot_wp / tot_pa
    K_WP = 200  # 縮小: 200打席でリーグ値と同重み
    out["wp_rate"] = {pid: round((wp_c.get(pid, 0) + K_WP * lg_wp) / (pa_c[pid] + K_WP), 5)
                      for pid in pa_c}
    out["wp_league"] = round(lg_wp, 5)
    out["sb_allow"] = {pid: {"att": a, "sb": s2, "pa": pa_c.get(pid, 0)}
                       for pid, (a, s2) in sb_c.items()}
    print(f"暴投率: リーグ{lg_wp:.4f}/打席(総{tot_wp}件) 投手別{len(out['wp_rate'])}人分を縮小推定で保存")
    print(f"盗塁許容: {len(sb_c)}投手分の企図/成功を保存(走力工事で走者側と合成予定)")

    m_cx, _ = mh_or(cross_p, "inx", "in1")
    r1_, n1_ = pooled(cross_p, "in1")
    rx_, nx_ = pooled(cross_p, "inx")
    out["cross"] = round(m_cx, 4)
    print(f"回またぎ(リリーフ・同一投手内MH・基準=登板回): 登板回{r1_:.3f}(n={n1_}) "
          f"またぎ{rx_:.3f}(n={nx_}) 乗数{m_cx:.3f}")
    # 乗数は基準カテゴリ比。分布は全打席混合なので、リーグ構成比で平均1に正規化
    for grp, strata in (("tto", tto_p), ("rest", rest_p)):
        ws = {b: pooled(strata, b)[1] for b in out[grp]}
        tot = sum(ws.values())
        mean = sum(out[grp][b] * ws[b] for b in ws) / tot if tot else 1.0
        for b in out[grp]:
            out[grp][b] = round(out[grp][b] / mean, 4)
    with open(os.path.join(LOGS, "pitcher_ctx.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("saved: pitcher_ctx.json")


if __name__ == "__main__":
    main()
