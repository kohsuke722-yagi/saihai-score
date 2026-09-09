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
from analyze import parse_game, game_ids, game_ids2, iter_games  # noqa

RAW = os.path.join(BASE, "data", "raw")
LOGS = os.path.join(BASE, "data", "logs")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NONPA = ("盗塁", "牽制", "暴投", "ワイルドピッチ", "ボーク", "パスボール", "走塁", "途中終了", "途中交代")


def classify(res: str):
    if "振り逃げ" in res:
        return "K"  # 括弧内の暴投/捕逸表記でNONPAに落ちていた(9/7監査#16)。記録は三振=標準準拠
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
    if "敬遠" in res:
        return "IBB"  # 申告敬遠=監督の指示であり投手の制球でない→分布・較正から除外(9/7監査#14)
    if "四球" in res or "フォアボール" in res:
        return "BB"
    if "死球" in res or "デッドボール" in res:
        return "HBP"
    if "安打" in res or "ヒット" in res:
        return "1B"
    if any(k in res for k in ("エラー", "失策", "打撃妨害", "走塁妨害")):
        # 失策出塁ROE(§3・9/9フェーズ2): 「◯◯ゴロ（エラー）」等=打者は生きて出塁。
        # 従来はゴロ/フライ判定が先に食いOUT_G/OUT_A扱い=出塁の系統的欠落(実得点比-12%の一因)
        return "ROE"
    if "併殺" in res or "ダブルプレー" in res or "ゲッツー" in res:
        return "DP"
    if "ゴロ" in res:
        return "OUT_G"
    if any(k in res for k in ("フライ", "ライナー", "邪飛", "犠飛", "犠牲フライ")):
        return "OUT_A"
    if "野選" in res or "野手選択" in res:
        return "OUT"  # FC=走者封殺でアウトは記録される(打者出塁は state 変化として近似内)
    return "?"


OUTCLS = ("OUT_G", "OUT_A", "DP", "OUT")


def name_id_map(html):
    mp = {}
    for pid, nm in re.findall(r'href="/bis/players/(\d+)\.html">([^<]+)</a>', html):
        mp[nm.strip()] = pid
    return mp


def build():
    batters, pitchers, unknown = {}, {}, {}
    try:  # 相手投手の利き腕注釈(9/8左右スプリット対応)
        HAND = json.load(open(os.path.join(LOGS, "handedness.json"), encoding="utf-8"))
    except Exception:
        HAND = {}
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
            ids2 = game_ids2(mmdd, gid)

            def rid(tm, nm):  # チーム文脈つきID解決(同姓衝突対策・9/7監査#1)
                return (ids2.get(tm) or {}).get(nm) or ids.get(nm)
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
                bid = rid(e["team"], bname)
                if bid:
                    # 5列目=相手投手の利き腕(左/右/空)。既存リーダーはidx0-3参照なので後方互換
                    ppid = rid(defense, cur_p.get(defense, "")) if cur_p.get(defense) else None
                    ph = (HAND.get(ppid) or {}).get("throws", "") if ppid else ""
                    batters.setdefault(bid, []).append([mmdd, cls, st, outs, ph])
                pname = cur_p.get(defense)
                pid = rid(defense, pname) if pname else None
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
    # 実測リーグ分布(9/8打順レビュー#3: ハードコードの縮小先が実リーグ比+0.44点の架空打者
    # だった問題の修正。stats.pyが縮小先・オッズ基準にこれを使う)
    lgc = {}
    lgc_h = {"左": {}, "右": {}}  # リーグの対左/対右投手別分布(9/8左右スプリット対応)
    for rows in batters.values():
        for r in rows:
            c = {"OUT_G": "OUT", "OUT_A": "OUT", "DP": "OUT"}.get(r[1], r[1])
            if c in ("SH", "IBB"):
                continue
            lgc[c] = lgc.get(c, 0) + 1
            ph = r[4] if len(r) > 4 else ""
            if ph in lgc_h:
                lgc_h[ph][c] = lgc_h[ph].get(c, 0) + 1
    tot_lg = sum(lgc.values())
    if tot_lg:
        meta["league_dist"] = {k: round(v / tot_lg, 5) for k, v in lgc.items()}
    for hh, cc in lgc_h.items():
        tot = sum(cc.values())
        if tot >= 5000:
            meta[f"league_dist_vs{hh}"] = {k: round(v / tot, 5) for k, v in cc.items()}
    json.dump(meta, open(os.path.join(LOGS, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    npa_b = sum(len(v) for v in batters.values())
    print(f"games={n_games} batters={len(batters)}({npa_b}打席) pitchers={len(pitchers)} 不明結果={len(unknown)}種")
    print("リーグ実測:", json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    build()
