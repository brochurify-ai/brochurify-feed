# brochurify-feed — Instagram feed auto-poster (@brochurify)

Plaatst automatisch **1 feed-post per dag** op Instagram, zonder dat er een
computer aan hoeft te staan. Draait op **GitHub Actions** (dagelijkse cron,
18:00 NL-tijd). Herbruikbaar voor elke volgende batch: nieuwe beelden + nieuwe
regels in `queue.json`, klaar.

## Hoe het werkt
- `images/` — de post-beelden (JPEG, 4:5). Publiek, zodat Instagram ze kan ophalen.
- `queue.json` — per post: `date`, `image`, `caption`.
- `publish.py` — zoekt de post van vandaag (Europe/Amsterdam) en publiceert die via
  de Instagram Content Publishing API. Idempotent via `posted.json`.
- `.github/workflows/feed-autopost.yml` — draait `publish.py` elke dag om 17:00 UTC
  (= 18:00 NL in nov/dec) en commit `posted.json` terug.

## Secrets (Settings → Secrets and variables → Actions)
- `IG_USER_ID` — Instagram Business user-id van @brochurify.
- `IG_ACCESS_TOKEN` — long-lived / system-user token met `instagram_content_publish`.

## Testen zonder te publiceren
Actions → **Feed autopost** → **Run workflow** → `dry_run = 1` (maakt alleen een
media-container). Of `force_n = 5` om post 5 te forceren.

## Een nieuwe batch toevoegen
1. Zet de JPEG's in `images/`.
2. Voeg regels toe aan `queue.json` met nieuwe datums.
3. Commit. De cron pakt ze vanzelf op.
