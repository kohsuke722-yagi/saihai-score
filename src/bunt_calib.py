# -*- coding: utf-8 -*-
"""baseballdata犠打ページ+NPBロスターから、バント分岐確率の実測較正値と監督辞書を作る(①裁定 9/3)
- 成功率の大枠: baseballdata 犠打企図/犠打(シーズン全量・毎晩更新)を投手/野手別に自前集計
- バントヒット率・失敗内訳(走者アウト:進塁なし)は従来代表値の比率を維持(外形から取れないため)
出力: data/logs/bunt_calib.json (phase1.pyが起動時に読む) / data/logs/managers.json
Usage: python src/bunt_calib.py
"""
import glob
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "raw")
LOGS = os.path.join(BASE, "data", "logs")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEAM_CODE = {"巨人": "g", "DeNA": "db", "阪神": "t", "広島": "c", "中日": "d", "ヤクルト": "s",
             "ソフトバンク": "h", "日本ハム": "f", "ロッテ": "m", "西武": "l",
             "オリックス": "b", "楽天": "e"}
# 分岐の内訳比率(実測不能部分・代表値のまま): バントヒット率 / 走者アウト:進塁なし比
HIT_SHARE = {"pitcher": 0.03, "fielder": 0.05}
LEADOUT_RATIO = {"pitcher": 14 / 25, "fielder": 10 / 15}


def norm(name):
    return re.sub(r"[\s　・]", "", name)


def roster_positions():
    pos_of, managers = {}, {}
    for f in glob.glob(os.path.join(RAW, "rosters", "rst_*.html")):
        tc = os.path.basename(f)[4:-5]
        html = open(f, encoding="utf-8").read()
        for part in re.split(r'class="rosterMainHead"', html)[1:]:
            m = re.search(r'<a name="[^"]*">([^<]+)</a>', part)
            head = m.group(1).strip() if m else None
            for nm in re.findall(r'class="rosterRegister"(?:><a[^>]*>|>)([^<]+)<', part):
                if head == "監督":
                    managers[tc] = nm.strip()
                elif head:
                    pos_of.setdefault((tc, norm(nm)), head)
    return pos_of, managers


def parse_bunt_page(path):
    html = open(path, encoding="utf-8").read()
    rows = []
    for tr in re.findall(r"<tr><td class='rank-col'>.*?</tr>", html, re.S):
        tds = [t.strip() for t in re.findall(r"<td[^>]*>(?:<a[^>]*>)?([^<]*)", tr)]
        if len(tds) < 12:
            continue
        rows.append(tds)
    if not rows:
        return []
    # 列位置の自動検出: 末尾からのオフセット候補(犠打成功率列が行内に残るか否か)
    for att_i, succ_i in ((-10, -9), (-9, -8)):
        ok = 0
        for tds in rows[:25]:
            try:
                att, succ = int(tds[att_i]), int(tds[succ_i])
                rate = float(tds[3].rstrip("%")) if tds[3].endswith("%") else None
                if 0 <= succ <= att and (att == 0 or rate is None
                                         or abs(succ / att * 100 - rate) < 1.5):
                    ok += 1
            except (ValueError, IndexError):
                pass
        if ok >= len(rows[:25]) * 0.8:
            out = []
            for tds in rows:
                try:
                    out.append({"name": tds[1], "team": tds[2],
                                "att": int(tds[att_i]), "succ": int(tds[succ_i])})
                except (ValueError, IndexError):
                    continue
            return out
    raise RuntimeError(f"列位置を特定できず: {path}")


def main():
    pos_of, managers = roster_positions()
    with open(os.path.join(LOGS, "managers.json"), "w", encoding="utf-8") as f:
        json.dump(managers, f, ensure_ascii=False, indent=1)
    print("監督:", " ".join(f"{k}={v}" for k, v in sorted(managers.items())))

    agg = {"pitcher": [0, 0], "fielder": [0, 0]}
    players, unknown = {}, 0
    for pref in ("cbtr", "pbtr"):
        files = sorted(glob.glob(os.path.join(RAW, "baseballdata", f"{pref}_*.html")))
        if not files:
            print(f"WARN: {pref} スナップショット無し")
            continue
        for row in parse_bunt_page(files[-1]):
            tc = TEAM_CODE.get(row["team"])
            pos = pos_of.get((tc, norm(row["name"])))
            if pos is None:
                unknown += 1
                continue
            kind = "pitcher" if "投" in pos else "fielder"
            agg[kind][0] += row["att"]
            agg[kind][1] += row["succ"]
            players[f"{tc}:{norm(row['name'])}"] = {"att": row["att"], "succ": row["succ"],
                                                    "kind": kind}
    bunt_p = {}
    stats = {}
    for kind in ("pitcher", "fielder"):
        att, succ = agg[kind]
        s = succ / att if att else 0.0
        hit = HIT_SHARE[kind]
        rem = (1 - s) * (1 - hit)
        bunt_p[kind] = {"succ": round(s * (1 - hit), 4), "hit": hit,
                        "leadout": round(rem * LEADOUT_RATIO[kind], 4),
                        "fail": round(rem * (1 - LEADOUT_RATIO[kind]), 4)}
        stats[kind] = {"att": att, "succ": succ, "rate": round(s, 4)}
        print(f"{kind}: 企図{att} 成功{succ} 成功率{s:.1%} → 分岐{bunt_p[kind]}")
    if unknown:
        print(f"注: ロスター照合不能 {unknown}人(移籍・登録抹消等)は集計外")
    with open(os.path.join(LOGS, "bunt_calib.json"), "w", encoding="utf-8") as f:
        json.dump({"stats": stats, "bunt_p": bunt_p, "players": players},
                  f, ensure_ascii=False, indent=1)
    print("saved: bunt_calib.json / managers.json")


if __name__ == "__main__":
    main()
