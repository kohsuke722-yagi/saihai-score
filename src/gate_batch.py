# -*- coding: utf-8 -*-
"""P4ゲート夜間バッチ(9/9フェーズ1): 前日全試合の三値判定を本走設定で確定
- nightly.ymlのDB再構築後に実行(rawが手元にある前提=load_atomsのparse_game用)
- 出力: data/gates/{mmdd}/{gid}_final.json(コミット対象・記録の正)
- 試合前版({gid}.json=配達時の軽量判定)は上書きしない(配達履歴として保存)
- 1試合エラーでも残りを続行。冪等(既に_finalがあればスキップ)
Usage: python src/gate_batch.py [MMDD](省略=環境変数MMDD→昨日JST)
"""
import datetime
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lineup_gate import run_gate, gates_path  # noqa

JST = datetime.timezone(datetime.timedelta(hours=9))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 本走設定(9/9の最終検品と同値: K200/B400/M_null40・7.2分/チーム級)
B, K, MN = 400, 200, 40


def main():
    mmdd = (sys.argv[1] if len(sys.argv) > 1 else "") or \
        (os.environ.get("MMDD") or "").strip() or \
        (datetime.datetime.now(JST) - datetime.timedelta(days=1)).strftime("%m%d")
    evdir = os.path.join(BASE, "data", "events", mmdd)
    if not os.path.isdir(evdir):
        print(f"{mmdd}: イベント無し(試合なし日)→ 終了")
        return
    gids = sorted(f[:-5] for f in os.listdir(evdir) if f.endswith(".json"))
    print(f"P4夜間バッチ {mmdd}: {len(gids)}試合 (B={B}/K={K}/MN={MN})", flush=True)
    t0 = time.perf_counter()
    ok = skip = fail = 0
    for gid in gids:
        if os.path.exists(gates_path(mmdd, gid, final=True)):
            print(f"{gid}: _final済み→スキップ", flush=True)
            skip += 1
            continue
        if not os.path.exists(os.path.join(BASE, "data", "raw", mmdd, gid, "box.html")):
            # ゲートはスタメン表(box raw)が必須。nightly内ではfetch.py pbpが先に走る
            print(f"{gid}: box raw無し→スキップ(先に python src/fetch.py pbp {mmdd})",
                  flush=True)
            fail += 1
            continue
        try:
            run_gate(mmdd, gid, B=B, K=K, MN=MN, pregame=False)
            ok += 1
        except Exception as e:
            print(f"{gid}: ERROR {e}", flush=True)
            fail += 1
    print(f"完了 {ok}件/スキップ{skip}/失敗{fail} ({(time.perf_counter()-t0)/60:.0f}分)")
    sys.exit(1 if (fail and not ok) else 0)


if __name__ == "__main__":
    main()
