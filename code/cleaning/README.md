# Cleaning

This directory contains the scripts that turn the raw taxman audit responses into tidy parquet tables in [`data/processed/audits/`](../../data/processed/audits/), plus the scripts that prepare the reference data: the city sample ([`data/processed/census/`](../../data/processed/census/)) and Guttmacher state policies ([`data/processed/guttmacher/`](../../data/processed/guttmacher/)).
Each audit script discovers runs through taxman's `manifest.json` files (complete runs only), parses every response through `toolkit.response_models`, and runs validation checks before writing anything.

## Contents

- [`clean_metadata_text.py`](clean_metadata_text.py): Builds `metadata` (one row per response, including study and location), `response_text`, and `audit_runs` (one row per taxman run).
- [`clean_citations.py`](clean_citations.py): Builds `text_citations` (URLs cited in the response text, with Gemini's resolved URLs joined in) and `tool_citations` (URLs search tools returned), each with a `domain` column.
- [`clean_tool_calls.py`](clean_tool_calls.py): Builds `tool_calls` (one row per search, page open, or code execution), including Anthropic code-execution outcomes.
- [`clean_token_usage.py`](clean_token_usage.py): Builds the long-format `token_usage` table, with a `unit` for every token type.
- [`select_state_cities.py`](select_state_cities.py): Selects the pilot-4cities sample from the Census file: the two most and two least populated incorporated places in each state (DC excluded, zero-population places dropped), with official and everyday city names.
- [`clean_guttmacher.py`](clean_guttmacher.py): Turns the newest raw Guttmacher download into one JSONL record per state and a CSV of each state's policy category and rank.

## Other instructions

Run [`code/data_collection/resolve_gemini_urls.py`](../data_collection/resolve_gemini_urls.py) before `clean_citations.py`; the citations script stops if a Gemini run has not been resolved.
The other scripts do not depend on each other and can run in any order:

```bash
uv run python code/data_collection/resolve_gemini_urls.py
uv run python code/cleaning/clean_metadata_text.py
uv run python code/cleaning/clean_citations.py
uv run python code/cleaning/clean_tool_calls.py
uv run python code/cleaning/clean_token_usage.py
```

Every audit script accepts `--audit-prefix` (e.g. `--audit-prefix pilot-`) to include only some audits.
The output filenames do not change with the prefix, so a filtered run overwrites the full tables.
Use `--audit-prefix pilot-4cities-` for the pilot-4cities audits alone; `pilot-` matches both pilots.
Each script also writes a short summary to [`results/reports/`](../../results/reports/).

`select_state_cities.py` and `clean_guttmacher.py` read the newest download in `data/raw/census/` and `data/raw/guttmacher/`; see [`code/data_collection/README.md`](../data_collection/README.md) for the order to run them in.
