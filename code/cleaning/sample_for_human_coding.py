"""
Purpose:
    Draw the sample of items that human coders code blind, to measure how
    well the workflow agents' coding agrees with human coding.

Notes:
    Blind design:
    - Coders code each sampled item from scratch with
      code/cleaning/human_code.py, following the same codebook as the
      agents, and never see the agents' codes. Agreement is computed
      afterwards. The sample is drawn from the task manifest, not from the
      agents' output, so it does not depend on what the agents coded.

    Samples:
    - places: N_ITEMS responses, split as evenly as possible across
      providers (a remainder goes to providers in alphabetical order), so
      each provider's agreement can be estimated; drawn at random within
      each provider. The provider is used only to draw the sample; coders
      see blinded item_ids.
    - domains: N_ITEMS domains drawn at random.
    - The draw uses a fixed seed (SEED) and the items are shuffled, so the
      sample and its order are the same on every run and coders do not see
      providers in blocks. The script will not overwrite an existing sample;
      pass --overwrite to draw again (only before coding starts).

Input:
    - data/interim/llm_coding/<task>/<study>/manifest.json, from
      code/cleaning/prepare_llm_coding.py.
    - data/processed/audits/metadata.parquet (places: each response's
      provider).
    - --task (required): "places" or "domains".
    - --study (optional): default "pilot-4cities".
    - --overwrite (optional): replace an existing sample.

    Usage (from anywhere):
        uv run python code/cleaning/sample_for_human_coding.py --task places

Output:
    - data/interim/human_coding/<task>/<study>/sample.json, with keys:
        - task, study, seed, created_on (YYYY-MM-DD), n_items.
        - n_by_stratum (dict): items per provider (places) or {"all": n}.
        - manifest_path (str): the manifest the items come from, relative to
          the repository root.
        - item_ids (list of str): the sampled items, in coding order.

Author: Matthew DeVerna
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
REPO_ROOT = Path("../..")
CODING_DIR = REPO_ROOT / "data/interim/llm_coding"
METADATA_PATH = REPO_ROOT / "data/processed/audits/metadata.parquet"
OUTPUT_DIR = REPO_ROOT / "data/interim/human_coding"

N_ITEMS = 100
SEED = 20261025


def parse_args():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        With attributes ``task``, ``study``, and ``overwrite``.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2].strip())
    parser.add_argument("--task", required=True, choices=("places", "domains"))
    parser.add_argument("--study", default="pilot-4cities")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def stratum_sizes(groups, n):
    """
    Split n as evenly as possible across groups.

    Parameters
    ----------
    groups : list of str
        Group names, sorted.
    n : int
        Total sample size.

    Returns
    -------
    dict
        {group: size}; the remainder goes to the first groups.
    """
    base, extra = divmod(n, len(groups))
    return {g: base + (i < extra) for i, g in enumerate(groups)}


def draw_sample(task, manifest):
    """
    Draw the sample of item_ids.

    Parameters
    ----------
    task : str
        "places" or "domains".
    manifest : dict
        The task manifest.

    Returns
    -------
    tuple of (list of str, dict)
        (item_ids in coding order, {stratum: n sampled}).
    """
    items = pd.DataFrame(manifest["items"])
    if task == "places":
        providers = pd.read_parquet(METADATA_PATH, columns=["response_id", "provider"])
        items = items.merge(
            providers, on="response_id", how="left", validate="one_to_one"
        )
        sizes = stratum_sizes(sorted(items["provider"].unique()), N_ITEMS)
        sample = pd.concat(
            items[items["provider"] == provider].sample(n=size, random_state=SEED)
            for provider, size in sizes.items()
        )
    else:
        sample = items.sample(n=min(N_ITEMS, len(items)), random_state=SEED)
        sizes = {"all": len(sample)}
    # Shuffle so coders do not see the strata in blocks.
    return sample.sample(frac=1, random_state=SEED)["item_id"].tolist(), sizes


def main():
    """
    Draw the sample and write sample.json.
    """
    args = parse_args()
    out_path = OUTPUT_DIR / args.task / args.study / "sample.json"
    if out_path.exists() and not args.overwrite:
        sys.exit(f"{out_path} exists; pass --overwrite to draw again")

    manifest_path = CODING_DIR / args.task / args.study / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    item_ids, sizes = draw_sample(args.task, manifest)

    record = {
        "task": args.task,
        "study": args.study,
        "seed": SEED,
        "created_on": date.today().isoformat(),
        "n_items": len(item_ids),
        "n_by_stratum": {k: int(v) for k, v in sizes.items()},
        # Not resolved: data/ may be a symbolic link to another drive.
        "manifest_path": os.path.relpath(manifest_path, REPO_ROOT),
        "item_ids": item_ids,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote a sample of {len(item_ids)} {args.task} items ({sizes}) to {out_path}"
    )


if __name__ == "__main__":
    main()
