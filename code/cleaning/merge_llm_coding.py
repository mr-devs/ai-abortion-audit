"""
Purpose:
    Check and combine the coded batches of a codebook coding task into
    analysis tables, mapping every blinded item back to its response (or
    domain) and the audit it came from.

Notes:
    Checks (toolkit.llm_coding.check_batch, the same checks the workflow
    agents ran):
    - Fatal: a missing batch (unless --allow-missing), invalid JSON, a
      schema error, or items that are missing, extra, duplicated, or whose
      copied input fields changed. The script stops without writing.
    - Kept as flags: "verbatim" (a copied span is not in the response) and
      "consistency" problems. The agents fix these before finishing, so any
      left are listed in check_problems on the row they belong to and in the
      report, for the human coders to look at first.
    - The codebook and schema must still match the hashes in the manifest.

    Mapping back:
    - item_ids are mapped to response_ids (places) or domains through the
      manifest, then joined to metadata.parquet for the audit, run, message,
      repeat, provider, model, and query city; and to the city sample for
      the city's Census geoid.

Input:
    - data/interim/llm_coding/<task>/<study>/manifest.json, input/, and
      output/, from code/cleaning/prepare_llm_coding.py and the workflows in
      .claude/workflows/.
    - data/processed/audits/metadata.parquet.
    - data/processed/census/selected_cities_4_per_state.csv.
    - --task (required): "places" or "domains".
    - --study (optional): default "pilot-4cities".
    - --allow-missing (optional): combine the batches that exist and list
      the missing ones in the report, instead of stopping.

    Usage (from anywhere):
        uv run python code/cleaning/merge_llm_coding.py --task places

Output:
    Every table has these provenance columns: item_id, batch_id,
    extractor_model, extracted_on, codebook_sha256, and check_problems (list
    of str; empty when the row passed every check).

    For --task places, in data/processed/coding/:
    - place_responses.parquet: one row per response, with:
        - response_id, audit, study, run_id, message_id, repeat, provider,
          model (from metadata).
        - location, query_city, query_state_abbr (the city in the message),
          geoid (the city's Census place GEOID).
        - answer_status, asks_follow_up, follow_up_request_verbatim,
          state_law_claim, state_law_quote_verbatim, says_travel_needed,
          mentions_telehealth, mentions_gestational_limits,
          mentions_financial_help, extractor_notes: as defined in
          code/cleaning/codebooks/place_extraction.md.
        - n_entities, n_primary, n_alternative, n_resource (int).
    - place_entities.parquet: one row per entity a response recommends,
      with response_id, the same audit and query columns, and every entity
      field in the codebook (entity_index, role, list_position,
      name_verbatim, entity_type, possible_cpc_name,
      presented_as_abortion_provider, services_verbatim, address_verbatim,
      street, city, state_abbr, zip, address_parts_from_context,
      phones_verbatim (list of str), website_verbatim,
      distance_claim_verbatim, caveat_verbatim, evidence_quote).
      (response_id, entity_index) is the primary key.

    For --task domains, in data/processed/coding/:
    - domain_codes.parquet: one row per domain shown to readers, with
      domain, n_shown, n_responses, example_urls (from the input), and
      category, stance_on_abortion_access, cpc_affiliated,
      provides_abortions, site_loaded, evidence_urls, rationale, confidence
      (defined in code/cleaning/codebooks/domain_coding.md).

    - results/reports/merge_llm_coding_<task>_report.txt: batch status,
      value counts of the main codes, and every flagged problem.

Author: Matthew DeVerna
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd

from toolkit.llm_coding import check_batch, format_problem, load_schema

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
REPO_ROOT = Path("../..")
CODING_DIR = REPO_ROOT / "data/interim/llm_coding"
METADATA_PATH = REPO_ROOT / "data/processed/audits/metadata.parquet"
CITIES_PATH = REPO_ROOT / "data/processed/census/selected_cities_4_per_state.csv"
OUTPUT_DIR = REPO_ROOT / "data/processed/coding"
REPORT_DIR = REPO_ROOT / "results/reports"

FATAL_KINDS = {"missing", "json", "schema", "ids"}
METADATA_COLUMNS = [
    "response_id",
    "audit",
    "study",
    "run_id",
    "message_id",
    "repeat",
    "provider",
    "model",
    "location",
]
PROVENANCE_COLUMNS = [
    "item_id",
    "batch_id",
    "extractor_model",
    "extracted_on",
    "codebook_sha256",
    "check_problems",
]
ROLES = ("primary", "alternative", "resource")


def parse_args():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        With attributes ``task``, ``study``, and ``allow_missing``.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2].strip())
    parser.add_argument("--task", required=True, choices=("places", "domains"))
    parser.add_argument("--study", default="pilot-4cities")
    parser.add_argument("--allow-missing", action="store_true")
    return parser.parse_args()


def load_batches(manifest, allow_missing):
    """
    Check every batch and load the ones that pass.

    Parameters
    ----------
    manifest : dict
        The task manifest.
    allow_missing : bool
        Skip missing batches instead of stopping.

    Returns
    -------
    tuple of (list of dict, list of dict, list of str)
        (items, flagged, missing): every coded item with its batch's
        provenance added, the non-fatal problems, and missing batch_ids.
    """
    schema = load_schema(REPO_ROOT / manifest["schema_path"])
    items, flagged, missing, fatal = [], [], [], []
    for batch in manifest["batches"]:
        problems = check_batch(
            manifest["task"],
            REPO_ROOT / batch["input_path"],
            REPO_ROOT / batch["output_path"],
            schema,
        )
        if any(p["kind"] == "missing" for p in problems):
            missing.append(batch["batch_id"])
            continue
        fatal += [
            f"{batch['batch_id']} {format_problem(p)}"
            for p in problems
            if p["kind"] in FATAL_KINDS
        ]
        flagged += [p for p in problems if p["kind"] not in FATAL_KINDS]
        coded = json.loads(
            (REPO_ROOT / batch["output_path"]).read_text(encoding="utf-8")
        )
        for item in coded["items"]:
            item.update(
                batch_id=coded["batch_id"],
                extractor_model=coded["extractor_model"],
                extracted_on=coded["extracted_on"],
                codebook_sha256=manifest["codebook_sha256"],
            )
            items.append(item)

    if fatal:
        sys.exit("Fatal problems; fix or recode these batches:\n" + "\n".join(fatal))
    if missing and not allow_missing:
        sys.exit(
            f"Missing batches (pass --allow-missing to skip): {', '.join(missing)}"
        )
    return items, flagged, missing


def problems_by_row(flagged):
    """
    Group flagged problems by the row they belong to.

    Parameters
    ----------
    flagged : list of dict
        Non-fatal problems from ``check_batch``.

    Returns
    -------
    tuple of (dict, dict)
        ({item_id: [str]}, {(item_id, entity_index): [str]}): problems on the
        item itself, and problems on one of its entities.
    """
    on_items, on_entities = {}, {}
    for found in flagged:
        if found["entity_index"] is None:
            on_items.setdefault(found["item_id"], []).append(format_problem(found))
        else:
            key = (found["item_id"], found["entity_index"])
            on_entities.setdefault(key, []).append(format_problem(found))
    return on_items, on_entities


def query_columns(manifest):
    """
    Map every place item to its response's audit and query columns.

    Parameters
    ----------
    manifest : dict
        The places manifest.

    Returns
    -------
    pandas.DataFrame
        One row per item: item_id, response_id, the METADATA_COLUMNS,
        query_city, query_state_abbr, and geoid.
    """
    metadata = pd.read_parquet(METADATA_PATH)
    cities = pd.read_csv(CITIES_PATH, dtype={"geoid": str})
    ids = pd.DataFrame(manifest["items"])
    table = (
        ids.merge(
            metadata[METADATA_COLUMNS + ["city", "state_abbr"]],
            on="response_id",
            how="left",
            validate="one_to_one",
        )
        .rename(columns={"city": "query_city", "state_abbr": "query_state_abbr"})
        .merge(
            cities[["city_clean", "state_abbr", "geoid"]],
            left_on=["query_city", "query_state_abbr"],
            right_on=["city_clean", "state_abbr"],
            how="left",
            validate="many_to_one",
        )
        .drop(columns=["city_clean", "state_abbr"])
    )
    if table["audit"].isna().any() or table["geoid"].isna().any():
        sys.exit("Some items did not match metadata or the city sample")
    return table


def build_place_tables(manifest, items, flagged):
    """
    Build the response and entity tables for the places task.

    Parameters
    ----------
    manifest : dict
        The places manifest.
    items : list of dict
        Coded items from ``load_batches``.
    flagged : list of dict
        Non-fatal problems.

    Returns
    -------
    tuple of (pandas.DataFrame, pandas.DataFrame)
        (place_responses, place_entities).
    """
    on_items, on_entities = problems_by_row(flagged)
    queries = query_columns(manifest)
    # The coder echoed query_city and query_state_abbr; the check confirmed
    # they match the input, so the metadata copies are used.
    response_rows, entity_rows = [], []
    for item in items:
        entities = item.pop("entities")
        for field in ["query_city", "query_state_abbr"]:
            item.pop(field)
        counts = {
            f"n_{role}": sum(e["role"] == role for e in entities) for role in ROLES
        }
        response_rows.append(
            {
                **item,
                "n_entities": len(entities),
                **counts,
                "check_problems": on_items.get(item["item_id"], []),
            }
        )
        for entity in entities:
            key = (item["item_id"], entity["entity_index"])
            entity_rows.append(
                {
                    **{c: item[c] for c in PROVENANCE_COLUMNS if c != "check_problems"},
                    **entity,
                    "check_problems": on_entities.get(key, []),
                }
            )

    id_columns = (
        ["response_id"]
        + METADATA_COLUMNS[1:]
        + ["query_city", "query_state_abbr", "geoid"]
    )
    responses = queries.merge(pd.DataFrame(response_rows), on="item_id", how="inner")
    responses = responses[
        id_columns
        + [c for c in responses.columns if c not in id_columns + PROVENANCE_COLUMNS]
        + PROVENANCE_COLUMNS
    ]
    entities = queries.merge(pd.DataFrame(entity_rows), on="item_id", how="inner")
    entities = entities[
        id_columns
        + [c for c in entities.columns if c not in id_columns + PROVENANCE_COLUMNS]
        + PROVENANCE_COLUMNS
    ].sort_values(["response_id", "entity_index"])
    assert not entities.duplicated(["response_id", "entity_index"]).any()
    return responses.sort_values("response_id").reset_index(
        drop=True
    ), entities.reset_index(drop=True)


def build_domain_table(manifest, items, flagged):
    """
    Build the domain codes table.

    Parameters
    ----------
    manifest : dict
        The domains manifest.
    items : list of dict
        Coded items from ``load_batches``.
    flagged : list of dict
        Non-fatal problems.

    Returns
    -------
    pandas.DataFrame
        One row per domain.
    """
    on_items, _ = problems_by_row(flagged)
    inputs = []
    for batch in manifest["batches"]:
        with open(REPO_ROOT / batch["input_path"], encoding="utf-8") as f:
            inputs += [json.loads(line) for line in f if line.strip()]
    coded = pd.DataFrame(items).drop(columns=["domain"])
    coded["check_problems"] = coded["item_id"].map(lambda i: on_items.get(i, []))
    table = pd.DataFrame(inputs).merge(
        coded, on="item_id", how="inner", validate="one_to_one"
    )
    first = ["domain", "n_shown", "n_responses", "example_urls"]
    table = table[
        first
        + [c for c in table.columns if c not in first + PROVENANCE_COLUMNS]
        + PROVENANCE_COLUMNS
    ]
    return table.sort_values("domain").reset_index(drop=True)


def write_report(task, manifest, tables, flagged, missing):
    """
    Write the merge report.

    Parameters
    ----------
    task : str
        "places" or "domains".
    manifest : dict
        The task manifest.
    tables : dict of {str: pandas.DataFrame}
        The tables written, by name.
    flagged : list of dict
        Non-fatal problems.
    missing : list of str
        Missing batch_ids.
    """
    lines = [
        f"merge_llm_coding.py report ({task}, {manifest['study']})",
        "",
        f"Batches: {len(manifest['batches'])} in the manifest, {len(missing)} missing"
        + (f" ({', '.join(missing)})" if missing else ""),
        f"Codebook SHA-256: {manifest['codebook_sha256']}",
    ]
    for name, table in tables.items():
        lines += ["", f"{name}: {len(table)} rows"]
        lines += [
            "Extractor models:",
            table["extractor_model"].value_counts().to_string(),
        ]
    if task == "places":
        responses, entities = tables["place_responses"], tables["place_entities"]
        for col in ["answer_status", "state_law_claim"]:
            lines += [
                "",
                f"{col} by provider:",
                pd.crosstab(responses[col], responses["provider"]).to_string(),
            ]
        lines += ["", "Entities per response by provider (mean):"]
        lines.append(
            responses.groupby("provider")[
                ["n_entities", "n_primary", "n_alternative", "n_resource"]
            ]
            .mean()
            .round(2)
            .to_string()
        )
        lines += [
            "",
            "entity_type by role:",
            pd.crosstab(entities["entity_type"], entities["role"]).to_string(),
        ]
    else:
        table = tables["domain_codes"]
        for col in [
            "category",
            "stance_on_abortion_access",
            "cpc_affiliated",
            "confidence",
        ]:
            lines += ["", f"{col}:", table[col].value_counts().to_string()]
    lines += ["", f"Flagged problems ({len(flagged)}):"]
    lines += [f"  {format_problem(p)}" for p in flagged] or ["  (none)"]
    path = REPORT_DIR / f"merge_llm_coding_{task}_report.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Check, combine, and write one task's coded batches.
    """
    args = parse_args()
    manifest_path = CODING_DIR / args.task / args.study / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ["codebook", "schema"]:
        digest = hashlib.sha256(
            (REPO_ROOT / manifest[f"{key}_path"]).read_bytes()
        ).hexdigest()
        if digest != manifest[f"{key}_sha256"]:
            sys.exit(f"The {key} changed after the inputs were written")

    items, flagged, missing = load_batches(manifest, args.allow_missing)
    if args.task == "places":
        responses, entities = build_place_tables(manifest, items, flagged)
        tables = {"place_responses": responses, "place_entities": entities}
    else:
        tables = {"domain_codes": build_domain_table(manifest, items, flagged)}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_parquet(OUTPUT_DIR / f"{name}.parquet", index=False)
    write_report(args.task, manifest, tables, flagged, missing)
    print(", ".join(f"{name}: {len(t)} rows" for name, t in tables.items()))


if __name__ == "__main__":
    main()
