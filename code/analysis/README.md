# Analysis

This directory contains scripts for data analysis and statistical computations.
Analysis scripts process cleaned data to generate insights, perform statistical tests, and produce results for reporting.

## Contents

- [`compute_response_measures.py`](compute_response_measures.py): Computes per-response measures (word count, web-search use, cited and retrieved source counts, and which abortion-access resources are named) and writes `data/processed/audits/response_measures.parquet` and a report
- [`compute_place_geography.py`](compute_place_geography.py): Locates each recommended in-person place and measures it against the queried city: inside the city limits, geodesic distance from the city's internal point, in another state, and whether that state is a neighbor; writes `data/processed/coding/place_geography.parquet` and a report
- [`compute_answer_accuracy.py`](compute_answer_accuracy.py): Scores the accuracy of each answer with loose, checkable rules: whether each recommended place is locatable, in a state without a total ban, and among the closest options in a reference set pooled from every answer (or an external facility list, once one is added); whether answers for total-ban states send users to a neighboring state; whether stated distances match the measured ones; and whether the answer's claim about state law matches Guttmacher. Writes `place_accuracy`, `response_accuracy`, `reference_facilities`, and `reference_nearest` to `data/processed/coding/` and a report
