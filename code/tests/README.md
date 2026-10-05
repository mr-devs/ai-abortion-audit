# Tests

This directory contains unit tests and integration tests for code validation.
Tests ensure code correctness, prevent regressions, and document expected behavior of functions and scripts.

## Contents

- [`test_response_models.py`](test_response_models.py): Tests the per-provider response models and audit-name parsing in `toolkit`, using small inline records that copy the structure of the pilot data.
- [`test_city_sample.py`](test_city_sample.py): Tests the city-name cleaning and city selection in `code/cleaning/select_state_cities.py`, the state abbreviations it takes from the `us` package, and the download-file helpers in `toolkit.utils`.
- [`test_resources.py`](test_resources.py): Tests the resource-mention lexicon in `toolkit.resources`, including near misses such as "I need an abortion" and "Plan B".

## Other instructions

Run the tests with `uv run pytest code/tests`.
