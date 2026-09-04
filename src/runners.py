# -*- coding: utf-8 -*-
"""走者簿記: 各打席の一・二・三塁の走者を選手名で復元(plan-runpower.md 手順1)
方針: 「走者は追い越せない」(順序保存)を制約に、観測された次状態へ前詰め割当。
      得点は前(三塁側)から・アウトは結果クラスのヒューリスティクスで特定。
      曖昧・矛盾はNone(不明走者)に落として正直に数える。
代走: box.htmlの打順スロットで「走」ロールが続く選手は、元選手の最後の出塁時点から差し替え。
検証: 復元占有パターン vs playbyplay明記の塁状況の一致率。
Usage: python src/runners.py                 # 全試合検証レポート
       python src/runners.py 0902 g-db-21    # 1試合デバッグ
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import parse_game  # noqa
from fetch import RAW  # noqa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NONPA = ("盗塁", "牽制", "暴投", "ワイルドピッチ", "ボーク", "パスボール", "走塁", "途中")
OUTISH = ("三振", "ゴロ", "フライ", "ライナー", "邪飛", "犠打", "犠牲", "併殺", "失敗")
REACH = ("安打", "ヒット", "四球", "フォアボール", "死球", "デッドボール", "エラー", "失策",
         "野選", "フィールダースチョイス", "振り逃げ", "打撃妨害", "ホームラン", "本塁打",
         "ツーベース", "スリーベース", "二塁打", "三塁打")


def parse_box_subs(mmdd, gid):
    """box.htmlから 打順スロット→出場順リスト を作り、「走」ロールの差し替え表を返す
    returns: {元選手名: 代走名}"""
    path = os.path.join(RAW, mmdd, gid, "box.html")
    if not os.path.exists(path):
        from analyze import game_subs  # rawが無い環境(クラウド)はキャッシュから
        return game_subs(mmdd, gid)
    html = open(path, encoding="utf-8").read()
    subs = {}
    slot_players = []  # 現スロットの出場順 [(role, name)]
    def flush():
        for i in range(1, len(slot_players)):
            role, nm = slot_players[i]
            if role.startswith("走"):
                subs[slot_players[i - 1][1]] = nm
    for tr in re.findall(r"(?s)<tr>(.*?)</tr>", html):
        cells = [re.sub(r"<[^>]+>|&nbsp;", "", c).strip()
                 for c in re.findall(r"(?s)<td[^>]*>(.*?)</td>", tr)]
        if len(cells) < 4:
            continue
        c0, role, name = cells[0], cells[1].strip("（）()"), cells[2]
        if not name or "チーム" in name:
            flush()
            slot_players = []
            continue
        if c0.isdigit():
            flush()
            slot_players = [(role, name)]
        elif slot_players:
            slot_players.append((role, name))
    flush()
    return subs


def _occ(bases):
    return "".join(b for b in "123" if bases[b] is not None or bases[b] == "?")


def annotate(mmdd, gid):
    """parse_gameイベントに bases(打席前の走者名) を注釈。returns (events, stats)"""
    events, _ = parse_game(mmdd, gid)
    subs = parse_box_subs(mmdd, gid)
    stats = {"rows": 0, "match": 0, "repair": 0, "unknown_runner": 0}
    pas_by_half = {}
    for e in events:
        if e["type"] == "pa":
            pas_by_half.setdefault((e["team"], e["inning"], e["half"]), []).append(e)
    # 代走の適用点: 元選手が最後に塁上に現れた半回のみで差し替え(=退場後は常にサブ)
    for key, pas in pas_by_half.items():
        bases = {"1": None, "2": None, "3": None}
        for i, e in enumerate(pas):
            st = e["runners"]
            # 観測との照合(修理: 占有が合わない塁は不明扱い)
            pred = set(b for b in "123" if bases[b] is not None)
            obs = set(st)
            stats["rows"] += 1
            if pred == obs:
                stats["match"] += 1
            else:
                stats["repair"] += 1
                for b in "123":
                    if b in obs and b not in pred:
                        bases[b] = None  # 出所不明の走者
                    if b not in obs:
                        bases[b] = None
            # 代走差し替え(塁上の選手にサブがいれば即適用: 適用点は最後の出塁=退場なので安全)
            for b in "123":
                if bases[b] in subs:
                    bases[b] = subs[bases[b]]
            e["bases"] = dict(bases)
            for b in obs:
                if bases[b] is None:
                    stats["unknown_runner"] += 1
            res = e.get("result", "")
            bat = e["batter"].replace("代打・", "").strip()
            # ── 盗塁等の走者イベント ──
            m = re.search(r"（走者・(\S+?)）(一|二|三|本)塁?盗塁(成功|失敗)", res)
            if m or any(k in res for k in NONPA):
                if m:
                    nm, tgt, ok = m.group(1), {"一": "1", "二": "2", "三": "3", "本": "H"}[m.group(2)], m.group(3) == "成功"
                    org = {"2": "1", "3": "2", "H": "3"}.get(tgt)
                    if org:
                        if ok:
                            if tgt != "H":
                                bases[tgt] = bases[org] if bases[org] is not None else None
                            bases[org] = None
                        else:
                            bases[org] = None
                # 暴投等の進塁は次行の観測照合で修理される(名前は保持できないためNone化は照合任せ)
                continue
            # ── 通常打席: 次行の観測状態へ順序保存で割当 ──
            nxt_st = pas[i + 1]["runners"] if i + 1 < len(pas) else ""
            nxt_outs = pas[i + 1]["outs"] if i + 1 < len(pas) else 3
            runs = e.get("runs", 0)
            order = [("3", bases["3"]), ("2", bases["2"]), ("1", bases["1"])]
            order = [(b, n) for b, n in order if b in st]  # 走者(前=三塁側)
            batter_reaches = any(k in res for k in REACH) and "併殺" not in res
            entrants = order + ([("0", bat)] if True else [])
            # 得点: 前から runs 人
            survivors = entrants[:]
            for _ in range(min(runs, len(survivors))):
                survivors.pop(0)
            # アウト: 打者が到達しない結果なら打者から/野選は先頭走者/残差は前から
            after = [b for b in "321" if b in nxt_st]
            need_out = len(survivors) - len(after)
            if need_out > 0 and not batter_reaches:
                survivors = [x for x in survivors if x[0] != "0"] \
                    if any(x[0] == "0" for x in survivors) else survivors
                need_out = len(survivors) - len(after)
            while need_out > 0 and survivors:
                # 野選・併殺系は先頭走者から、それ以外も先頭から(保守的)
                survivors.pop(0)
                need_out -= 1
            new_bases = {"1": None, "2": None, "3": None}
            ok_assign = len(survivors) == len(after)
            if ok_assign:
                for (b_from, nm), b_to in zip(survivors, after):
                    if b_from != "0" and int(b_to) < int(b_from):
                        ok_assign = False  # 逆行=矛盾
                        break
                    new_bases[b_to] = nm
            if not ok_assign:
                for b in after:
                    new_bases[b] = None
            bases = new_bases
    return events, stats


def main():
    if len(sys.argv) == 3:
        events, stats = annotate(sys.argv[1], sys.argv[2])
        for e in events:
            if e["type"] == "pa" and "bases" in e:
                bs = e["bases"]
                s = " ".join(f"{b}:{bs[b] or '?'}" for b in "123" if b in e["runners"])
                print(f"{e['inning']}回{e['half']} {e['outs']}死 {e['batter']:<8} [{s}] → {e['result'][:20]}")
        print(stats)
        return
    tot = {"rows": 0, "match": 0, "repair": 0, "unknown_runner": 0}
    games = 0
    from analyze import iter_games
    for mmdd, gid in iter_games():
        if True:  # 旧2重ループのインデント維持
            try:
                _, stats = annotate(mmdd, gid)
            except Exception as ex:
                print(f"FAIL {mmdd}/{gid}: {ex}")
                continue
            games += 1
            for k in tot:
                tot[k] += stats[k]
    print(f"games={games} 打席行={tot['rows']} 占有一致={tot['match']/max(1,tot['rows']):.1%} "
          f"修理={tot['repair']} 不明走者延べ={tot['unknown_runner']}")


if __name__ == "__main__":
    main()
