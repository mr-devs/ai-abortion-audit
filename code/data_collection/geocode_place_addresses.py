"""
Purpose:
    Geocode the street addresses of the places AI chatbot responses
    recommended, using the US Census Geocoder, with OpenStreetMap's
    Nominatim as the fallback for addresses the Census cannot match.

Notes:
    Which addresses:
    - Entities with role "primary" or "alternative" (in-person places) and a
      street, from data/processed/coding/place_entities.parquet. Resources
      (hotlines, websites) have no location, and an address with no street
      cannot be placed precisely, so neither is geocoded.
    - Addresses are geocoded as written in the response (street, city, state,
      ZIP). Nothing is corrected, so a wrong address geocodes to the wrong
      place or to none.
    - Each distinct address is geocoded once. address_key, the address
      uppercased with whitespace collapsed ("STREET|CITY|ST|ZIP"), identifies
      it.

    Geocoders:
    - US Census Geocoder (censusgeocode package), batch endpoint, benchmark
      "Public_AR_Current" and vintage "Current_Current"; free, no key, and
      it returns the state and county FIPS codes. Addresses are sent in
      batches of CENSUS_BATCH_SIZE.
    - Nominatim (geopy package), for Census non-matches only, queried with
      the structured address and country "us", one request per second as
      its usage policy requires. Its place_rank says how precise a match is
      (30 = a building, 26-27 = a street; lower = a town or region).
    - Only addresses, which are public facility addresses, are sent; nothing
      identifying the project's users or coders.

    Caching (append-only):
    - Every result, match or not, is appended to a cache file with the date
      it was queried, and an address already in a cache is never sent
      again. Rerunning the script therefore sends only new addresses, and
      the caches are the record of what each geocoder returned. Delete a
      cache file to geocode everything again.

Input:
    - data/processed/coding/place_entities.parquet, from
      code/cleaning/merge_llm_coding.py --task places.

    Usage (from anywhere):
        uv run python code/data_collection/geocode_place_addresses.py

Output:
    - data/raw/geocoding/census_geocoder.jsonl: one JSON record per address
      sent to the Census Geocoder, with keys:
        - address_key (str), street, city, state_abbr, zip (str or null):
          the address sent.
        - queried_on (str): YYYY-MM-DD.
        - benchmark, vintage (str): the Census locator version.
        - match (bool), matchtype (str or null: "Exact" or "Non_Exact"),
          matched_address (str or null), lat, lon (float or null),
          statefp, countyfp, tract, block (str or null), tigerlineid,
          side (str or null): as the Census returned them.
    - data/raw/geocoding/nominatim.jsonl: one JSON record per address sent
      to Nominatim, with keys:
        - address_key, street, city, state_abbr, zip, queried_on: as above.
        - match (bool), matched_address (str or null), lat, lon (float or
          null), place_rank (int or null), osm_class, osm_type (str or null:
          the OSM feature's class and type, e.g. "amenity", "clinic"),
          osm_id (int or null).
    - data/logs/geocode_place_addresses/<YYYY-MM-DD>.log: run log (appended).

Author: Matthew DeVerna
"""

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from censusgeocode import CensusGeocode
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from toolkit.utils import setup_logging

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
ENTITIES_PATH = Path("../../data/processed/coding/place_entities.parquet")
GEOCODING_DIR = Path("../../data/raw/geocoding")
CENSUS_CACHE = GEOCODING_DIR / "census_geocoder.jsonl"
NOMINATIM_CACHE = GEOCODING_DIR / "nominatim.jsonl"
LOG_DIR = Path("../../data/logs/geocode_place_addresses")

PLACE_ROLES = ("primary", "alternative")
ADDRESS_FIELDS = ["street", "city", "state_abbr", "zip"]

CENSUS_BENCHMARK = "Public_AR_Current"
CENSUS_VINTAGE = "Current_Current"
CENSUS_BATCH_SIZE = 1000  # the Census limit is 10,000
CENSUS_TIMEOUT_SECONDS = 600

NOMINATIM_USER_AGENT = "ai-abortion-audit-research"
NOMINATIM_DELAY_SECONDS = 1.0

WHITESPACE_PATTERN = re.compile(r"\s+")


def address_key(row):
    """
    Return the key that identifies an address.

    Parameters
    ----------
    row : mapping
        With street, city, state_abbr, and zip (each str or None).

    Returns
    -------
    str
        "STREET|CITY|ST|ZIP", uppercased, whitespace collapsed; a missing
        part is empty.
    """
    parts = [
        row[field] if isinstance(row[field], str) else "" for field in ADDRESS_FIELDS
    ]
    return "|".join(WHITESPACE_PATTERN.sub(" ", part).strip().upper() for part in parts)


def load_addresses():
    """
    Return the distinct addresses to geocode.

    Returns
    -------
    pandas.DataFrame
        One row per address_key, with street, city, state_abbr, and zip.
    """
    entities = pd.read_parquet(ENTITIES_PATH)
    places = entities[
        entities["role"].isin(PLACE_ROLES) & entities["street"].notna()
    ].copy()
    places["address_key"] = places.apply(address_key, axis=1)
    return places.drop_duplicates("address_key")[["address_key"] + ADDRESS_FIELDS]


def cached_keys(path):
    """
    Return the address keys already in a cache file.

    Parameters
    ----------
    path : pathlib.Path
        A JSONL cache.

    Returns
    -------
    set of str
        The cached keys (empty if the file does not exist).
    """
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        return {json.loads(line)["address_key"] for line in f if line.strip()}


def append_records(path, records):
    """
    Append records to a JSONL cache.

    Parameters
    ----------
    path : pathlib.Path
        The cache.
    records : list of dict
        Records to append.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def geocode_census(addresses, logger):
    """
    Geocode addresses with the Census batch geocoder and cache the results.

    Parameters
    ----------
    addresses : pandas.DataFrame
        Addresses not yet in the Census cache.
    logger : logging.Logger
        Logger for progress messages.
    """
    geocoder = CensusGeocode(benchmark=CENSUS_BENCHMARK, vintage=CENSUS_VINTAGE)
    rows = addresses.to_dict("records")
    for start in range(0, len(rows), CENSUS_BATCH_SIZE):
        chunk = rows[start : start + CENSUS_BATCH_SIZE]
        # The batch file's id is the row's position, so results map back
        # whatever order the Census returns them in.
        request = [
            {
                "id": i,
                "street": row["street"] or "",
                "city": row["city"] or "",
                "state": row["state_abbr"] or "",
                "zip": row["zip"] or "",
            }
            for i, row in enumerate(chunk)
        ]
        results = {
            int(r["id"]): r
            for r in geocoder.addressbatch(request, timeout=CENSUS_TIMEOUT_SECONDS)
        }
        if len(results) != len(chunk):
            raise RuntimeError(
                f"The Census returned {len(results)} of {len(chunk)} results"
            )
        today = date.today().isoformat()
        records = []
        for i, row in enumerate(chunk):
            result = results[i]
            records.append(
                {
                    **row,
                    "queried_on": today,
                    "benchmark": CENSUS_BENCHMARK,
                    "vintage": CENSUS_VINTAGE,
                    "match": result["match"],
                    "matchtype": result["matchtype"],
                    "matched_address": result["parsed"],
                    "lat": result["lat"],
                    "lon": result["lon"],
                    **{
                        k: result[k]
                        for k in [
                            "statefp",
                            "countyfp",
                            "tract",
                            "block",
                            "tigerlineid",
                            "side",
                        ]
                    },
                }
            )
        append_records(CENSUS_CACHE, records)
        logger.info(
            f"Census: {sum(r['match'] for r in records)} of {len(records)} addresses matched"
        )


def geocode_nominatim(addresses, logger):
    """
    Geocode addresses with Nominatim and cache the results.

    Parameters
    ----------
    addresses : pandas.DataFrame
        Census non-matches not yet in the Nominatim cache.
    logger : logging.Logger
        Logger for progress messages.
    """
    geocoder = Nominatim(user_agent=NOMINATIM_USER_AGENT, timeout=60)
    geocode = RateLimiter(geocoder.geocode, min_delay_seconds=NOMINATIM_DELAY_SECONDS)
    n_matched = 0
    for row in addresses.to_dict("records"):
        query = {
            "street": row["street"],
            "city": row["city"],
            "state": row["state_abbr"],
            "postalcode": row["zip"],
            "country": "us",
        }
        location = geocode({k: v for k, v in query.items() if v}, exactly_one=True)
        raw = location.raw if location else {}
        n_matched += location is not None
        # Append one record at a time, so an interrupted run keeps its work.
        append_records(
            NOMINATIM_CACHE,
            [
                {
                    **row,
                    "queried_on": date.today().isoformat(),
                    "match": location is not None,
                    "matched_address": raw.get("display_name"),
                    "lat": float(raw["lat"]) if location else None,
                    "lon": float(raw["lon"]) if location else None,
                    "place_rank": raw.get("place_rank"),
                    "osm_class": raw.get("class"),
                    "osm_type": raw.get("type"),
                    "osm_id": raw.get("osm_id"),
                }
            ],
        )
    logger.info(f"Nominatim: {n_matched} of {len(addresses)} addresses matched")


def main():
    """
    Geocode every address not yet cached.
    """
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    logger = setup_logging(
        log_level="INFO", log_file=str(log_file), console_output=True, append_mode=True
    )
    addresses = load_addresses()
    logger.info(f"{len(addresses)} distinct addresses to place")

    new_census = addresses[~addresses["address_key"].isin(cached_keys(CENSUS_CACHE))]
    logger.info(f"Census: {len(new_census)} not yet cached")
    if len(new_census):
        geocode_census(new_census, logger)

    with open(CENSUS_CACHE, encoding="utf-8") as f:
        census = pd.DataFrame([json.loads(line) for line in f if line.strip()])
    unmatched = set(census.loc[~census["match"], "address_key"])
    new_nominatim = addresses[
        addresses["address_key"].isin(unmatched)
        & ~addresses["address_key"].isin(cached_keys(NOMINATIM_CACHE))
    ]
    logger.info(f"Nominatim: {len(new_nominatim)} Census non-matches not yet cached")
    if len(new_nominatim):
        geocode_nominatim(new_nominatim, logger)
    logger.info("Done")


if __name__ == "__main__":
    main()
