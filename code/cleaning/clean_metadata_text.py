"""
Purpose:
    Build the metadata, response-text, and audit-runs tables from the raw
    taxman audit responses.

Notes:
    - Every response is parsed through its provider's response model
      (toolkit.response_models), so all field extraction lives in one place;
      this script only assembles rows.
    - study and location are parsed from the audit name
      ("<study>-<provider>[-<location>]"; see toolkit.loading.
      parse_audit_name). message_id identifies the same question across
      locations, because every location's message file lists the same
      questions in the same order.
    - Failed requests (status "error") are kept in metadata, with their
      error, so they stay visible; they have no text.

Input:
    - data/raw/audits/<audit>/<run_id>/manifest.json - taxman run manifests
    - data/raw/audits/<audit>/<run_id>/responses.jsonl - taxman responses
    - --audit-prefix (optional): only include audits whose name starts with
      this prefix (e.g. "pilot-").

Output:
    - data/processed/audits/metadata.parquet - one row per response
        Columns:
            - response_id (str): "<audit>__<run_id>__<message_id>__r<repeat>";
              primary key, joins all tables.
            - audit (str): taxman audit name.
            - study (str): Study part of the audit name (e.g. "pilot").
            - location (str): Location part of the audit name (e.g.
              "houston-tx"); "none" when the audit has no location.
            - run_id (str): taxman run id.
            - message_id (str): taxman message id (e.g. "m0000"), the same
              question across locations.
            - repeat (int): Repeat number (0-based).
            - message (str): The query text sent.
            - provider (str): anthropic | openai | gemini.
            - model (str): Model name.
            - requested_at (datetime, UTC): When the request was sent.
            - received_at (datetime, UTC): When the response arrived.
            - latency_ms (int): Request latency in milliseconds.
            - status (str): "ok" or "error".
            - error (str or None): Error details as a JSON string.
            - attempts (int): Number of attempts taxman made.
            - message_hash (str): Hash of the message text.
            - system_prompt_hash (str or None): Hash of the system prompt.
            - stop_reason (str or None): Why generation ended (anthropic:
              stop_reason; openai/gemini: response status).
            - stop_detail (str or None): Further stop details (JSON string).
    - data/processed/audits/response_text.parquet - one row per response
        Columns:
            - response_id (str): Primary key.
            - provider (str): Provider name.
            - text (str or None): Response text shown to the user.
    - data/processed/audits/audit_runs.parquet - one row per taxman run
        Columns:
            - audit (str), study (str), location (str), run_id (str),
              provider (str), model (str): As in metadata.
            - status (str): Manifest status (always "complete" here).
            - n_messages (int): Messages in the message file.
            - repeats (int): Repeats per message.
            - n_ok (int), n_error (int): taxman's response counts.
            - n_responses (int): Lines in responses.jsonl.
            - started_at (datetime, UTC), finished_at (datetime, UTC):
              Run start and end.
            - duration_seconds (float): finished_at minus started_at.
            - messages_path (str): Message file used.
            - messages_hash (str): Hash of the message file.
            - system_prompt_path (str or None): System prompt file used.
            - taxman_version (str): taxman version that collected the run.
    - results/reports/clean_metadata_text_report.txt - row counts per table,
      responses per (provider, location), and responses without text

Author: Matthew DeVerna
"""

import argparse
import os
from pathlib import Path

import pandas as pd

from toolkit.loading import discover_runs, load_run_responses, parse_audit_name

os.chdir(Path(__file__).resolve().parent)

AUDITS_DIR = Path("../../data/raw/audits")
OUTPUT_DIR = Path("../../data/processed/audits")
REPORT_PATH = Path("../../results/reports/clean_metadata_text_report.txt")

RUN_COLUMNS = [
    "audit",
    "study",
    "location",
    "run_id",
    "provider",
    "model",
    "status",
    "n_messages",
    "repeats",
    "n_ok",
    "n_error",
    "n_responses",
    "started_at",
    "finished_at",
    "duration_seconds",
    "messages_path",
    "messages_hash",
    "system_prompt_path",
    "taxman_version",
]


def parse_args():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        With attribute ``audit_prefix`` (str or None).
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2].strip())
    parser.add_argument(
        "--audit-prefix",
        default=None,
        help="Only include audits whose name starts with this prefix.",
    )
    return parser.parse_args()


def build_tables(audit_prefix):
    """
    Build the metadata, response-text, and audit-runs tables.

    Parameters
    ----------
    audit_prefix : str or None
        Only include audits whose name starts with this prefix.

    Returns
    -------
    tuple of pandas.DataFrame
        (metadata, response_text, audit_runs).
    """
    metadata_rows = []
    text_rows = []
    run_rows = []
    for run in discover_runs(AUDITS_DIR, audit_prefix):
        names = parse_audit_name(run["audit"], run["provider"])
        responses = load_run_responses(run)
        for response in responses:
            metadata_rows.append(
                {
                    **response.get_metadata(),
                    **names,
                    **response.get_stop_info(),
                }
            )
            text_rows.append(
                {
                    "response_id": response.get_response_id(),
                    "provider": response.record["provider"],
                    "text": response.get_text(),
                }
            )
        run_rows.append({**run, **names, "n_responses": len(responses)})

    metadata = pd.DataFrame(metadata_rows)
    first = ["response_id", "audit", "study", "location"]
    metadata = metadata[first + [c for c in metadata.columns if c not in first]]
    for col in ["requested_at", "received_at"]:
        metadata[col] = pd.to_datetime(metadata[col], utc=True)
    nullable_str = ["error", "system_prompt_hash", "stop_reason", "stop_detail"]
    metadata[nullable_str] = metadata[nullable_str].astype("str")

    response_text = pd.DataFrame(text_rows)
    response_text["text"] = response_text["text"].astype("str")

    audit_runs = pd.DataFrame(run_rows)
    for col in ["started_at", "finished_at"]:
        audit_runs[col] = pd.to_datetime(audit_runs[col], utc=True)
    audit_runs["duration_seconds"] = (
        audit_runs["finished_at"] - audit_runs["started_at"]
    ).dt.total_seconds()
    audit_runs = audit_runs[RUN_COLUMNS]
    audit_runs["system_prompt_path"] = audit_runs["system_prompt_path"].astype("str")

    return metadata, response_text, audit_runs


def validate(metadata, response_text, audit_runs):
    """
    Assert the tables are internally consistent before writing.

    Parameters
    ----------
    metadata, response_text, audit_runs : pandas.DataFrame
        The tables from ``build_tables``.

    Raises
    ------
    AssertionError
        If any check fails.
    """
    assert len(metadata) > 0, "No responses found"
    assert metadata["response_id"].is_unique, "Duplicate response_id in metadata"
    assert response_text["response_id"].is_unique, "Duplicate response_id in text"
    assert len(metadata) == len(response_text), "metadata/text row counts differ"
    assert metadata["status"].isin(["ok", "error"]).all(), "Unexpected status"

    # Each run must hold exactly the responses its manifest promises.
    expected = audit_runs["n_messages"] * audit_runs["repeats"]
    bad = audit_runs[
        (audit_runs["n_responses"] != expected)
        | (audit_runs["n_responses"] != audit_runs["n_ok"] + audit_runs["n_error"])
    ]
    assert bad.empty, f"Runs with unexpected response counts:\n{bad}"

    # taxman's ok/error counts must match the per-response statuses.
    counts = (
        metadata.groupby(["audit", "run_id"])["status"]
        .value_counts()
        .unstack(fill_value=0)
    )
    for _, run in audit_runs.iterrows():
        row = counts.loc[(run["audit"], run["run_id"])]
        assert row.get("ok", 0) == run["n_ok"], f"n_ok mismatch for {run['audit']}"
        assert row.get("error", 0) == run["n_error"], (
            f"n_error mismatch for {run['audit']}"
        )


def write_report(metadata, response_text, audit_runs):
    """
    Write a short text report of row counts.

    Parameters
    ----------
    metadata, response_text, audit_runs : pandas.DataFrame
        The validated tables.
    """
    merged = metadata.merge(response_text[["response_id", "text"]], on="response_id")
    no_text = merged[(merged["status"] == "ok") & merged["text"].isna()]
    lines = [
        "clean_metadata_text.py report",
        "",
        f"metadata rows:      {len(metadata)}",
        f"response_text rows: {len(response_text)}",
        f"audit_runs rows:    {len(audit_runs)}",
        "",
        "Responses per provider and location (status counts):",
        metadata.groupby(["provider", "location"])["status"]
        .value_counts()
        .unstack(fill_value=0)
        .to_string(),
        "",
        f"Successful responses without text: {len(no_text)}",
    ]
    lines += [f"  {rid}" for rid in no_text["response_id"]]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Build, validate, and write the metadata, response-text, and audit-runs
    tables.
    """
    args = parse_args()
    metadata, response_text, audit_runs = build_tables(args.audit_prefix)
    validate(metadata, response_text, audit_runs)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    metadata.to_parquet(OUTPUT_DIR / "metadata.parquet", index=False)
    response_text.to_parquet(OUTPUT_DIR / "response_text.parquet", index=False)
    audit_runs.to_parquet(OUTPUT_DIR / "audit_runs.parquet", index=False)
    write_report(metadata, response_text, audit_runs)
    print(f"Wrote {len(metadata)} responses from {len(audit_runs)} runs")


if __name__ == "__main__":
    main()
