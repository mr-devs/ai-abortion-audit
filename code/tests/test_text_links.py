"""
Unit tests for link extraction: URL normalization in toolkit.utils, the
links and website names found in response text by toolkit.text_links, and
the citation-duplicate rule in code/cleaning/build_link_events.py.

The example texts are short copies of the patterns seen in the pilot-4cities
responses, so the tests do not depend on the data directory.

Run with: uv run pytest code/tests
"""

import importlib.util
import os
from pathlib import Path

import pandas as pd
import pytest

from toolkit.text_links import extract_text_links, is_web_host
from toolkit.utils import normalize_url

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "cleaning" / "build_link_events.py"


@pytest.fixture(scope="module")
def link_events_script():
    """Import build_link_events.py, restoring the working directory it changes."""
    cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location("build_link_events", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)
    return module


@pytest.mark.parametrize(
    "url, expected",
    [
        # OpenAI's tracking parameter and "www." are dropped.
        (
            "https://www.ineedana.com/us/alabama/mobile?utm_source=openai",
            "https://ineedana.com/us/alabama/mobile",
        ),
        # Scheme, host case, trailing slash, and fragment are normalized...
        ("http://AbortionFinder.org/Find/#top", "https://abortionfinder.org/Find"),
        # ...but other query parameters are kept, in order.
        ("https://a.org/p?id=3&utm_medium=x&b=2", "https://a.org/p?id=3&b=2"),
        # A website named without a scheme is read as https.
        (
            "plancpills.org/abortion-pill/alaska",
            "https://plancpills.org/abortion-pill/alaska",
        ),
        # A scheme counts only at the start, so this named site gets one.
        ("plancpills.org/x?u=https://y.org", "https://plancpills.org/x?u=https%3A%2F%2Fy.org"),
        # "www." is dropped only as a subdomain, and a host needs a dot.
        ("https://www.com/x", "https://www.com/x"),
        ("https://www.", None),
        ("https://", None),
        (float("nan"), None),  # a missing value from a pandas column
        ("", None),
        (None, None),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


def test_is_web_host():
    assert is_web_host("ineedana.com")
    assert is_web_host("portal.ct.gov")
    assert not is_web_host("Node.js")  # "js" is not a top-level domain


def test_extract_text_links_finds_each_channel():
    text = (
        "Call ([abortionfinder.org](https://www.abortionfinder.org/x?utm_source=openai)). "
        "See https://www.plannedparenthood.org/clinic. "
        "The I Need An A website (ineedana.com) and plancpills.org/abortion-pill/alaska."
    )
    links = extract_text_links(text)
    assert [(link["channel"], link["url"]) for link in links] == [
        ("md_link", "https://www.abortionfinder.org/x?utm_source=openai"),
        ("bare_url", "https://www.plannedparenthood.org/clinic"),
        ("named_site", "ineedana.com"),
        # The path is kept and the sentence's final period is not.
        ("named_site", "plancpills.org/abortion-pill/alaska"),
    ]
    md_link = links[0]
    assert md_link["label"] == "abortionfinder.org"
    # The markdown link's span is "[label](url)"; the label inside it is not
    # also counted as a named site.
    assert text[md_link["start_index"] : md_link["end_index"]].startswith(
        "[abortionfinder"
    )
    for link in links:
        assert link["url"] in text[link["start_index"] : link["end_index"]]


@pytest.mark.parametrize(
    "text",
    [
        "Email help@abortionfunds.org for help.",  # an email, not a site
        "Built with Node.js and St.Paul data at 9 a.m., e.g. today.",  # not domains
        "Call [the hotline](tel:+18007721001).",  # tel: links are not websites
    ],
)
def test_extract_text_links_skips_non_websites(text):
    assert extract_text_links(text) == []


def test_extract_text_links_handles_markdown_emphasis_and_parentheses():
    text = "Use **AbortionFinder.org** or [wiki](https://en.wikipedia.org/wiki/A_(b))."
    links = extract_text_links(text)
    assert [(link["channel"], link["url"]) for link in links] == [
        ("named_site", "AbortionFinder.org"),
        ("md_link", "https://en.wikipedia.org/wiki/A_(b)"),
    ]


def test_citation_link_span_trims_openai_parentheses(link_events_script):
    text = "Clinic. ([site.org](https://site.org))\n"
    start = text.index("(")
    trimmed = link_events_script.citation_link_span(text, start, len(text))
    assert text[slice(*trimmed)] == "[site.org](https://site.org)"


def test_find_duplicates_matches_only_the_same_link(link_events_script):
    def span(text, part):
        start = text.index(part)
        return start, start + len(part)

    text = "A clinic. ([a.org](https://a.org)) Gemini cites [b.org](https://b.org) here."
    # The first citation is exactly the a.org link with parentheses (OpenAI);
    # the second covers a sentence that contains the b.org link (Gemini).
    cited = [span(text, "([a.org](https://a.org))"), span(text, "Gemini cites [b.org](https://b.org) here.")]
    linked = [span(text, "[a.org](https://a.org)"), span(text, "[b.org](https://b.org)")]
    citations = pd.DataFrame(
        {
            "response_id": ["r1", "r1"],
            "index": [0, 1],
            "url": ["https://a.org", "https://redirect/b"],
            "url_norm": ["https://a.org", "https://b.org"],
            "start_index": [s for s, _ in cited],
            "end_index": [e for _, e in cited],
        }
    )
    links = pd.DataFrame(
        {
            "response_id": ["r1", "r1"],
            "url": ["https://a.org", "https://b.org"],
            "url_norm": ["https://a.org", "https://b.org"],
            "start_index": [s for s, _ in linked],
            "end_index": [e for _, e in linked],
        }
    )
    duplicates = link_events_script.find_duplicates(citations, links, {"r1": text})
    assert duplicates.iloc[0] == 0  # the same visible link
    assert pd.isna(duplicates.iloc[1])  # a separate link inside a cited sentence


def test_extract_text_links_keeps_whole_bare_urls():
    text = "Go to https://a.org/wiki/A_(b) or https://a.org/path_ (see https://x.org)."
    assert [link["url"] for link in extract_text_links(text)] == [
        "https://a.org/wiki/A_(b)",  # balanced parentheses are part of the URL
        "https://a.org/path_",  # a final "_" is kept
        "https://x.org",  # the closing ")" and "." are not
    ]


def test_extract_text_links_keeps_placeholder_links():
    (link,) = extract_text_links("See [link](https://) for more.")
    assert (link["channel"], link["url"]) == ("md_link", "https://")
    assert normalize_url(link["url"]) is None


def test_find_duplicates_matches_gemini_on_the_resolved_url(link_events_script):
    # A Gemini citation that is exactly a markdown link: its verbatim url is
    # a Google redirect, but url_norm (from the resolved URL) matches.
    text = "[a.org](https://www.a.org/)"
    citations = pd.DataFrame(
        {
            "response_id": ["r1"],
            "index": [0],
            "url": ["https://vertexaisearch.cloud.google.com/redirect/1"],
            "url_norm": ["https://a.org"],
            "start_index": [0],
            "end_index": [len(text)],
        }
    )
    links = pd.DataFrame(
        {
            "response_id": ["r1"],
            "url": ["https://www.a.org/"],
            "url_norm": ["https://a.org"],
            "start_index": [0],
            "end_index": [len(text)],
        }
    )
    duplicates = link_events_script.find_duplicates(citations, links, {"r1": text})
    assert duplicates.iloc[0] == 0


def test_load_tables_rejects_tables_from_different_runs(link_events_script, tmp_path, monkeypatch):
    from toolkit.loading import RUNS_ATTR

    for name in ["text_citations", "text_links", "tool_citations", "tool_calls", "response_text"]:
        df = pd.DataFrame({"response_id": ["r1"]})
        # text_links was built from one audit only, the rest from two.
        df.attrs[RUNS_ATTR] = ["a/1"] if name == "text_links" else ["a/1", "b/2"]
        df.to_parquet(tmp_path / f"{name}.parquet", index=False)
    monkeypatch.setattr(link_events_script, "PROCESSED_DIR", tmp_path)
    with pytest.raises(SystemExit, match="different runs"):
        link_events_script.load_tables()
