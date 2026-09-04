# -*- coding: utf-8 -*-
"""走力スコア: 走者簿記(runners.py)から選手別の走塁データを集計(plan-runpower.md 手順2)
集計項目(全て機会数付き・エンジン側で縮小推定):
  sb: 盗塁機会(一塁走者・二塁空き)/企図/成功
  a13: 単打時に一塁→三塁へ進んだか(一塁のみ走者・単打)
  a2h: 単打時に二塁→生還したか(二塁走者あり・三塁なし・単打)
  dp: ゴロ系アウト時に併殺になったか(一塁走者・2死未満)
出力: data/logs/runpower.json {走者名: {各項目のカウント}}
Usage: python src/runpower.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runners import annotate  # noqa
from fetch import RAW  # noqa
from analyze import iter_games  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGS = os.path.join(os.path.dirname(RAW), "logs")


def main():
    P = {}

    def bump(nm, key, hit):
        if not nm:
            return
        d = P.setdefault(nm, {"sb_opp": 0, "sb_att": 0, "sb_succ": 0,
                              "a13_n": 0, "a13_y": 0, "a2h_n": 0, "a2h_y": 0,
                              "dp_n": 0, "dp_y": 0})
        d[key + "_n" if key in ("a13", "a2h", "dp") else key] += 1
        if hit and key in ("a13", "a2h", "dp"):
            d[key + "_y"] += 1

    games = 0
    for mmdd, gid in iter_games():
        if True:  # 旧2重ループのインデント維持
            try:
                events, _ = annotate(mmdd, gid)
            except Exception as ex:
                print(f"FAIL {mmdd}/{gid}: {ex}")
                continue
            games += 1
            pas = [e for e in events if e["type"] == "pa" and "bases" in e]
            for i, e in enumerate(pas):
                st, res, bs = e["runners"], e.get("result", ""), e["bases"]
                tm = e["team"]
                r1 = f"{tm}:{bs['1']}" if bs.get("1") else None
                # 盗塁: 機会と企図・成功(runners.pyと同じ正規表現の簡易版)
                if r1 and "2" not in st:
                    if "盗塁" in res:
                        bump(r1, "sb_att", False)
                        if "成功" in res:
                            bump(r1, "sb_succ", False)
                    else:
                        bump(r1, "sb_opp", False)
                if "盗塁" in res or "（走者" in res:
                    continue
                runs = e.get("runs", 0)
                is_1b = ("ヒット" in res or "安打" in res) and "二塁打" not in res \
                    and "三塁打" not in res and "ツーベース" not in res and "スリーベース" not in res
                # a2h: 二塁走者(三塁なし)+単打→生還?
                if is_1b and "2" in st and "3" not in st and bs.get("2"):
                    bump(f"{tm}:{bs['2']}", "a2h", runs >= 1)
                # a13: 一塁のみ走者+単打→次の行で三塁にいるか
                if is_1b and st == "1" and r1 and i + 1 < len(pas):
                    n = pas[i + 1]
                    if n["inning"] == e["inning"] and n["half"] == e["half"]:
                        bump(r1, "a13", n["bases"].get("3") == bs.get("1"))
                # dp: 一塁走者・2死未満・ゴロ系
                if r1 and e["outs"] < 2 and ("ゴロ" in res or "併殺" in res):
                    bump(r1, "dp", "併殺" in res or "ダブルプレー" in res or "ゲッツー" in res)
    out = {nm: d for nm, d in P.items() if d and sum(d.values()) > 0}
    with open(os.path.join(LOGS, "runpower.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    n_sb = sum(1 for d in out.values() if d["sb_att"] > 0)
    top = sorted(out.items(), key=lambda kv: -(kv[1]["sb_succ"]))[:5]
    print(f"games={games} 走者{len(out)}人 盗塁企図あり{n_sb}人 saved: runpower.json")
    print("盗塁成功トップ5:", ", ".join(f"{k}({v['sb_succ']}/{v['sb_att']})" for k, v in top))


if __name__ == "__main__":
    main()
