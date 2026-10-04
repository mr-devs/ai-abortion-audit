"""
Purpose:
    Build the long-format token-usage table from the raw taxman audit
    responses.

Notes:
    - One row per (response, token_type): the providers' usage payloads have
      very different shapes, so a long table with a `unit` column is the
      only shape that does not imply false comparability. 
    - token_type names are the provider's usage keys, dot-flattened (e.g.
      "output_tokens_details.thinking_tokens"). OpenAI's separate
      `tool_usage` payload is included with the prefix "tool_usage.".
    - The unit of every token_type comes from an explicit map
      (TOKEN_UNIT_MAP, built from every type in the 2026-10-04 pilot). An
      unknown token_type raises ValueError on purpose: when a provider adds
      a usage field, it must be classified here rather than guessed.

Input:
    - data/raw/audits/<audit>/<run_id>/manifest.json - taxman run manifests
    - data/raw/audits/<audit>/<run_id>/responses.jsonl - taxman responses
    - --audit-prefix (optional): only include audits whose name starts with
      this prefix (e.g. "pilot-").

Output:
    - data/processed/token_usage.parquet - one row per (response, token_type)
        Columns:
            - response_id (str): Joins to metadata. (response_id,
              token_type) is the primary key.
            - provider (str): anthropic | openai | gemini.
            - token_type (str): Usage metric name, dot-flattened.
            - unit (str): "tokens" or "count" (number of tool requests).
            - value (float): Value of the metric.
    - results/reports/clean_token_usage_report.txt - row count and the mean
      and sum of each (provider, token_type)

Author: Matthew DeVerna
"""

import argparse
import os
from pathlib import Path

import pandas as pd

from toolkit.loading import discover_runs, load_run_responses

os.chdir(Path(__file__).resolve().parent)

AUDITS_DIR = Path("../../data/raw/audits")
OUTPUT_DIR = Path("../../data/processed")
REPORT_PATH = Path("../../results/reports/clean_token_usage_report.txt")

# (provider, token_type) -> unit. Every type observed in the pilot data.
TOKEN_UNIT_MAP = {
    ("anthropic", "input_tokens"): "tokens",
    ("anthropic", "output_tokens"): "tokens",
    ("anthropic", "output_tokens_details.thinking_tokens"): "tokens",
    ("anthropic", "cache_creation_input_tokens"): "tokens",
    ("anthropic", "cache_read_input_tokens"): "tokens",
    ("anthropic", "cache_creation.ephemeral_1h_input_tokens"): "tokens",
    ("anthropic", "cache_creation.ephemeral_5m_input_tokens"): "tokens",
    ("anthropic", "server_tool_use.web_search_requests"): "count",
    ("anthropic", "server_tool_use.web_fetch_requests"): "count",
    ("openai", "input_tokens"): "tokens",
    ("openai", "input_tokens_details.cached_tokens"): "tokens",
    ("openai", "input_tokens_details.cache_write_tokens"): "tokens",
    ("openai", "output_tokens"): "tokens",
    ("openai", "output_tokens_details.reasoning_tokens"): "tokens",
    ("openai", "total_tokens"): "tokens",
    ("openai", "tool_usage.web_search.num_requests"): "count",
    ("openai", "tool_usage.image_gen.input_tokens"): "tokens",
    ("openai", "tool_usage.image_gen.input_tokens_details.image_tokens"): "tokens",
    ("openai", "tool_usage.image_gen.input_tokens_details.text_tokens"): "tokens",
    ("openai", "tool_usage.image_gen.output_tokens"): "tokens",
    ("openai", "tool_usage.image_gen.output_tokens_details.image_tokens"): "tokens",
    ("openai", "tool_usage.image_gen.output_tokens_details.text_tokens"): "tokens",
    ("openai", "tool_usage.image_gen.total_tokens"): "tokens",
    ("gemini", "total_tokens"): "tokens",
    ("gemini", "total_input_tokens"): "tokens",
    ("gemini", "total_cached_tokens"): "tokens",
    ("gemini", "total_output_tokens"): "tokens",
    ("gemini", "total_thought_tokens"): "tokens",
    ("gemini", "total_tool_use_tokens"): "tokens",
    ("gemini", "raw_prompt_token"): "tokens",
}


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
    Build the token-usage table.

    Parameters
    ----------
    audit_prefix : str or None
        Only include audits whose name starts with this prefix.

    Returns
    -------
    pandas.DataFrame
        The long-format token-usage table.

    Raises
    ------
    ValueError
        If a (provider, token_type) is not in TOKEN_UNIT_MAP.
    """
    rows = []
    for run in discover_runs(AUDITS_DIR, audit_prefix):
        for response in load_run_responses(run):
            provider = response.record["provider"]
            for usage in response.get_token_usage():
                key = (provider, usage["token_type"])
                if key not in TOKEN_UNIT_MAP:
                    raise ValueError(
                        f"Unknown token type {key}; add it to TOKEN_UNIT_MAP "
                        "with its unit."
                    )
                rows.append(
                    {
                        "response_id": response.get_response_id(),
                        "provider": provider,
                        "token_type": usage["token_type"],
                        "unit": TOKEN_UNIT_MAP[key],
                        "value": usage["value"],
                    }
                )
    return pd.DataFrame(rows)


def validate(token_usage):
    """
    Assert the table is internally consistent before writing.

    Parameters
    ----------
    token_usage : pandas.DataFrame
        The table from ``build_table``.

    Raises
    ------
    AssertionError
        If any check fails.
    """
    assert not token_usage.duplicated(["response_id", "token_type"]).any(), (
        "Duplicate (response_id, token_type) in token_usage"
    )
    assert pd.api.types.is_float_dtype(token_usage["value"]), "value is not float"
    assert (token_usage["value"] >= 0).all(), "Negative usage value"


def write_report(token_usage):
    """
    Write a short text report of token usage.

    Parameters
    ----------
    token_usage : pandas.DataFrame
        The validated table.
    """
    lines = [
        "clean_token_usage.py report",
        "",
        f"token_usage rows: {len(token_usage)}",
        "",
        "Mean and sum by provider, token_type, and unit:",
        token_usage.groupby(["provider", "token_type", "unit"])["value"]
        .agg(["mean", "sum"])
        .round(1)
        .to_string(),
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Build, validate, and write the token-usage table.
    """
    args = parse_args()
    token_usage = build_table(args.audit_prefix)
    validate(token_usage)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    token_usage.to_parquet(OUTPUT_DIR / "token_usage.parquet", index=False)
    write_report(token_usage)
    print(f"Wrote {len(token_usage)} token-usage rows")


if __name__ == "__main__":
    main()
