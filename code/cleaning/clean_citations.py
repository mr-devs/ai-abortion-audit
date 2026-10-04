"""
Purpose:
    Build the text-citations and tool-citations tables from the raw taxman
    audit responses.

Notes:
    - Text vs tool citations: text citations are attached to the response
      text a user sees; tool citations are URLs a search tool returned in
      the payload, which the response may or may not have used.
    - The script stops if the URLs of a Gemini collection have not been resolved yet.
    - domain is the registrable domain (toolkit.utils.extract_domain): for
      gemini it comes from resolved_url (null when unresolved), for everyone
      else from url.
    - Every tool citation's tool_id is checked against the tool calls of its
      own response, so tool_citations joins with tool_calls.

Input:
    - data/raw/audits/<audit>/<run_id>/manifest.json - taxman run manifests
    - data/raw/audits/<audit>/<run_id>/responses.jsonl - taxman responses
    - data/raw/audits/<gemini audit>/<run_id>/resolved_urls.jsonl - resolved
      Gemini redirect URLs
    - --audit-prefix (optional): only include audits whose name starts with
      this prefix (e.g. "pilot-").

Output:
    - data/processed/text_citations.parquet - one row per URL cited in the
      response text
        Columns:
            - response_id (str): Joins to metadata. (response_id, index) is
              the primary key.
            - provider (str): anthropic | openai | gemini.
            - index (int): Zero-based citation order within the response.
            - url (str): Cited URL, verbatim (gemini: Google redirect URL).
            - resolved_url (str or None): Gemini only - the cited URL from
              the redirect's Location header; None if unresolved or not
              gemini.
            - domain (str or None): Registrable domain (gemini: from
              resolved_url; others: from url).
            - title (str or None): Title as reported by the provider (gemini
              reports the cited site's domain).
            - cited_text (str or None): Anthropic only - the cited passage.
            - start_index (int or None): openai/gemini - start offset of the
              cited span in the response text.
            - end_index (int or None): openai/gemini - end offset.
    - data/processed/tool_citations.parquet - one row per URL a search tool
      returned
        Columns:
            - response_id (str): Joins to metadata. (response_id, index) is
              the primary key.
            - provider (str): anthropic | openai.
            - index (int): Zero-based order within the response payload.
            - url (str): URL, verbatim.
            - domain (str or None): Registrable domain from url.
            - title (str or None): Anthropic only - search result title.
            - page_age (str or None): Anthropic only - reported page age.
            - tool_id (str): The tool call that returned the URL; joins to
              tool_calls.parquet on (response_id, tool_id).
    - results/reports/clean_citations_report.txt - row counts, citations per
      response by provider and location, dropped rows, and the Gemini
      resolution rate

Author: Matthew DeVerna
"""

import argparse
import os
from pathlib import Path

import pandas as pd

from toolkit.loading import (
    discover_runs,
    load_resolved_urls,
    load_run_responses,
    parse_audit_name,
)
from toolkit.utils import extract_domain

os.chdir(Path(__file__).resolve().parent)

AUDITS_DIR = Path("../../data/raw/audits")
OUTPUT_DIR = Path("../../data/processed")
REPORT_PATH = Path("../../results/reports/clean_citations_report.txt")

TEXT_COLUMNS = [
    "response_id",
    "provider",
    "index",
    "url",
    "resolved_url",
    "domain",
    "title",
    "cited_text",
    "start_index",
    "end_index",
]
TOOL_COLUMNS = [
    "response_id",
    "provider",
    "index",
    "url",
    "domain",
    "title",
    "page_age",
    "tool_id",
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
    Build the text-citations and tool-citations tables.

    Parameters
    ----------
    audit_prefix : str or None
        Only include audits whose name starts with this prefix.

    Returns
    -------
    tuple of pandas.DataFrame
        (text_citations, tool_citations, responses), where responses has one
        row per response (response_id, provider, location) so the report
        can count responses that have no citations.

    Raises
    ------
    SystemExit
        If a Gemini run has no resolved-URLs file, or a tool citation's
        tool_id matches none of its response's tool calls.
    """
    text_rows = []
    tool_rows = []
    response_rows = []
    for run in discover_runs(AUDITS_DIR, audit_prefix):
        location = parse_audit_name(run["audit"], run["provider"])["location"]
        resolved = {}
        if run["provider"] == "gemini":
            resolved = load_resolved_urls(run["run_dir"])
            if not resolved:
                raise SystemExit(
                    f"No resolved URLs for {run['audit']} run {run['run_id']}; "
                    "run code/data_collection/resolve_gemini_urls.py first."
                )

        for response in load_run_responses(run):
            response_id = response.get_response_id()
            provider = response.record["provider"]
            base = {"response_id": response_id, "provider": provider}
            response_rows.append({**base, "location": location})

            for row in response.get_text_citations():
                if provider == "gemini":
                    if response_id not in resolved:
                        raise SystemExit(
                            f"{response_id} is missing from the resolved URLs; "
                            "re-run code/data_collection/resolve_gemini_urls.py."
                        )
                    resolved_url = resolved[response_id]["resolved_urls"].get(
                        row["url"]
                    )
                    domain = extract_domain(resolved_url) if resolved_url else None
                else:
                    resolved_url = None
                    domain = extract_domain(row["url"]) if row["url"] else None
                text_rows.append(
                    {**base, **row, "resolved_url": resolved_url, "domain": domain}
                )

            tool_ids = {call["tool_id"] for call in response.get_tool_calls()}
            for row in response.get_tool_citations():
                if row["tool_id"] not in tool_ids:
                    raise SystemExit(
                        f"{response_id}: tool citation {row['index']} has tool_id "
                        f"{row['tool_id']!r}, which matches no tool call"
                    )
                domain = extract_domain(row["url"]) if row["url"] else None
                tool_rows.append({**base, **row, "domain": domain})

    text_citations = pd.DataFrame(text_rows).reindex(columns=TEXT_COLUMNS)
    tool_citations = pd.DataFrame(tool_rows).reindex(columns=TOOL_COLUMNS)

    # Offsets are null for providers that do not report them, so use the
    # nullable integer type; text columns are cast to string so all-null
    # columns are not written with the parquet "null" type.
    for col in ["start_index", "end_index"]:
        text_citations[col] = text_citations[col].astype("Int64")
    for df, cols in [
        (text_citations, ["url", "resolved_url", "domain", "title", "cited_text"]),
        (tool_citations, ["url", "domain", "title", "page_age", "tool_id"]),
    ]:
        df[cols] = df[cols].astype("str")
    return text_citations, tool_citations, pd.DataFrame(response_rows)


def drop_null_urls(df):
    """
    Drop rows without a URL.

    Parameters
    ----------
    df : pandas.DataFrame
        A citations table.

    Returns
    -------
    tuple of (pandas.DataFrame, pandas.DataFrame)
        The kept rows and the dropped rows.
    """
    missing = df["url"].isna()
    return df[~missing].reset_index(drop=True), df[missing]


def validate(text_citations, tool_citations):
    """
    Assert the tables are internally consistent before writing.

    Parameters
    ----------
    text_citations, tool_citations : pandas.DataFrame
        The citation tables after null-URL rows are dropped.

    Raises
    ------
    AssertionError
        If any check fails.
    """
    for name, df in [("text", text_citations), ("tool", tool_citations)]:
        assert not df.duplicated(["response_id", "index"]).any(), (
            f"Duplicate (response_id, index) in {name}_citations"
        )
        assert df["url"].notna().all(), f"Null url in {name}_citations"
    non_gemini = text_citations[text_citations["provider"] != "gemini"]
    assert non_gemini["resolved_url"].isna().all(), "resolved_url set for non-gemini"


def write_report(text_citations, tool_citations, dropped, responses):
    """
    Write a short text report of citation counts.

    Parameters
    ----------
    text_citations, tool_citations : pandas.DataFrame
        The validated tables.
    dropped : dict
        {table name: DataFrame of rows dropped for a null url}.
    responses : pandas.DataFrame
        One row per response (response_id, provider, location), so
        responses with zero citations count toward the per-response means.
    """

    def per_response(df):
        # Count citations per response, keeping responses with none, then
        # average within provider x location.
        counts = df.groupby("response_id").size().rename("n")
        merged = responses.merge(
            counts, left_on="response_id", right_index=True, how="left"
        )
        merged["n"] = merged["n"].fillna(0)
        return (
            merged.groupby(["provider", "location"])["n"]
            .agg(
                total="sum",
                mean_per_response="mean",
                share_with_any=lambda s: (s > 0).mean(),
            )
            .round(2)
            .to_string()
        )

    gemini = text_citations[text_citations["provider"] == "gemini"]
    lines = [
        "clean_citations.py report",
        "",
        f"text_citations rows: {len(text_citations)}",
        f"tool_citations rows: {len(tool_citations)}",
        "",
        "Text citations by provider and location:",
        per_response(text_citations),
        "",
        "Tool citations by provider and location:",
        per_response(tool_citations),
        "",
        f"Gemini text citations resolved: {gemini['resolved_url'].notna().sum()} "
        f"of {len(gemini)}",
        "",
        "Rows dropped for a null url:",
    ]
    for name, df in dropped.items():
        lines.append(f"  {name}: {len(df)}")
        lines += [f"    {r.provider} {r.response_id}" for r in df.itertuples()]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Build, validate, and write the text-citations and tool-citations tables.
    """
    args = parse_args()
    text_citations, tool_citations, responses = build_tables(args.audit_prefix)
    text_citations, dropped_text = drop_null_urls(text_citations)
    tool_citations, dropped_tool = drop_null_urls(tool_citations)
    validate(text_citations, tool_citations)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    text_citations.to_parquet(OUTPUT_DIR / "text_citations.parquet", index=False)
    tool_citations.to_parquet(OUTPUT_DIR / "tool_citations.parquet", index=False)
    write_report(
        text_citations,
        tool_citations,
        {"text_citations": dropped_text, "tool_citations": dropped_tool},
        responses,
    )
    print(
        f"Wrote {len(text_citations)} text citations and "
        f"{len(tool_citations)} tool citations"
    )


if __name__ == "__main__":
    main()
