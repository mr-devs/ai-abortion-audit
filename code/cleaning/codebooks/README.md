# Codebooks

This directory contains the instructions and output schemas for the coding tasks that the workflow agents in [`.claude/workflows/`](../../../.claude/workflows/) and the human coders both follow.
Each task has a codebook (the rules and every field's definition) and a JSON Schema that [`toolkit.llm_coding`](../../toolkit/toolkit/llm_coding.py) validates coded batches against.

## Contents

- [`place_extraction.md`](place_extraction.md): How to extract, from one response, every place and resource it recommends and the response-level claims (answer type, the state's legal status, travel, telehealth).
- [`place_extraction.schema.json`](place_extraction.schema.json): The JSON Schema of a coded place-extraction batch.
- [`domain_coding.md`](domain_coding.md): How to code a domain shown to readers: the organization's type, stance on abortion access, crisis pregnancy center affiliation, and whether it provides abortions, after visiting its site.
- [`domain_coding.schema.json`](domain_coding.schema.json): The JSON Schema of a coded domain batch.

## Other instructions

[`prepare_llm_coding.py`](../prepare_llm_coding.py) records each codebook's and schema's SHA-256 hash in the task manifest, and the check and merge scripts stop if either has changed since, so edit a codebook only before writing a task's inputs.
