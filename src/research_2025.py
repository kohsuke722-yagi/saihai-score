# -*- coding: utf-8 -*-
"""2025年シーズンの研究用取得・検証(9/7社長「夏の酷使を去年のデータで確認できない?」)
- 本体パイプライン(2026)とは完全分離: data/raw2025/ + data/events2025/ + pitchers2025.json
- playbyplayのみ取得(1.1s間隔の礼儀ウェイト)。rawは公開リポにコミットしない(gitignore済み領域)
Usage:
  python src/research_2025.py fetch     # 全季取得(~20分)
  python src/research_2025.py build     # 投手ログ構築
  python src/research_2025.py analyze   # 夏酷使→秋劣化のDiD+通算軸+負荷2軸の再現
"""
import datetime
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get, save, NPB  # noqa
import analyze  # noqa (RAW/EVDIRを2025用に差し替えて使う)
from palog import classify  # noqa

RAW25 = os.path.join(BASE, "data", "raw2025")
EV25 = os.path.join(BASE, "data", "events2025")
PLOG25 = os.path.join(BASE, "data", "logs", "pitchers2025.json")
analyze.RAW = RAW25
analyze.EVDIR = EV25

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ONBASE = ("BB", "HBP", "1B", "2B", "3B", "HR")


def d_of(m):
    return datetime.date(2025, int(m[:2]), int(m[2:]))


def fetch_all():
    games = []
    for mo in ("03", "04", "05", "06", "07", "08", "09", "10"):
        try:
            h = get(f"{NPB}/games/2025/schedule_{mo}_detail.html")
        except Exception as e:
            print(f"schedule {mo}: {e}")
            continue
        links = sorted(set(re.findall(r'href="(/scores/2025/(\d{4})/([a-z]+-[a-z]+-\d+))/?"', h)))
        games += [(mmdd, gid) for _, mmdd, gid in links]
        time.sleep(1.0)
    games = sorted(set(games))
    print(f"2025年: {len(games)}試合")
    done = 0
    for mmdd, gid in games:
        path = os.path.join(RAW25, mmdd, gid, "playbyplay.html")
        if os.path.exists(path):
            done += 1
            continue
        try:
            save(path, get(f"{NPB}/scores/2025/{mmdd}/{gid}/playbyplay.html"))
            done += 1
        except Exception as e:
            print(f"FAIL {mmdd}/{gid}: {e}", flush=True)
        if done % 50 == 0:
            print(f"{done}/{len(games)}", flush=True)
        time.sleep(1.1)
    print(f"fetch done: {done}/{len(games)}")


def iter25():
    for mmdd in sorted(os.listdir(RAW25)):
        day = os.path.join(RAW25, mmdd)
        if not os.path.isdir(day):
            continue
        for gid in sorted(os.listdir(day)):
            if os.path.exists(os.path.join(day, gid, "playbyplay.html")):
                yield mmdd, gid


def build():
    pitchers = {}
    n = fail = 0
    for mmdd, gid in iter25():
        try:
            events, _ = analyze.parse_game(mmdd, gid)
            ids = analyze.game_ids(mmdd, gid)
        except Exception as e:
            fail += 1
            print(f"parse FAIL {mmdd}/{gid}: {e}")
            continue
        away = next((e["team"] for e in events if e["half"] == "表"), None)
        home = next((e["team"] for e in events if e["half"] == "裏"), None)
        cur = {}
        for e in events:
            dfs = home if e["half"] == "表" else away
            if e["type"] == "pitching":
                m = re.search(r"先発投手[）)]?\s*(\S+)", e["text"]) or re.search(r"→\s*(\S+)", e["text"])
                if m:
                    cur[dfs] = ids.get(m.group(1))
                continue
            if e["type"] != "pa" or not cur.get(dfs):
                continue
            cls = classify(e.get("result", ""))
            if cls is None or cls == "?":
                continue
            pitchers.setdefault(cur[dfs], []).append([mmdd, cls, e["inning"]])
        n += 1
        if n % 100 == 0:
            print(f"{n}試合処理済み", flush=True)
    json.dump(pitchers, open(PLOG25, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"build done: {n}試合(fail {fail}) 投手{len(pitchers)}人 → pitchers2025.json")


def analyze_wear():
    p = json.load(open(PLOG25, encoding="utf-8"))
    # 投手ごと: 日別(先発/救援・PA結果)
    per = {}
    for pid, rows in p.items():
        by = {}
        for mmdd, cls, inn in rows:
            by.setdefault(mmdd, []).append((cls, inn))
        per[pid] = by

    def ob_counts(pid, months, relief_only=True):
        ob = n = 0
        for mmdd, clss in per[pid].items():
            if int(mmdd[:2]) not in months:
                continue
            if relief_only and clss[0][1] == 1:
                continue
            for cls, _ in clss:
                if cls == "SH":
                    continue
                ob += 1 if cls in ONBASE else 0
                n += 1
        return ob, n

    def apps(pid, months, relief_only=True):
        return sum(1 for mmdd, clss in per[pid].items()
                   if int(mmdd[:2]) in months and not (relief_only and clss[0][1] == 1))

    # ── DiD: 夏(7-8月)の登板数で層別し、春(4-6月)→秋(9-10月)の同一投手内オッズ変化を比較 ──
    groups = {"低負荷(夏19以下)": [], "中負荷(夏20-27)": [], "高負荷(夏28+)": []}
    for pid in per:
        a_sum = apps(pid, (7, 8))
        ob_sp, n_sp = ob_counts(pid, (4, 5, 6))
        ob_au, n_au = ob_counts(pid, (9, 10))
        if n_sp < 40 or n_au < 25:  # 両期間に十分な打席がある投手のみ
            continue
        g = "高負荷(夏28+)" if a_sum >= 28 else ("中負荷(夏20-27)" if a_sum >= 20 else "低負荷(夏19以下)")
        groups[g].append((pid, ob_sp, n_sp, ob_au, n_au))
    print("=== 2025年: 夏の酷使→秋の劣化(同一投手の春→秋オッズ比・グループ平均) ===")
    for g, xs in groups.items():
        if not xs:
            print(f"{g}: 該当なし")
            continue
        num = den = sp_ob = sp_n = au_ob = au_n = 0
        for pid, o1, n1, o2, n2 in xs:
            # MH合成(春を基準に秋のオッズ比)
            nn = n1 + n2
            num += o2 * (n1 - o1) / nn
            den += o1 * (n2 - o2) / nn
            sp_ob += o1; sp_n += n1; au_ob += o2; au_n += n2
        orr = num / den if den else 1.0
        print(f"{g}: 投手{len(xs)}人 春被出塁{sp_ob/sp_n:.3f}(n={sp_n}) → 秋{au_ob/au_n:.3f}(n={au_n})"
              f"  秋/春オッズ比{orr:.3f}")

    # ── 通算軸の再現(9-10月・月内投手間・通算登板数バケット) ──
    print("=== 2025年9-10月: その時点の通算登板数と被出塁(月内・投手間) ===")
    mstr = {}
    for pid, by in per.items():
        dates = sorted(by, key=d_of)
        for i, mmdd in enumerate(dates):
            clss = by[mmdd]
            if clss[0][1] == 1 or int(mmdd[:2]) not in (9, 10):
                continue
            b = "c50+" if i >= 50 else ("c35-49" if i >= 35 else "c<35")
            for cls, _ in clss:
                if cls == "SH":
                    continue
                s = mstr.setdefault(int(mmdd[:2]), {}).setdefault(b, [0, 0])
                s[0] += 1 if cls in ONBASE else 0
                s[1] += 1
    for b in ("c<35", "c35-49", "c50+"):
        ob = sum(d.get(b, [0, 0])[0] for d in mstr.values())
        n = sum(d.get(b, [0, 0])[1] for d in mstr.values())
        num = den = 0.0
        for d in mstr.values():
            if b not in d or "c<35" not in d:
                continue
            a, nb = d[b]
            c, nr = d["c<35"]
            t = nb + nr
            if t:
                num += a * (nr - c) / t
                den += c * (nb - a) / t
        orr = 1.0 if b == "c<35" else (num / den if den else 1.0)
        print(f"  {b}: 被出塁{ob/max(1,n):.3f} (n={n}) オッズ比{orr:.3f}")

    # ── 負荷2軸(5日/30日換算=暦30日で近似)の再現(2025全季) ──
    print("=== 2025年: 負荷2軸の再現(同一投手内MH・基準=両方低) ===")
    strata = {}
    for pid, by in per.items():
        dates = sorted(by, key=d_of)
        dset = set(d_of(x) for x in dates)
        for mmdd in dates:
            clss = by[mmdd]
            if clss[0][1] == 1:
                continue
            d = d_of(mmdd)
            n5 = sum(1 for k in range(1, 6) if (d - datetime.timedelta(days=k)) in dset)
            n30 = sum(1 for k in range(1, 31) if (d - datetime.timedelta(days=k)) in dset)
            b = ("base", "burst", "heavy", "both")[(1 if n5 >= 2 else 0) + (2 if n30 >= 12 else 0)]
            for cls, _ in clss:
                if cls == "SH":
                    continue
                s = strata.setdefault(pid, {}).setdefault(b, [0, 0])
                s[0] += 1 if cls in ONBASE else 0
                s[1] += 1
    for b, lb in (("base", "基準"), ("burst", "短期高"), ("heavy", "長期高"), ("both", "両方高")):
        ob = sum(d.get(b, [0, 0])[0] for d in strata.values())
        n = sum(d.get(b, [0, 0])[1] for d in strata.values())
        num = den = 0.0
        for d in strata.values():
            if b not in d or "base" not in d:
                continue
            a, nb = d[b]
            c, nr = d["base"]
            t = nb + nr
            if t:
                num += a * (nr - c) / t
                den += c * (nb - a) / t
        orr = 1.0 if b == "base" else (num / den if den else 1.0)
        print(f"  {lb}: 被出塁{ob/max(1,n):.3f} (n={n}) オッズ比{orr:.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    if cmd == "fetch":
        fetch_all()
    elif cmd == "build":
        build()
    else:
        analyze_wear()
