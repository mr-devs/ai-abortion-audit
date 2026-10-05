# taxman

This directory contains the [ai-taxman](https://pypi.org/project/ai-taxman/) audit files and the messages they send.
The folders are set in the project's [`taxman.yaml`](../taxman.yaml); responses are written to `data/raw/audits/` and logs to `data/logs/taxman/`.

## Contents

- [`audits/`](audits/): One YAML file per audit, named `<study>-<provider>[-<location>].yaml`:
  - `pilot-<provider>.yaml`, `pilot-<provider>-houston-tx.yaml`, `pilot-<provider>-portland-or.yaml`: The first pilot, with ten general questions asked with no location, about Houston, and about Portland (3 repeats).
  - `pilot-4cities-<provider>.yaml`: The pilot-4cities study, with one location-specific query per selected city (1 repeat).
- [`messages/`](messages/): One message per line; taxman numbers them by position (`m0000`, `m0001`, ...):
  - [`pilot-queries.txt`](messages/pilot-queries.txt), [`pilot-queries-houston-tx.txt`](messages/pilot-queries-houston-tx.txt), [`pilot-queries-portland-or.txt`](messages/pilot-queries-portland-or.txt): The first pilot's questions.
  - [`pilot-4cities-queries.txt`](messages/pilot-4cities-queries.txt): "I live in [city, ST]. Where can I get an abortion near me? ..." for each city in the pilot-4cities sample. Written by [`code/data_collection/write_4cities_messages.py`](../code/data_collection/write_4cities_messages.py); do not edit by hand.
- `prompts/`: System prompts (none are used yet).

## Other instructions

Create a new audit with `uv run taxman audits new <provider> <audit-name>`, then edit the generated file; copying an existing YAML can miss settings the current template includes.
Check an audit without sending anything with `uv run taxman audits validate <audit-name>`.
The audits are run by the scripts in [`code/data_collection/`](../code/data_collection/).
