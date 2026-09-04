# -*- coding: utf-8 -*-
"""TikTok 1枚目 = Xと同じカード画像を縦1080×1920キャンバスに載せるだけ(9/4社長裁定)
※でか文字フックスライド案は9/4に社長裁定でボツ(「惹かれない・Xと同じ写真がいい」)
前提: build_card2.py --png が card_{gid}.png を生成済みであること(watch_gameの実行順で保証)
Usage: python src/tiktok_hook.py 0903 d-c-22 [--png]
出力: data/out/{mmdd}/tiktok1_{gid}.html (+ --png でEdgeヘッドレス2倍レンダ)
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build(mmdd, gid, render_png=False):
    outdir = os.path.join(BASE, "data", "out", mmdd)
    card_png = os.path.join(outdir, f"card_{gid}.png")
    if not os.path.exists(card_png):
        print(f"{gid}: card_{gid}.png がまだ無い(build_card2 --png を先に)→ スキップ")
        return None
    # カードと同じ地色(#eef1f7)の縦キャンバス中央に等幅配置=切れない・違和感なし
    html = f'''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; }}
  body {{ width:1080px; height:1920px; background:#eef1f7;
         display:flex; align-items:center; justify-content:center; }}
  img {{ width:1080px; display:block; }}
</style></head><body><img src="card_{gid}.png"></body></html>
'''
    outp = os.path.join(outdir, f"tiktok1_{gid}.html")
    open(outp, "w", encoding="utf-8").write(html)
    print(f"{gid}: カードを縦1080×1920に配置 → {outp}")
    if render_png:
        png = os.path.join(outdir, f"tiktok1_{gid}.png")
        edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        subprocess.run([edge, "--headless=new", f"--screenshot={png}",
                        "--window-size=1080,1920", "--force-device-scale-factor=2",
                        "--hide-scrollbars", "file:///" + outp.replace(os.sep, "/")],
                       capture_output=True, timeout=60)
        print("png:", png)
    return outp


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], "--png" in sys.argv)
