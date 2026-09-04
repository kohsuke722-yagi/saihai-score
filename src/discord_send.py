# -*- coding: utf-8 -*-
"""Discord Webhookへ本文+画像を配達(9/4 GitHub移行: カード+投稿文をスマホへ)
Usage: python src/discord_send.py "本文" [img1.png img2.png ...]
Webhook URL: 環境変数 DISCORD_WEBHOOK(GitHub ActionsはSecrets経由)
             無ければ .secrets/discord_webhook ファイル(ローカル用・git管理外)
"""
import json
import os
import sys
import urllib.request
import uuid

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def webhook_url():
    url = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if url:
        return url
    p = os.path.join(BASE, ".secrets", "discord_webhook")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().strip()
    raise SystemExit("Webhook URLが無い: 環境変数DISCORD_WEBHOOK か .secrets/discord_webhook を用意")


def send(content, files=()):
    """multipart/form-data組み立て(標準ライブラリのみ・Actionsランナーでも追加依存なし)"""
    boundary = uuid.uuid4().hex
    body = b""
    payload = {"content": content[:1990]}  # Discord上限2000字
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
             f"Content-Type: application/json\r\n\r\n").encode() + \
        json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\r\n"
    for i, fp in enumerate(files):
        fn = os.path.basename(fp)
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; "
                 f"filename=\"{fn}\"\r\nContent-Type: image/png\r\n\r\n").encode()
        body += open(fp, "rb").read() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        webhook_url(), data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "User-Agent": "baseball-ev delivery"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"discord: {r.status}")


if __name__ == "__main__":
    send(sys.argv[1], sys.argv[2:])
