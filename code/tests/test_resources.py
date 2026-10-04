"""
Tests for the resource-mention lexicon in toolkit.resources.
"""

import pytest

from toolkit.resources import RESOURCES, find_resources


@pytest.mark.parametrize(
    "text, resource_id",
    [
        ("Try AbortionFinder.org to search.", "abortionfinder"),
        ("Visit INeedAnA.com", "ineedana"),
        ("I Need An A helps you find clinics", "ineedana"),
        ("Call 1-800-772-9100 for referrals", "naf"),
        ("the National Abortion Federation hotline", "naf"),
        ("The National Network of Abortion Funds can help", "abortion_funds"),
        ("**Plan C** (plancpills.org)", "plan_c"),
        ("Aid Access mails pills", "aid_access"),
        ("The M+A Hotline (1-833-246-2632)", "ma_hotline"),
        ("Repro Legal Helpline", "repro_legal"),
        ("Avoid crisis pregnancy centers", "cpc"),
        ("so-called pregnancy resource centres", "cpc"),
        ("providers protected by shield laws", "shield_laws"),
    ],
)
def test_resource_matches(text, resource_id):
    """Each resource is found in a typical phrasing."""
    assert find_resources(text)[resource_id]


@pytest.mark.parametrize(
    "text, resource_id",
    [
        ("I need an abortion as soon as possible.", "ineedana"),
        ("Make a plan carefully.", "plan_c"),
        ("Plan B is emergency contraception.", "plan_c"),
    ],
)
def test_resource_non_matches(text, resource_id):
    """Common near-miss phrasings are not counted."""
    assert not find_resources(text)[resource_id]


def test_every_resource_reported():
    """find_resources returns a key for every resource, even for empty text."""
    assert list(find_resources(None)) == [rid for rid, _, _ in RESOURCES]
