# -*- coding: utf-8 -*-
"""スタメン発表見張り(GitHub Actions用・9/8社長「発表されたらすぐカード→Discord」)
- 当日全試合のbox.htmlをポーリングし、スタメン発表を検知したら打順カード生成→Discord配達
- 配達済みは data/posted/{mmdd}/{gid}_lineup マーカー(cloud_watchと同機構)で二重配達防止
- 中止検知でマーカーを残して以降の便も止める。--deadlineで必ず退出(次の便が引き取る)
Usage: python src/cloud_pregame.py [mmdd] --deadline 18:40
"""
import datetime
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get, save, NPB, RAW, game_urls  # noqa
from discord_send import send  # noqa
from cloud_watch import commit_marker, JST  # noqa
from runners import parse_box_lineup  # noqa

PY = sys.executable
SRC = os.path.dirname(os.path.abspath(__file__))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def announced(mmdd, gid):
    """保存済みbox.htmlからスタメン(両軍9人)が読めるか"""
    try:
        lu = parse_box_lineup(mmdd, gid)
    except Exception:
        return False
    return bool(lu) and len(lu) == 2 and all(
        len(d) == 9 and all(d.get(s, ("", ""))[1] for s in range(9)) for d in lu)


# P4ゲート試合前設定(9/9裁定A: 発表後ゲート→配達。FP検証と同水準の軽量設定)
GATE_B = int(os.environ.get("GATE_B", "200"))
GATE_MN = int(os.environ.get("GATE_MN", "20"))
GATE_BUDGET_MIN = int(os.environ.get("GATE_BUDGET_MIN", "18"))  # 1試合の時間予算(分)


def run_gate(mmdd, gid, deadline):
    """三値判定を配達前に実行(data/gates/へ保存→カードが読む)。
    締切までの残りが予算未満なら見送り=「検定中」バッジで即配達(誠実なフォールバック)"""
    remain = (deadline - datetime.datetime.now(JST)).total_seconds() / 60
    if remain < GATE_BUDGET_MIN + 4:
        print(f"{gid}: 残り{remain:.0f}分<予算{GATE_BUDGET_MIN}分 → ゲート見送り(検定中表示)",
              flush=True)
        return False
    print(f"{gid}: P4ゲート開始 (B={GATE_B}/MN={GATE_MN})", flush=True)
    try:
        r = subprocess.run(
            [PY, os.path.join(SRC, "lineup_gate.py"), mmdd, gid, "--pregame",
             "--b", str(GATE_B), "--mnull", str(GATE_MN)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=GATE_BUDGET_MIN * 60)
        print((r.stdout or "")[-900:] or (r.stderr or "")[-500:], flush=True)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"{gid}: ゲートtimeout({GATE_BUDGET_MIN}分) → 検定中表示で配達", flush=True)
        return False
    except Exception as e:
        print(f"{gid}: ゲート失敗 {e} → 検定中表示で配達", flush=True)
        return False


def deliver(mmdd, gid, deadline=None):
    for page in ("roster.html", "index.html"):
        try:
            save(os.path.join(RAW, mmdd, gid, page),
                 get(f"{NPB}/scores/2026/{mmdd}/{gid}/{page}"))
        except Exception as e:
            print(f"{gid}: {page}取得失敗 {e}", flush=True)
        time.sleep(1.2)
    if deadline is not None:
        run_gate(mmdd, gid, deadline)
    r = subprocess.run([PY, os.path.join(SRC, "pregame_card.py"), mmdd, gid, "--png"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or "")[-1200:] or (r.stderr or "")[-600:], flush=True)
    outdir = os.path.join(BASE, "data", "out", mmdd)
    png = os.path.join(outdir, f"lineup_{gid}.png")
    txtp = os.path.join(outdir, f"lineup_{gid}.txt")
    txt = open(txtp, encoding="utf-8").read() if os.path.exists(txtp) else \
        f"スタメン発表 {mmdd} {gid}"
    if os.path.exists(png):
        send(txt, [png])
        print(f"DELIVERED lineup: {gid}", flush=True)
        return True
    send(f"⚠ 打順カード生成失敗: {mmdd} {gid}")
    print(f"FAIL: png無し {gid}", flush=True)
    return True  # 失敗通知済み=マーカーを残して再送ループを防ぐ(手動リカバリ)


def main():
    args = sys.argv[1:]
    mmdd = next((a for a in args if a.isdigit() and len(a) == 4), None) or \
        (os.environ.get("MMDD") or "").strip() or \
        datetime.datetime.now(JST).strftime("%m%d")
    dl = args[args.index("--deadline") + 1] if "--deadline" in args else "18:40"
    deadline = datetime.datetime.now(JST).replace(
        hour=int(dl[:2]), minute=int(dl[3:5]), second=0, microsecond=0)
    try:
        gids = [u.rstrip("/").split("/")[-1] for u in game_urls(mmdd)]
    except Exception as e:
        print(f"試合一覧取得失敗: {e}")
        return
    pending = [g for g in gids if not os.path.exists(
        os.path.join(BASE, "data", "posted", mmdd, f"{g}_lineup"))]
    print(f"{mmdd}: {len(gids)}試合・見張り対象{len(pending)} 締切{dl}", flush=True)
    while pending and datetime.datetime.now(JST) < deadline:
        for gid in list(pending):
            try:
                box = get(f"{NPB}/scores/2026/{mmdd}/{gid}/box.html")
                save(os.path.join(RAW, mmdd, gid, "box.html"), box)
            except Exception as e:
                print(f"{gid}: fetch err {e}", flush=True)
                continue
            if "中止】" in box:
                print(f"{gid}: 中止検知", flush=True)
                commit_marker(mmdd, f"{gid}_lineup", note="中止")
                pending.remove(gid)
                continue
            if announced(mmdd, gid):
                print(f"{gid}: スタメン発表検知!", flush=True)
                try:
                    ok = deliver(mmdd, gid, deadline)
                except Exception as e:
                    print(f"{gid}: 配達エラー {e}(次周で再試行)", flush=True)
                    ok = False
                if ok:
                    commit_marker(mmdd, f"{gid}_lineup")
                    pending.remove(gid)
            else:
                print(f"{gid}: 未発表...", flush=True)
            time.sleep(1.2)
        if pending:
            time.sleep(150)
    print(f"退出: 残り{len(pending)}試合"
          f"({'全配達済み' if not pending else '次の便が引き取る'})", flush=True)


if __name__ == "__main__":
    main()
