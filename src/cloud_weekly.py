# -*- coding: utf-8 -*-
"""週間監督通信簿の月曜朝自動便(9/9フェーズ1・design-weekly 1節)
- 対象週: 直近の火〜日(月曜8:00 JST起動を想定・試合ゼロ週も動いてテキスト通知)
- Actionsランナーには_ph.json(gitignore対象)が無いため、コミット済みイベントから
  現行モデルで再計算してから集計(バックフィル思想=モデル改定は常に最新値で再計算)
- 日曜分のイベントが未着(nightly遅延)ならrawを取得して自前でイベント化する保険つき
- 二重配達防止: data/posted/weekly/{d0}_{d1} マーカー(cloud_watchと同機構)
Usage: python src/cloud_weekly.py [d0 d1](省略=直近の火〜日)
"""
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cloud_watch import commit_marker, JST  # noqa
from discord_send import send  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def week_range():
    """直近の完了した火〜日(JST)。月曜に呼べば前日までの1週間"""
    today = datetime.datetime.now(JST).date()
    d1 = today - datetime.timedelta(days=(today.weekday() + 1) % 7)  # 直近の日曜
    d0 = d1 - datetime.timedelta(days=5)                             # その週の火曜
    return d0.strftime("%m%d"), d1.strftime("%m%d")


def days_between(d0, d1):
    a = datetime.date(2026, int(d0[:2]), int(d0[2:]))
    b = datetime.date(2026, int(d1[:2]), int(d1[2:]))
    return [(a + datetime.timedelta(days=i)).strftime("%m%d")
            for i in range((b - a).days + 1)]


def ensure_events(mmdd):
    """当該日のイベントが未着(nightly遅延)ならrawを取得してイベント化する保険"""
    evdir = os.path.join(BASE, "data", "events", mmdd)
    have = set(f[:-5] for f in os.listdir(evdir)) if os.path.isdir(evdir) else set()
    try:
        from fetch import game_urls, fetch_pbp
        gids = [u.rstrip("/").split("/")[-1] for u in game_urls(mmdd)]
    except Exception as e:
        print(f"{mmdd}: 試合一覧取得失敗({e})→ 手持ちイベントのみで続行")
        return sorted(have)
    missing = [g for g in gids if g not in have]
    if missing:
        print(f"{mmdd}: イベント未着{missing} → raw取得してイベント化", flush=True)
        try:
            fetch_pbp(mmdd)
            from analyze import parse_game
            for gid in missing:
                try:
                    parse_game(mmdd, gid)  # キャッシュ書き込み副作用
                    have.add(gid)
                except Exception as e:
                    print(f"{mmdd}/{gid}: イベント化失敗 {e}(中止試合なら正常)")
        except Exception as e:
            print(f"{mmdd}: raw取得失敗 {e}")
    return sorted(have)


def ensure_ph(d0, d1):
    """週内全試合の_ph.jsonを現行モデルで再計算(ランナーはgitignoreで持っていない)"""
    from phase1 import analyze_ph
    done = fail = 0
    for mmdd in days_between(d0, d1):
        for gid in ensure_events(mmdd):
            outp = os.path.join(BASE, "data", "out", mmdd, f"{gid}_ph.json")
            if os.path.exists(outp):
                continue
            try:
                res = analyze_ph(mmdd, gid)
            except Exception as e:
                print(f"FAIL {mmdd}/{gid}: {e}", flush=True)
                fail += 1
                continue
            os.makedirs(os.path.dirname(outp), exist_ok=True)
            json.dump(res, open(outp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            done += 1
    print(f"_ph再計算: {done}件(失敗{fail})", flush=True)
    return fail


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d0, d1 = (args[0], args[1]) if len(args) >= 2 else week_range()
    marker = os.path.join(BASE, "data", "posted", "weekly", f"{d0}_{d1}")
    if os.path.exists(marker):
        print(f"週間便 {d0}-{d1}: 配達済みマーカーあり→スキップ")
        return
    print(f"週間便 {d0}-{d1} 開始", flush=True)
    ensure_ph(d0, d1)
    from weekly_card import build
    png = build(d0, d1, png=True)
    period = f"{int(d0[:2])}/{int(d0[2:])}(火)〜{int(d1[:2])}/{int(d1[2:])}(日)"
    if png:
        send(f"📊 週間 監督通信簿|{period}\n"
             f"NPB全試合の采配を勝率換算で自動採点した週間収支ランキング。\n"
             f"±は95%誤差帯・「=」は上位との差が誤差帯内(順位の断定なし)。\n"
             f"※β試験運用・結果は使わず指示の瞬間で採点・計算方法はnoteで全公開",
             [png])
        print("DELIVERED weekly", flush=True)
    else:
        send(f"📊 週間 監督通信簿|{period}\n今週は採点対象の試合がありませんでした(雨天等)。")
        print("試合なし週の通知のみ", flush=True)
    commit_marker("weekly", f"{d0}_{d1}", note="posted-weekly")


if __name__ == "__main__":
    main()
