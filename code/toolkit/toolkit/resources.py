"""
Keyword lexicon of abortion-access resources that responses may mention.

Each pattern is a case-insensitive regular expression written in the subset of
syntax shared by Python's `re` and JavaScript's `RegExp`, so the interactive
explorer can highlight exactly the matches that were counted here. Matches are
exploratory keyword hits: a hit means the response names the resource, not
that it recommends or endorses it.
"""

import re
from typing import Dict, List

#: (id, label, pattern). Order is the display order in reports and figures.
RESOURCES = [
    ("abortionfinder", "AbortionFinder", r"abortion\s?finder"),
    # The trailing \b keeps "I need an abortion" from matching.
    ("ineedana", "I Need An A", r"i\s?need\s?an\s?a\b"),
    ("planned_parenthood", "Planned Parenthood", r"planned\s+parenthood"),
    (
        "naf",
        "National Abortion Federation / hotline",
        r"national\s+abortion\s+federation|\bNAF\b|800[-.\s]?772[-.\s]?9100",
    ),
    (
        "abortion_funds",
        "Abortion funds",
        r"abortion\s+funds?\b|abortionfunds\.org",
    ),
    ("plan_c", "Plan C", r"\bplan\s?c\b|plancpills"),
    ("aid_access", "Aid Access", r"aid\s?access"),
    (
        "ma_hotline",
        "M+A Hotline",
        r"M\s?\+\s?A\s+hotline|miscarriage\s*(?:&|and|\+)\s*abortion\s+hotline"
        r"|833[-.\s]?246[-.\s]?2632",
    ),
    (
        "repro_legal",
        "Repro Legal Helpline",
        r"repro\s?legal\s+(?:help\s?line|defense)|if/when/how",
    ),
    ("telehealth", "Telehealth abortion", r"telehealth|tele-health|telemedicine"),
    ("shield_laws", "Shield laws", r"shield\s+laws?|shield\s+provider"),
    (
        "cpc",
        "Crisis pregnancy centers",
        r"crisis\s+pregnancy\s+cent(?:er|re)s?|pregnancy\s+resource\s+cent(?:er|re)s?"
        r"|fake\s+(?:abortion\s+)?clinics?",
    ),
]

_COMPILED = [(rid, re.compile(pattern, re.IGNORECASE)) for rid, _, pattern in RESOURCES]


def find_resources(text: str) -> Dict[str, bool]:
    """
    Return which resources a response text mentions.

    Parameters
    ----------
    text : str
        The response text shown to the user (markdown, links included).

    Returns
    -------
    dict
        {resource_id: bool} for every resource in RESOURCES, in order.
    """
    text = text or ""
    return {rid: bool(rx.search(text)) for rid, rx in _COMPILED}


def resource_table() -> List[Dict[str, str]]:
    """
    Return the lexicon as a list of records for export.

    Returns
    -------
    list of dict
        One {"id", "label", "pattern"} dict per resource, in display order.
    """
    return [
        {"id": rid, "label": label, "pattern": pattern}
        for rid, label, pattern in RESOURCES
    ]
