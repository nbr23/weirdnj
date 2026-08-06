# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests>=2.31",
#     "beautifulsoup4>=4.12",
# ]
# ///
"""Build web/locations.json from the Weird NJ outlets page.

Street-level coordinates already in web/locations.json are reused, so a routine
refresh only geocodes new rows. Use --force to re-geocode everything.
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://weirdnj.com/weird-news/outlets-distributors/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "weirdnj-outlets-map/1.0 (self-hosted store locator; contact via project repository)"
OUTPUT = Path(__file__).resolve().parent.parent / "web" / "locations.json"

NOMINATIM_DELAY = 1.1
MAX_RETRIES = 5
BACKOFF_SECONDS = 10

PHONE_RE = re.compile(
    r"(\(\d{3}\)\s*\d{3}[-.\s]?\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b|\+1\s?\d{10})"
)

# Hyphenated house numbers are real: Fair Lawn addresses look like "12-23 River Rd".
HOUSE_RE = re.compile(r"^\d+(?:-\d+)?[A-Za-z]?\s+[A-Za-z0-9]")

# Matches only the leading token so finditer can find every candidate start.
# The lookbehind catches the row written as "Barnes & Noble1156 US-46".
ADDRESS_RE = re.compile(
    r"(?:^|[,\s]|(?<=[A-Za-z]))(\d+(?:-\d+)?[A-Za-z]?\s+[A-Za-z0-9])"
)

# Nominatim usually fails on a suite suffix, so it is stripped for a retry.
SUITE_RE = re.compile(
    r"(?:\s*#\s*[\w-]+"
    r"|\s+(?:Unit|Ste\.?|Suite|Apt\.?|Bldg\.?|Building)\s*#?\s*[\w-]+"
    r"|\s+[A-Z])$",
    re.IGNORECASE,
)

STATE_NAMES = {"NJ": "New Jersey", "NY": "New York", "PA": "Pennsylvania"}

# City cells that aren't a plain town name, mapped to (display, geocode, state).
# A literal table beats a heuristic here: the two Menlo Park Mall spellings need
# opposite halves of the parenthesised pair.
CITY_OVERRIDES = {
    "Adelphia / Howell": ("Adelphia", "Adelphia", "NJ"),
    "Allamuchy / Hackettstown": ("Hackettstown", "Hackettstown", "NJ"),
    "Edison (Menlo Park Mall)": ("Edison", "Edison", "NJ"),
    "Menlo Park Mall (Edison)": ("Edison", "Edison", "NJ"),
    "Fairless Hills, PA": ("Fairless Hills", "Fairless Hills", "PA"),
    "New Hope, PA": ("New Hope", "New Hope", "PA"),
    "Suffern, NY": ("Suffern", "Suffern", "NY"),
    "South Amboy (Bordentown Rd.)": ("South Amboy", "South Amboy", "NJ"),
    "Easton PA": ("Easton", "Easton", "PA"),
    # Misspelled in the source; OSM only knows the correct spelling.
    "Fairlawn": ("Fair Lawn", "Fair Lawn", "NJ"),
    "Westfeild": ("Westfield", "Westfield", "NJ"),
    "Succasuna": ("Succasunna", "Succasunna", "NJ"),
    "Lavalette": ("Lavallette", "Lavallette", "NJ"),
    "N. Plainfield": ("North Plainfield", "North Plainfield", "NJ"),
}


def clean(text):
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip(" ,.•")


def parse_rows(html):
    table = BeautifulSoup(html, "html.parser").find("table")
    if table is None:
        raise SystemExit("No <table> found on the outlets page - the page layout changed.")

    records = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        city_raw = clean(cells[0].get_text(" ", strip=True))
        body = clean(cells[1].get_text(" ", strip=True))
        if not city_raw and not body:
            continue

        link = cells[1].find("a", href=True)
        city, geocode_city, state = CITY_OVERRIDES.get(city_raw, (city_raw, city_raw, "NJ"))

        phone_match = PHONE_RE.search(body)
        phone = clean(phone_match.group(0)) if phone_match else None
        body = clean(PHONE_RE.sub("", body))

        name, address = split_name_address(body)
        address = strip_trailing_city(address, geocode_city)

        records.append(
            {
                "city": city,
                "name": name,
                "address": address,
                "phone": phone,
                "url": link["href"] if link else None,
                "maps_url": maps_url(name, address, city, state),
                "geocode_city": geocode_city,
                "state": state,
            }
        )
    return records


def split_name_address(body):
    """Split "Pantry 1 Food Mart, 440 Lake Ave" into name and street address.

    Store names often contain their own digits ("Act 2 Books", "19 Express"),
    so the address starts at the *last* house number, not the first number in
    the string.
    """
    parts = [clean(part) for part in body.split(",")]
    if len(parts) > 1:
        for index in range(len(parts) - 1, 0, -1):
            if HOUSE_RE.match(parts[index]):
                return ", ".join(parts[:index]), ", ".join(parts[index:])

    matches = list(ADDRESS_RE.finditer(body))
    for match in reversed(matches):
        name = clean(body[: match.start(1)])
        if name:
            return name, clean(body[match.start(1):])
    if matches:
        return "", clean(body)
    return body, None


def strip_trailing_city(address, city):
    """Drop a town name repeated at the end of the address ("... 517, Hackettstown")."""
    if not address:
        return address
    trimmed = re.sub(rf",\s*{re.escape(city)}\.?$", "", address, flags=re.IGNORECASE)
    return clean(trimmed) or address


def maps_url(name, address, city, state):
    parts = [p for p in (name, address, city, state) if p]
    query = urllib.parse.urlencode({"api": 1, "query": ", ".join(parts)})
    return f"https://www.google.com/maps/search/?{query}"


def dedupe(records):
    seen = {}
    for record in records:
        seen.setdefault(identity(record), record)
    return list(seen.values())


def identity(record):
    return (record["name"], record["address"], record["city"])


class RateLimited(SystemExit):
    pass


class Geocoder:
    def __init__(self, session):
        self.session = session
        self.cache = {}
        self.requests_made = 0

    def request(self, query):
        """Query Nominatim, backing off on throttling and transient errors.

        Aborts once the retry budget is gone: treating a 429 as "no result"
        would write a wrong coordinate and then cache it as a real answer.
        """
        for attempt in range(MAX_RETRIES):
            if self.requests_made:
                time.sleep(NOMINATIM_DELAY)
            self.requests_made += 1

            try:
                response = self.session.get(
                    NOMINATIM_URL,
                    params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
                    timeout=30,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                backoff = BACKOFF_SECONDS * (2**attempt)
                print(
                    f"  ! {exc} for {query!r} - retrying in {backoff}s"
                    f" ({attempt + 1}/{MAX_RETRIES})",
                    file=sys.stderr,
                )
                time.sleep(backoff)

        raise RateLimited(
            f"Nominatim kept refusing requests (last query: {query!r}).\n"
            "Existing data was left untouched. Wait a while, then re-run;\n"
            "already-geocoded rows are reused, so the retry is much shorter."
        )

    def lookup(self, query, state):
        if query in self.cache:
            return self.cache[query]

        results = self.request(query)

        hit = None
        if results:
            found = results[0]
            # Guard against Nominatim drifting into another state entirely.
            if STATE_NAMES.get(state, state) in found.get("display_name", ""):
                hit = (float(found["lat"]), float(found["lon"]))

        self.cache[query] = hit
        return hit

    def geocode(self, record):
        where = f"{record['geocode_city']}, {record['state']}"

        if record["address"]:
            candidates = [record["address"]]
            without_suite = clean(SUITE_RE.sub("", record["address"]))
            if without_suite and without_suite != record["address"]:
                candidates.append(without_suite)

            for address in candidates:
                hit = self.lookup(f"{address}, {where}", record["state"])
                if hit:
                    return hit[0], hit[1], "address"

        hit = self.lookup(where, record["state"])
        if hit:
            return hit[0], hit[1], "city"

        return None, None, "none"


def load_existing():
    if not OUTPUT.exists():
        return {}
    try:
        entries = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Ignoring unreadable {OUTPUT.name}: {exc}", file=sys.stderr)
        return {}
    # Only street-level hits are final. Town-level and missing results are
    # retried every run, so extractor fixes take effect without --force.
    return {
        identity(entry): entry for entry in entries if entry.get("precision") == "address"
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-geocode every row instead of reusing cached coordinates"
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print(f"Fetching {SOURCE_URL}", file=sys.stderr)
    response = session.get(SOURCE_URL, timeout=60)
    response.raise_for_status()

    records = parse_rows(response.text)
    total = len(records)
    records = dedupe(records)
    print(f"Parsed {total} rows, {len(records)} after dedupe", file=sys.stderr)

    cached = {} if args.force else load_existing()
    geocoder = Geocoder(session)
    entries = []
    reused = 0

    for index, record in enumerate(records, 1):
        previous = cached.get(identity(record))
        if previous:
            lat, lon, precision = previous["lat"], previous["lon"], previous["precision"]
            reused += 1
        else:
            lat, lon, precision = geocoder.geocode(record)
            print(f"  [{index}/{len(records)}] {precision:7} {record['name']}", file=sys.stderr)

        entries.append(
            {
                "city": record["city"],
                "name": record["name"],
                "address": record["address"],
                "phone": record["phone"],
                "url": record["url"],
                "maps_url": record["maps_url"],
                "lat": lat,
                "lon": lon,
                "precision": precision,
            }
        )

    entries.sort(key=lambda e: (e["city"].lower(), e["name"].lower()))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    counts = {"address": 0, "city": 0, "none": 0}
    for entry in entries:
        counts[entry["precision"]] += 1

    print(
        f"\nWrote {OUTPUT} - {len(entries)} records\n"
        f"  address precision : {counts['address']}\n"
        f"  city precision    : {counts['city']}\n"
        f"  not located       : {counts['none']}\n"
        f"  reused from cache : {reused}\n"
        f"  nominatim requests: {geocoder.requests_made}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
