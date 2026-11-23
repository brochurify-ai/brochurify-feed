#!/usr/bin/env python3
"""Post een hele RIJ van 3 (carrousel + Reel + beeld) in volgorde op @brochurify.

Waarom een aparte poster: de feed heeft een vast ritme — navy in de MIDDENKOLOM,
tekst om-en-om op de covers (zie de werkafspraak in de hoofd-repo). Eén losse post
verschuift het raster en breekt dat ritme, dus posten we per RIJ van 3 tegelijk, in
de juiste tijdvolgorde (laatst geplaatste = linksboven). `row.json` staat dus in
POSTVOLGORDE: eerst wat rechtsboven moet landen, als laatst wat linksboven moet landen.

Types in row.json:
  carousel  images:[pad,...]  -> kind-containers (is_carousel_item) + CAROUSEL-container
  reel      video_url:url     -> REELS-container, status pollen tot FINISHED
  image     image:pad         -> losse foto

Env: IG_USER_ID, IG_ACCESS_TOKEN, RAW_BASE (publieke basis voor de lokale beeldpaden).
DRY_RUN=1 maakt wel de containers maar publiceert niet (veilige proef).
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
GRAPH = "https://graph.facebook.com/v21.0"


def die(m):
    print(m, file=sys.stderr)
    sys.exit(1)


def post(path, params, token):
    p = dict(params)
    p["access_token"] = token
    r = requests.post(f"{GRAPH}/{path}", data=p, timeout=180)
    body = r.text.replace(token, "***")
    if r.status_code != 200:
        die(f"Graph API fout {r.status_code} op /{path}:\n{body}")
    return r.json()


def get(path, params, token):
    p = dict(params)
    p["access_token"] = token
    r = requests.get(f"{GRAPH}/{path}", params=p, timeout=60)
    return r.json()


def url_for(raw_base, path):
    return f"{raw_base.rstrip('/')}/{path.lstrip('/')}"


def maak_carousel(ig, token, raw_base, item):
    kids = []
    for img in item["images"]:
        c = post(f"{ig}/media",
                 {"image_url": url_for(raw_base, img), "is_carousel_item": "true"},
                 token)
        kids.append(c["id"])
        print("  kind:", c["id"], img)
    cont = post(f"{ig}/media",
                {"media_type": "CAROUSEL", "children": ",".join(kids),
                 "caption": item["caption"]}, token)
    return cont["id"]


def maak_reel(ig, token, item):
    params = {"media_type": "REELS", "video_url": item["video_url"],
              "caption": item["caption"]}
    if item.get("thumb_offset") is not None:
        params["thumb_offset"] = str(item["thumb_offset"])
    cont = post(f"{ig}/media", params, token)
    cid = cont["id"]
    # Een Reel moet eerst verwerkt worden; pas bij FINISHED mag publish.
    for i in range(50):
        st = get(cid, {"fields": "status_code,status"}, token)
        code = st.get("status_code")
        print(f"  reel-status {i}: {code}")
        if code == "FINISHED":
            return cid
        if code == "ERROR":
            die(f"Reel-verwerking mislukt: {st}")
        time.sleep(6)
    die("Reel werd niet op tijd FINISHED.")


def maak_image(ig, token, raw_base, item):
    c = post(f"{ig}/media",
             {"image_url": url_for(raw_base, item["image"]),
              "caption": item["caption"]}, token)
    return c["id"]


def main():
    token = os.environ.get("IG_ACCESS_TOKEN")
    ig = os.environ.get("IG_USER_ID")
    raw_base = os.environ.get("RAW_BASE", "").rstrip("/")
    dry = os.environ.get("DRY_RUN") == "1"
    if not token or not ig:
        die("IG_ACCESS_TOKEN of IG_USER_ID ontbreekt.")

    row = json.loads((HERE / "row.json").read_text())
    print(f"{len(row)} posts in volgorde (laatste = linksboven). dry={dry}")
    gepubliceerd = []
    for i, item in enumerate(row, 1):
        t = item["type"]
        print(f"[{i}/{len(row)}] {t}")
        if t == "carousel":
            cid = maak_carousel(ig, token, raw_base, item)
        elif t == "reel":
            cid = maak_reel(ig, token, item)
        elif t == "image":
            cid = maak_image(ig, token, raw_base, item)
        else:
            die(f"onbekend type {t!r}")
        print("  container:", cid)
        if dry:
            print("  DRY_RUN — container gemaakt, niet gepubliceerd.")
            continue
        pub = post(f"{ig}/media_publish", {"creation_id": cid}, token)
        print("  GEPUBLICEERD media_id:", pub.get("id"))
        gepubliceerd.append(pub.get("id"))
        time.sleep(5)  # even ademen tussen posts
    print("KLAAR:", gepubliceerd)


if __name__ == "__main__":
    main()
