"""
corpus.py — build a reference corpus of real, public businesses: a name, a
photo, and (for most of them) a declared official website.

Source: Wikidata, via its public SPARQL endpoint (query.wikidata.org). No API
key, no rate-limit problems in practice (unlike some public OSM mirrors, which
is why this project uses Wikidata instead).

Why the "declared website" column matters: it is GROUND TRUTH. Roughly 60% of
entries already have an official website on record. That lets this project
measure contact-discovery precision objectively — run the discovery pipeline
on an entry whose real website is already known, and check whether it found
the same one — rather than relying only on a hand-labelled sample. The other
~40%, with no declared website, is the real target population: a business
with a name and a photo but no contact info on file, same shape as the
original production problem this project generalizes.
"""
import csv
import os
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, os.pardir, "data")
CORPUS_CSV = os.path.join(DATA, "corpus.csv")

UA = "reverse-image-contact-discovery-portfolio-project/1.0 (educational; github.com/rimma-serheieva)"
SPARQL = "https://query.wikidata.org/sparql"

# A handful of business/venue categories with good photo coverage on Wikidata.
# Q11707 restaurant, Q30022 cafe, Q27686 hotel, Q33506 museum.
CATEGORIES = {
    "restaurant": "Q11707",
    "cafe": "Q30022",
    "hotel": "Q27686",
    "museum": "Q33506",
}

QUERY = """
SELECT ?item ?itemLabel ?image ?website ?coord ?cityLabel WHERE {{
  ?item wdt:P31/wdt:P279* wd:{qid} .
  ?item wdt:P18 ?image .
  ?item wdt:P17 wd:Q30 .
  OPTIONAL {{ ?item wdt:P856 ?website }}
  OPTIONAL {{ ?item wdt:P625 ?coord }}
  OPTIONAL {{ ?item wdt:P131 ?city }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT {limit}
"""


def fetch_category(category, qid, limit=400, tries=3):
    for attempt in range(tries):
        try:
            r = requests.get(SPARQL, params={"query": QUERY.format(qid=qid, limit=limit),
                                              "format": "json"},
                             headers={"User-Agent": UA}, timeout=60)
            if r.status_code == 200:
                return r.json()["results"]["bindings"]
        except requests.RequestException:
            pass
        time.sleep(5 * (attempt + 1))
    return []


def build(limit_per_category=300, out_path=CORPUS_CSV):
    os.makedirs(DATA, exist_ok=True)
    seen = set()
    rows = []
    for cat, qid in CATEGORIES.items():
        bindings = fetch_category(cat, qid, limit_per_category)
        print("  %-12s %4d entries from Wikidata" % (cat, len(bindings)), flush=True)
        for b in bindings:
            item_uri = b["item"]["value"]
            qid_of_item = item_uri.rsplit("/", 1)[-1]
            if qid_of_item in seen:
                continue
            seen.add(qid_of_item)
            name = b.get("itemLabel", {}).get("value", "")
            image = b.get("image", {}).get("value", "")
            website = b.get("website", {}).get("value", "")
            city = b.get("cityLabel", {}).get("value", "")
            coord = b.get("coord", {}).get("value", "")
            lat, lon = "", ""
            if coord.startswith("Point("):
                try:
                    lon_s, lat_s = coord[6:-1].split(" ")
                    lat, lon = lat_s, lon_s
                except ValueError:
                    pass
            if name and image:
                rows.append({"qid": qid_of_item, "category": cat, "name": name,
                            "image_url": image, "declared_website": website,
                            "city": city, "lat": lat, "lon": lon})
        time.sleep(2)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["qid", "category", "name", "image_url",
                                          "declared_website", "city", "lat", "lon"])
        w.writeheader()
        w.writerows(rows)

    has_site = sum(1 for r in rows if r["declared_website"])
    print("\n%d corpus entries written to %s" % (len(rows), out_path), flush=True)
    print("  %d already have a declared website (ground truth for validation)"
          % has_site)
    print("  %d have no declared website (the real target population)"
          % (len(rows) - has_site))
    return rows


if __name__ == "__main__":
    build()
