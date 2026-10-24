# Interactive

This directory contains interactive, browser-based views of the audit data.
Each page reads a data bundle that a Python script writes to `data/processed/explorer/`; the pages compute nothing themselves.

## Contents

- [`archive-taxman-0.1.1/`](archive-taxman-0.1.1/): The D3 explorer of the first pilot (2026-10-04, 270 responses), collected with taxman 0.1.1, which reads its bundle from `data/processed/archive-taxman-0.1.1/explorer/`.

## Other instructions

[`code/generate_figures/build_pilot_explorer_data.py`](../../../code/generate_figures/build_pilot_explorer_data.py) builds the first pilot's bundle shape (queries asked with no location, about Houston, and about Portland) into `data/processed/explorer/`; it has not been adapted to pilot-4cities.
