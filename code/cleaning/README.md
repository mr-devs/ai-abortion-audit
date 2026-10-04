# Cleaning

This directory contains the scripts that turn the raw taxman audit responses into tidy parquet tables in [`data/processed/`](../../data/processed/).
Each script discovers runs through taxman's `manifest.json` files (complete runs only), parses every response through `toolkit.response_models`, and runs validation checks before writing anything.

## Contents

- [`clean_metadata_text.py`](clean_metadata_text.py): Builds `metadata` (one row per response, including study and location), `response_text`, and `audit_runs` (one row per taxman run).
- [`clean_citations.py`](clean_citations.py): Builds `text_citations` (URLs cited in the response text, with Gemini's resolved URLs joined in) and `tool_citations` (URLs search tools returned), each with a `domain` column.
- [`clean_tool_calls.py`](clean_tool_calls.py): Builds `tool_calls` (one row per search, page open, or code execution), including Anthropic code-execution outcomes.
- [`clean_token_usage.py`](clean_token_usage.py): Builds the long-format `token_usage` table, with a `unit` for every token type.

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

Every script accepts `--audit-prefix` (e.g. `--audit-prefix pilot-`) to include only some audits.
The output filenames do not change with the prefix, so a filtered run overwrites the full tables.
Each script also writes a short summary to [`results/reports/`](../../results/reports/).
