# Analysis

This directory contains scripts for data analysis and statistical computations.
Analysis scripts process cleaned data to generate insights, perform statistical tests, and produce results for reporting.

## Contents

- [`compute_response_measures.py`](compute_response_measures.py): Computes per-response measures (word count, web-search use, cited and retrieved source counts, and which abortion-access resources are named) and writes `data/processed/audits/response_measures.parquet` and a report
- [`compute_place_geography.py`](compute_place_geography.py): Locates each recommended in-person place and measures it against the queried city: inside the city limits, geodesic distance from the city's internal point, in another state, and whether that state is a neighbor; writes `data/processed/coding/place_geography.parquet` and a report
