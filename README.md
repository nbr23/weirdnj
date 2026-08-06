# Weird NJ Outlets Map

An interactive map of every shop that sells *Weird NJ*, scraped from the
magazine's [outlets list](https://weirdnj.com/weird-news/outlets-distributors/)
and geocoded onto a Leaflet map with a searchable, town-grouped sidebar.

**415 locations across 227 towns** — 395 pinned to their street address, 20 to
the town centre.

Live at <https://nbr23.github.io/weirdnj/>.

## Run it locally

```sh
docker build -t weirdnj-map .
docker run --rm -p 8080:80 weirdnj-map
```

Then open http://localhost:8080. The geocoded data and Leaflet itself are
committed, so the build needs no network; the browser fetches map tiles from
openstreetmap.org at runtime.

If you allow location access, the map centres on you and the sidebar gains a
"Nearest to you" list. Browsers only offer this over HTTPS or on localhost, so
served from another host over plain HTTP it is silently skipped — on the Pages
site, which is HTTPS, it always works.

`docker compose up` instead refreshes the data first, then serves it.

## Deploy

`.github/workflows/deploy.yml` publishes `web/` to GitHub Pages on every push to
`main` that touches it, or on demand from the Actions tab. There is no build
step — the directory is uploaded as-is — and every asset reference is relative,
so the site works unchanged under the `/weirdnj/` sub-path.

One-time setup: Settings → Pages → Source: **GitHub Actions**. The repo must be
public unless the account has Pro or Team.

## Refresh the data

```sh
./scripts/update.sh           # re-fetch, geocode new rows only
./scripts/update.sh --force   # re-geocode everything (~9 min)
```

Rewrites `web/locations.json`; review the diff before committing. Pushing that
commit redeploys the site.

## Source data

The outlets table is hand-maintained and irregular, so `scripts/build_data.py`
corrects a fair amount as it goes: store name and address share one cell and
must be split (Nominatim returns nothing if the name is left in the query, and
names contain digits, so the address starts at the *last* house number); five
towns are misspelled; three entries are out of state; one shop is listed twice.

Geocoding uses [Nominatim](https://nominatim.openstreetmap.org/) — free, no key,
but rate-limited and unhappy about bulk jobs. Hence the committed output: a
refresh reuses existing coordinates and costs ~40 requests instead of ~470.
The 20 town-level pins are addresses OpenStreetMap lacks at house-number
resolution; those are labelled approximate in the UI and every record carries a
Google Maps link as a fallback.
