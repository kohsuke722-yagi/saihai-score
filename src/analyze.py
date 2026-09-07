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


# ── WP表 v0(design-model-v2.md①): retableの得点分布rdから後ろ向きDPで勝ち価値を構築 ──
# 勝ち=1・引分=0.5・負け=0(NPB: 延長12回打ち切り)。9回以降は表終了時にホームリードで即終了、
# 裏はサヨナラ(勝ち越し=即1.0)。分布は1-8回実測の流用(9回裏の1点狙い歪みは未補正=v0近似)
_WPM = 15          # 点差の飽和(|d|>=15は勝敗確定扱い)
_WPTAB = {}        # (inning, half, d) -> {"st|o": V(打撃側)}
_WPEND = {}        # (inning, half, d) -> 半回終了時のV(打撃側)
HAS_WP = False


def _build_wp():
    global HAS_WP
    if not all("rd" in (_RETAB.get(f"{s or '-'}|{o}") or {})
               for s in ("", "1", "2", "3", "12", "13", "23", "123") for o in (0, 1, 2)):
        return
    states = ["", "1", "2", "3", "12", "13", "23", "123"]
    D = {(s, o): _RETAB[f"{s or '-'}|{o}"]["rd"] for s in states for o in (0, 1, 2)}
    start = {}  # (i, half, d) -> 半回開始時のV

    def vstart(i, half, d):
        if d >= _WPM:
            return 1.0
        if d <= -_WPM:
            return 0.0
        return start[(i, half, d)]

    def end_top(i, d):
        """表打撃側の半回終了時(d=打撃側マージン)。9回以降ホームリードなら裏なしで敗北"""
        if i >= 9 and d < 0:
            return 0.0
        return 1.0 - vstart(i, "裏", -d)

    def end_bottom(i, d):
        """裏打撃側の半回終了時。勝ち越し=サヨナラ勝ち(途中終了と同値)"""
        if d > 0:
            return 1.0 if i >= 9 else 1.0 - vstart(i + 1, "表", -d)
        if i >= 12:
            return 0.5 if d == 0 else 0.0
        if i >= 9 and d < 0:
            return 0.0
        return 1.0 - vstart(i + 1, "表", -d)

    for i in range(12, 0, -1):
        for half in ("裏", "表"):
            endf = end_bottom if half == "裏" else end_top
            for d in range(-_WPM + 1, _WPM):
                _WPEND[(i, half, d)] = endf(i, d)
                cell = {}
                for s in states:
                    for o in (0, 1, 2):
                        cell[f"{s or '-'}|{o}"] = sum(
                            p * endf(i, min(_WPM - 1, d + r)) for r, p in enumerate(D[(s, o)]))
                _WPTAB[(i, half, d)] = cell
                start[(i, half, d)] = cell["-|0"]
    HAS_WP = True


def _wp_clamp(inning, half, d):
    return (min(12, max(1, inning)), half, max(-_WPM + 1, min(_WPM - 1, d)))


def wp_end(inning, half, d):
    """半回終了時の打撃側勝ち価値(win=1, draw=0.5)"""
    if d >= _WPM:
        return 1.0
    if d <= -_WPM:
        return 0.0
    return _WPEND[_wp_clamp(inning, half, d)]


def wp_of(inning, half, d, state, outs):
    """回中(塁,アウト)からの打撃側勝ち価値。裏9回以降の勝ち越しマージンは即1.0(サヨナラ)"""
    if half == "裏" and inning >= 9 and d > 0:
        return 1.0
    if outs >= 3:
        return wp_end(inning, half, d)
    if d >= _WPM:
        return 1.0
    if d <= -_WPM:
        return 0.0
    key = _wp_clamp(inning, half, d)
    return _WPTAB[key][f"{state or '-'}|{outs}"]


try:
    _build_wp()
except Exception:
    HAS_WP = False


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


def game_ids2(mmdd, gid):
    """チーム別の 選手名→ID(9/7監査#1: 両チーム同姓の衝突対策)。
    {チーム名: {名前: pid}}。旧形式キャッシュ(ids2なし)は空dict=呼び出し側で平坦にフォールバック"""
    path = os.path.join(RAW, mmdd, gid, "playbyplay.html")
    cachep = os.path.join(EVDIR, mmdd, f"{gid}.json")
    if os.path.exists(path):
        parse_game(mmdd, gid)  # 最新形式でキャッシュ再生成(ids2を焼き込む)
    try:
        with open(cachep, encoding="utf-8") as f:
            return json.load(f).get("ids2", {}) or {}
    except Exception:
        return {}


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


def _box_linescore(mmdd, gid):
    """box.htmlのイニング別得点 {(回, 表/裏): 得点}。無ければ空(9/7監査#4: 簿記検算用)"""
    path = os.path.join(RAW, mmdd, gid, "box.html")
    if not os.path.exists(path):
        return {}
    plain = re.sub(r"<[^>]+>", " ", open(path, encoding="utf-8").read())
    plain = re.sub(r"[\s　]+", " ", plain.replace("&nbsp;", " "))
    if "計 H E" not in plain:
        return {}
    mt = re.search(r"】 (\S+?) vs (\S+?) \d+回戦", plain)
    if not mt:
        return {}
    ls = {}
    for full, half in ((mt.group(2), "表"), (mt.group(1), "裏")):  # NPB表記はhome vs away
        try:
            i = plain.index(full + " ", plain.index("計 H E"))
        except ValueError:
            return {}
        toks = []
        for t in plain[i + len(full):].split()[:22]:
            if re.fullmatch(r"\d+[xX]?|[xX]", t):
                toks.append(t)
            elif toks:
                break
        for inn, t in enumerate(toks[:-3], start=1):  # 末尾3つは計/H/E
            if t not in ("x", "X"):
                ls[(inn, half)] = int(re.sub(r"[xX]", "", t))
    return ls


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
    ids2_raw = []    # (攻撃チーム, 守備側の行か, [(pid,名前)]) → 後段でチーム別ids2へ(9/7監査#1)
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
            links = re.findall(r'href="/bis/players/(\d+)\.html">([^<]+)</a>', row)
            if links:
                is_def = ("投手交代" in txt or "先発投手" in txt
                          or "守備交代" in txt or "守備変更" in txt)
                ids2_raw.append((team, is_def, links))
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
        NONPA = ("盗塁", "牽制", "暴投", "ワイルドピッチ", "ボーク", "パスボール", "途中")
        for i, pa in enumerate(pas):
            # 盗塁等は打席完了ではない=簿記に「打者+1」を入れない。
            # 振り逃げは括弧内に暴投/捕逸を含むが打席完了(9/7監査#16の幽霊run対策)
            batter_done = 1 if "振り逃げ" in pa["result"] \
                else (0 if any(k in pa["result"] for k in NONPA) else 1)
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
    # ── 簿記の検算(9/7監査#4): box.htmlのイニング別得点と照合し、残差は末尾打席へ帰属 ──
    # (保存則簿記は暴投得点・最終打席の近似で半回あたり±1点ずれることがある。真値=公式線スコア)
    ls = _box_linescore(mmdd, gid)
    if ls:
        by_half = {}
        for e in events:
            if e["type"] == "pa":
                by_half.setdefault((e["inning"], e["half"]), []).append(e)
        for key, pas_h in by_half.items():
            truth = ls.get(key)
            if truth is None:
                continue
            diff_r = truth - sum(p.get("runs", 0) for p in pas_h)
            if diff_r > 0:  # 過小計上(暴投得点等の取りこぼし)→末尾打席へ
                last = pas_h[-1]
                last["runs"] = last.get("runs", 0) + diff_r
                last["dRE"] = last.get("dRE", 0.0) + diff_r
            elif diff_r < 0:  # 過大計上(幽霊run等)→後方から差し引き
                need = -diff_r
                for p_ in reversed(pas_h):
                    take = min(need, p_.get("runs", 0))
                    if take:
                        p_["runs"] -= take
                        p_["dRE"] = p_.get("dRE", 0.0) - take
                        need -= take
                    if not need:
                        break
    # キャッシュ書き出し(dREを除いた素の事実のみ+ids+代走差し替え表)
    try:
        from runners import parse_box_subs  # 遅延import(循環回避)
        subs = parse_box_subs(mmdd, gid)
    except Exception:
        subs = {}
    # チーム別ids2の構築: 打席系の行=攻撃側・投手/守備系の行=守備側に帰属(9/7監査#1)
    away_t = next((e["team"] for e in events if e["half"] == "表"), None)
    home_t = next((e["team"] for e in events if e["half"] == "裏"), None)
    ids2 = {}
    if away_t and home_t:
        ids2 = {away_t: {}, home_t: {}}
        for atk, is_def, links in ids2_raw:
            owner = (home_t if atk == away_t else away_t) if is_def else atk
            for pid, nm in links:
                ids2.setdefault(owner, {})[nm.strip()] = pid
    ce = [{k: v for k, v in e.items() if k != "dRE"} for e in events]
    os.makedirs(os.path.dirname(cachep), exist_ok=True)
    with open(cachep, "w", encoding="utf-8") as f:
        json.dump({"events": ce, "unknowns": unknowns, "ids": _ids_from_html(html),
                   "ids2": ids2, "subs": subs}, f, ensure_ascii=False)
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
