#!/usr/bin/env python3
"""Publiceer de feed-post van vandaag op @brochurify (Instagram).

Draait dagelijks via GitHub Actions (zie .github/workflows/feed-autopost.yml).
Leest queue.json (datum -> beeld + caption), vindt de post waarvan de datum
vandaag is (Europe/Amsterdam) en die nog niet in posted.json staat, en
publiceert die via de Instagram Content Publishing API.

Idempotent: na een geslaagde publicatie wordt het postnummer in posted.json
gezet; de workflow commit dat terug. Een tweede run op dezelfde dag doet niets.

Env:
  IG_USER_ID         Instagram Business user-id (@brochurify)
  IG_ACCESS_TOKEN    long-lived / system-user token met instagram_content_publish
  RAW_BASE           publieke basis-URL voor de beelden (raw.githubusercontent...)
  DRY_RUN=1          maak alleen de media-container, publiceer niet (test)
  FORCE_N=<n>        negeer de datum en draai post n (test)
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

HERE = Path(__file__).resolve().parent
GRAPH = "https://graph.facebook.com/v21.0"
TZ = ZoneInfo("Europe/Amsterdam")


def die(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def post(path: str, params: dict, token: str) -> dict:
    p = dict(params)
    p["access_token"] = token
    r = requests.post(f"{GRAPH}/{path}", data=p, timeout=60)
    body = r.text.replace(token, "***")
    if r.status_code != 200:
        die(f"Graph API fout {r.status_code} op /{path}:\n{body}")
    return r.json()


def main():
    token = os.environ.get("IG_ACCESS_TOKEN")
    ig_user = os.environ.get("IG_USER_ID")
    raw_base = os.environ.get("RAW_BASE", "").rstrip("/")
    if not token or not ig_user or not raw_base:
        die("Ontbrekende env: IG_ACCESS_TOKEN, IG_USER_ID of RAW_BASE.")

    queue = json.loads((HERE / "queue.json").read_text())
    posted = json.loads((HERE / "posted.json").read_text() or "[]")

    force_n = os.environ.get("FORCE_N")
    if force_n:
        item = next((q for q in queue if str(q["n"]) == str(force_n)), None)
        if not item:
            die(f"FORCE_N={force_n} niet in queue.")
    else:
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        # Pak de VROEGSTE nog-niet-geplaatste post die op of vóór vandaag valt.
        # Zo haalt een gemiste dag zichzelf in (max 1 per run), i.p.v. permanent over te slaan.
        due = sorted((q for q in queue if q["n"] not in posted and q["date"] <= today),
                     key=lambda q: (q["date"], q["n"]))
        if not due:
            print(f"Niets te plaatsen voor {today} (niets due of al geplaatst). Klaar.")
            return
        item = due[0]

    image_url = f"{raw_base}/{item['image']}"
    caption = item["caption"]
    dry = os.environ.get("DRY_RUN") == "1"
    print(f"Post #{item['n']} ({item['date']}): {image_url}")
    print(f"Caption: {caption}")

    # 1) container
    cont = post(f"{ig_user}/media", {"image_url": image_url, "caption": caption}, token)
    cid = cont.get("id")
    if not cid:
        die(f"Geen creation_id terug: {cont}")
    print(f"Container: {cid}")

    if dry:
        print("DRY_RUN — container gemaakt, niet gepubliceerd.")
        return

    # IG heeft even nodig om de media te verwerken voor publish
    time.sleep(5)
    pub = post(f"{ig_user}/media_publish", {"creation_id": cid}, token)
    media_id = pub.get("id")
    print(f"GEPUBLICEERD: media_id={media_id}")

    if not force_n:
        posted.append(item["n"])
        (HERE / "posted.json").write_text(json.dumps(sorted(posted)) + "\n")
        print(f"posted.json bijgewerkt: {sorted(posted)}")


if __name__ == "__main__":
    main()
