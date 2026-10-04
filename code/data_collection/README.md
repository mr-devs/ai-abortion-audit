# Data Collection

This directory contains scripts for gathering and downloading data from various sources.
Data collection scripts handle API calls, web scraping, file downloads, and other data acquisition tasks.

## Contents

- [`run_pilot_audits.sh`](run_pilot_audits.sh): Runs all nine pilot taxman audits, with the three providers in parallel within each location group (base, Houston, Portland) and the groups one after another.
- [`resolve_gemini_urls.py`](resolve_gemini_urls.py): Resolves the Google redirect URLs that Gemini cites to the URLs Google cited (one HEAD request per link, reading the 302 `Location` header), writing `resolved_urls.jsonl` into each Gemini run directory; skips responses already resolved.

## Other instructions

Run the pilot audits from anywhere with:

```bash
bash code/data_collection/run_pilot_audits.sh
```

It needs `taxman` on your PATH, and the API key environment variables named in the audit files must be set.
Keep the terminal open until it finishes; closing it stops the runs.

After collection, resolve the Gemini citation links (needed before [`code/cleaning/clean_citations.py`](../cleaning/clean_citations.py)):

```bash
uv run python code/data_collection/resolve_gemini_urls.py  # optional: --audit-prefix pilot-
```
