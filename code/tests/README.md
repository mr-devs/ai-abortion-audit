# Tests

This directory contains unit tests and integration tests for code validation.
Tests ensure code correctness, prevent regressions, and document expected behavior of functions and scripts.

## Contents

- [`test_response_models.py`](test_response_models.py): Tests the per-provider response models, audit-name parsing, and one-row-per-pair response loading in `toolkit`, using small inline taxman 0.2.0 records with raw payloads copied from the pilot data.
- [`test_text_links.py`](test_text_links.py): Tests URL normalization in `toolkit.utils`, the links and website names `toolkit.text_links` finds in text (including non-websites such as emails and "Node.js"), and the citation-duplicate rule and run check in [`code/cleaning/build_link_events.py`](../cleaning/build_link_events.py).
- [`test_city_sample.py`](test_city_sample.py): Tests the city-name cleaning and city selection in [`code/cleaning/select_state_cities.py`](../cleaning/select_state_cities.py), the state abbreviations it takes from the `us` package, and the message-city parsing and download-file helpers in `toolkit.utils`.
- [`test_llm_coding.py`](test_llm_coding.py): Tests the coding-task checks in `toolkit.llm_coding` (verbatim spans, schema errors, altered or missing items, role rules) on small place and domain batches.
- [`test_resources.py`](test_resources.py): Tests the resource-mention lexicon in `toolkit.resources`, including near misses such as "I need an abortion" and "Plan B".

## Other instructions

Run the tests with `uv run pytest code/tests`.
