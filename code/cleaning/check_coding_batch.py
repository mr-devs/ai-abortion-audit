"""
Purpose:
    Check one coded batch from a codebook coding task against its input and
    the task's JSON Schema. The workflow agents run this on their own output
    and fix what it reports before they finish.

Notes:
    - Checks (toolkit.llm_coding.check_batch): the output exists and is
      valid JSON; it matches the schema; it has exactly one item per input
      item with the input fields unchanged; for places, every verbatim field
      and evidence quote appears in the response (ignoring curly quotes,
      markdown emphasis, and whitespace), entity indexes run 1..n, list
      positions belong only to primary entities, and answer_status agrees
      with the entities.
    - The codebook and schema hashes must still match the manifest, so a
      batch is never coded with instructions that changed after the inputs
      were written.

Input:
    - data/interim/llm_coding/<task>/<study>/manifest.json, written by
      code/cleaning/prepare_llm_coding.py.
    - --manifest (required): path to the manifest.
    - --batch-id (required): e.g. "batch_000".

    Usage (from the repository root, as the workflow agents run it):
        uv run python code/cleaning/check_coding_batch.py \
            --manifest data/interim/llm_coding/places/pilot-4cities/manifest.json \
            --batch-id batch_000

Output:
    - Prints "OK" and exits 0 if the batch passes; otherwise prints one line
      per problem ("<kind>: <message>") and exits 1.

Author: Matthew DeVerna
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from toolkit.llm_coding import check_batch, format_problem, load_schema

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
# Paths given on the command line are relative to the repository root.
REPO_ROOT = Path("../..")
MAX_PROBLEMS_SHOWN = 50


def parse_args():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        With attributes ``manifest`` and ``batch_id``.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2].strip())
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--batch-id", required=True)
    return parser.parse_args()


def main():
    """
    Check the batch and report the result.
    """
    args = parse_args()
    manifest = json.loads((REPO_ROOT / args.manifest).read_text(encoding="utf-8"))
    batch = next(
        (b for b in manifest["batches"] if b["batch_id"] == args.batch_id), None
    )
    if batch is None:
        sys.exit(f"{args.batch_id} is not in {args.manifest}")

    for key in ["codebook", "schema"]:
        digest = hashlib.sha256(
            (REPO_ROOT / manifest[f"{key}_path"]).read_bytes()
        ).hexdigest()
        if digest != manifest[f"{key}_sha256"]:
            sys.exit(
                f"The {key} changed after the inputs were written; rerun prepare_llm_coding.py"
            )

    problems = check_batch(
        manifest["task"],
        REPO_ROOT / batch["input_path"],
        REPO_ROOT / batch["output_path"],
        load_schema(REPO_ROOT / manifest["schema_path"]),
    )
    if not problems:
        print("OK")
        return
    for found in problems[:MAX_PROBLEMS_SHOWN]:
        print(format_problem(found))
    if len(problems) > MAX_PROBLEMS_SHOWN:
        print(f"... and {len(problems) - MAX_PROBLEMS_SHOWN} more")
    sys.exit(1)


if __name__ == "__main__":
    main()
