#!/usr/bin/env python3
"""Publiceer @brochurify-posts op WISSELENDE tijden, met een dagdoel.

De workflow draait elk uur in een venster (zie feed-autopost.yml). Elke run beslist
zelf of hij NU post, zodat de posttijd per dag verschilt (niet elke dag hetzelfde moment).
Zo werkt het:
  - Dagdoel: 2 posts/dag t/m BOOST_END (tijdelijke opschroef), daarna 1/dag.
  - Al genoeg geplaatst vandaag? Dan niets doen.
  - Minstens MIN_GAP minuten tussen twee posts op dezelfde dag.
  - Anders kans-op-posten = (nog nodig) / (resterende uurslots), dus de post valt op een
    willekeurig uur; aan het eind van het venster wordt hij geforceerd zodat het dagdoel haalt.

Post de vroegste nog-niet-geplaatste post uit FEED.json (op n-volgorde). Media staat als
absolute, publieke URL in FEED.json (Spaces CDN). Idempotent via geplaatst.json, nu met
tijdstempel per post. DRY_RUN=1 bouwt alleen de container. FORCE_N=<n> post die post nu,
los van dagdoel/tijd (handmatig).
"""
import json, os, sys, time, random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

HERE = Path(__file__).resolve().parent
GRAPH = "https://graph.facebook.com/v21.0"
TZ = ZoneInfo("Europe/Amsterdam")

# --- cadans-instellingen ---
BOOST_END = datetime(2026, 12, 8).date()  # t/m deze dag 2 posts/dag, daarna 1/dag
MIN_GAP = 150            # minuten minimaal tussen twee posts op dezelfde dag
WINDOW_EIND_UUR = 21     # laatste uur (Amsterdam) waarop nog gepost mag worden

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
    params = {"media_type": "REELS", "video_url": item["video_url"], "caption": item["caption"]}
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
    return post(f"{ig}/media", {"image_url": item["image_url"], "caption": item["caption"]}, token)["id"]

def wacht_finished(cid, token, pogingen=20):
    """Wacht tot de container verwerkt is (carrousel/beeld hebben ook even nodig)."""
    for i in range(pogingen):
        code = get(cid, {"fields": "status_code,status"}, token).get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            die(f"Container {cid} kreeg status ERROR.")
        print(f"  wacht op container {i}: {code}")
        time.sleep(6)

def publiceer_met_retry(ig, cid, token, pogingen=10):
    """media_publish; IG geeft soms 9007/2207027 'even geduld' tot de container klaar is."""
    for i in range(pogingen):
        p = {"creation_id": cid, "access_token": token}
        r = requests.post(f"{GRAPH}/{ig}/media_publish", data=p, timeout=120)
        if r.status_code == 200:
            return r.json().get("id")
        body = r.text.replace(token, "***")
        if '2207027' in body or '"code":9007' in body:
            print(f"  container nog niet publiceerbaar (poging {i}), wacht..."); time.sleep(8); continue
        die(f"Graph API fout {r.status_code} op /media_publish:\n{body}")
    die("Container werd niet op tijd publiceerbaar.")

def bouw_en_publiceer(ig, token, item, dry):
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
        print("DRY_RUN — container gemaakt, niet gepubliceerd."); return None
    wacht_finished(cid, token)
    media_id = publiceer_met_retry(ig, cid, token)
    print("GEPUBLICEERD media_id:", media_id)
    return media_id

def main():
    token = os.environ.get("IG_ACCESS_TOKEN"); ig = os.environ.get("IG_USER_ID")
    if not token or not ig:
        die("IG_ACCESS_TOKEN of IG_USER_ID ontbreekt.")
    dry = os.environ.get("DRY_RUN") == "1"

    feed = sorted(json.loads((HERE / "FEED.json").read_text()), key=lambda x: x["n"])
    gpad = HERE / "geplaatst.json"
    gedaan = json.loads(gpad.read_text() or "[]") if gpad.exists() else []
    done_ids = {g["n"] for g in gedaan}
    now = datetime.now(TZ)

    force = os.environ.get("FORCE_N")
    if force:
        item = next((q for q in feed if str(q["n"]) == str(force)), None)
        if not item:
            die(f"FORCE_N={force} niet in FEED.json.")
    else:
        today = now.date().isoformat()
        doel = 2 if now.date() <= BOOST_END else 1
        vandaag = [g for g in gedaan if g["at"][:10] == today]
        if len(vandaag) >= doel:
            print(f"Dagdoel {doel} al gehaald vandaag ({len(vandaag)}). Niets doen."); return
        if vandaag:
            laatst = max(datetime.fromisoformat(g["at"]) for g in vandaag)
            mins = (now - laatst).total_seconds() / 60
            if mins < MIN_GAP:
                print(f"Vorige post {mins:.0f} min geleden (< {MIN_GAP}). Nog even wachten."); return
        nodig = doel - len(vandaag)
        slots_over = max(1, WINDOW_EIND_UUR - now.hour)  # resterende uurslots incl. nu
        moet = slots_over <= nodig
        if not moet and random.random() > nodig / slots_over:
            print(f"Slot overslaan voor spreiding (uur {now.hour}, nodig {nodig}, slots {slots_over})."); return
        item = next((q for q in feed if q["n"] not in done_ids), None)
        if not item:
            print("Wachtrij leeg, niets meer te plaatsen."); return

    media_id = bouw_en_publiceer(ig, token, item, dry)
    if dry or media_id is None:
        return
    gedaan.append({"n": item["n"], "at": now.isoformat(timespec="seconds")})
    gpad.write_text(json.dumps(gedaan, ensure_ascii=False, indent=0))
    print("geplaatst.json bijgewerkt, nu", len(gedaan), "posts.")

if __name__ == "__main__":
    main()
