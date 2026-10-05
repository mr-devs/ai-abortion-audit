# Data Collection

This directory contains scripts for gathering and downloading data from various sources.
Data collection scripts handle API calls, web scraping, file downloads, and other data acquisition tasks.

## Contents

- [`run_pilot_audits.sh`](run_pilot_audits.sh): Runs all nine pilot taxman audits, with the three providers in parallel within each location group (base, Houston, Portland) and the groups one after another, then resolves the Gemini citation links.
- [`run_pilot_4cities_audits.sh`](run_pilot_4cities_audits.sh): Runs the three `pilot-4cities-<provider>` audits in parallel, then resolves the Gemini citation links.
- [`download_census_city_populations.py`](download_census_city_populations.py): Downloads the Census Bureau's 2020-2025 city and town population estimates (`sub-est2025.csv`, saved as UTF-8) and its column documentation (`SUB-EST2025.pdf`) to timestamped files; skips any file already downloaded.
- [`download_guttmacher.py`](download_guttmacher.py): Downloads the state data behind Guttmacher's abortion policy map to a timestamped raw JSON file; exits if a download already exists.
- [`write_4cities_messages.py`](write_4cities_messages.py): Writes the `pilot-4cities` taxman message file (one "I live in [city, ST]..." query per selected city) and a crosswalk from taxman message ids to cities.
- [`resolve_gemini_urls.py`](resolve_gemini_urls.py): Resolves the Google redirect URLs that Gemini cites to the URLs Google cited (one HEAD request per link, reading the 302 `Location` header), writing `resolved_urls.jsonl` into each Gemini run directory; skips responses already resolved.

## Other instructions

Each runner does all of the data collection for its pilot: it runs the audits and then resolves the Gemini citation links that [`code/cleaning/clean_citations.py`](../cleaning/clean_citations.py) needs.
Run them from anywhere with:

```bash
bash code/data_collection/run_pilot_audits.sh          # first pilot (nine audits)
bash code/data_collection/run_pilot_4cities_audits.sh  # pilot-4cities (three audits)
```

They run taxman through `uv run`, so they use the version pinned in [`uv.lock`](../../uv.lock) (run `uv sync` first), and the API key environment variables named in the audit files must be set.
Keep the terminal open until they finish; closing it stops the runs.

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
