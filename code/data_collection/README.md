# Data Collection

This directory contains scripts for gathering and downloading data from various sources.
Data collection scripts handle API calls, web scraping, file downloads, and other data acquisition tasks.

## Contents

- [`run_pilot_4cities_audits.sh`](run_pilot_4cities_audits.sh): Runs the three `pilot-4cities-<provider>` audits in parallel, then resolves the Gemini citation links.
- [`download_census_city_populations.py`](download_census_city_populations.py): Downloads the Census Bureau's 2020-2025 city and town population estimates (`sub-est2025.csv`, saved as UTF-8) and its column documentation (`SUB-EST2025.pdf`) to timestamped files; skips any file already downloaded.
- [`download_guttmacher.py`](download_guttmacher.py): Downloads the state data behind Guttmacher's abortion policy map to a timestamped raw JSON file; exits if a download already exists.
- [`write_4cities_messages.py`](write_4cities_messages.py): Writes the `pilot-4cities` taxman message file (one "I live in [city, ST]..." query per selected city), in the order of the cities file.
- [`resolve_gemini_urls.py`](resolve_gemini_urls.py): Resolves the Google redirect URLs that Gemini cites to the URLs Google cited (one HEAD request per link, reading the 302 `Location` header), writing `resolved_urls.jsonl` into each Gemini run directory; skips responses already resolved.
- [`archive-taxman-0.1.1/`](archive-taxman-0.1.1/): The runner that collected the first pilot with taxman 0.1.1 (`run_pilot_audits.sh`); kept as a record, it no longer runs.

## Other instructions

The runner does all of the data collection for its pilot: it runs the audits and then resolves the Gemini citation links that [`code/cleaning/clean_citations.py`](../cleaning/clean_citations.py) needs.
Run it from anywhere with:

```bash
bash code/data_collection/run_pilot_4cities_audits.sh
```

It runs taxman through `uv run`, so it uses the version pinned in [`uv.lock`](../../uv.lock) (run `uv sync` first), and the API key environment variables named in the audit files must be set.
Keep the terminal open until it finishes; closing it stops the runs.
If a run is interrupted, run the script again: taxman finishes each audit's latest run, sending only the responses it is missing or that failed.

To resolve Gemini citation links on their own (e.g. after an interrupted run):

```bash
uv run python code/data_collection/resolve_gemini_urls.py  # optional: --audit-prefix pilot-4cities-
```

### pilot-4cities inputs

Build the city sample and its message file in this order before running the pilot-4cities audits:

```bash
uv run python code/data_collection/download_census_city_populations.py
uv run python code/cleaning/select_state_cities.py
uv run python code/data_collection/write_4cities_messages.py
```

The Guttmacher policy data, used to map results by state, is separate:

```bash
uv run python code/data_collection/download_guttmacher.py
uv run python code/cleaning/clean_guttmacher.py
```

The download scripts never overwrite: if a file was already downloaded, they warn and skip it.
Delete the existing file to download it again.
