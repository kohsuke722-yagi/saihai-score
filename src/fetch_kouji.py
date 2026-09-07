# -*- coding: utf-8 -*-
"""NPB公示の日次取得(②-a Layer2・9/7): 出場選手登録・抹消+一軍出場選手一覧スナップショット
- https://npb.jp/announcement/roster/ は当日分しか載らないため毎日実行して蓄積する
- 出力: data/logs/kouji.json  {"moves": {MMDD: {"in": [[code,名前],..], "out": [...]}},
         "rosters": {MMDD: {code: [名前,..]}}}  名前は空白除去済み
- 用途: 負傷交代の後追い検知(数日内の抹消)・将来のベンチ在籍データ(エンジン評価④)
Usage: python src/fetch_kouji.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get  # noqa

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "logs", "kouji.json")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEAM_FULL2CODE = {
    "読売ジャイアンツ": "g", "阪神タイガース": "t", "横浜DeNAベイスターズ": "db",
    "広島東洋カープ": "c", "東京ヤクルトスワローズ": "s", "中日ドラゴンズ": "d",
    "福岡ソフトバンクホークス": "h", "北海道日本ハムファイターズ": "f",
    "千葉ロッテマリーンズ": "m", "オリックス・バファローズ": "b",
    "埼玉西武ライオンズ": "l", "東北楽天ゴールデンイーグルス": "e",
}
POS = ("投手", "捕手", "内野手", "外野手")


def norm(nm):
    return re.sub(r"[\s　]", "", nm or "")


def main():
    html = get("https://npb.jp/announcement/roster/")
    toks = [t.strip() for t in re.split(r"<[^>]+>", html)]
    toks = [t.replace("　", " ").strip() for t in toks if t.strip()]
    m = None
    for t in toks:
        m = re.search(r"(\d+)月(\d+)日の出場選手登録", t)
        if m:
            break
    if not m:
        print("公示日付が見つからない(ページ構造変化?)")
        return
    mmdd = f"{int(m.group(1)):02d}{int(m.group(2)):02d}"

    moves = {"in": [], "out": []}
    rosters = {}
    section = None      # "in" / "out" / "roster"
    cur_team = None
    i = 0
    while i < len(toks):
        t = toks[i]
        if "出場選手登録抹消" in t:
            section = "out"
        elif t == "出場選手一覧":
            section = "roster"
        elif re.fullmatch(r"出場選手登録", t):
            section = "in"
        elif t in TEAM_FULL2CODE:
            cur_team = TEAM_FULL2CODE[t]
            if section == "roster":
                rosters.setdefault(cur_team, [])
        elif t in POS and section and cur_team:
            # (ポジション, 背番号, 名前) の並び
            num = toks[i + 1] if i + 1 < len(toks) else ""
            name = toks[i + 2] if i + 2 < len(toks) else ""
            if re.fullmatch(r"[0-9０-９]+", num) and name and not any(k in name for k in ("登録", "抹消", "※")):
                if section == "roster":
                    rosters[cur_team].append(norm(name))
                else:
                    moves[section].append([cur_team, norm(name)])
                i += 2
        i += 1

    data = {"moves": {}, "rosters": {}}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data.setdefault("moves", {})[mmdd] = moves
    data.setdefault("rosters", {})[mmdd] = rosters
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    nr = sum(len(v) for v in rosters.values())
    print(f"{mmdd}: 登録{len(moves['in'])}件 抹消{len(moves['out'])}件 "
          f"一軍一覧{len(rosters)}球団{nr}人 → kouji.json(累積{len(data['moves'])}日分)")


if __name__ == "__main__":
    main()
