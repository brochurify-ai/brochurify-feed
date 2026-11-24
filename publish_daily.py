#!/usr/bin/env python3
"""Publiceer de @brochurify-post van vandaag (reel, carrousel of beeld).

Draait dagelijks via GitHub Actions. Leest FEED.json (de content-eerste wachtrij,
1 post per dag, zie het plan in de hoofdrepo) en pakt de vroegste nog-niet-geplaatste
post waarvan de datum op of vóór vandaag valt (Europe/Amsterdam). Idempotent: na een
geslaagde publicatie komt het postnummer in geplaatst.json, dat de workflow terugcommit.
Een gemiste dag haalt zichzelf in (max 1 per run).

Alle media staat als absolute, publieke URL in FEED.json (DigitalOcean Spaces CDN),
dus hier is geen RAW_BASE meer nodig. Geen vast kleurenraster meer: een reel is gewoon
een reel, geen witte cover nodig tenzij FEED.json er een meegeeft.

Env: IG_USER_ID, IG_ACCESS_TOKEN. DRY_RUN=1 maakt de container maar publiceert niet.
FORCE_N=<n> draait post n, los van de datum (test).
"""
import json, os, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

HERE = Path(__file__).resolve().parent
GRAPH = "https://graph.facebook.com/v21.0"
TZ = ZoneInfo("Europe/Amsterdam")

def die(m, code=1):
    print(m, file=sys.stderr); sys.exit(code)

def post(path, params, token):
    p = dict(params); p["access_token"] = token
    r = requests.post(f"{GRAPH}/{path}", data=p, timeout=180)
    body = r.text.replace(token, "***")
    if r.status_code != 200:
        die(f"Graph API fout {r.status_code} op /{path}:\n{body}")
    return r.json()

def get(path, params, token):
    p = dict(params); p["access_token"] = token
    return requests.get(f"{GRAPH}/{path}", params=p, timeout=60).json()

def container_carousel(ig, token, item):
    kids = []
    for url in item["images"]:
        c = post(f"{ig}/media", {"image_url": url, "is_carousel_item": "true"}, token)
        kids.append(c["id"]); print("  kind:", c["id"])
    return post(f"{ig}/media", {"media_type": "CAROUSEL",
            "children": ",".join(kids), "caption": item["caption"]}, token)["id"]

def container_reel(ig, token, item):
    params = {"media_type": "REELS", "video_url": item["video_url"],
              "caption": item["caption"]}
    if item.get("cover_url"):
        params["cover_url"] = item["cover_url"]
    elif item.get("thumb_offset") is not None:
        params["thumb_offset"] = str(item["thumb_offset"])
    cid = post(f"{ig}/media", params, token)["id"]
    for i in range(60):
        code = get(cid, {"fields": "status_code,status"}, token).get("status_code")
        print(f"  reel-status {i}: {code}")
        if code == "FINISHED":
            return cid
        if code == "ERROR":
            die(f"Reel-verwerking mislukt bij container {cid}")
        time.sleep(6)
    die("Reel werd niet op tijd FINISHED.")

def container_image(ig, token, item):
    return post(f"{ig}/media",
        {"image_url": item["image_url"], "caption": item["caption"]}, token)["id"]

def main():
    token = os.environ.get("IG_ACCESS_TOKEN")
    ig = os.environ.get("IG_USER_ID")
    if not token or not ig:
        die("IG_ACCESS_TOKEN of IG_USER_ID ontbreekt.")
    dry = os.environ.get("DRY_RUN") == "1"

    feed = json.loads((HERE / "FEED.json").read_text())
    gpad = HERE / "geplaatst.json"
    gedaan = json.loads(gpad.read_text() or "[]") if gpad.exists() else []

    force = os.environ.get("FORCE_N")
    if force:
        item = next((q for q in feed if str(q["n"]) == str(force)), None)
        if not item:
            die(f"FORCE_N={force} niet in FEED.json.")
    else:
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        due = sorted((q for q in feed if q["n"] not in gedaan and q["date"] <= today),
                     key=lambda q: (q["date"], q["n"]))
        if not due:
            print(f"Niets te plaatsen voor {today}. Klaar."); return
        item = due[0]

    t = item["type"]
    print(f"Post #{item['n']} ({item.get('date')}, {t}): {item['caption'][:70]}...")
    if t == "carousel":
        cid = container_carousel(ig, token, item)
    elif t == "reel":
        cid = container_reel(ig, token, item)
    elif t == "image":
        cid = container_image(ig, token, item)
    else:
        die(f"onbekend type {t!r}")
    print("container:", cid)

    if dry:
        print("DRY_RUN — container gemaakt, niet gepubliceerd."); return
    pub = post(f"{ig}/media_publish", {"creation_id": cid}, token)
    print("GEPUBLICEERD media_id:", pub.get("id"))
    if not force:
        gedaan.append(item["n"])
        gpad.write_text(json.dumps(sorted(gedaan)))
        print("geplaatst.json bijgewerkt:", sorted(gedaan))

if __name__ == "__main__":
    main()
