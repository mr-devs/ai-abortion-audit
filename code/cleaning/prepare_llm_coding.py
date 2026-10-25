"""
Purpose:
    Write the input batches for a codebook coding task, which the Claude Code
    workflows in code/cleaning/workflows/ then code in parallel:
        - places: extract the places and resources each response recommends
          (codebook: code/cleaning/codebooks/place_extraction.md).
        - domains: code each domain shown to readers
          (codebook: code/cleaning/codebooks/domain_coding.md).

Notes:
    Blinding:
    - Coders see an opaque item_id ("r0001" for a response, "d0001" for a
      domain), never the response_id, because response_ids name the audit and
      so the provider. The manifest maps item_ids back to response_ids.
    - Place-extraction records hold only the query (city, state, message) and
      the response text, not the provider or model.

    Items:
    - places: one item per successful response in the study (metadata status
      "ok"), in response_id order before shuffling.
    - domains: one item per distinct domain among the links shown to readers
      (link_events rows with shown_to_reader, counted once where a text link
      duplicates a citation), in domain order before shuffling. Each record
      gives the number of times and responses it was shown and up to
      N_EXAMPLE_URLS of its most often shown normalized URLs.

    Batches:
    - Items are shuffled with a fixed seed (SEED) and split into batches of
      BATCH_SIZE[task], so each batch mixes providers and cities and reruns
      give the same batches.
    - The manifest records the codebook's and schema's SHA-256 hashes, so a
      coded batch can be traced to the exact instructions it was coded with.
    - The script will not overwrite an existing manifest, because coded
      batches depend on it; pass --overwrite to rebuild the inputs (delete or
      move old coded outputs first).

Input:
    - data/processed/audits/metadata.parquet, response_text.parquet, and
      link_events.parquet, from the scripts in code/cleaning/.
    - data/processed/census/selected_cities_4_per_state.csv (for each
      city's geoid, recorded in the manifest).
    - --task (required): "places" or "domains".
    - --study (optional): the study to code (default "pilot-4cities").
    - --overwrite (optional): replace an existing manifest and inputs.

    Usage (from anywhere):
        uv run python code/cleaning/prepare_llm_coding.py --task places

Output:
    - data/interim/llm_coding/<task>/<study>/input/batch_<NNN>.jsonl: one
      JSON record per item. Fields:
        - places: item_id, query_city, query_state_abbr, message, text.
        - domains: item_id, domain, n_shown (times shown to readers),
          n_responses (responses that showed it), example_urls (list of str).
    - data/interim/llm_coding/<task>/<study>/output/: empty; the workflow
      writes one coded batch_<NNN>.json here per input batch.
    - data/interim/llm_coding/<task>/<study>/manifest.json, with keys:
        - task, study, created_on (YYYY-MM-DD), seed, batch_size, n_items.
        - codebook_path, schema_path (relative to the repository root), and
          codebook_sha256, schema_sha256.
        - items (list): {item_id, response_id} (places) or {item_id, domain}
          (domains).
        - batches (list): {batch_id, input_path, output_path, item_ids};
          paths are relative to the repository root.

Author: Matthew DeVerna
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from toolkit.llm_coding import write_batches

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
REPO_ROOT = Path("../..")
AUDITS_DIR = REPO_ROOT / "data/processed/audits"
CITIES_PATH = REPO_ROOT / "data/processed/census/selected_cities_4_per_state.csv"
CODING_DIR = REPO_ROOT / "data/interim/llm_coding"
CODEBOOK_DIR = Path("codebooks")

TASKS = ("places", "domains")
CODEBOOKS = {
    "places": ("place_extraction.md", "place_extraction.schema.json"),
    "domains": ("domain_coding.md", "domain_coding.schema.json"),
}
# About 20 responses (~40k characters) per agent; domains need a site visit
# each, so an agent gets 10.
BATCH_SIZE = {"places": 20, "domains": 10}
SEED = 20261024
N_EXAMPLE_URLS = 5


def parse_args():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        With attributes ``task``, ``study``, and ``overwrite``.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2].strip())
    parser.add_argument("--task", required=True, choices=TASKS)
    parser.add_argument("--study", default="pilot-4cities")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def place_records(study):
    """
    Build one blinded input record per successful response in a study.

    Parameters
    ----------
    study : str
        The study to include.

    Returns
    -------
    tuple of (list of dict, list of dict)
        (records, items): records are the coder's inputs; items map each
        item_id to its response_id.
    """
    metadata = pd.read_parquet(AUDITS_DIR / "metadata.parquet")
    text = pd.read_parquet(AUDITS_DIR / "response_text.parquet")
    responses = (
        metadata[(metadata["study"] == study) & (metadata["status"] == "ok")]
        .merge(
            text[["response_id", "text"]],
            on="response_id",
            how="left",
            validate="one_to_one",
        )
        .sort_values("response_id")
        .reset_index(drop=True)
    )
    if responses["text"].isna().any():
        sys.exit("Some responses have no text; rebuild response_text.parquet")

    records, items = [], []
    for i, row in enumerate(responses.itertuples(), start=1):
        item_id = f"r{i:04d}"
        records.append(
            {
                "item_id": item_id,
                "query_city": row.city,
                "query_state_abbr": row.state_abbr,
                "message": row.message,
                "text": row.text,
            }
        )
        items.append({"item_id": item_id, "response_id": row.response_id})
    return records, items


def domain_records(study):
    """
    Build one input record per distinct domain shown to readers in a study.

    Parameters
    ----------
    study : str
        The study to include.

    Returns
    -------
    tuple of (list of dict, list of dict)
        (records, items): records are the coder's inputs; items map each
        item_id to its domain.
    """
    metadata = pd.read_parquet(
        AUDITS_DIR / "metadata.parquet", columns=["response_id", "study"]
    )
    events = pd.read_parquet(AUDITS_DIR / "link_events.parquet")
    study_ids = set(metadata.loc[metadata["study"] == study, "response_id"])
    shown = events[
        events["response_id"].isin(study_ids)
        & events["shown_to_reader"]
        & events["duplicate_of_citation"].isna()
        & events["domain"].notna()
    ]

    records, items = [], []
    for i, (domain, rows) in enumerate(shown.groupby("domain", sort=True), start=1):
        item_id = f"d{i:04d}"
        examples = rows["url_norm"].dropna().value_counts().index[:N_EXAMPLE_URLS]
        records.append(
            {
                "item_id": item_id,
                "domain": domain,
                "n_shown": len(rows),
                "n_responses": rows["response_id"].nunique(),
                "example_urls": list(examples),
            }
        )
        items.append({"item_id": item_id, "domain": domain})
    return records, items


def sha256(path):
    """
    Return the SHA-256 hex digest of a file.

    Parameters
    ----------
    path : pathlib.Path
        The file.

    Returns
    -------
    str
        The digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_relative(path):
    """
    Return a path relative to the repository root, as a string.

    Parameters
    ----------
    path : pathlib.Path
        A path relative to this script's directory.

    Returns
    -------
    str
        The same path relative to the repository root (where workflow
        agents run).
    """
    # Not resolved: data/ may be a symbolic link to another drive.
    return os.path.relpath(path, REPO_ROOT)


def main():
    """
    Write the batches and manifest for one task.
    """
    args = parse_args()
    task_dir = CODING_DIR / args.task / args.study
    manifest_path = task_dir / "manifest.json"
    if manifest_path.exists() and not args.overwrite:
        sys.exit(f"{manifest_path} exists; pass --overwrite to rebuild the inputs")

    builder = place_records if args.task == "places" else domain_records
    records, items = builder(args.study)
    batches = write_batches(records, task_dir / "input", BATCH_SIZE[args.task], SEED)
    (task_dir / "output").mkdir(parents=True, exist_ok=True)

    codebook, schema = (CODEBOOK_DIR / name for name in CODEBOOKS[args.task])
    for batch in batches:
        batch["input_path"] = repo_relative(Path(batch["input_path"]))
        batch["output_path"] = repo_relative(
            task_dir / "output" / f"{batch['batch_id']}.json"
        )
    manifest = {
        "task": args.task,
        "study": args.study,
        "created_on": date.today().isoformat(),
        "seed": SEED,
        "batch_size": BATCH_SIZE[args.task],
        "n_items": len(records),
        "codebook_path": repo_relative(codebook),
        "schema_path": repo_relative(schema),
        "codebook_sha256": sha256(codebook),
        "schema_sha256": sha256(schema),
        "items": items,
        "batches": batches,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(records)} {args.task} items in {len(batches)} batches to {task_dir}"
    )


if __name__ == "__main__":
    main()
