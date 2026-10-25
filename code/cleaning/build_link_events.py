"""
Purpose:
    Build the link-events table: every link, citation, and website name in
    every response, whether shown to the reader or only retrieved by a
    search, stacked into one long table with one row per occurrence.

Notes:
    - This is the table the analysis counts sources from. It stacks the
      cleaned tables rather than re-reading the raw responses, so each row
      can be traced back with (source_table, source_index):
        - citation (text_citations): a structured citation attached to the
          text.
        - md_link, bare_url, named_site (text_links): a link or website name
          written in the text.
        - search_result (tool_citations): a URL a search returned.
        - open_page, find_in_page (tool_calls): a page OpenAI opened, or
          searched within.
    - shown_to_reader is True for the first four channels: a reader sees a
      source whether it is a citation, a link, or a website named in plain
      text, so all of them count as sources shown. The rest were retrieved
      but not necessarily shown.
    - Counting rule (duplicates): the same visible link can be both a
      citation and a markdown link. In pilot-4cities every OpenAI citation is
      exactly one markdown link with parentheses around it, "([site](url))".
      A text link is marked as a duplicate of a citation (duplicate_of_citation
      holds the citation's index) when the citation's span, after trimming
      whitespace and one pair of surrounding parentheses, is exactly the
      link's span, and both point to the same page (same url_norm, which for
      Gemini comes from the resolved URL). Count occurrences with
      duplicate_of_citation null. Distinct-URL and distinct-domain counts are
      unaffected. A Gemini link inside a cited sentence is not a duplicate:
      the reader sees both the link and a citation marker.
    - The script stops if any OpenAI citation is not matched by exactly one
      markdown link, because the counting rule depends on that. It also
      stops if its input tables were built from different runs (e.g. the
      cleaning scripts were run with different --audit-prefix values): each
      table records its runs (toolkit.loading.tag_runs), and they must match.
    - Opened pages are taken only from page actions that ran
      (tool_calls.ran) and have a URL.
    - url is the URL the source points to: the verbatim URL, except for
      Gemini citations, where it is the resolved URL (the verbatim Google
      redirect URL stays in text_citations.url). For named_site it is the
      website name as written.
    - search_caller says how an Anthropic search was run: "code_execution"
      when Claude ran it from code (dynamic filtering), "direct" when Claude
      called it directly. Only directly called searches have produced
      structured citations.

Input:
    - data/processed/audits/text_citations.parquet and tool_citations.parquet
      (clean_citations.py)
    - data/processed/audits/text_links.parquet (clean_text_links.py)
    - data/processed/audits/tool_calls.parquet (clean_tool_calls.py)
    - data/processed/audits/response_text.parquet (clean_metadata_text.py)

Output:
    - data/processed/audits/link_events.parquet - one row per link occurrence
        Columns:
            - response_id (str): Joins to metadata. (response_id,
              source_table, source_index) is the primary key.
            - provider (str): anthropic | openai | gemini.
            - channel (str): citation | md_link | bare_url | named_site |
              search_result | open_page | find_in_page.
            - shown_to_reader (bool): True for citation, md_link, bare_url,
              and named_site.
            - url (str): The URL the source points to (see Notes).
            - url_norm (str or None): Normalized URL
              (toolkit.utils.normalize_url).
            - domain (str or None): Registrable domain.
            - start_index (int or None): Character offset where the source
              starts in the response text (shown channels only).
            - end_index (int or None): Character offset where it ends.
            - tool_id (str or None): The tool call that retrieved the URL
              (retrieved channels only); joins to tool_calls.
            - search_caller (str or None): Anthropic search_result only -
              "code_execution" or "direct".
            - duplicate_of_citation (int or None): Text links only - the
              text_citations index of the citation this link is the same
              object as; null when it is not a duplicate.
            - source_table (str): text_citations | text_links |
              tool_citations | tool_calls.
            - source_index (int): The row's index in source_table (within
              its response).
    - results/reports/build_link_events_report.txt - rows by provider and
      channel, duplicates, and distinct domains shown to the reader per
      response

Author: Matthew DeVerna
"""

import os
from pathlib import Path

import pandas as pd

from toolkit.loading import RUNS_ATTR
from toolkit.utils import extract_domain, normalize_url

os.chdir(Path(__file__).resolve().parent)

PROCESSED_DIR = Path("../../data/processed/audits")
OUTPUT_PATH = PROCESSED_DIR / "link_events.parquet"
REPORT_PATH = Path("../../results/reports/build_link_events_report.txt")

#: Channels a reader sees in the response text.
SHOWN_CHANNELS = ["citation", "md_link", "bare_url", "named_site"]
#: tool_calls tool types that open a page, mapped to their channel.
PAGE_TOOL_CHANNELS = {
    "web_search.open_page": "open_page",
    "web_search.find_in_page": "find_in_page",
}

COLUMNS = [
    "response_id",
    "provider",
    "channel",
    "shown_to_reader",
    "url",
    "url_norm",
    "domain",
    "start_index",
    "end_index",
    "tool_id",
    "search_caller",
    "duplicate_of_citation",
    "source_table",
    "source_index",
]
STRING_COLUMNS = [
    "channel",
    "url",
    "url_norm",
    "domain",
    "tool_id",
    "search_caller",
    "source_table",
]
INT_COLUMNS = ["start_index", "end_index", "duplicate_of_citation", "source_index"]


def load_tables():
    """
    Read the cleaned tables this script stacks.

    Returns
    -------
    dict of pandas.DataFrame
        Keyed by table name.

    Raises
    ------
    SystemExit
        If the tables were not all built from the same runs.
    """
    names = [
        "text_citations",
        "text_links",
        "tool_citations",
        "tool_calls",
        "response_text",
    ]
    tables = {name: pd.read_parquet(PROCESSED_DIR / f"{name}.parquet") for name in names}

    # Each cleaning script writes a fixed filename whatever --audit-prefix it
    # was given, so check that every table covers the same runs.
    runs = {name: tuple(df.attrs.get(RUNS_ATTR) or ()) for name, df in tables.items()}
    if len(set(runs.values())) != 1 or not runs["response_text"]:
        lines = [f"  {name}: {len(r)} runs" for name, r in runs.items()]
        raise SystemExit(
            "The input tables were built from different runs (or are untagged):\n"
            + "\n".join(lines)
            + "\nRe-run the cleaning scripts with the same --audit-prefix."
        )
    return tables


def opened_pages(tool_calls):
    """
    Return which tool calls opened a page: page actions that ran and have a URL.

    Parameters
    ----------
    tool_calls : pandas.DataFrame
        tool_calls.parquet.

    Returns
    -------
    pandas.Series of bool
        Aligned with tool_calls.
    """
    return (
        tool_calls["tool_type"].isin(PAGE_TOOL_CHANNELS)
        & tool_calls["ran"]
        & tool_calls["url"].notna()
    )


def citation_link_span(text, start, end):
    """
    Return a citation's span with whitespace and one pair of parentheses trimmed.

    OpenAI's citation span is the markdown link with the parentheses around
    it, "([site](url))"; trimming them gives the markdown link's own span.

    Parameters
    ----------
    text : str
        The response text.
    start, end : int
        The citation's character offsets.

    Returns
    -------
    tuple of (int, int)
        The trimmed (start, end).
    """
    segment = text[start:end]
    start += len(segment) - len(segment.lstrip())
    end -= len(segment) - len(segment.rstrip())
    if text[start : start + 1] == "(" and text[end - 1 : end] == ")":
        start, end = start + 1, end - 1
    return start, end


def find_duplicates(text_citations, text_links, texts):
    """
    Return, for each text link, the index of the citation it duplicates.

    Parameters
    ----------
    text_citations, text_links : pandas.DataFrame
        The cleaned tables.
    texts : dict
        {response_id: response text}.

    Returns
    -------
    pandas.Series
        Aligned with text_links: the duplicated citation's index, or NA.
    """
    # (response_id, start, end, url_norm) of every citation's trimmed span.
    # Pages are compared on url_norm, which for Gemini holds the resolved URL
    # rather than the Google redirect. Rows without one cannot match.
    citation_spans = {}
    for row in text_citations[text_citations["url_norm"].notna()].itertuples():
        start, end = citation_link_span(
            texts[row.response_id], row.start_index, row.end_index
        )
        citation_spans[(row.response_id, start, end, row.url_norm)] = row.index
    return pd.Series(
        [
            citation_spans.get((r.response_id, r.start_index, r.end_index, r.url_norm))
            if pd.notna(r.url_norm)
            else None
            for r in text_links.itertuples()
        ],
        index=text_links.index,
        dtype="Int64",
    )


def build_table(tables):
    """
    Stack the cleaned tables into the link-events table.

    Parameters
    ----------
    tables : dict of pandas.DataFrame
        From ``load_tables``.

    Returns
    -------
    pandas.DataFrame
        The link-events table.
    """
    texts = dict(
        zip(tables["response_text"]["response_id"], tables["response_text"]["text"])
    )
    text_citations = tables["text_citations"]
    text_links = tables["text_links"]
    tool_citations = tables["tool_citations"]
    tool_calls = tables["tool_calls"]

    citations = text_citations.assign(
        channel="citation",
        # Gemini's verbatim url is a Google redirect; the source is resolved_url.
        url=text_citations["resolved_url"].fillna(text_citations["url"]),
        source_table="text_citations",
        source_index=text_citations["index"],
    )

    links = text_links.assign(
        duplicate_of_citation=find_duplicates(text_citations, text_links, texts),
        source_table="text_links",
        source_index=text_links["index"],
    )

    # A search launched from code has a caller_tool_id; a direct one does not.
    anthropic_searches = tool_calls[
        (tool_calls["provider"] == "anthropic")
        & (tool_calls["tool_type"] == "web_search")
    ]
    callers = dict(
        zip(
            zip(anthropic_searches["response_id"], anthropic_searches["tool_id"]),
            anthropic_searches["caller_tool_id"]
            .notna()
            .map({True: "code_execution", False: "direct"}),
        )
    )
    results = tool_citations.assign(
        channel="search_result",
        search_caller=[
            callers.get(pair)
            for pair in zip(tool_citations["response_id"], tool_citations["tool_id"])
        ],
        source_table="tool_citations",
        source_index=tool_citations["index"],
    )

    pages = tool_calls[opened_pages(tool_calls)]
    pages = pages.assign(
        channel=pages["tool_type"].map(PAGE_TOOL_CHANNELS),
        url_norm=pages["url"].map(normalize_url),
        domain=pages["url"].map(extract_domain),
        source_table="tool_calls",
        source_index=pages["index"],
    )

    events = pd.concat(
        [df.reindex(columns=COLUMNS) for df in [citations, links, results, pages]],
        ignore_index=True,
    )
    events["shown_to_reader"] = events["channel"].isin(SHOWN_CHANNELS)
    events[STRING_COLUMNS] = events[STRING_COLUMNS].astype("str")
    events[INT_COLUMNS] = events[INT_COLUMNS].astype("Int64")
    events["shown_to_reader"] = events["shown_to_reader"].astype("bool")
    return events


def validate(events, tables):
    """
    Assert the table is complete and consistent before writing.

    Parameters
    ----------
    events : pandas.DataFrame
        The table from ``build_table``.
    tables : dict of pandas.DataFrame
        The cleaned input tables.

    Raises
    ------
    AssertionError
        If any check fails.
    """
    assert not events.duplicated(
        ["response_id", "source_table", "source_index"]
    ).any(), "Duplicate (response_id, source_table, source_index) in link_events"
    assert events["url"].notna().all(), "Null url in link_events"

    # Every input row is in the table exactly once.
    pages = opened_pages(tables["tool_calls"]).sum()
    expected = {
        "text_citations": len(tables["text_citations"]),
        "text_links": len(tables["text_links"]),
        "tool_citations": len(tables["tool_citations"]),
        "tool_calls": pages,
    }
    observed = events["source_table"].value_counts().to_dict()
    for table, n in expected.items():
        assert observed.get(table, 0) == n, f"{table}: {observed.get(table, 0)} != {n}"

    # The counting rule assumes each OpenAI citation is one markdown link.
    openai_cites = tables["text_citations"]["provider"] == "openai"
    links = events[events["source_table"] == "text_links"]
    matches = links["duplicate_of_citation"].notna()
    per_citation = (
        links[matches]
        .groupby(["response_id", "duplicate_of_citation"])
        .size()
        .rename("n")
    )
    openai_keys = tables["text_citations"].loc[openai_cites, ["response_id", "index"]]
    matched = openai_keys.merge(
        per_citation.reset_index(),
        left_on=["response_id", "index"],
        right_on=["response_id", "duplicate_of_citation"],
        how="left",
    )["n"]
    assert (matched == 1).all(), (
        f"{(matched != 1).sum()} OpenAI citations are not exactly one markdown link; "
        "review the duplicate rule in build_link_events.py"
    )


def write_report(events, responses):
    """
    Write a short text report of link-event counts.

    Parameters
    ----------
    events : pandas.DataFrame
        The validated table.
    responses : pandas.DataFrame
        One row per response (response_text.parquet).
    """
    shown = events[events["shown_to_reader"]]
    domains = shown.groupby("response_id")["domain"].nunique().rename("n_domains")
    per_response = responses[["response_id", "provider"]].merge(
        domains, left_on="response_id", right_index=True, how="left"
    )
    per_response["n_domains"] = per_response["n_domains"].fillna(0)

    lines = [
        "build_link_events.py report",
        "",
        f"link_events rows: {len(events)}",
        "",
        "Rows by provider and channel:",
        events.groupby(["provider", "channel"]).size().to_string(),
        "",
        "Text links that duplicate a citation, by provider:",
        events[events["duplicate_of_citation"].notna()]
        .groupby("provider")
        .size()
        .to_string(),
        "",
        "Anthropic search results by search_caller:",
        events[events["search_caller"].notna()]
        .groupby("search_caller")
        .size()
        .to_string(),
        "",
        "Distinct domains shown to the reader per response, by provider:",
        per_response.groupby("provider")["n_domains"]
        .agg(
            mean="mean",
            median="median",
            n_with_none=lambda s: int((s == 0).sum()),
            n_responses="size",
        )
        .round(2)
        .to_string(),
        "",
        "Distinct domains shown to the reader across all responses:",
        shown.groupby("provider")["domain"].nunique().to_string(),
        f"all providers: {shown['domain'].nunique()}",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Build, validate, and write the link-events table.
    """
    tables = load_tables()
    events = build_table(tables)
    validate(events, tables)
    events.to_parquet(OUTPUT_PATH, index=False)
    write_report(events, tables["response_text"])
    print(f"Wrote {len(events)} link events")


if __name__ == "__main__":
    main()
