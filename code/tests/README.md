# Tests

This directory contains unit tests and integration tests for code validation.
Tests ensure code correctness, prevent regressions, and document expected behavior of functions and scripts.

## Contents

- [`test_response_models.py`](test_response_models.py): Tests the per-provider response models and audit-name parsing in `toolkit`, using small inline records that copy the structure of the pilot data.

## Other instructions

Run the tests with `uv run pytest code/tests`.
