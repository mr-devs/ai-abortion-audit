"""
Purpose:
    Build the text-links table: every link and website name written in the
    response text, from the raw taxman audit responses.

Notes:
    - A reader sees a source whether it is a structured citation, a link, or
      a website named in plain text, so all of them are counted. Structured
      citations are in text_citations.parquet (clean_citations.py); this
      table holds what is written in the text itself.
    - Three kinds are found (toolkit.text_links.extract_text_links), each
      only where no earlier kind matched:
        1. md_link: a markdown link "[label](https://...)".
        2. bare_url: a full http(s) URL outside a markdown link.
        3. named_site: a website named without a link, e.g. "ineedana.com"
           or "plancpills.org/abortion-pill/alaska", outside any link. It
           counts only if its ending is a real top-level domain (the public
           suffix list bundled with tldextract), so "Node.js" is not a site.
           Some non-websites still pass, such as a file name whose extension
           is a country's domain ("script.py"); none occur in pilot-4cities.
    - Nothing is filtered against a list of known sites. Every match is kept
      so it can be reviewed later; the report lists every distinct named
      site to make that review easy.
    - The text is the whole response text (response_text.parquet): for
      Anthropic it includes the short text before a search ("I'll search
      for...") as well as the answer, joined into one text per response.
    - Text links are not deduplicated against text_citations here. OpenAI's
      citations are its markdown links, so the same link is in both tables;
      build_link_events.py marks those duplicates.

Input:
    - data/raw/audits/<audit>/<run_id>/manifest.json - taxman run manifests
    - data/raw/audits/<audit>/<run_id>/responses.jsonl - taxman responses
    - --audit-prefix (optional): only include audits whose name starts with
      this prefix (e.g. "pilot-").

Output:
    - data/processed/audits/text_links.parquet - one row per link or website
      name in the response text
        Columns:
            - response_id (str): Joins to metadata. (response_id, index) is
              the primary key.
            - provider (str): anthropic | openai | gemini.
            - index (int): Zero-based order of the link in the text.
            - channel (str): md_link | bare_url | named_site.
            - url (str): The link target or website name, verbatim as
              written (named_site: no scheme, e.g. "AbortionFinder.org").
            - label (str or None): md_link only - the link's visible text.
            - url_norm (str or None): Normalized URL
              (toolkit.utils.normalize_url; a named site is read as https).
            - domain (str or None): Registrable domain
              (toolkit.utils.extract_domain); None for a link with no real
              host, such as a placeholder "[link](https://)".
            - start_index (int): Character offset where the match starts in
              the response text (an md_link spans "[label](url)").
            - end_index (int): Character offset where it ends.
    - results/reports/clean_text_links_report.txt - row counts by provider
      and channel, links per response, and every distinct named site with
      its count

Author: Matthew DeVerna
"""

import argparse
import os
from pathlib import Path

import pandas as pd

from toolkit.loading import discover_runs, load_run_responses, tag_runs
from toolkit.text_links import CHANNELS, extract_text_links
from toolkit.utils import extract_domain, normalize_url

os.chdir(Path(__file__).resolve().parent)

AUDITS_DIR = Path("../../data/raw/audits")
OUTPUT_DIR = Path("../../data/processed/audits")
REPORT_PATH = Path("../../results/reports/clean_text_links_report.txt")

COLUMNS = [
    "response_id",
    "provider",
    "index",
    "channel",
    "url",
    "label",
    "url_norm",
    "domain",
    "start_index",
    "end_index",
]
STRING_COLUMNS = ["channel", "url", "label", "url_norm", "domain"]


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
    Build the text-links table.

    Parameters
    ----------
    audit_prefix : str or None
        Only include audits whose name starts with this prefix.

    Returns
    -------
    tuple of (pandas.DataFrame, pandas.DataFrame)
        (text_links, responses), where responses has one row per response
        (response_id, provider, text) for validation and the report.
    """
    rows = []
    response_rows = []
    for run in discover_runs(AUDITS_DIR, audit_prefix):
        for response in load_run_responses(run):
            base = {
                "response_id": response.get_response_id(),
                "provider": response.record["provider"],
            }
            text = response.get_text() or ""
            response_rows.append({**base, "text": text})
            for link in extract_text_links(text):
                rows.append(
                    {
                        **base,
                        **link,
                        "url_norm": normalize_url(link["url"]),
                        "domain": extract_domain(link["url"]),
                    }
                )

    text_links = pd.DataFrame(rows).reindex(columns=COLUMNS)
    # Cast so columns that are null for most rows keep a stable type.
    text_links[STRING_COLUMNS] = text_links[STRING_COLUMNS].astype("str")
    for col in ["index", "start_index", "end_index"]:
        text_links[col] = text_links[col].astype("Int64")
    return text_links, pd.DataFrame(response_rows)


def validate(text_links, responses):
    """
    Assert the table is internally consistent before writing.

    Parameters
    ----------
    text_links : pandas.DataFrame
        The table from ``build_table``.
    responses : pandas.DataFrame
        One row per response, with its text.

    Raises
    ------
    AssertionError
        If any check fails.
    """
    assert not text_links.duplicated(["response_id", "index"]).any(), (
        "Duplicate (response_id, index) in text_links"
    )
    assert text_links["channel"].isin(CHANNELS).all(), "Unknown channel"
    assert text_links["url"].notna().all(), "Null url in text_links"
    # A named site always has a domain (is_web_host checked it); a link may
    # not, e.g. a placeholder "[link](https://)", and is kept for review.
    named = text_links[text_links["channel"] == "named_site"]
    assert named["domain"].notna().all(), "A named site has no domain"

    # Each match must be found in its response text at its offsets, and
    # matches must not overlap.
    texts = dict(zip(responses["response_id"], responses["text"]))
    for row in text_links.itertuples():
        span = texts[row.response_id][row.start_index : row.end_index]
        assert row.url in span, (
            f"{row.response_id} link {row.index}: {row.url!r} is not at its offsets"
        )
    ordered = text_links.sort_values(["response_id", "start_index"])
    previous_end = ordered.groupby("response_id")["end_index"].shift()
    assert not (ordered["start_index"] < previous_end).any(), "Overlapping links"


def write_report(text_links, responses):
    """
    Write a short text report of text-link counts.

    Parameters
    ----------
    text_links : pandas.DataFrame
        The validated table.
    responses : pandas.DataFrame
        One row per response (response_id, provider, text).
    """
    # Count links per response, keeping responses with none.
    counts = text_links.groupby(["response_id", "channel"]).size().unstack(fill_value=0)
    per_response = (
        responses[["response_id", "provider"]]
        .merge(counts, left_on="response_id", right_index=True, how="left")
        .fillna(0)
    )
    channels = [c for c in CHANNELS if c in per_response.columns]

    named = text_links[text_links["channel"] == "named_site"]
    named_counts = (
        named.assign(name=named["url"].str.lower())
        .groupby(["name", "provider"])
        .size()
        .unstack(fill_value=0)
    )
    named_counts["total"] = named_counts.sum(axis=1)
    named_counts = named_counts.sort_values(["total"], ascending=False)

    lines = [
        "clean_text_links.py report",
        "",
        f"text_links rows: {len(text_links)}",
        "",
        "Rows by provider and channel:",
        text_links.groupby(["provider", "channel"]).size().to_string(),
        "",
        "Links per response by provider (mean, and share of responses with any):",
        per_response.groupby("provider")[channels].mean().round(2).to_string(),
        (per_response.set_index("provider")[channels] > 0)
        .groupby("provider")
        .mean()
        .round(2)
        .to_string(),
        "",
        "Distinct domains by provider and channel:",
        text_links.groupby(["provider", "channel"])["domain"].nunique().to_string(),
        "",
        f"Every distinct named site ({len(named_counts)}), for review:",
        named_counts.to_string() if len(named_counts) else "  (none)",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Build, validate, and write the text-links table.
    """
    args = parse_args()
    text_links, responses = build_table(args.audit_prefix)
    validate(text_links, responses)
    # Record which runs the table covers, for scripts that combine tables.
    tag_runs(text_links, discover_runs(AUDITS_DIR, args.audit_prefix))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    text_links.to_parquet(OUTPUT_DIR / "text_links.parquet", index=False)
    write_report(text_links, responses)
    print(f"Wrote {len(text_links)} text links")


if __name__ == "__main__":
    main()
