"""
Purpose:
    Build the tool-calls table from the raw taxman audit responses.

Notes:
    - One row per server-side tool invocation: web searches for every
      provider, OpenAI page opens, and Anthropic code executions.
    - Anthropic runs web searches from inside code execution:
      caller_tool_id links each such search to the code_execution call that
      launched it, and code_execution rows carry the execution outcome
      (return_code, stdout, stderr, encrypted, abort_reason). stdout is null
      when the result was returned encrypted.
    - search_queries is a list column: one OpenAI search action or Gemini
      search call can issue several queries, while an Anthropic web_search
      issues exactly one.
    - tool_id joins to tool_citations.parquet on (response_id, tool_id).

Input:
    - data/raw/audits/<audit>/<run_id>/manifest.json - taxman run manifests
    - data/raw/audits/<audit>/<run_id>/responses.jsonl - taxman responses
    - --audit-prefix (optional): only include audits whose name starts with
      this prefix (e.g. "pilot-").

Output:
    - data/processed/tool_calls.parquet - one row per tool invocation
        Columns:
            - response_id (str): Joins to metadata. (response_id, index) is
              the primary key.
            - provider (str): anthropic | openai | gemini.
            - index (int): Zero-based invocation order within the response.
            - tool_type (str): anthropic: "web_search" | "code_execution";
              openai: "web_search.search" | "web_search.open_page";
              gemini: "google_search".
            - tool_id (str): Provider's invocation id.
            - status (str or None): Invocation status (openai: provider
              status; gemini: "error" when the search errored, else None;
              anthropic: None).
            - search_queries (list of str or None): Search queries issued.
            - code (str or None): Anthropic code_execution only - the code.
            - caller_tool_id (str or None): Anthropic web_search only - the
              code_execution call that launched it.
            - url (str or None): OpenAI open_page only - the opened page.
            - return_code (int or None): Anthropic code_execution only.
            - stdout (str or None): Anthropic code_execution only, when not
              encrypted.
            - stderr (str or None): Anthropic code_execution only.
            - encrypted (bool or None): Anthropic code_execution only - True
              when the result was encrypted.
            - abort_reason (str or None): Anthropic code_execution only.
    - results/reports/clean_tool_calls_report.txt - row counts by provider
      and tool_type, and searches per response by provider and location

Author: Matthew DeVerna
"""

import argparse
import os
from pathlib import Path

import pandas as pd

from toolkit.loading import discover_runs, load_run_responses, parse_audit_name

os.chdir(Path(__file__).resolve().parent)

AUDITS_DIR = Path("../../data/raw/audits")
OUTPUT_DIR = Path("../../data/processed")
REPORT_PATH = Path("../../results/reports/clean_tool_calls_report.txt")

COLUMNS = [
    "response_id",
    "provider",
    "index",
    "tool_type",
    "tool_id",
    "status",
    "search_queries",
    "code",
    "caller_tool_id",
    "url",
    "return_code",
    "stdout",
    "stderr",
    "encrypted",
    "abort_reason",
]
STRING_COLUMNS = [
    "tool_type",
    "tool_id",
    "status",
    "code",
    "caller_tool_id",
    "url",
    "stdout",
    "stderr",
    "abort_reason",
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


def build_table(audit_prefix):
    """
    Build the tool-calls table.

    Parameters
    ----------
    audit_prefix : str or None
        Only include audits whose name starts with this prefix.

    Returns
    -------
    tuple of pandas.DataFrame
        (tool_calls, responses), where responses has one row per response
        (response_id, provider, location) for the report.
    """
    rows = []
    response_rows = []
    for run in discover_runs(AUDITS_DIR, audit_prefix):
        location = parse_audit_name(run["audit"], run["provider"])["location"]
        for response in load_run_responses(run):
            base = {
                "response_id": response.get_response_id(),
                "provider": response.record["provider"],
            }
            response_rows.append({**base, "location": location})
            rows += [{**base, **call} for call in response.get_tool_calls()]

    tool_calls = pd.DataFrame(rows).reindex(columns=COLUMNS)
    # Cast so columns that are null for most providers keep a stable type.
    tool_calls[STRING_COLUMNS] = tool_calls[STRING_COLUMNS].astype("str")
    tool_calls["return_code"] = tool_calls["return_code"].astype("Int64")
    tool_calls["encrypted"] = tool_calls["encrypted"].astype("boolean")
    return tool_calls, pd.DataFrame(response_rows)


def validate(tool_calls):
    """
    Assert the table is internally consistent before writing.

    Parameters
    ----------
    tool_calls : pandas.DataFrame
        The table from ``build_table``.

    Raises
    ------
    AssertionError
        If any check fails.
    """
    assert not tool_calls.duplicated(["response_id", "index"]).any(), (
        "Duplicate (response_id, index) in tool_calls"
    )
    assert tool_calls["tool_id"].notna().all(), "Null tool_id"
    assert not tool_calls.duplicated(["response_id", "tool_id"]).any(), (
        "Duplicate tool_id within a response"
    )
    # Every caller_tool_id must point at a code_execution call in the same
    # response.
    callers = tool_calls[tool_calls["caller_tool_id"].notna()]
    code_calls = tool_calls[tool_calls["tool_type"] == "code_execution"]
    known = set(zip(code_calls["response_id"], code_calls["tool_id"]))
    unknown = [
        pair
        for pair in zip(callers["response_id"], callers["caller_tool_id"])
        if pair not in known
    ]
    assert not unknown, f"caller_tool_id with no code_execution call: {unknown[:5]}"


def write_report(tool_calls, responses):
    """
    Write a short text report of tool-call counts.

    Parameters
    ----------
    tool_calls : pandas.DataFrame
        The validated table.
    responses : pandas.DataFrame
        One row per response (response_id, provider, location).
    """
    searches = tool_calls[tool_calls["search_queries"].notna()]
    counts = searches.groupby("response_id").size().rename("n_searches")
    per_response = responses.merge(
        counts, left_on="response_id", right_index=True, how="left"
    )
    per_response["n_searches"] = per_response["n_searches"].fillna(0)
    lines = [
        "clean_tool_calls.py report",
        "",
        f"tool_calls rows: {len(tool_calls)}",
        "",
        "Tool calls by provider and tool_type:",
        tool_calls.groupby(["provider", "tool_type"]).size().to_string(),
        "",
        "Search calls per response by provider and location:",
        per_response.groupby(["provider", "location"])["n_searches"]
        .agg(
            total="sum",
            mean_per_response="mean",
            share_with_any=lambda s: (s > 0).mean(),
        )
        .round(2)
        .to_string(),
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Build, validate, and write the tool-calls table.
    """
    args = parse_args()
    tool_calls, responses = build_table(args.audit_prefix)
    validate(tool_calls)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tool_calls.to_parquet(OUTPUT_DIR / "tool_calls.parquet", index=False)
    write_report(tool_calls, responses)
    print(f"Wrote {len(tool_calls)} tool calls")


if __name__ == "__main__":
    main()
