# -*- coding: utf-8 -*-
"""采配ペナントレースの日次集計簿(9/10): チーム×日付の采配収支(%WP)を
data/logs/pennant_daily.json へ永続化(コミット対象)。
- 穴の恒久対策(9/10発見): ペナントカードはシーズン全量の_ph.jsonを読むが、
  _phはgitignore=Actionsランナーには当該週の再計算分しか無く、月曜便の累計折れ線が
  ほぼ空で公開されるところだった
- 全再構築 --rebuild: 手元の全_phから集計を作り直す(モデル改定後のバックフィルで実行)
- 日次追記 --append MMDD: nightly用。_phが無ければ現行モデルで計算してから追記
集計定義は週間通信簿と同一(壊すとペナントと通信簿が食い違うので変更はセットで)
Usage: python src/pennant_daily.py --rebuild | --append MMDD
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PATH = os.path.join(BASE, "data", "logs", "pennant_daily.json")


def team_day_values(recs):
    """1試合の_phレコード→{team: 収支%WP}(週間通信簿と同じ計上規則)"""
    out = {}
    for r in recs:
        if "error" in r:
            continue
        k = r.get("kind")
        tm = r.get("def_team") if k in ("relief", "ibb", "relief_scan") else r.get("team")
        if not tm:
            continue
        if r.get("decision") is not None:
            if k == "swing" and not r.get("counted"):
                continue
            w = r.get("decision_wp_net", r.get("decision_wp"))
            v = (w or 0.0) * 100
        elif r.get("decision_head_wp") is not None:
            v = r["decision_head_wp"] * 100
        elif r.get("engine_loss_wp"):
            v = -r["engine_loss_wp"] * 100
        else:
            continue
        out[tm] = out.get(tm, 0.0) + v
    return out


def scan_local(only_mmdd=None):
    """手元の_ph.json走査→{team: {mmdd: v}}(ダブルヘッダーは同日加算)"""
    daily = {}
    pat = os.path.join(BASE, "data", "out", only_mmdd or "*", "*_ph.json")
    for f in glob.glob(pat):
        mmdd = os.path.basename(os.path.dirname(f))
        if not mmdd.isdigit():
            continue
        try:
            recs = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for tm, v in team_day_values(recs).items():
            daily.setdefault(tm, {})
            daily[tm][mmdd] = daily[tm].get(mmdd, 0.0) + v
    return daily


def load_book():
    try:
        return json.load(open(PATH, encoding="utf-8"))
    except Exception:
        return {"daily": {}}


def save_book(book):
    for tm, dd in book["daily"].items():
        book["daily"][tm] = {d: round(v, 4) for d, v in sorted(dd.items())}
    json.dump(book, open(PATH, "w", encoding="utf-8"), ensure_ascii=False,
              indent=0, sort_keys=True)
    n_d = len({d for dd in book["daily"].values() for d in dd})
    print(f"pennant_daily: {len(book['daily'])}チーム×{n_d}日 保存")


def ensure_ph_day(mmdd):
    """当日の_phが無ければ現行モデルで計算(cloud_weekly.ensure_phの単日版・
    ランナー用。中止試合のイベント無しはスキップ)"""
    evdir = os.path.join(BASE, "data", "events", mmdd)
    if not os.path.isdir(evdir):
        print(f"{mmdd}: イベント無し(試合なし日)")
        return
    from phase1 import analyze_ph
    for f in sorted(os.listdir(evdir)):
        if not f.endswith(".json"):
            continue
        gid = f[:-5]
        outp = os.path.join(BASE, "data", "out", mmdd, f"{gid}_ph.json")
        if os.path.exists(outp):
            continue
        try:
            res = analyze_ph(mmdd, gid)
        except Exception as e:
            print(f"FAIL {mmdd}/{gid}: {e}", flush=True)
            continue
        os.makedirs(os.path.dirname(outp), exist_ok=True)
        json.dump(res, open(outp, "w", encoding="utf-8"), ensure_ascii=False,
                  indent=1)
        print(f"_ph計算 {mmdd}/{gid}", flush=True)


def main():
    args = sys.argv[1:]
    if "--rebuild" in args:
        save_book({"daily": scan_local()})
        return
    if "--append" in args:
        mmdd = args[args.index("--append") + 1]
        ensure_ph_day(mmdd)
        book = load_book()
        for tm, dd in scan_local(only_mmdd=mmdd).items():
            book["daily"].setdefault(tm, {}).update(dd)
        save_book(book)
        return
    print(__doc__)


if __name__ == "__main__":
    main()
