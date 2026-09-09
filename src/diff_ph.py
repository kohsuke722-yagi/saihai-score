# -*- coding: utf-8 -*-
"""新旧並走diff(9/7の掟の道具化・9/9フェーズ2): 2つのdata/outツリーの*_ph.jsonを突合
- 採点に影響する母体変更(例: ROEクラス新設)の検品用。レコードは(日付,試合,通し番号)で対応
- 集計: 件数整合・decision_wpの平均|Δ|/最大|Δ|・符号反転数・見逃し(head/engine)のΔ・
  |Δ|上位の目視リスト(反転数・大きさ上位の目視=掟の要求)
Usage: python src/diff_ph.py <旧data/out> <新data/out> [--top 20]
"""
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_tree(root):
    out = {}
    for f in glob.glob(os.path.join(root, "*", "*_ph.json")):
        mmdd = os.path.basename(os.path.dirname(f))
        gid = os.path.basename(f).replace("_ph.json", "")
        try:
            out[(mmdd, gid)] = json.load(open(f, encoding="utf-8"))
        except Exception:
            out[(mmdd, gid)] = None
    return out


def wp_of(r):
    if r.get("decision") is not None:
        return r.get("decision_wp_net", r.get("decision_wp"))
    return None


def main():
    old_root, new_root = sys.argv[1], sys.argv[2]
    top_n = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 20
    O, N = load_tree(old_root), load_tree(new_root)
    common = sorted(set(O) & set(N))
    print(f"旧{len(O)}試合 / 新{len(N)}試合 / 共通{len(common)}試合"
          f" (旧のみ{len(set(O)-set(N))}・新のみ{len(set(N)-set(O))})")
    n_rec = n_pair = flips = 0
    diffs = []
    miss_d = 0.0
    len_mismatch = []
    for key in common:
        ro, rn = O[key], N[key]
        if ro is None or rn is None:
            continue
        if len(ro) != len(rn):
            len_mismatch.append((key, len(ro), len(rn)))
            continue
        for i, (a, b) in enumerate(zip(ro, rn)):
            if a.get("kind") != b.get("kind"):
                len_mismatch.append((key, f"kind不一致@{i}", ""))
                break
            n_rec += 1
            wa, wb = wp_of(a), wp_of(b)
            if wa is not None and wb is not None:
                n_pair += 1
                d = (wb - wa) * 100
                if (wa >= 0) != (wb >= 0) and abs(d) > 0.05:
                    flips += 1
                diffs.append((abs(d), d, key, i, a))
            ha = a.get("decision_head_wp") or -(a.get("engine_loss_wp") or 0)
            hb = b.get("decision_head_wp") or -(b.get("engine_loss_wp") or 0)
            if ha and hb:
                miss_d += abs(hb - ha) * 100
    diffs.sort(reverse=True, key=lambda x: x[0])
    mean_d = sum(x[0] for x in diffs) / max(1, len(diffs))
    print(f"采配レコード{n_rec}件 / decision対{n_pair}件")
    print(f"decision_wp: 平均|Δ|={mean_d:.3f}% 最大|Δ|={diffs[0][0]:.3f}%"
          f" 符号反転={flips}件({flips / max(1, n_pair):.1%})" if diffs else "対なし")
    print(f"見逃し系|Δ|合計={miss_d:.2f}%")
    if len_mismatch:
        print(f"⚠ レコード数/種別の不一致: {len(len_mismatch)}試合 {len_mismatch[:5]}")
    print(f"\n|Δ|上位{top_n}件(目視用):")
    for adx, d, key, i, a in diffs[:top_n]:
        print(f"  {key[0]}/{key[1]} #{i} {a.get('kind')} {a.get('inning')}回"
              f" {a.get('team') or a.get('def_team')} Δ{d:+.3f}% "
              f"{(a.get('ph') or a.get('new') or a.get('batter') or '')}")


if __name__ == "__main__":
    main()
