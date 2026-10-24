# Archive: taxman 0.1.1

This directory holds data collection scripts that ran with taxman 0.1.1 and no longer run under the version pinned in [`uv.lock`](../../../uv.lock).
They are kept as a record of how the first pilot's data was collected.

## Contents

- [`run_pilot_audits.sh`](run_pilot_audits.sh): Ran the nine first-pilot audits on 2026-10-04, with the three providers in parallel within each location group (base, Houston, Portland), then resolved the Gemini citation links.

## Other instructions

The code that cleaned and analyzed this data (in [`code/cleaning/`](../../cleaning/), [`code/analysis/`](../../analysis/), and [`code/generate_figures/`](../../generate_figures/)) was not archived; its 0.1.1-compatible version is in the git history before the upgrade to taxman 0.2.0.
