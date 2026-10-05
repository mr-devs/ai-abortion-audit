# Interactive

This directory contains interactive, browser-based views of the audit data.
Each page reads a data bundle that a Python script writes to `data/processed/explorer/`; the pages compute nothing themselves.

## Contents

- [`pilot_explorer.html`](pilot_explorer.html): D3 explorer of the 2026-10-04 pilot (270 responses). It has a query rail with full-text search, plus four tabs:
  - **Responses**: every repeat side by side, by provider for one location or by location for one provider.
  - **Overview**: dot plots of response measures for the selected location, or one panel per location when comparing. Each query × provider line shows every run (one marker shape per run) and their mean.
  - **Resources named**: a dot matrix of the share of responses naming each abortion-access resource.
  - **Search & sources**: search rates, top cited and retrieved domains, and the search strings sent.

## Other instructions

Build the data bundle from the project root, then open the HTML file in a browser (a double-click works; no server is needed):

```bash
uv run python code/analysis/compute_response_measures.py
uv run python code/generate_figures/build_pilot_explorer_data.py
```

The page loads `../../../data/processed/explorer/pilot_explorer_data.js`, so the `data/` symlink must exist (see the `setup-data-symlink` skill).
D3, marked, and DOMPurify load from cdnjs, so the page needs an internet connection.
The view (tab, query, location, and so on) is kept in the URL hash, so a link reopens the same view.
