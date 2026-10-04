# Reports

This directory contains simple text-based reports with statistics and key findings summaries.
Reports are written by the scripts that produce them, as noted below.

## Contents

- [`clean_metadata_text_report.txt`](clean_metadata_text_report.txt): Row counts per table, responses per provider and location by status, and successful responses without text (from `code/cleaning/clean_metadata_text.py`).
- [`clean_citations_report.txt`](clean_citations_report.txt): Text and tool citation counts per response by provider and location, the Gemini resolution rate, and rows dropped for a null URL (from `code/cleaning/clean_citations.py`).
- [`clean_tool_calls_report.txt`](clean_tool_calls_report.txt): Tool calls by provider and tool type, and searches per response by provider and location (from `code/cleaning/clean_tool_calls.py`).
- [`clean_token_usage_report.txt`](clean_token_usage_report.txt): Mean and sum of every token type by provider (from `code/cleaning/clean_token_usage.py`).
- [`compute_response_measures_report.txt`](compute_response_measures_report.txt): Mean words, search rate, searches, cited and retrieved URLs, and resources named per response, plus the share of responses naming each resource, by provider and location (from `code/analysis/compute_response_measures.py`).
- [`build_pilot_explorer_data_report.txt`](build_pilot_explorer_data_report.txt): Size of the explorer data bundle and its record counts (from `code/generate_figures/build_pilot_explorer_data.py`).
