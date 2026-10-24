# Archive: taxman 0.1.1

This directory holds the audit and message files of the first pilot (2026-10-04), which was collected with taxman 0.1.1.
They are kept as a record of what was run and are not meant to be run again: taxman only looks for audits in [`../audits/`](../audits/), and taxman 0.2.0 refuses these files (they set `execution.shuffle`, and the Gemini audits set `temperature` and `top_p`).

## Contents

- [`audits/`](audits/): The nine pilot audit files, `pilot-<provider>[-<location>].yaml`.
- [`messages/`](messages/): The three pilot message files they sent.

## Other instructions

The files are unchanged, so their `messages:` paths and the `messages_path` in each run's manifest still name the original location, `taxman/messages/<file>`; the files now live in [`messages/`](messages/).
The data they produced is in `data/raw/archive-taxman-0.1.1/`, and the runner that collected it is [`code/data_collection/archive-taxman-0.1.1/run_pilot_audits.sh`](../../code/data_collection/archive-taxman-0.1.1/run_pilot_audits.sh).
