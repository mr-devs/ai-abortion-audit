# taxman

This directory contains the [ai-taxman](https://pypi.org/project/ai-taxman/) audit files and the messages they send.
The folders are set in the project's [`taxman.yaml`](../taxman.yaml); responses are written to `data/raw/audits/` and logs to `data/logs/taxman/`.
Everything here runs with taxman 0.2.0, the version pinned in [`uv.lock`](../uv.lock).

## Contents

- [`audits/`](audits/): One YAML file per audit, named `<study>-<provider>[-<location>].yaml`:
  - `pilot-4cities-<provider>.yaml`: The pilot-4cities study, with one location-specific query per selected city (1 repeat).
- [`messages/`](messages/): One message per line; taxman gives each message an id that is a UUID5 of its text, so the same text has the same id in every file and run:
  - [`pilot-4cities-queries.txt`](messages/pilot-4cities-queries.txt): "I live in [city, ST]. Where can I get an abortion near me? ..." for each city in the pilot-4cities sample. Written by [`code/data_collection/write_4cities_messages.py`](../code/data_collection/write_4cities_messages.py); do not edit by hand.
  - [`pilot-4cities-queries-lookup.csv`](messages/pilot-4cities-queries-lookup.csv): Each pilot-4cities message with its taxman `message_id` (the output of `taxman messages ids`).
- [`archive-taxman-0.1.1/`](archive-taxman-0.1.1/): The first pilot's audit and message files, collected with taxman 0.1.1; kept as a record and not run again.
- `prompts/`: System prompts (none are used yet).

## Other instructions

Create a new audit with `uv run taxman audits new <provider> <audit-name>`, then edit the generated file; copying an existing YAML can miss settings the current template includes.
Check an audit without sending anything with `uv run taxman audits validate <audit-name>`.
List the id of every message in a file with `uv run taxman messages ids taxman/messages/<file>.txt`.
The audits are run by the scripts in [`code/data_collection/`](../code/data_collection/).
