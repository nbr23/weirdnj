# Weird NJ Outlets Map

An interactive map of every shop that sells *Weird NJ*, scraped from the
magazine's [outlets list](https://weirdnj.com/weird-news/outlets-distributors/)
and geocoded onto a Leaflet map with a searchable, town-grouped sidebar.

## Run it locally

```sh
docker build -t weirdnj-map .
docker run --rm -p 8080:80 weirdnj-map
```

`docker compose up` instead refreshes the data first, then serves it.

## Container image

`.github/workflows/publish.yml` builds the `Dockerfile` and pushes
`ghcr.io/nbr23/weirdnj` — `:latest` plus a commit-SHA tag — on every push to
`main` that touches `web/`, or on demand from the Actions tab.

## Refresh the data

```sh
./scripts/update.sh           # re-fetch, geocode new rows only
./scripts/update.sh --force   # re-geocode everything (~9 min)
```

Rewrites `web/locations.json`; review the diff before committing. Pushing that
commit publishes a new image.

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
