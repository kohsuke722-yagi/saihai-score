# -*- coding: utf-8 -*-
"""自己検診日報(design-ops.md 1節・9/9フェーズ1): 「穴を社長より先に見つける」の常設化
- 6チェック(パース/簿記/配達/較正ドリフト/鮮度/受入)+P4ゲート進捗を1メッセージでDiscordへ
- 各1行・異常のみ🟥⚠・正常は✅(ゼロノイズ方針: 既知の乖離は急変時のみ警告)
- nightly.ymlのDB再構築+選手鮮度更新の後に実行(9/8夜の実害3件=cron全便不発・
  defense_starts空上書き・マーカー競合二重配達、は全部この日報の検知対象)
Usage: python src/health_report.py [MMDD] [--dry](省略=環境変数MMDD→昨日JST。--dry=送信せず表示)
"""
import datetime
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

JST = datetime.timezone(datetime.timedelta(hours=9))
SNAP = os.path.join(BASE, "data", "logs", "calib_prev.json")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def day_before(mmdd):
    d = datetime.date(2026, int(mmdd[:2]), int(mmdd[2:])) - datetime.timedelta(days=1)
    return d.strftime("%m%d")


def load_json(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def check_parse(mmdd, gids):
    """パース: イベント化成功数/失敗数・不明結果クラス数(0であること)"""
    from palog import classify
    ok, unk = 0, set()
    for gid in gids:
        d = load_json(os.path.join(BASE, "data", "events", mmdd, f"{gid}.json"))
        if not d or not d.get("events"):
            continue
        ok += 1
        for e in d["events"]:
            if e.get("type") == "pa" and classify(e.get("result", "")) == "?":
                unk.add(e.get("result", ""))
    bad = (ok < len(gids)) or unk
    return (f"{'🟥' if bad else '✅'} パース: {ok}/{len(gids)}試合 "
            f"不明結果{len(unk)}種" + (f" {sorted(unk)[:3]}" if unk else "")), bad


def check_books(mmdd, gids):
    """簿記: イベントの得点合計がbox線スコアと半回単位で一致するか(検算は実装済み・件数報告)"""
    from analyze import _box_linescore
    checked = mismatch = 0
    for gid in gids:
        ls = _box_linescore(mmdd, gid)
        d = load_json(os.path.join(BASE, "data", "events", mmdd, f"{gid}.json"))
        if not ls or not d:
            continue
        checked += 1
        by_half = {}
        for e in d.get("events", []):
            if e.get("type") == "pa":
                k = (e["inning"], e["half"])
                by_half[k] = by_half.get(k, 0) + int(e.get("runs", 0))
        mismatch += sum(1 for k, v in ls.items() if by_half.get(k, 0) != v)
    if checked == 0:
        return f"⚠ 簿記: 検算不可(box raw無し・{len(gids)}試合)", False
    bad = mismatch > 0
    return (f"{'🟥' if bad else '✅'} 簿記: 線スコア照合 {checked}/{len(gids)}試合 "
            f"不一致{mismatch}半回"), bad


def check_delivery(mmdd, gids):
    """配達: 当日試合数 vs postedマーカー数(cron全便不発の翌朝検知)"""
    pdir = os.path.join(BASE, "data", "posted", mmdd)
    marks = set(os.listdir(pdir)) if os.path.isdir(pdir) else set()
    miss_g = [g for g in gids if g not in marks]
    miss_l = [g for g in gids if f"{g}_lineup" not in marks]
    bad = bool(miss_g or miss_l)
    msg = f"{'🟥' if bad else '✅'} 配達: 試合カード{len(gids)-len(miss_g)}/{len(gids)}" \
          f"・打順カード{len(gids)-len(miss_l)}/{len(gids)}"
    if miss_g:
        msg += f" 未配達{miss_g}"
    if miss_l:
        msg += f" 打順未{miss_l}"
    return msg, bad


def _flat(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        elif isinstance(v, (int, float)):
            out[f"{prefix}{k}"] = float(v)
    return out


def check_calib(snap):
    """較正ドリフト: league_dist/負荷乗数/代打ペナルティの前日比(急変=データ事故の疑い)"""
    meta = load_json(os.path.join(BASE, "data", "logs", "meta.json"), {})
    pc = load_json(os.path.join(BASE, "data", "logs", "pitcher_ctx.json"), {})
    ph = load_json(os.path.join(BASE, "data", "logs", "ph_calib.json"), {})
    cur = {"dist": dict(meta.get("league_dist") or {}),
           "mult": _flat({k: pc.get(k) for k in ("tto", "rest", "load")}),
           "ph_mult": float(ph.get("mult") or 0)}
    prev = snap.get("calib")
    snap["calib"] = cur
    if not prev:
        return "✅ 較正: 基準を初期化(明日から前日比を監視)", False
    d_dist = max((abs(cur["dist"].get(k, 0) - v) for k, v in prev["dist"].items()),
                 default=0.0)
    d_mult = max((abs(cur["mult"].get(k, v) - v) / v for k, v in prev["mult"].items()
                  if v), default=0.0)
    d_ph = abs(cur["ph_mult"] - prev.get("ph_mult", cur["ph_mult"])) / (prev.get("ph_mult") or 1)
    bad = d_dist > 0.003 or d_mult > 0.05 or d_ph > 0.05
    return (f"{'🟥' if bad else '✅'} 較正: 分布Δ{d_dist:.4f} 乗数Δ{d_mult:.1%} "
            f"代打Δ{d_ph:.1%}"), bad


def check_fresh(snap):
    """鮮度: 空キャッシュ(bat/pit両None)の残数。急増=空上書き事故の疑い(9/8実害の型)"""
    n_empty = 0
    for p in glob.glob(os.path.join(BASE, "data", "players", "*.json")):
        d = load_json(p, {})
        if d.get("bat") is None and d.get("pit") is None:
            n_empty += 1
    prev = snap.get("n_empty")
    snap["n_empty"] = n_empty
    bad = prev is not None and n_empty > prev + 3
    return (f"{'🟥' if bad else '✅'} 鮮度: 空キャッシュ{n_empty}件"
            + (f"(前日比{n_empty - prev:+d})" if prev is not None else "")), bad


def check_accept(snap):
    """受入: リーグクローン9回換算EV vs 実得点平均(打順設計9-1)。
    既知のROE未実装乖離(約-1割)は急変時のみ警告(フェーズ2で±3%ゲートに昇格)"""
    from lineup_ev import game_ev
    meta = load_json(os.path.join(BASE, "data", "logs", "meta.json"), {})
    d = meta.get("league_dist")
    if not d:
        return "🟥 受入: league_dist無し(meta.json)", True
    ev = game_ev([dict(d)] * 9)
    runs = games = 0
    for f in glob.glob(os.path.join(BASE, "data", "events", "*", "*.json")):
        g = load_json(f)
        if not g or not g.get("events"):
            continue
        games += 1
        runs += sum(int(e.get("runs", 0)) for e in g["events"] if e.get("type") == "pa")
    if not games:
        return "🟥 受入: イベント無し", True
    actual = runs / (2 * games)
    dev = (ev - actual) / actual * 100
    prev = snap.get("accept_dev")
    snap["accept_dev"] = round(dev, 2)
    bad = prev is not None and abs(dev - prev) > 2.0
    tag = "急変!" if bad else ("既知乖離・ROEフェーズ2" if dev < -3 else "±3%内")
    return (f"{'🟥' if bad else '✅'} 受入: クローンEV{ev:.2f} vs 実{actual:.2f}点 "
            f"({dev:+.1f}%・{tag})"), bad


def check_gates(mmdd):
    """P4ゲート進捗: 前夜バッチ分(前日の試合)の_final確定数"""
    prev = day_before(mmdd)
    evdir = os.path.join(BASE, "data", "events", prev)
    if not os.path.isdir(evdir):
        return f"✅ ゲート: {int(prev[:2])}/{int(prev[2:])}は試合なし", False
    gids = [f[:-5] for f in os.listdir(evdir) if f.endswith(".json")]
    gdir = os.path.join(BASE, "data", "gates", prev)
    done = sum(1 for g in gids
               if os.path.exists(os.path.join(gdir, f"{g}_final.json")))
    bad = done < len(gids)
    return f"{'⚠' if bad else '✅'} ゲート: 前夜分 {done}/{len(gids)}試合確定", bad


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    mmdd = next((a for a in args if a.isdigit() and len(a) == 4), None) or \
        (os.environ.get("MMDD") or "").strip() or \
        (datetime.datetime.now(JST) - datetime.timedelta(days=1)).strftime("%m%d")
    evdir = os.path.join(BASE, "data", "events", mmdd)
    gids = sorted(f[:-5] for f in os.listdir(evdir)
                  if f.endswith(".json")) if os.path.isdir(evdir) else []
    # 中止試合(postedマーカーがnote=中止)は検診の分母から除外(雨天を事故と誤検知しない)
    pdir = os.path.join(BASE, "data", "posted", mmdd)
    cancelled = set()
    if os.path.isdir(pdir):
        for f in os.listdir(pdir):
            try:
                if open(os.path.join(pdir, f), encoding="utf-8").read(6).startswith("中止"):
                    cancelled.add(f.replace("_lineup", ""))
            except Exception:
                pass
    gids = [g for g in gids if g not in cancelled]
    snap = load_json(SNAP, {}) or {}
    lines = []
    if cancelled:
        lines.append(f"✅ 中止{len(cancelled)}試合を検診対象から除外")
    if not gids:
        lines.append(f"✅ {int(mmdd[:2])}/{int(mmdd[2:])}は試合なし(パース/簿記/配達は対象外)")
    else:
        for fn in (check_parse, check_books, check_delivery):
            try:
                msg, _ = fn(mmdd, gids)
            except Exception as e:
                msg = f"🟥 {fn.__name__}: 検診自体が失敗 {e}"
            lines.append(msg)
    for fn in (check_calib, check_fresh, check_accept):
        try:
            msg, _ = fn(snap)
        except Exception as e:
            msg = f"🟥 {fn.__name__}: 検診自体が失敗 {e}"
        lines.append(msg)
    try:
        lines.append(check_gates(mmdd)[0])
    except Exception as e:
        lines.append(f"🟥 ゲート進捗: 検診自体が失敗 {e}")
    n_bad = sum(1 for l in lines if l.startswith(("🟥", "⚠")))
    head = f"🩺 自己検診日報 {int(mmdd[:2])}/{int(mmdd[2:])}分" + \
        ("(全チェック正常)" if n_bad == 0 else f"(要確認 {n_bad}件)")
    body = "\n".join([head] + lines)
    json.dump(snap, open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(body)
    if not dry:
        from discord_send import send
        send(body)
        print("→ Discord送信済み")


if __name__ == "__main__":
    main()
