# Interactive

This directory contains interactive, browser-based views of the audit data.
The pilot-4cities pages are self-contained HTML files; the first pilot's explorer reads a separate data bundle.

## Contents

- [`pilot-4cities/`](pilot-4cities/): Three self-contained pages for the pilot-4cities audit (approach, response explorer, data brief), built by [`code/generate_figures/build_pilot_4cities_pages.py`](../../../code/generate_figures/build_pilot_4cities_pages.py). Each opens with a double-click, with no server or internet connection, and can be shared as a single file.
- [`archive-taxman-0.1.1/`](archive-taxman-0.1.1/): The D3 explorer of the first pilot (2026-10-04, 270 responses), collected with taxman 0.1.1, which reads its bundle from `data/processed/archive-taxman-0.1.1/explorer/`.

## Other instructions

Rebuild the pilot-4cities pages after changing their data or templates (never edit the built HTML):

```bash
uv run python code/analysis/compute_answer_accuracy.py
uv run python code/generate_figures/build_pilot_4cities_pages.py
```

[`code/generate_figures/build_pilot_explorer_data.py`](../../../code/generate_figures/build_pilot_explorer_data.py) builds the first pilot's bundle shape (queries asked with no location, about Houston, and about Portland) into `data/processed/explorer/`; it has not been adapted to pilot-4cities.
