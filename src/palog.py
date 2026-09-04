# -*- coding: utf-8 -*-
"""data/raw/ の全playbyplayから打席単位ログDBを構築 v2
  batters.json: pid -> [[mmdd, cls, state, outs], ...]
  pitchers.json: pid -> [[mmdd, cls, inning, state, outs], ...]
  meta.json: リーグ実測パラメータ(進塁確率・併殺率・ゴロ率) ← 定数の較正に使う
cls: BB/HBP/K/1B/2B/3B/HR/SH/OUT_G(ゴロ)/OUT_A(フライ系)/DP(併殺)/OUT(その他アウト)
分類不能な結果文は unknown_results.json に正直記録。
Usage: python src/palog.py
"""
import os, re, json, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import parse_game, game_ids, iter_games  # noqa

RAW = os.path.join(BASE, "data", "raw")
LOGS = os.path.join(BASE, "data", "logs")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NONPA = ("盗塁", "牽制", "暴投", "ワイルドピッチ", "ボーク", "パスボール", "走塁", "途中終了", "途中交代")


def classify(res: str):
    if any(k in res for k in NONPA):
        return None
    if "犠牲バント" in res or "犠打" in res or "スリーバント" in res:
        return "SH"
    if "ホームラン" in res or "本塁打" in res:
        return "HR"
    if "スリーベース" in res or "三塁打" in res:
        return "3B"
    if "ツーベース" in res or "二塁打" in res:
        return "2B"
    if "三振" in res:
        return "K"
    if "敬遠" in res or "四球" in res or "フォアボール" in res:
        return "BB"
    if "死球" in res or "デッドボール" in res:
        return "HBP"
    if "安打" in res or "ヒット" in res:
        return "1B"
    if "併殺" in res or "ダブルプレー" in res or "ゲッツー" in res:
        return "DP"
    if "ゴロ" in res:
        return "OUT_G"
    if any(k in res for k in ("フライ", "ライナー", "邪飛", "犠飛", "犠牲フライ")):
        return "OUT_A"
    if any(k in res for k in ("失策", "エラー", "野選", "野手選択", "振り逃げ", "打撃妨害", "走塁妨害")):
        return "OUT"
    return "?"


OUTCLS = ("OUT_G", "OUT_A", "DP", "OUT")


def name_id_map(html):
    mp = {}
    for pid, nm in re.findall(r'href="/bis/players/(\d+)\.html">([^<]+)</a>', html):
        mp[nm.strip()] = pid
    return mp


def build():
    batters, pitchers, unknown = {}, {}, {}
    # リーグ実測カウンタ
    M = {"adv_1b_r2": [0, 0],      # 1Bで二塁走者が生還したか(r3なし状況)
         "adv_1b_r1to3": [0, 0],   # 1Bで一塁走者が三塁へ(r1のみ状況)
         "adv_2b_r1": [0, 0],      # 2Bで一塁走者が生還(r1のみ状況)
         "adv_out_r3": [0, 0],     # 外野系アウトで三塁走者生還(2死未満)
         "dp_given_out": [0, 0],   # 併殺機会(r1・2死未満・インプレーアウト)中の併殺
         "gb_share": [0, 0]}       # インプレーアウト中のゴロ率
    n_games = 0
    for mmdd, gid in iter_games():
        if True:  # 旧2重ループのインデント維持
            try:
                events, _ = parse_game(mmdd, gid)
            except Exception as e:
                unknown.setdefault("PARSE_FAIL", []).append(f"{mmdd}/{gid}: {e}")
                continue
            n_games += 1
            ids = game_ids(mmdd, gid)
            away = next((e["team"] for e in events if e["half"] == "表"), None)
            home = next((e["team"] for e in events if e["half"] == "裏"), None)
            cur_p = {}
            pas_by_half = {}
            for e in events:
                defense = home if e["half"] == "表" else away
                if e["type"] == "pitching":
                    m = re.search(r"先発投手[）)]?\s*(\S+)", e["text"])
                    if m:
                        cur_p[defense] = m.group(1)
                    m = re.search(r"→\s*(\S+)", e["text"])
                    if m:
                        cur_p[defense] = m.group(1)
                    continue
                if e["type"] != "pa":
                    continue
                res = e.get("result", "")
                cls = classify(res)
                if cls is None:
                    continue
                if cls == "?":
                    unknown[res] = unknown.get(res, 0) + 1
                    continue
                st, outs = e["runners"], e["outs"]
                runs = e.get("runs", 0)
                # ── リーグ実測 ──
                if cls == "1B" and "3" not in st and "2" in st:
                    M["adv_1b_r2"][0] += 1 if runs >= 1 else 0
                    M["adv_1b_r2"][1] += 1
                if cls == "1B" and st == "1":
                    key = pas_key = None  # 次状態で判定
                    pas_by_half.setdefault(id(e), None)
                if cls == "2B" and st == "1":
                    M["adv_2b_r1"][0] += 1 if runs >= 1 else 0
                    M["adv_2b_r1"][1] += 1
                if cls == "OUT_A" and "3" in st and outs < 2:
                    M["adv_out_r3"][0] += 1 if runs >= 1 else 0
                    M["adv_out_r3"][1] += 1
                if cls in OUTCLS and "1" in st and outs < 2:
                    M["dp_given_out"][0] += 1 if cls == "DP" else 0
                    M["dp_given_out"][1] += 1
                if cls in ("OUT_G", "OUT_A", "DP"):
                    M["gb_share"][0] += 1 if cls in ("OUT_G", "DP") else 0
                    M["gb_share"][1] += 1
                # ── 個人ログ ──
                bname = e["batter"].replace("代打・", "").strip()
                if bname.startswith("（"):
                    continue
                bid = ids.get(bname)
                if bid:
                    batters.setdefault(bid, []).append([mmdd, cls, st, outs])
                pname = cur_p.get(defense)
                pid = ids.get(pname) if pname else None
                if pid:
                    pitchers.setdefault(pid, []).append([mmdd, cls, e["inning"], st, outs])
            # 1B時のr1→3塁判定(次の打席行の状態を見る)
            pas = [e for e in events if e["type"] == "pa"]
            for i, pa in enumerate(pas[:-1]):
                if classify(pa.get("result", "")) == "1B" and pa["runners"] == "1":
                    nst = pas[i + 1]["runners"]
                    if pas[i + 1]["inning"] == pa["inning"] and pas[i + 1]["half"] == pa["half"]:
                        M["adv_1b_r1to3"][0] += 1 if "3" in nst else 0
                        M["adv_1b_r1to3"][1] += 1
    os.makedirs(LOGS, exist_ok=True)
    json.dump(batters, open(os.path.join(LOGS, "batters.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(pitchers, open(os.path.join(LOGS, "pitchers.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(unknown, open(os.path.join(LOGS, "unknown_results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    meta = {}
    for k, (a, b) in M.items():
        meta[k] = {"p": round(a / b, 4) if b else None, "n": b}
    json.dump(meta, open(os.path.join(LOGS, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    npa_b = sum(len(v) for v in batters.values())
    print(f"games={n_games} batters={len(batters)}({npa_b}打席) pitchers={len(pitchers)} 不明結果={len(unknown)}種")
    print("リーグ実測:", json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    build()
