"""NPB公式からデータ取得(全て公開ページ・User-Agent明示・アクセスは試合単位で数リクエストのみ)
Usage:
  python src/fetch.py games 0902        # 当日の試合URL一覧
  python src/fetch.py pbp 0902          # 当日全試合のplaybyplay+indexを data/raw/ へ保存
"""
import sys, os, re, time, urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE_DIR, "data", "raw")
UA = {"User-Agent": "Mozilla/5.0 (baseball-ev personal research)"}
NPB = "https://npb.jp"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")


def save(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def game_urls(mmdd: str):
    month = mmdd[:2]
    html = get(f"{NPB}/games/2026/schedule_{month}_detail.html")
    save(os.path.join(RAW, f"schedule_{month}.html"), html)
    links = sorted(set(re.findall(rf'href="(/scores/2026/{mmdd}/[^"]+?)"', html)))
    # ディレクトリ形式(/scores/2026/0902/s-t-19/)のみ
    return [l if l.endswith("/") else l + "/" for l in links if re.search(r"/[a-z]+-[a-z]+-\d+/?$", l)]


def fetch_pbp(mmdd: str):
    urls = game_urls(mmdd)
    print(f"{len(urls)} games on {mmdd}")
    for u in urls:
        gid = u.rstrip("/").split("/")[-1]
        for page in ("playbyplay.html", "index.html", "box.html"):
            try:
                html = get(NPB + u + page)
                save(os.path.join(RAW, mmdd, gid, page), html)
                print(f"  saved {gid}/{page} ({len(html)} bytes)")
            except Exception as e:
                print(f"  FAIL {gid}/{page}: {e}")
            time.sleep(1.2)  # 礼儀としてのウェイト


if __name__ == "__main__":
    cmd, mmdd = sys.argv[1], sys.argv[2]
    if cmd == "games":
        for u in game_urls(mmdd):
            print(u)
    elif cmd == "pbp":
        fetch_pbp(mmdd)
