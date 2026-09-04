# -*- coding: utf-8 -*-
"""v0: NPB公式playbyplayを解析し、打席ごとの得点期待値(RE24)差分と采配イベントを出す
Usage: python src/analyze.py 0902 [game_id]
設計: 状態(アウト×走者)は公式データに明記されているので再構成不要。
      ΔRE = RE(次の状態) - RE(前の状態) + その間の得点(簿記: 走者+打者の保存則で導出)
v0の采配台帳: 犠牲バント=指示/実行を分離計上。代打・投手交代・申告敬遠=検出してΔRE参考値を列挙。
"""
import sys, os, re, json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE_DIR, "data", "raw")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# RE24テーブル v0(公開セイバー研究の代表値・NPB得点環境向け暫定。順=アウト0/1/2)
# TODO: 年度別NPBデータで自前較正(design.md §1)
RE = {
    "": (0.47, 0.25, 0.10),
    "1": (0.82, 0.49, 0.21),
    "2": (1.05, 0.64, 0.31),
    "3": (1.30, 0.90, 0.35),
    "12": (1.39, 0.85, 0.41),
    "13": (1.71, 1.10, 0.47),
    "23": (1.94, 1.30, 0.54),
    "123": (2.20, 1.52, 0.72),
}
RUNNER_MAP = {
    "": "", "&nbsp;": "", "1塁": "1", "2塁": "2", "3塁": "3",
    "1・2塁": "12", "1・3塁": "13", "2・3塁": "23", "満塁": "123",
}


def nrunners(state):
    return len(state)


# 当季実測RE/得点確率表(retab.py出力)。あれば縮小ブレンドで使用(2026-09-03裁定: 借り物→実測)
_RETAB = {}
try:
    with open(os.path.join(BASE_DIR, "data", "logs", "retable.json"), encoding="utf-8") as _f:
        _RETAB = json.load(_f).get("table", {})
except Exception:
    _RETAB = {}
HAS_RETAB = bool(_RETAB)
_K_RE = 300  # 縮小の強さ: 実測nが300打席で借り物と同じ重み(バックテスト較正予定)


def re_of(state, outs):
    if outs >= 3:
        return 0.0
    prior = RE[state][outs]
    t = _RETAB.get(f"{state or '-'}|{outs}")
    if not t:
        return prior
    return (t["n"] * t["re"] + _K_RE * prior) / (t["n"] + _K_RE)


def ps_of(state, outs, k=1):
    """その状態から回終了までにk点以上入る確率(当季実測・k∈{1,2}想定)。表なしは0=安全側"""
    if outs >= 3:
        return 0.0
    if k <= 0:
        return 1.0
    t = _RETAB.get(f"{state or '-'}|{outs}")
    if not t:
        return 0.0
    if k == 1:
        return t["ps"]
    return t.get("ps2", t["ps"] * 0.45)


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", "").strip()


# ── イベントキャッシュ(9/4 GitHub移行): rawのHTMLは公開リポに置けないため、
#    解析済みの派生データ(events/ids/subs)を試合ごとにJSON化してコミットする。
#    再構築系(palog/retab/runpower/pitcher_ctx)はrawが無くてもキャッシュで全量再現できる。
#    dREは較正表(retable)依存なのでキャッシュに焼き込まない(汚染防止)。
EVDIR = os.path.join(BASE_DIR, "data", "events")


def _ids_from_html(html):
    mp = {}
    for pid, nm in re.findall(r'href="/bis/players/(\d+)\.html">([^<]+)</a>', html):
        mp[nm.strip()] = pid
    return mp


def game_ids(mmdd, gid):
    """playbyplay内の 選手名→ID 辞書。rawが無ければイベントキャッシュから"""
    path = os.path.join(RAW, mmdd, gid, "playbyplay.html")
    if os.path.exists(path):
        return _ids_from_html(open(path, encoding="utf-8").read())
    with open(os.path.join(EVDIR, mmdd, f"{gid}.json"), encoding="utf-8") as f:
        return json.load(f)["ids"]


def game_subs(mmdd, gid):
    """box.html由来の代走差し替え表(キャッシュ側)。呼び出し元はraw優先で使う"""
    try:
        with open(os.path.join(EVDIR, mmdd, f"{gid}.json"), encoding="utf-8") as f:
            return json.load(f).get("subs", {})
    except Exception:
        return {}


def iter_games():
    """全試合(mmdd,gid)の列挙: raw∪イベントキャッシュの和集合・ソート済み"""
    seen = set()
    if os.path.isdir(RAW):
        for mmdd in os.listdir(RAW):
            day = os.path.join(RAW, mmdd)
            if not (os.path.isdir(day) and mmdd.isdigit() and len(mmdd) == 4):
                continue
            for gid in os.listdir(day):
                if os.path.exists(os.path.join(day, gid, "playbyplay.html")):
                    seen.add((mmdd, gid))
    if os.path.isdir(EVDIR):
        for mmdd in os.listdir(EVDIR):
            day = os.path.join(EVDIR, mmdd)
            if os.path.isdir(day) and mmdd.isdigit() and len(mmdd) == 4:
                for f in os.listdir(day):
                    if f.endswith(".json"):
                        seen.add((mmdd, f[:-5]))
    return sorted(seen)


def parse_game(mmdd, gid):
    path = os.path.join(RAW, mmdd, gid, "playbyplay.html")
    cachep = os.path.join(EVDIR, mmdd, f"{gid}.json")
    if not os.path.exists(path):  # クラウド等: rawが無ければキャッシュから復元
        with open(cachep, encoding="utf-8") as f:
            c = json.load(f)
        return c["events"], c["unknowns"]
    html = open(path, encoding="utf-8").read()
    # ハーフイニングごとに分割(h5タグは属性付き)
    halves = re.split(r"<h5[^>]*>", html)[1:]
    events = []      # 全打席イベント
    unknowns = []    # 解析不能行(正直記録)
    for h in halves:
        m = re.match(r"(\d+)回(表|裏)（(.+?)の攻撃）", strip_tags(h[:200]))
        if not m:
            continue
        inning, half, team = int(m.group(1)), m.group(2), m.group(3)
        # 特殊行(投手交代・先発投手)と打席行を順に拾う
        rows = re.findall(r"(?s)<tr>(.*?)</tr>", h)
        half_events = []
        for row in rows:
            txt = strip_tags(row)
            cells = re.findall(r'(?s)<td[^>]*>(.*?)</td>', row)
            cells = [strip_tags(c) for c in cells]
            if not cells:
                continue
            if "投手交代" in txt or "先発投手" in txt:
                half_events.append({"type": "pitching", "text": txt, "team": team,
                                    "inning": inning, "half": half})
                continue
            if "代走" in txt and "アウト" not in (cells[0] if cells else ""):
                half_events.append({"type": "pinchrun", "text": txt, "team": team,
                                    "inning": inning, "half": half})
                continue
            if "守備交代" in txt or "守備変更" in txt:
                half_events.append({"type": "defsub", "text": txt, "team": team,
                                    "inning": inning, "half": half})
                continue
            # 打席行: [アウト, 走者, 打者, カウント, 結果] (カウント欄が無い場合あり)
            m2 = re.match(r"(\d)アウト", cells[0]) if cells else None
            if m2 and len(cells) >= 3:
                outs = int(m2.group(1))
                runners = RUNNER_MAP.get(cells[1].strip(), None)
                if runners is None:
                    unknowns.append(f"{inning}回{half} 走者不明: {cells[1]!r}")
                    continue
                batter = cells[2]
                result = cells[-1]
                half_events.append({"type": "pa", "team": team, "inning": inning,
                                    "half": half, "outs": outs, "runners": runners,
                                    "batter": batter, "result": result})
            elif txt:
                unknowns.append(f"{inning}回{half}: {txt[:60]}")
        # ΔREの簿記(次の打席行の状態と比較)
        pas = [e for e in half_events if e["type"] == "pa"]
        NONPA = ("盗塁", "牽制", "暴投", "ワイルドピッチ", "ボーク", "パスボール")
        for i, pa in enumerate(pas):
            # 盗塁等は打席完了ではない=簿記に「打者+1」を入れない
            batter_done = 0 if any(k in pa["result"] for k in NONPA) else 1
            if i + 1 < len(pas):
                nxt = pas[i + 1]
                d_outs = nxt["outs"] - pa["outs"]
                runs = nrunners(pa["runners"]) + batter_done - nrunners(nxt["runners"]) - d_outs
                runs = max(0, runs)
                pa["runs"] = runs
                pa["dRE"] = re_of(nxt["runners"], nxt["outs"]) - re_of(pa["runners"], pa["outs"]) + runs
                pa["end"] = False
            else:
                # イニング最終打席: 3アウト到達とみなす。得点は結果文の打点で近似(v0)
                rbi = re.search(r"打点(\d)", pa["result"])
                runs = int(rbi.group(1)) if rbi else 0
                pa["runs"] = runs
                pa["dRE"] = 0.0 - re_of(pa["runners"], pa["outs"]) + runs
                pa["end"] = True
        events.extend(half_events)
    # キャッシュ書き出し(dREを除いた素の事実のみ+ids+代走差し替え表)
    try:
        from runners import parse_box_subs  # 遅延import(循環回避)
        subs = parse_box_subs(mmdd, gid)
    except Exception:
        subs = {}
    ce = [{k: v for k, v in e.items() if k != "dRE"} for e in events]
    os.makedirs(os.path.dirname(cachep), exist_ok=True)
    with open(cachep, "w", encoding="utf-8") as f:
        json.dump({"events": ce, "unknowns": unknowns, "ids": _ids_from_html(html),
                   "subs": subs}, f, ensure_ascii=False)
    return events, unknowns


def saihai_ledger(events):
    """采配台帳v0: 犠牲バント=指示/実行分離。代打・申告敬遠・投手交代=検出+参考ΔRE"""
    ledger = []
    for e in events:
        if e["type"] != "pa":
            if e["type"] == "pitching" and "投手交代" in e["text"]:
                ledger.append({"cat": "継投", "team": e["team"], "inning": e["inning"],
                               "half": e["half"], "desc": e["text"], "decision": None, "exec": None})
            elif e["type"] == "pinchrun":
                ledger.append({"cat": "代走", "team": e["team"], "inning": e["inning"],
                               "half": e["half"], "desc": e["text"], "decision": None, "exec": None})
            elif e["type"] == "defsub":
                ledger.append({"cat": "守備交代", "team": e["team"], "inning": e["inning"],
                               "half": e["half"], "desc": e["text"], "decision": None, "exec": None})
            continue
        res, st, outs = e["result"], e["runners"], e["outs"]
        if "盗塁" in res:
            # グレー枠: 指示か選手判断か外形不明=別集計(ΔREは記録)
            ledger.append({"cat": "盗塁(グレー)", "team": e["team"], "inning": e["inning"], "half": e["half"],
                           "desc": f"{res}(状況:{outs}死{st or '走者無'})",
                           "state_before": f"{outs}死{st or '走者無'}",
                           "re_before": round(re_of(st, outs), 3),
                           "decision": None, "exec": round(e.get("dRE", 0.0), 3)})
            continue
        # バント指示の外形: 犠打成功だけでなくバントヒット(最良)・スリーバント失敗(最悪)も指示として計上
        # (2026-09-03修正: 従来は犠打のみ検出で19件/169試合が台帳漏れ)
        bunt_like = ("犠牲バント" in res or "犠打" in res
                     or "バントヒット" in res or "スリーバント" in res)
        if bunt_like and "3" in st:
            # スクイズ(三塁走者ありのバント)
            re_b = re_of(st, outs)
            act = e.get("dRE", 0.0)
            ledger.append({"cat": "スクイズ", "team": e["team"], "inning": e["inning"], "half": e["half"],
                           "desc": f"{e['batter']} {res}(状況:{outs}死{st})",
                           "state_before": f"{outs}死{st}", "re_before": round(re_b, 3),
                           "decision": None, "exec": round(act, 3)})
        elif bunt_like:
            # 指示の収支: 平均的成功(打者アウト・走者1つ進塁)を前提に評価
            # decisionは指示時点の評価なので結果(ヒット/スリーバント失敗)によらず同じ・差はexecに出る
            succ = {"1": "2", "2": "3", "12": "23", "13": "23" if False else "13", "3": "3", "23": "23", "123": "123"}
            s_after = succ.get(st, st)
            re_b = re_of(st, outs)
            re_a = re_of(s_after, outs + 1)
            dec = re_a - re_b
            act = e.get("dRE", 0.0)
            ledger.append({"cat": "バント", "team": e["team"], "inning": e["inning"], "half": e["half"],
                           "desc": f"{e['batter']} {res}(状況:{outs}死{st or '走者無'})",
                           "state_before": f"{outs}死{st or '走者無'}",
                           "re_before": round(re_b, 3), "re_after": round(re_a, 3),
                           "decision": round(dec, 3), "exec": round(act - dec, 3)})
        elif "申告敬遠" in res or "敬遠" in res:
            ledger.append({"cat": "申告敬遠", "team": "守備側", "inning": e["inning"], "half": e["half"],
                           "desc": f"{e['batter']} {res}", "decision": round(e.get("dRE", 0.0), 3), "exec": 0.0})
        if e["batter"].startswith("代打"):
            ledger.append({"cat": "代打", "team": e["team"], "inning": e["inning"], "half": e["half"],
                           "desc": f"{e['batter']} → {res}", "decision": None,
                           "exec": round(e.get("dRE", 0.0), 3)})
    return ledger


def report(mmdd, gid):
    events, unknowns = parse_game(mmdd, gid)
    pas = [e for e in events if e["type"] == "pa"]
    # 全打席にre_before/re_afterを付与(表示しなくても記録する=2026-09-02社長指示)
    for pa in pas:
        pa["re_before"] = round(re_of(pa["runners"], pa["outs"]), 3)
        pa["re_after_actual"] = round(pa["re_before"] + pa.get("dRE", 0.0) - pa.get("runs", 0), 3)
    print(f"===== {gid} ({mmdd}) 打席数={len(pas)} =====")
    ledger = saihai_ledger(events)
    # 生データ台帳をJSON保存(カードに出さない詳細も全部残す)
    outdir = os.path.join(BASE_DIR, "data", "out", mmdd)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, f"{gid}.json"), "w", encoding="utf-8") as f:
        json.dump({"game": gid, "date": mmdd, "pa_events": events, "saihai_ledger": ledger,
                   "unknown_rows": unknowns}, f, ensure_ascii=False, indent=1)
    if ledger:
        print("--- 采配台帳 ---")
        for l in ledger:
            dec = f"指示{l['decision']:+.3f}" if l["decision"] is not None else "指示-"
            ex = f"実行{l['exec']:+.3f}" if l["exec"] is not None else ""
            print(f"  {l['inning']}回{l['half']} [{l['cat']}] {l['desc']} | {dec} {ex}")
    # チーム別ΔRE合計(攻撃)
    teams = {}
    for e in pas:
        teams.setdefault(e["team"], 0.0)
        teams[e["team"]] += e.get("dRE", 0.0)
    print("--- 攻撃のΔRE合計(参考) ---")
    for t, v in teams.items():
        print(f"  {t}: {v:+.2f}点")
    if unknowns:
        print(f"--- 未解析行 {len(unknowns)}件(正直記録) ---")
        for u in unknowns[:10]:
            print(f"  ? {u}")
    return events, ledger


if __name__ == "__main__":
    mmdd = sys.argv[1]
    if len(sys.argv) > 2:
        report(mmdd, sys.argv[2])
    else:
        day_dir = os.path.join(RAW, mmdd)
        for gid in sorted(os.listdir(day_dir)):
            if os.path.isdir(os.path.join(day_dir, gid)):
                report(mmdd, gid)
                print()
