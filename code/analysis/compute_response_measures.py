"""
Purpose:
    Compute descriptive measures for every response: length, web-search use,
    cited and retrieved sources, and which abortion-access resources the
    response names.

Notes:
    - Word count: markdown link targets and bare URLs are removed before
      counting, because OpenAI and Gemini put URLs in the text and Anthropic
      does not; counting them would inflate those providers' lengths. Words
      are runs of letters, digits, apostrophes, or hyphens.
    - Search calls: one per tool call that runs a web search. The search
      tool types are Anthropic `web_search`, Gemini `google_search`, and
      OpenAI `web_search.search`. OpenAI `web_search.open_page` (opening a
      page) and Anthropic `code_execution` are not searches. Anthropic runs
      some searches from inside code execution; those still appear as
      `web_search` rows and are counted.
    - Cited sources come from text_citations (URLs attached to the answer
      text). Anthropic attached none in the pilot, so its cited counts are 0
      by construction, not because it used no sources. Gemini's cited URLs
      are its resolved URLs.
    - Retrieved sources come from tool_citations (URLs a search returned,
      cited or not). Gemini exposes none, so its retrieved counts are 0 by
      construction. The `has_cited_data` / `has_retrieved_data` columns flag
      which providers report each kind.
    - Resource mentions use the keyword lexicon in toolkit.resources; a
      mention means the resource is named, not endorsed. These are
      exploratory keyword hits, not validated content codes.

Input:
    - data/processed/audits/metadata.parquet
    - data/processed/audits/response_text.parquet
    - data/processed/audits/tool_calls.parquet
    - data/processed/audits/text_citations.parquet
    - data/processed/audits/tool_citations.parquet

Output:
    - data/processed/audits/response_measures.parquet - one row per response
        Columns:
            - response_id (str): Joins to metadata.
            - provider (str): anthropic | gemini | openai.
            - location (str): none | houston-tx | portland-or.
            - message_id (str): Query id, shared across locations.
            - repeat (int): Zero-based repeat number.
            - n_words (int): Words in the response, URLs removed.
            - n_chars (int): Characters in the response text, verbatim.
            - n_searches (int): Web-search tool calls.
            - searched (bool): n_searches > 0.
            - n_search_queries (int): Search strings sent across all calls.
            - n_cited_urls (int): Distinct URLs cited in the answer text.
            - n_cited_domains (int): Distinct domains cited in the text.
            - n_retrieved_urls (int): Distinct URLs returned by searches.
            - n_retrieved_domains (int): Distinct domains returned.
            - has_cited_data (bool): Provider reports text citations.
            - has_retrieved_data (bool): Provider reports search results.
            - n_resources (int): Number of lexicon resources named.
            - res_<id> (bool): One column per resource in
              toolkit.resources.RESOURCES; True if the response names it.
    - results/reports/compute_response_measures_report.txt - mean measures
      and resource-mention shares by provider and location

Author: Matthew DeVerna
"""

import os
import re
from pathlib import Path

import pandas as pd

from toolkit.resources import RESOURCES, find_resources

os.chdir(Path(__file__).resolve().parent)

PROCESSED_DIR = Path("../../data/processed/audits")
OUTPUT_PATH = PROCESSED_DIR / "response_measures.parquet"
REPORT_PATH = Path("../../results/reports/compute_response_measures_report.txt")

# Tool types that run a web search (see Notes).
SEARCH_TOOL_TYPES = {"web_search", "google_search", "web_search.search"}

# Providers whose payloads report each kind of source (see Notes).
CITED_DATA_PROVIDERS = {"gemini", "openai"}
RETRIEVED_DATA_PROVIDERS = {"anthropic", "openai"}

MARKDOWN_LINK_TARGET = re.compile(r"\]\([^)]*\)")
BARE_URL = re.compile(r"https?://\S+")
WORD = re.compile(r"[A-Za-z0-9'’\-]+")


def count_words(text):
    """
    Return the number of words in a response, ignoring URLs.

    Parameters
    ----------
    text : str
        Response text (markdown).

    Returns
    -------
    int
        Word count after removing markdown link targets and bare URLs.
    """
    text = MARKDOWN_LINK_TARGET.sub("]", text or "")
    text = BARE_URL.sub(" ", text)
    return len(WORD.findall(text))


def search_measures(tool_calls):
    """
    Return per-response search counts.

    Parameters
    ----------
    tool_calls : pandas.DataFrame
        tool_calls.parquet.

    Returns
    -------
    pandas.DataFrame
        Indexed by response_id with n_searches and n_search_queries.
    """
    searches = tool_calls[tool_calls["tool_type"].isin(SEARCH_TOOL_TYPES)].copy()
    searches["n_queries"] = searches["search_queries"].apply(
        lambda q: 0 if q is None else len(q)
    )
    return searches.groupby("response_id").agg(
        n_searches=("tool_type", "size"), n_search_queries=("n_queries", "sum")
    )


def source_measures(citations, prefix, url_col="url"):
    """
    Return per-response counts of distinct URLs and domains.

    Parameters
    ----------
    citations : pandas.DataFrame
        text_citations or tool_citations.
    prefix : str
        Column prefix, "cited" or "retrieved".
    url_col : str
        Column holding the URL to deduplicate on.

    Returns
    -------
    pandas.DataFrame
        Indexed by response_id with n_<prefix>_urls and n_<prefix>_domains.
    """
    return citations.groupby("response_id").agg(
        **{
            f"n_{prefix}_urls": (url_col, "nunique"),
            f"n_{prefix}_domains": ("domain", "nunique"),
        }
    )


def build_measures(meta, text, tool_calls, text_cites, tool_cites):
    """
    Return the response_measures table.

    Parameters
    ----------
    meta, text, tool_calls, text_cites, tool_cites : pandas.DataFrame
        The processed tables named in the script header.

    Returns
    -------
    pandas.DataFrame
        One row per response with the columns listed in the script header.
    """
    df = meta[["response_id", "provider", "location", "message_id", "repeat"]].merge(
        text[["response_id", "text"]], on="response_id", how="left", validate="1:1"
    )
    df["n_words"] = df["text"].apply(count_words)
    df["n_chars"] = df["text"].fillna("").str.len()

    # Gemini's verbatim url is a Google redirect; dedupe on the resolved URL.
    text_cites = text_cites.assign(
        dedupe_url=text_cites["resolved_url"].fillna(text_cites["url"])
    )
    for part in [
        search_measures(tool_calls),
        source_measures(text_cites, "cited", url_col="dedupe_url"),
        source_measures(tool_cites, "retrieved"),
    ]:
        df = df.merge(part, left_on="response_id", right_index=True, how="left")

    count_cols = [
        "n_searches",
        "n_search_queries",
        "n_cited_urls",
        "n_cited_domains",
        "n_retrieved_urls",
        "n_retrieved_domains",
    ]
    # A response absent from a source table has zero of that thing.
    df[count_cols] = df[count_cols].fillna(0).astype(int)
    df["searched"] = df["n_searches"] > 0
    df["has_cited_data"] = df["provider"].isin(CITED_DATA_PROVIDERS)
    df["has_retrieved_data"] = df["provider"].isin(RETRIEVED_DATA_PROVIDERS)

    hits = pd.DataFrame([find_resources(t) for t in df["text"]], index=df.index)
    hits.columns = [f"res_{c}" for c in hits.columns]
    df = pd.concat([df, hits], axis=1)
    df["n_resources"] = hits.sum(axis=1).astype(int)
    return df.drop(columns="text")


def write_report(df):
    """
    Write a plain-text summary of the measures.

    Parameters
    ----------
    df : pandas.DataFrame
        The response_measures table.
    """
    group = ["provider", "location"]
    means = df.groupby(group)[
        [
            "n_words",
            "searched",
            "n_searches",
            "n_cited_urls",
            "n_retrieved_urls",
            "n_resources",
        ]
    ].mean()
    res_cols = [f"res_{rid}" for rid, _, _ in RESOURCES]
    shares = df.groupby(group)[res_cols].mean().T
    shares.index = [label for _, label, _ in RESOURCES]

    lines = [
        "compute_response_measures.py report",
        "",
        f"response_measures rows: {len(df)}",
        "",
        "Mean per response by provider and location",
        "(searched = share of responses with any search):",
        means.round(2).to_string(),
        "",
        "Share of responses naming each resource (keyword lexicon):",
        shares.round(2).to_string(),
        "",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    meta = pd.read_parquet(PROCESSED_DIR / "metadata.parquet")
    meta = meta[meta["status"] == "ok"]
    text = pd.read_parquet(PROCESSED_DIR / "response_text.parquet")
    tool_calls = pd.read_parquet(PROCESSED_DIR / "tool_calls.parquet")
    text_cites = pd.read_parquet(PROCESSED_DIR / "text_citations.parquet")
    tool_cites = pd.read_parquet(PROCESSED_DIR / "tool_citations.parquet")

    df = build_measures(meta, text, tool_calls, text_cites, tool_cites)
    df.to_parquet(OUTPUT_PATH, index=False)
    write_report(df)
    print(f"Wrote {len(df)} rows to {OUTPUT_PATH}")
    print(f"Wrote report to {REPORT_PATH}")


if __name__ == "__main__":
    main()
