# Generate Figures

This directory contains scripts for creating visualizations and plots.
Figure generation scripts transform analysis results into publication-ready charts, graphs, and diagrams.

## Contents

- [`build_pilot_explorer_data.py`](build_pilot_explorer_data.py): Builds `data/processed/explorer/pilot_explorer_data.js`, the data bundle read by the first pilot's explorer, [`results/figures/interactive/archive-taxman-0.1.1/pilot_explorer.html`](../../results/figures/interactive/archive-taxman-0.1.1/pilot_explorer.html) (whose own bundle is archived in `data/processed/archive-taxman-0.1.1/explorer/`); it expects the first pilot's locations and has not been adapted to pilot-4cities. It holds response text and every aggregate the page draws: per-query cell means, resource-mention shares, search rates, top domains, and search strings. Run it after [`../analysis/compute_response_measures.py`](../analysis/compute_response_measures.py)
