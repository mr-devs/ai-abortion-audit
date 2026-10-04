# Generate Figures

This directory contains scripts for creating visualizations and plots.
Figure generation scripts transform analysis results into publication-ready charts, graphs, and diagrams.

## Contents

- [`build_pilot_explorer_data.py`](build_pilot_explorer_data.py): Builds `data/processed/pilot_explorer_data.js`, the data bundle read by [`results/figures/interactive/pilot_explorer.html`](../../results/figures/interactive/pilot_explorer.html). It holds response text and every aggregate the page draws: per-query cell means, resource-mention shares, search rates, top domains, and search strings. Run it after [`../analysis/compute_response_measures.py`](../analysis/compute_response_measures.py)
