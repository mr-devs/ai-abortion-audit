"""
Purpose:
    Download the state data behind Guttmacher's "US Abortion Policies and
    Access After Roe" interactive map (https://states.guttmacher.org/policies/).

Notes:
    Source:
    - The map is built from a public Cockpit CMS API. One GET of its
      `states` collection with populate=1 returns every state entry with its
      policy category, summary sentences, and structured policy filters.
    - The API is paged with limit/skip in case it caps the number of results
      per request; there is a one-second pause between pages.
    - The response is saved untouched, apart from two added keys:
      `_downloaded_on` (the download date, YYYY-MM-DD) and `_source_url`.

    No re-downloads:
    - The filename gets the date and time of the download, for the record.
      Before downloading, the script looks for an earlier download (any
      timestamp). If one exists, it logs a warning and ends; delete the
      existing file to download it again.

    Checks:
    - Logs a warning unless exactly 51 entries (50 states + DC) come back.

Input:
    - None. The API URL is a constant below.

    Usage (from anywhere):
        uv run python code/data_collection/download_guttmacher.py

Output:
    - data/raw/guttmacher/guttmacher_raw_states_<YYYY-MM-DD_HHMMSS>.json:
      the API response, with keys:
        - entries (list of dict): one entry per state, as returned.
        - fields (dict): the CMS schema of an entry's fields.
        - total (int): number of entries the API reports.
        - _downloaded_on (str): download date, YYYY-MM-DD.
        - _source_url (str): the URL requested.
    - data/logs/download_guttmacher/<YYYY-MM-DD>.log: run log (appended).

Author: Matthew DeVerna
"""

import json
import os
import time
from datetime import date, datetime
from pathlib import Path

import requests

from toolkit.utils import find_existing_downloads, setup_logging, timestamped_path

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
URL = "https://states.guttmacher.org/policies/admin/api/collections/get/states/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (academic research)",
    "Referer": "https://states.guttmacher.org/policies/",
    "Accept": "application/json",
}
PAGE_SIZE = 100
SECONDS_BETWEEN_PAGES = 1
REQUEST_TIMEOUT_SECONDS = 30
EXPECTED_ENTRIES = 51  # 50 states + DC
OUTPUT_DIR = Path("../../data/raw/guttmacher")
OUTPUT_STEM = "guttmacher_raw_states"
OUTPUT_SUFFIX = ".json"
LOG_DIR = Path("../../data/logs/download_guttmacher")


def download_states():
    """
    Fetch every state entry from the API, paging with limit/skip.

    Returns
    -------
    dict
        The last page's payload with `entries` replaced by the entries from
        all pages.
    """
    entries, skip, payload = [], 0, {}
    while True:
        params = {"populate": 1, "limit": PAGE_SIZE, "skip": skip}
        response = requests.get(
            URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("entries", [])
        entries.extend(batch)
        total = payload.get("total", len(entries))
        # Stop on a short page or once the reported total is reached.
        if len(batch) < PAGE_SIZE or len(entries) >= total:
            break
        skip += PAGE_SIZE
        time.sleep(SECONDS_BETWEEN_PAGES)
    return {**payload, "entries": entries}


def main():
    """
    Download the Guttmacher state data unless an earlier download exists.
    """
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    logger = setup_logging(
        log_level="INFO", log_file=str(log_file), console_output=True, append_mode=True
    )
    logger.info("Downloading Guttmacher state policy data")

    existing = find_existing_downloads(OUTPUT_DIR, OUTPUT_STEM, OUTPUT_SUFFIX)
    if existing:
        logger.warning(
            f"Guttmacher data already exists: {', '.join(str(p) for p in existing)}. "
            "Delete the existing file if you want to re-download it. Exiting."
        )
        return

    data = download_states()
    data["_downloaded_on"] = date.today().isoformat()
    data["_source_url"] = URL + "?populate=1"

    out_path = timestamped_path(OUTPUT_DIR, OUTPUT_STEM, OUTPUT_SUFFIX)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    n_entries = len(data["entries"])
    logger.info(f"Saved {n_entries} entries to {out_path}")
    if n_entries != EXPECTED_ENTRIES:
        logger.warning(f"Expected {EXPECTED_ENTRIES} entries (50 states + DC).")


if __name__ == "__main__":
    main()
