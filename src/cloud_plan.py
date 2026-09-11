# -*- coding: utf-8 -*-
"""試合日ディスパッチャ(GitHub Actions用): 今日(JST)の試合一覧から未配達分を出力
- 配達済み判定は data/posted/{mmdd}/{gid}{SUFFIX} マーカー(cloud_watch.pyがcommitする)
  SUFFIX環境変数: 空=試合カード(watch)、"_lineup"=打順カード(pregameリレーの残数判定用)
- 出力はGITHUB_OUTPUT(games=JSON配列, mmdd, has)。ローカル実行時はprintのみ
Usage: [MMDD=0904] [SUFFIX=_lineup] python src/cloud_plan.py
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import game_urls  # noqa

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST = datetime.timezone(datetime.timedelta(hours=9))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    mmdd = os.environ.get("MMDD", "").strip() or datetime.datetime.now(JST).strftime("%m%d")
    try:
        gids = [u.rstrip("/").split("/")[-1] for u in game_urls(mmdd)]
    except Exception as e:
        print(f"schedule fetch FAIL: {e}")  # NPBに繋がらない場合もワークフローは正常終了させる
        gids = []
    sfx = os.environ.get("SUFFIX", "")
    todo = [g for g in gids
            if not os.path.exists(os.path.join(BASE, "data", "posted", mmdd, g + sfx))]
    print(f"{mmdd}: 全{len(gids)}試合 {gids} → 未配達{len(todo)} {todo}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"mmdd={mmdd}\n")
            f.write(f"games={json.dumps(todo)}\n")
            f.write(f"has={'true' if todo else 'false'}\n")


if __name__ == "__main__":
    main()
