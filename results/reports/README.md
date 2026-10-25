# Reports

This directory contains simple text-based reports with statistics and key findings summaries.
Reports are written by the scripts that produce them, as noted below.

## Contents

- [`select_state_cities_report.txt`](select_state_cities_report.txt): The pilot-4cities sample: cities and states selected, states with fewer than four cities, population ties at the cut-off, renamed cities, and the full list (from [`code/cleaning/select_state_cities.py`](../../code/cleaning/select_state_cities.py)).
- [`clean_guttmacher_report.txt`](clean_guttmacher_report.txt): The raw Guttmacher file used and the number of states in each policy category (from [`code/cleaning/clean_guttmacher.py`](../../code/cleaning/clean_guttmacher.py)).
- [`clean_metadata_text_report.txt`](clean_metadata_text_report.txt): Response, run, and status counts (from [`code/cleaning/clean_metadata_text.py`](../../code/cleaning/clean_metadata_text.py)).
- [`clean_citations_report.txt`](clean_citations_report.txt): Text and tool citation counts per response and the Gemini resolution rate (from [`code/cleaning/clean_citations.py`](../../code/cleaning/clean_citations.py)).
- [`clean_text_links_report.txt`](clean_text_links_report.txt): Markdown links, bare URLs, and named sites by provider, and every distinct named site for review (from [`code/cleaning/clean_text_links.py`](../../code/cleaning/clean_text_links.py)).
- [`clean_tool_calls_report.txt`](clean_tool_calls_report.txt): Tool calls by type, calls that did not run, and searches that ran per response (from [`code/cleaning/clean_tool_calls.py`](../../code/cleaning/clean_tool_calls.py)).
- [`clean_token_usage_report.txt`](clean_token_usage_report.txt): Mean and total token usage by provider and token type (from [`code/cleaning/clean_token_usage.py`](../../code/cleaning/clean_token_usage.py)).
- [`build_link_events_report.txt`](build_link_events_report.txt): Link events by provider and channel, citation duplicates, and distinct domains shown to the reader per response (from [`code/cleaning/build_link_events.py`](../../code/cleaning/build_link_events.py)).
- [`compute_response_measures_report.txt`](compute_response_measures_report.txt): Per-response measures by provider: word counts, searches that ran, distinct cited and retrieved sources, and resource mentions (from [`code/analysis/compute_response_measures.py`](../../code/analysis/compute_response_measures.py)).
- [`archive-taxman-0.1.1/`](archive-taxman-0.1.1/): The cleaning, analysis, and explorer reports of the first pilot (2026-10-04), collected with taxman 0.1.1.
