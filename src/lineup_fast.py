# -*- coding: utf-8 -*-
"""素DPのnumpy行列版(9/9・統計ゲートの本番設定FP検定を可能にする高速化)
- 状態24次元(塁8×アウト3)の行列DP。打者行列(遷移M・吸収a・期待得点r)は並び非依存の
  前計算 → 1並びの評価が行列積連鎖になり、多数並び×多数レプリケートの評価が桁違いに速い
- game_ev_from()と厳密同値(打ち切り・持ち越しの端数処理まで鏡写し)。同値性テストは
  verify_fast()で毎回実行可能。走力DP(game_ev_speed)は状態が動的なため対象外
"""
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lineup_ev import MAX_PA_INN  # noqa

STATES = [(st, o) for st in ("", "1", "2", "3", "12", "13", "23", "123")
          for o in (0, 1, 2)]
SIDX = {s: i for i, s in enumerate(STATES)}
START = SIDX[("", 0)]


def build_mats(t):
    """遷移表dict[(st,o)]→[(p,runs,ns,no)] から (M[24,24], a[24], r[24])"""
    M = np.zeros((24, 24))
    a = np.zeros(24)
    r = np.zeros(24)
    for (st, o), i in SIDX.items():
        for p, rn, ns, no in t[(st, o)]:
            r[i] += p * rn
            if no >= 3:
                a[i] += p
            else:
                M[i, SIDX[(ns, no)]] += p
    return M, a, r


def ev_orders(T9, orders):
    """T9=打者別遷移表(lineup_ev._trans_table形式)・orders=並びリスト → EV配列[n]"""
    mats = [build_mats(t) for t in T9]
    O = np.asarray(orders)
    n = len(O)
    inn_runs = np.zeros((n, 9))
    NL = np.zeros((n, 9, 9))  # [order, lead, 次イニング先頭slot]
    for lead in range(9):
        V = np.zeros((n, 24))
        V[:, START] = 1.0
        runs = np.zeros(n)
        for k in range(MAX_PA_INN):
            slot = (lead + k) % 9
            nl = (slot + 1) % 9
            b = O[:, slot]
            for bi in np.unique(b):
                m = b == bi
                Mb, ab, rb = mats[bi]
                Vm = V[m]
                runs[m] += Vm @ rb
                NL[m, lead, nl] += Vm @ ab
                V[m] = Vm @ Mb
            if V.sum() < 1e-14:
                break
        # 打ち切り残り: 原実装と同じく(最終カウンタ+1)%9へ持ち越し(質量~1e-12)
        NL[:, lead, (lead + MAX_PA_INN + 1) % 9] += V.sum(axis=1)
        inn_runs[:, lead] = runs
    total = np.zeros(n)
    ld = np.zeros((n, 9))
    ld[:, 0] = 1.0
    for _ in range(9):
        total += (ld * inn_runs).sum(axis=1)
        ld = np.einsum("nl,nlm->nm", ld, NL)
    return total


def fast_full_search(dists, fixed=None, topk=200, bunts=None):
    """総当りの行列DP版(full_searchと同結果・~6秒/チーム)。
    returns (best_order, best_ev, top[(ev, order)降順])"""
    import itertools
    from lineup_ev import _trans_table
    T = _trans_table(dists, bunts)
    free = [i for i in range(9) if i != fixed]
    orders = []
    for perm in itertools.permutations(free):
        it = iter(perm)
        orders.append([fixed if i == fixed else next(it) for i in range(9)])
    evs = ev_orders(T, orders)
    idx = np.argsort(-evs)[:topk]
    top = [(float(evs[i]), orders[i]) for i in idx]
    bi = int(np.argmax(evs))
    return orders[bi], float(evs[bi]), top


def verify_fast(dists, fixed=None, n_orders=30, seed=1, bunts=None):
    """同値性テスト: ランダム並びでgame_ev_fromと突き合わせ。returns 最大絶対差"""
    import random
    from lineup_ev import _trans_table, game_ev_from
    rng = random.Random(seed)
    free = [i for i in range(9) if i != fixed]
    orders = []
    for _ in range(n_orders):
        p = free[:]
        rng.shuffle(p)
        it = iter(p)
        orders.append([fixed if i == fixed else next(it) for i in range(9)])
    T = _trans_table(dists, bunts)
    fast = ev_orders(T, orders)
    slow = np.array([game_ev_from(T, o) for o in orders])
    return float(np.abs(fast - slow).max())
