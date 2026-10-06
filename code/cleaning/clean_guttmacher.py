"""
Purpose:
    Clean the raw Guttmacher policy-map data.

Notes:
    Policy category (environment_type):
    - The map sorts states into seven categories, from "Most Restrictive" to
      "Most Protective". The raw API spells some inconsistently (e.g.
      "Some restrictions/protections", "restrictive"); they are matched case
      insensitively to the canonical spellings in CATEGORIES. An unrecognized
      category is kept as is and reported.
    - category_rank numbers the categories 1 (Most Restrictive) to
      7 (Most Protective).

    Dates:
    - as_of is the date Guttmacher last edited the state's entry in its CMS
      (the entry's `_modified` timestamp, in UTC). It is not necessarily the
      date a policy took effect.
    - downloaded_on comes from the raw file's `_downloaded_on` key, or from
      the file's modification date for files saved before that key existed.

    Other fields:
    - Single-valued fields are kept as the strings the API returns (trimmed;
      empty values become null). Fields in the API's schema come first, so
      every record has the same keys even when a state lacks one.
    - The pipe-delimited `policies_currently_in_effect` string becomes the
      list policy_summary; the structured `filters` become policies, grouped
      by type in the order the map lists them.
    - CMS bookkeeping fields (_id, _by, _mby, _created, _modified, _o, _pid,
      _link) are dropped.

    Joining to Census data:
    - Guttmacher names the District of Columbia "DC"; Census files spell it
      out. Every other state name matches the Census STNAME column.

Input:
    - data/raw/guttmacher/guttmacher_raw_states_<timestamp>.json (latest by date in filename),
      written by code/data_collection/download_guttmacher.py.
    - --raw-file (optional): specifiy a different raw file to clean.

    Usage (from anywhere):
        uv run python code/cleaning/clean_guttmacher.py

Output:
    - data/processed/guttmacher/guttmacher_states.jsonl: one JSON object per state,
      sorted by state, with keys:
        - state (str): state name ("DC" for the District of Columbia).
        - state_slug (str): lowercase, hyphenated state name (e.g. "new-york").
        - environment_type (str): policy category, canonical spelling.
        - category_rank (int): 1 = Most Restrictive ... 7 = Most Protective;
          null if the category is unrecognized.
        - as_of (str): date the entry was last edited, YYYY-MM-DD.
        - downloaded_on (str): date the raw file was downloaded, YYYY-MM-DD.
        - <other API fields> (str or null): the map's single-valued fields
          (e.g. wora_in_state_15_49, abortions_obtained_in_2017, the
          aowdd_15_49_* driving-distance sentences, shield_law), verbatim.
        - policy_summary (list of str): Guttmacher's summary sentences.
        - policies (dict): {"abortion_ban", "restrictions", "protections"},
          each a list of {"title": str, "label": str}.
        - policy_counts (dict): number of policies in each group.
    - data/processed/guttmacher/guttmacher_state_categories.csv: one row per state,
      sorted by state_slug, with columns:
        - state_slug (str): as above.
        - environment_type (str): policy category, lowercase.
        - category_rank (int): as above.
        - as_of (str): as above.
        - downloaded_on (str): as above.
    - results/reports/clean_guttmacher_report.txt: states per category.

Author: Matthew DeVerna
"""

import argparse
import csv
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from toolkit.utils import latest_download

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
RAW_DIR = Path("../../data/raw/guttmacher")
RAW_STEM = "guttmacher_raw_states"
RAW_SUFFIX = ".json"
OUTPUT_DIR = Path("../../data/processed/guttmacher")
JSONL_PATH = OUTPUT_DIR / "guttmacher_states.jsonl"
CSV_PATH = OUTPUT_DIR / "guttmacher_state_categories.csv"
REPORT_PATH = Path("../../results/reports/clean_guttmacher_report.txt")

# Canonical spellings of the map's seven categories, most restrictive to most
# protective. A category's rank is its position in this list, plus one.
CATEGORIES = [
    "Most Restrictive",
    "Very Restrictive",
    "Restrictive",
    "Some Restrictions/Protections",
    "Protective",
    "Very Protective",
    "Most Protective",
]
CATEGORY_LOOKUP = {c.lower(): c for c in CATEGORIES}

# Policy groups as they appear in the API, mapped to JSON-friendly keys.
GROUPS = {
    "abortion-ban": "abortion_ban",
    "restrictions": "restrictions",
    "protections": "protections",
}

# Fields that are handled separately or are CMS bookkeeping.
EXCLUDE = {
    "filters",
    "policies_currently_in_effect",
    "environment_type",
    "_id",
    "_by",
    "_mby",
    "_created",
    "_modified",
    "_o",
    "_pid",
    "_link",
}

CSV_COLUMNS = [
    "state_slug",
    "environment_type",
    "category_rank",
    "as_of",
    "downloaded_on",
]


def parse_args():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        With attribute raw_file (pathlib.Path or None).
    """
    parser = argparse.ArgumentParser(
        description="Clean a raw Guttmacher policy-map download."
    )
    parser.add_argument(
        "--raw-file",
        type=Path,
        default=None,
        help="Raw JSON to clean (default: newest file in data/raw/guttmacher/).",
    )
    return parser.parse_args()


def clean(value):
    """
    Trim whitespace from a string, leaving other values unchanged.

    Parameters
    ----------
    value : object
        Any field value from the API.

    Returns
    -------
    object
        The stripped string, or `value` unchanged if it is not a string.
    """
    return value.strip() if isinstance(value, str) else value


def normalize_category(raw):
    """
    Map a raw category to its canonical spelling, ignoring case.

    Parameters
    ----------
    raw : str or None
        The entry's environment_type as returned by the API.

    Returns
    -------
    str or None
        The canonical category; the trimmed raw value if it is unrecognized;
        None if it is missing or empty.
    """
    raw = clean(raw)
    if not raw:
        return None
    if raw.lower() not in CATEGORY_LOOKUP:
        print(f"  note: unrecognized category {raw!r}, kept as is")
        return raw
    return CATEGORY_LOOKUP[raw.lower()]


def build_record(entry, downloaded_on, schema_fields=()):
    """
    Build the cleaned record for one state.

    Parameters
    ----------
    entry : dict
        One state's entry from the raw API response.
    downloaded_on : str
        Date the raw file was downloaded, YYYY-MM-DD.
    schema_fields : sequence of str
        Field names from the API's schema, so every record has the same keys.

    Returns
    -------
    dict
        The state's record, with the keys listed in the script header.
    """
    record = {
        "state": clean(entry.get("state")),
        "state_slug": clean(entry.get("state_slug")),
        "environment_type": normalize_category(entry.get("environment_type")),
        "category_rank": None,
        "as_of": None,
        "downloaded_on": downloaded_on,
    }
    if record["environment_type"] in CATEGORIES:
        record["category_rank"] = CATEGORIES.index(record["environment_type"]) + 1

    if entry.get("_modified"):
        modified = datetime.fromtimestamp(entry["_modified"], timezone.utc)
        record["as_of"] = modified.date().isoformat()

    # Remaining single-valued fields, as strings exactly as returned (None
    # becomes null). Schema fields come first so every line has the same keys,
    # even when a state lacks one.
    for key in list(schema_fields) + list(entry):
        if key not in EXCLUDE and key not in record:
            record[key] = clean(entry.get(key))

    # Summary sentences: one pipe-delimited string in the API, a list here.
    summary = entry.get("policies_currently_in_effect") or ""
    record["policy_summary"] = [s.strip() for s in summary.split("|") if s.strip()]

    # Structured policies grouped by type, in the order the map lists them.
    policies = {key: [] for key in GROUPS.values()}
    for item in sorted(entry.get("filters") or [], key=lambda f: f.get("_o", 0)):
        policy = {
            "title": clean(item.get("filter_title")),
            "label": clean(item.get("filter_label")),
        }
        for group in item.get("filter_group") or []:
            policies.setdefault(GROUPS.get(group, group), []).append(policy)
    record["policies"] = policies
    record["policy_counts"] = {key: len(value) for key, value in policies.items()}

    return record


def category_row(record):
    """
    Reduce a state's record to its row in the categories CSV.

    Parameters
    ----------
    record : dict
        A record from build_record().

    Returns
    -------
    dict
        Values for CSV_COLUMNS; environment_type is lowercased.
    """
    environment_type = record["environment_type"]
    return {
        "state_slug": record["state_slug"],
        "environment_type": environment_type.lower() if environment_type else None,
        "category_rank": record["category_rank"],
        "as_of": record["as_of"],
        "downloaded_on": record["downloaded_on"],
    }


def write_report(records, raw_path):
    """
    Write the number of states in each category.

    Parameters
    ----------
    records : list of dict
        The cleaned records.
    raw_path : pathlib.Path
        The raw file they came from.
    """
    counts = {}
    for record in records:
        counts[record["environment_type"]] = (
            counts.get(record["environment_type"], 0) + 1
        )
    lines = [
        "clean_guttmacher.py report",
        "",
        f"Raw file: {raw_path.name}",
        f"States: {len(records)}",
        "",
        "States per category (most restrictive first):",
    ]
    for category in CATEGORIES + [c for c in counts if c not in CATEGORIES]:
        if category in counts:
            lines.append(f"  {category:<30} {counts[category]}")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Clean the raw download and write the JSONL, CSV, and report.
    """
    args = parse_args()
    raw_path = args.raw_file or latest_download(RAW_DIR, RAW_STEM, RAW_SUFFIX)
    print(f"Cleaning {raw_path}")

    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)
    downloaded_on = raw.get("_downloaded_on")
    if not downloaded_on:  # files saved before that key existed: use file date
        downloaded_on = date.fromtimestamp(raw_path.stat().st_mtime).isoformat()

    schema_fields = list((raw.get("fields") or {}).keys())
    records = sorted(
        (build_record(entry, downloaded_on, schema_fields) for entry in raw["entries"]),
        key=lambda r: r["state"] or "",
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(JSONL_PATH, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    rows = sorted(
        (category_row(r) for r in records), key=lambda r: r["state_slug"] or ""
    )
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    write_report(records, raw_path)
    print(f"Wrote {len(records)} states to {JSONL_PATH} and {CSV_PATH}")


if __name__ == "__main__":
    main()
