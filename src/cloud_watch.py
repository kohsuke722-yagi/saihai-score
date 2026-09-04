# -*- coding: utf-8 -*-
"""クラウド見張り(1試合・GitHub Actions用): 終了検知→取得→采配計算→カード→Discord配達
- watch_game.pyのクラウド版。配達後に data/posted/{mmdd}/{gid} マーカーをcommit&push
  (昼便と夜便の二重配達防止。競合はpull --rebaseリトライで解決)
- --deadline HH:MM (JST) で必ず退出。昼便17:15退出→夜便が未配達分を引き取る設計
Usage: python src/cloud_watch.py 0904 d-c-23 --deadline 23:20
"""
import datetime
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get, save, NPB, RAW  # noqa
from discord_send import send  # noqa

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST = datetime.timezone(datetime.timedelta(hours=9))
PY = sys.executable
SRC = os.path.dirname(os.path.abspath(__file__))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(script, *args):
    r = subprocess.run([PY, os.path.join(SRC, script), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or "")[-1500:] or (r.stderr or "")[-800:], flush=True)
    return r.returncode == 0


def commit_marker(mmdd, gid):
    """マーカーをcommit&push。Actions外(ローカルテスト)ではスキップ"""
    mp = os.path.join(BASE, "data", "posted", mmdd, gid)
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(datetime.datetime.now(JST).isoformat())
    if not os.environ.get("GITHUB_ACTIONS"):
        print("(local) マーカー書き込みのみ・commit省略")
        return
    def g(*a):
        return subprocess.run(["git", "-C", BASE, *a], capture_output=True, text=True)
    g("config", "user.name", "saihai-bot")
    g("config", "user.email", "actions@users.noreply.github.com")
    for attempt in range(5):  # 同時終了した他試合ジョブとのpush競合をリトライで解決
        g("add", "data/posted", "data/players")
        g("commit", "-m", f"posted: {mmdd} {gid}")
        g("pull", "--rebase")
        r = g("push")
        if r.returncode == 0:
            print("marker pushed")
            return
        time.sleep(5 + attempt * 5)
    print("WARN: marker push失敗(配達自体は完了)")


def main():
    mmdd, gid = sys.argv[1], sys.argv[2]
    dl = sys.argv[sys.argv.index("--deadline") + 1] if "--deadline" in sys.argv else "23:20"
    now = datetime.datetime.now(JST)
    deadline = now.replace(hour=int(dl[:2]), minute=int(dl[3:5]), second=0, microsecond=0)
    if os.path.exists(os.path.join(BASE, "data", "posted", mmdd, gid)):
        print(f"{gid}: 配達済みマーカーあり→スキップ")
        return
    while datetime.datetime.now(JST) < deadline:
        try:
            box = get(f"{NPB}/scores/2026/{mmdd}/{gid}/box.html")
            done = ("【試合終了】" in box) or ("◇終了 " in box)
        except Exception as e:
            print(f"fetch err: {e}", flush=True)
            box, done = None, False
        print(f"{gid}: {'終了!' if done else '試合中/未開始...'}", flush=True)
        if done:
            save(os.path.join(RAW, mmdd, gid, "box.html"), box)
            for page in ("playbyplay.html", "index.html"):
                save(os.path.join(RAW, mmdd, gid, page),
                     get(f"{NPB}/scores/2026/{mmdd}/{gid}/{page}"))
                time.sleep(1.2)
            if not run("phase1.py", mmdd, gid):
                print("phase1失敗")
            run("build_card2.py", mmdd, gid, "--png")
            png = os.path.join(BASE, "data", "out", mmdd, f"card_{gid}.png")
            txtp = os.path.join(BASE, "data", "out", mmdd, f"card_{gid}.txt")
            txt = open(txtp, encoding="utf-8").read() if os.path.exists(txtp) else f"{mmdd} {gid}"
            if os.path.exists(png):
                send(txt, [png])
                print(f"DELIVERED: {gid}")
            else:
                send(f"⚠ カード生成失敗: {mmdd} {gid}\n{txt}")
                print(f"FAIL: png無し {gid}")
            commit_marker(mmdd, gid)
            return
        time.sleep(180)
    print(f"{gid}: 締切{dl}到達・未終了のまま退出(次の便が引き取る)")


if __name__ == "__main__":
    main()
