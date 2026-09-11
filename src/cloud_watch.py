# -*- coding: utf-8 -*-
"""クラウド見張り(1試合・GitHub Actions用): 終了検知→取得→采配計算→カード→Discord配達
- watch_game.pyのクラウド版。配達後に data/posted/{mmdd}/{gid} マーカーをcommit&push
  (昼便と夜便の二重配達防止。競合はpull --rebaseリトライで解決)
- --deadline HH:MM (JST) で必ず退出。加えて起動+320分でも自主退出
  (ジョブ強制kill355分の手前で綺麗に抜ける)。未配達分はリレー便が引き取る(9/11リレー方式)
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


def commit_marker(mmdd, gid, note="posted"):
    """マーカーをcommit&push。Actions外(ローカルテスト)ではスキップ"""
    mp = os.path.join(BASE, "data", "posted", mmdd, gid)
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(f"{note} {datetime.datetime.now(JST).isoformat()}")
    if not os.environ.get("GITHUB_ACTIONS"):
        print("(local) マーカー書き込みのみ・commit省略")
        return
    def g(*a):
        return subprocess.run(["git", "-C", BASE, *a], capture_output=True, text=True)
    g("config", "user.name", "saihai-bot")
    g("config", "user.email", "actions@users.noreply.github.com")
    for attempt in range(10):  # push競合をリトライで解決(9/8: 5回で突破できず二重配達→10回+長め退避)
        g("add", "data/posted", "data/players", "data/gates")
        g("commit", "-m", f"{note}: {mmdd} {gid}")
        g("pull", "--rebase")
        r = g("push")
        if r.returncode == 0:
            print("marker pushed")
            return
        time.sleep(8 + attempt * 8)
    print("WARN: marker push失敗(配達自体は完了)")


def main():
    mmdd, gid = sys.argv[1], sys.argv[2]
    dl = sys.argv[sys.argv.index("--deadline") + 1] if "--deadline" in sys.argv else "23:20"
    now = datetime.datetime.now(JST)
    deadline = now.replace(hour=int(dl[:2]), minute=int(dl[3:5]), second=0, microsecond=0)
    soft = now + datetime.timedelta(minutes=320)
    if soft < deadline:
        deadline, dl = soft, soft.strftime("%H:%M")
    if os.path.exists(os.path.join(BASE, "data", "posted", mmdd, gid)):
        print(f"{gid}: 配達済みマーカーあり→スキップ")
        return
    first_pass = True  # 9/9実害対策: cron大遅延で締切超過起動→即退出だと全便が死ぬ。
    # 最低1回は判定し、終了済みなら配達してから退出(遅延便の自己救済)
    while first_pass or datetime.datetime.now(JST) < deadline:
        first_pass = False
        try:
            box = get(f"{NPB}/scores/2026/{mmdd}/{gid}/box.html")
            done = ("【試合終了】" in box) or ("◇終了 " in box)
        except Exception as e:
            print(f"fetch err: {e}", flush=True)
            box, done = None, False
        if box and "中止】" in box:  # 【雨天のため中止】等。マーカーを残して以降の便のジョブも止める
            print(f"{gid}: 中止検知→カード無しで退出", flush=True)
            commit_marker(mmdd, gid, note="中止")
            return
        print(f"{gid}: {'終了!' if done else '試合中/未開始...'}", flush=True)
        if done:
            # 配達直前にリモートのマーカーを再確認(9/8実害: マーカーpush失敗×ジョブ再起動で
            # 二重配達。起動時チェックだけでは他ジョブの配達を見逃す)
            if os.environ.get("GITHUB_ACTIONS"):
                subprocess.run(["git", "-C", BASE, "pull", "--rebase"],
                               capture_output=True, text=True)
                if os.path.exists(os.path.join(BASE, "data", "posted", mmdd, gid)):
                    print(f"{gid}: 配達済みマーカーをリモートで検出→スキップ", flush=True)
                    return
            save(os.path.join(RAW, mmdd, gid, "box.html"), box)
            for page in ("playbyplay.html", "index.html", "roster.html"):
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
    print(f"{gid}: 締切{dl}到達・未終了のまま退出(リレー/次の便が引き取る)")


if __name__ == "__main__":
    main()
