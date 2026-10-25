# Workflows

This directory contains the Claude Code workflow scripts that code the audit data in parallel: each script splits a coding task into batches and gives each batch to one Sonnet agent, which follows a codebook, writes its coded batch, and checks it with [`code/cleaning/check_coding_batch.py`](../../code/cleaning/check_coding_batch.py) before finishing.

## Contents

- [`extract-recommended-places.js`](extract-recommended-places.js): Extracts the places and resources each response recommends (names, addresses, phone numbers, types, and response-level claims such as the state's legal status), following [`code/cleaning/codebooks/place_extraction.md`](../../code/cleaning/codebooks/place_extraction.md).
- [`code-domains.js`](code-domains.js): Codes each domain shown to readers (organization type, stance on abortion access, crisis pregnancy center affiliation) after visiting its site, following [`code/cleaning/codebooks/domain_coding.md`](../../code/cleaning/codebooks/domain_coding.md).

## Other instructions

Each task runs in three steps, from the repository root:

1. Write the input batches: `uv run python code/cleaning/prepare_llm_coding.py --task places` (or `--task domains`).
2. Ask Claude Code to run the workflow, e.g. "run the extract-recommended-places workflow". Both scripts take optional args: `manifest` (default: the pilot-4cities manifest), `batch_ids` (code only these batches), and `overwrite` (recode batches that already pass the check). The workflow returns `failed_batch_ids`; rerun those by passing them as `batch_ids`. Batches that already pass are skipped, so rerunning the whole workflow is safe.
3. Combine the coded batches: `uv run python code/cleaning/merge_llm_coding.py --task places`.

Agents see only blinded item ids (`r0001`, `d0001`), never response ids or providers.
Changing a codebook or schema after step 1 makes the check fail, so every batch is coded with the same instructions; rerun step 1 with `--overwrite` (after moving the old outputs) to recode with new instructions.
