# Cleaning

This directory contains the scripts that turn the raw taxman audit responses into tidy parquet tables in [`data/processed/audits/`](../../data/processed/audits/), plus the scripts that prepare the reference data: the city sample ([`data/processed/census/`](../../data/processed/census/)) and Guttmacher state policies ([`data/processed/guttmacher/`](../../data/processed/guttmacher/)).
Each audit script discovers runs through taxman's `manifest.json` files (complete runs only), parses every response through `toolkit.response_models`, and runs validation checks before writing anything.

## Contents

- [`clean_metadata_text.py`](clean_metadata_text.py): Builds `metadata` (one row per response, including study and location; for pilot-4cities, location, city, and state_abbr are parsed from the message), `response_text`, and `audit_runs` (one row per taxman run).
- [`clean_citations.py`](clean_citations.py): Builds `text_citations` (structured citations attached to the response text, with Gemini's resolved URLs joined in and character offsets for every provider) and `tool_citations` (URLs search tools returned), each with `url_norm` and `domain` columns.
- [`clean_text_links.py`](clean_text_links.py): Builds `text_links`: every markdown link, bare URL, and website named without a link (e.g. "ineedana.com") in the response text, with no list of known sites filtering the matches; the report lists every distinct named site for later review.
- [`clean_tool_calls.py`](clean_tool_calls.py): Builds `tool_calls` (one row per search, page open, or code execution), including Anthropic code-execution outcomes, the error code of rejected calls, and whether each call ran.
- [`build_link_events.py`](build_link_events.py): Stacks the cleaned citation, text-link, search-result, and opened-page tables into `link_events`, one row per link occurrence with a `channel` and `shown_to_reader` flag, and marks text links that are the same object as a citation (every OpenAI citation is one markdown link) so they are counted once.
- [`clean_token_usage.py`](clean_token_usage.py): Builds the long-format `token_usage` table, with a `unit` for every token type.
- [`select_state_cities.py`](select_state_cities.py): Selects the pilot-4cities sample from the Census file: the two most and two least populated incorporated places in each state (DC excluded, zero-population places dropped), with official and everyday city names.
- [`clean_guttmacher.py`](clean_guttmacher.py): Turns the newest raw Guttmacher download into one JSONL record per state and a CSV of each state's policy category and rank.

## Other instructions

Run [`code/data_collection/resolve_gemini_urls.py`](../data_collection/resolve_gemini_urls.py) before [`clean_citations.py`](clean_citations.py); the citations script stops if a Gemini run has not been resolved.
Run [`build_link_events.py`](build_link_events.py) last: it reads the tables the other scripts write, and stops if they were not all built from the same runs (each table records the runs it covers).
The other scripts do not depend on each other and can run in any order:

```bash
uv run python code/data_collection/resolve_gemini_urls.py
uv run python code/cleaning/clean_metadata_text.py
uv run python code/cleaning/clean_citations.py
uv run python code/cleaning/clean_text_links.py
uv run python code/cleaning/clean_tool_calls.py
uv run python code/cleaning/clean_token_usage.py
uv run python code/cleaning/build_link_events.py
```

Every audit script except [`build_link_events.py`](build_link_events.py) accepts `--audit-prefix` (e.g. `--audit-prefix pilot-`) to include only some audits.
The output filenames do not change with the prefix, so a filtered run overwrites the full tables; run every script with the same prefix.
Use `--audit-prefix pilot-4cities-` for the pilot-4cities audits alone; `pilot-` matches both pilots.
Each script also writes a short summary to [`results/reports/`](../../results/reports/).

[`select_state_cities.py`](select_state_cities.py) and [`clean_guttmacher.py`](clean_guttmacher.py) read the newest download in [`data/raw/census/`](../../data/raw/census/) and [`data/raw/guttmacher/`](../../data/raw/guttmacher/); see [`code/data_collection/README.md`](../data_collection/README.md) for the order to run them in.
