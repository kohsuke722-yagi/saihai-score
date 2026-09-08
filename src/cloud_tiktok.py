# -*- coding: utf-8 -*-
"""全試合終了後のTikTok用文章をDiscordへ(9/8社長要望)
- 当日全試合の配達マーカーが揃ったら(=結果カード出揃い)、各試合の投稿文を集約して
  「今日イチの采配/やらかし+試合別ひとこと+タグ」のダイジェストを1メッセージ配達
- 必要な_ph/txtはランナーに無いので各試合を取得→phase1→build_card2(txt)を自前で再生成
- マーカー: data/posted/{mmdd}/tiktok
Usage: python src/cloud_tiktok.py [mmdd] --deadline 23:40
"""
import datetime
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get, save, NPB, RAW, game_urls  # noqa
from discord_send import send  # noqa
from cloud_watch import commit_marker, JST, run  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def game_texts(mmdd, gids):
    """各試合を最終データで再生成し(スコア行, 采配ひとこと行)のリストを返す"""
    out = []
    for gid in gids:
        for page in ("playbyplay.html", "index.html", "box.html", "roster.html"):
            try:
                save(os.path.join(RAW, mmdd, gid, page),
                     get(f"{NPB}/scores/2026/{mmdd}/{gid}/{page}"))
            except Exception as e:
                print(f"{gid}: {page} fetch err {e}", flush=True)
            time.sleep(1.2)
        run("phase1.py", mmdd, gid)
        run("build_card2.py", mmdd, gid)  # txtのみ(pngは配達済み)
        txtp = os.path.join(BASE, "data", "out", mmdd, f"card_{gid}.txt")
        if not os.path.exists(txtp):
            print(f"{gid}: txt生成失敗→ダイジェストから除外", flush=True)
            continue
        lines = [ln.strip() for ln in open(txtp, encoding="utf-8").read().splitlines()
                 if ln.strip() and not ln.startswith("#")]
        if len(lines) >= 2:
            out.append((gid, lines[0], lines[1]))
    return out


def compose(mmdd, rows):
    """TikTok読み上げ/キャプション用ダイジェスト"""
    best, worst = None, None
    for gid, score, punch in rows:
        for m in re.finditer(
                r"(\d+)回の([^・]+)・([^(]+?)(?:が[^(]*)?\(勝率([+-][\d.]+)%\)", punch):
            v = float(m.group(4))
            item = (v, f"{m.group(2)} {m.group(1)}回 {m.group(3).strip()}({v:+.1f}%)")
            if v >= 0 and (best is None or v > best[0]):
                best = item
            if v < 0 and (worst is None or v < worst[0]):
                worst = item
    d = f"{int(mmdd[:2])}/{int(mmdd[2:])}"
    L = [f"🎬 TikTok用ダイジェスト {d}(全{len(rows)}試合)"]
    if best:
        L.append(f"👑 今日イチの采配: {best[1]}")
    if worst:
        L.append(f"💀 今日のやらかし: {worst[1]}")
    L.append("─" * 18)
    for gid, score, punch in rows:
        L.append(f"▼ {score}")
        L.append(f"  {punch}")
    L.append("─" * 18)
    L.append("#プロ野球 #NPB #野球 #采配 #データ野球 #野球解説")
    return "\n".join(L)


def main():
    args = sys.argv[1:]
    mmdd = next((a for a in args if a.isdigit() and len(a) == 4), None) or \
        (os.environ.get("MMDD") or "").strip() or \
        datetime.datetime.now(JST).strftime("%m%d")
    dl = args[args.index("--deadline") + 1] if "--deadline" in args else "23:40"
    deadline = datetime.datetime.now(JST).replace(
        hour=int(dl[:2]), minute=int(dl[3:5]), second=0, microsecond=0)
    mark = os.path.join(BASE, "data", "posted", mmdd, "tiktok")
    if os.path.exists(mark):
        print("tiktok配達済み→スキップ")
        return
    try:
        gids = [u.rstrip("/").split("/")[-1] for u in game_urls(mmdd)]
    except Exception as e:
        print(f"試合一覧取得失敗: {e}")
        return
    while datetime.datetime.now(JST) < deadline:
        played, undone = [], []
        for gid in gids:
            mp = os.path.join(BASE, "data", "posted", mmdd, gid)
            if os.path.exists(mp):
                note = open(mp, encoding="utf-8").read()
                if "中止" not in note:
                    played.append(gid)
            else:
                undone.append(gid)
        if not undone:
            if not played:
                print("全試合中止→配達なし")
                commit_marker(mmdd, "tiktok", note="全中止")
                return
            print(f"全試合終了を確認({len(played)}試合)→生成開始", flush=True)
            rows = game_texts(mmdd, played)
            if not rows:
                send(f"⚠ TikTokダイジェスト生成失敗: {mmdd}")
            else:
                send(compose(mmdd, rows))
                print("DELIVERED tiktok digest", flush=True)
            commit_marker(mmdd, "tiktok")
            return
        print(f"未終了{len(undone)}試合: {' '.join(undone)}(待機)", flush=True)
        # 未配達の把握はリモートマーカーが正: 定期的に取り込む
        if os.environ.get("GITHUB_ACTIONS"):
            subprocess.run(["git", "-C", BASE, "pull", "--rebase"],
                           capture_output=True, text=True)
        time.sleep(180)
    print(f"締切{dl}到達・未終了あり→退出(翌朝の検診で検知)")


if __name__ == "__main__":
    main()
