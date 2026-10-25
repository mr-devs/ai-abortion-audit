"""
Find the links and website names written in a response's text.
"""

import re
from typing import Any, Dict, List

from .utils import TLD_EXTRACTOR

#: Characters a URL or web address cannot contain here: whitespace, quotes,
#: angle and square brackets, and parentheses (which are allowed only in
#: balanced pairs, see URL_TAIL).
_URL_CHAR = r"[^\s<>\"'`()\[\]]"
#: The rest of a URL after its first character: URL characters, with one
#: level of balanced parentheses allowed (as Wikipedia URLs have, e.g.
#: ".../wiki/A_(b)"), so a URL inside "(see https://x.org)" ends before ")".
URL_TAIL = rf"{_URL_CHAR}*(?:\({_URL_CHAR}*\){_URL_CHAR}*)*"

#: A markdown link, "[label](https://...)". The URL may hold one level of
#: balanced parentheses (as Wikipedia URLs do), may be wrapped in <>, and may
#: be followed by a quoted title. Only http(s) links count: tel: and mailto:
#: links are not websites.
MARKDOWN_LINK_PATTERN = re.compile(
    r"\[(?P<label>[^\]\n]*)\]"
    r"\(\s*<?(?P<url>https?://[^\s<>()]*(?:\([^\s<>()]*\)[^\s<>()]*)*)>?"
    r"(?:\s+\"[^\"]*\")?\s*\)"
)

#: A URL written out in full outside a markdown link.
BARE_URL_PATTERN = re.compile(rf"https?://{_URL_CHAR}{URL_TAIL}")

#: A website named without a link, e.g. "ineedana.com" or
#: "plancpills.org/abortion-pill/alaska". The host is dot-separated labels
#: ending in letters, not preceded by a word character, "@", ".", "/", or "-"
#: (so it is not the middle of a longer host, URL, or email) and not followed
#: by a word character, "@", or "-" (so it is not the name part of an email).
#: An optional path follows. Whether the ending is a real top-level domain is
#: checked separately, against the public suffix list (see is_web_host).
NAMED_SITE_PATTERN = re.compile(
    r"(?<![\w@./-])"
    r"(?P<host>(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63})"
    r"(?![\w@-])"
    rf"(?P<path>/{URL_TAIL})?",
    re.IGNORECASE,
)

#: Punctuation that ends a sentence or closes markdown bold, stripped from the
#: end of a bare URL or named site ("Visit ineedana.com." -> ineedana.com).
#: "_" is not stripped: URLs can end in one.
TRAILING_PUNCTUATION = ".,;:!?*'\""

#: Link types, in the order they are matched.
CHANNELS = ("md_link", "bare_url", "named_site")


def is_web_host(host: str) -> bool:
    """
    Return whether a host ends in a real top-level domain.

    This rules out many dotted words that are not websites ("Node.js",
    "St.Louis", "a.m."), but not all: a file name whose extension is also a
    country's domain ("script.py": Paraguay; "readme.md": Moldova) passes, as
    does a missing space after a period that happens to form a real domain
    ("abortion.Care"). No such matches occur in pilot-4cities, and none are
    filtered out, so they surface in the review of named sites.

    Parameters
    ----------
    host : str
        A candidate host, e.g. "ineedana.com" or "Node.js".

    Returns
    -------
    bool
        True when tldextract finds both a registrable name and a public
        suffix ("ineedana.com"), False otherwise ("Node.js": "js" is not a
        top-level domain). Uses the suffix list bundled with tldextract
        (toolkit.utils.TLD_EXTRACTOR), so results do not depend on when or
        where the code runs.
    """
    extracted = TLD_EXTRACTOR(host)
    return bool(extracted.domain and extracted.suffix)


def _overlaps(start: int, end: int, spans: List[tuple]) -> bool:
    """Return whether [start, end) overlaps any of the (start, end) spans."""
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def extract_text_links(text: str) -> List[Dict[str, Any]]:
    """
    Return every link and website name written in a text, in text order.

    Three kinds are found, each only where no earlier kind already matched:

    1. md_link: a markdown link; ``url`` is its target and ``label`` its
       visible text.
    2. bare_url: a full URL outside a markdown link.
    3. named_site: a website named without a link, outside any link or URL;
       ``url`` is the name as written (e.g. "AbortionFinder.org"), which has
       no scheme.

    Nothing is filtered by a list of known sites: every match is returned so
    it can be reviewed later. A named site counts only if its host ends in a
    real top-level domain (``is_web_host``).

    Parameters
    ----------
    text : str or None
        The response text.

    Returns
    -------
    list of dict
        Zero-indexed rows: index, channel, url (verbatim as written), label
        (md_link only, else None), start_index, end_index (character offsets
        of the whole match in ``text``; an md_link spans "[label](url)").
    """
    text = text or ""
    found = []  # (start, end, channel, url, label)

    for match in MARKDOWN_LINK_PATTERN.finditer(text):
        found.append(
            (match.start(), match.end(), "md_link", match["url"], match["label"])
        )
    link_spans = [(start, end) for start, end, *_ in found]

    for match in BARE_URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(TRAILING_PUNCTUATION)
        start, end = match.start(), match.start() + len(url)
        if not _overlaps(start, end, link_spans):
            found.append((start, end, "bare_url", url, None))
    link_spans = [(start, end) for start, end, *_ in found]

    for match in NAMED_SITE_PATTERN.finditer(text):
        name = match.group(0).rstrip(TRAILING_PUNCTUATION)
        start, end = match.start(), match.start() + len(name)
        if is_web_host(match["host"]) and not _overlaps(start, end, link_spans):
            found.append((start, end, "named_site", name, None))

    found.sort(key=lambda row: row[0])
    return [
        {
            "index": i,
            "channel": channel,
            "url": url,
            "label": label,
            "start_index": start,
            "end_index": end,
        }
        for i, (start, end, channel, url, label) in enumerate(found)
    ]
