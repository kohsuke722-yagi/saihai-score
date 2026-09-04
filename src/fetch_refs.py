# -*- coding: utf-8 -*-
"""参照データ取得: 12球団の支配下選手一覧(投打左右)+baseballdata犠打ページ(日次スナップショット)
Usage: python src/fetch_refs.py
出力: data/raw/rosters/rst_X.html → data/logs/handedness.json (選手ID→投打)
      data/raw/baseballdata/{cbtr,pbtr}_YYYYMMDD.html (犠打企図/成功の日次差分用)
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.request

from fetch import RAW, NPB, UA, get, save

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEAMS = ["g", "t", "db", "c", "d", "s", "h", "f", "m", "l", "b", "e"]
LOGS = os.path.join(os.path.dirname(RAW), "logs")


def get_auto(url: str) -> str:
    """charset宣言を見て自動デコード(baseballdata等の非UTF-8サイト対応)"""
    req = urllib.request.Request(url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=20).read()
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
    enc = m.group(1).decode("ascii", "replace") if m else "utf-8"
    try:
        return raw.decode(enc, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


def fetch_rosters():
    hand = {}
    for tc in TEAMS:
        try:
            html = get(f"{NPB}/bis/teams/rst_{tc}.html")
        except Exception as e:
            print(f"FAIL roster {tc}: {e}", flush=True)
            continue
        save(os.path.join(RAW, "rosters", f"rst_{tc}.html"), html)
        n = 0
        for row in re.findall(r"<tr[\s\S]*?</tr>", html):
            m = re.search(r'href="/bis/players/(\d+)\.html"[^>]*>([^<]+)</a>', row)
            if not m:
                continue
            cells = [c.strip() for c in re.findall(r"<td[^>]*>([^<]*)</td>", row)]
            lr = [c for c in cells if c in ("右", "左", "両")]
            if len(lr) >= 2:
                hand[m.group(1)] = {
                    "name": re.sub(r"\s+", " ", m.group(2)).strip(),
                    "team": tc,
                    "throws": lr[-2],
                    "bats": lr[-1],
                }
                n += 1
        print(f"{tc}: {n} players", flush=True)
        time.sleep(1.2)
    out = os.path.join(LOGS, "handedness.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(hand, f, ensure_ascii=False, indent=1)
    print(f"handedness.json: {len(hand)} players", flush=True)


def fetch_baseballdata():
    today = datetime.date.today().strftime("%Y%m%d")
    for name in ("cbtr", "pbtr"):
        try:
            html = get_auto(f"https://baseballdata.jp/{name}.html")
            save(os.path.join(RAW, "baseballdata", f"{name}_{today}.html"), html)
            print(f"saved {name}_{today}.html ({len(html)} bytes)", flush=True)
        except Exception as e:
            print(f"FAIL {name}: {e}", flush=True)
        time.sleep(1.2)


if __name__ == "__main__":
    fetch_rosters()
    fetch_baseballdata()
