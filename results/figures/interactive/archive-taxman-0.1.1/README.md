# Archive: taxman 0.1.1

This directory holds the interactive explorer of the first pilot (2026-10-04, 270 responses), which was collected with taxman 0.1.1.

## Contents

- [`pilot_explorer.html`](pilot_explorer.html): D3 explorer with a query rail with full-text search and four tabs: **Responses** (every repeat side by side), **Overview** (dot plots of response measures), **Resources named** (share of responses naming each abortion-access resource), and **Search & sources** (search rates, top domains, and search strings).

## Other instructions

Open the HTML file in a browser (a double-click works; no server is needed).
It loads its data bundle from `../../../../data/processed/archive-taxman-0.1.1/explorer/pilot_explorer_data.js`, so the `data/` symlink must exist (see the `setup-data-symlink` skill); D3, marked, and DOMPurify load from cdnjs, so it needs an internet connection.
The bundle is not rebuilt: [`code/generate_figures/build_pilot_explorer_data.py`](../../../../code/generate_figures/build_pilot_explorer_data.py) now writes to `data/processed/explorer/`.
