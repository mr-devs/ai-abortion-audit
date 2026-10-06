"""
Unit tests for the pilot-4cities city sample: city-name cleaning, city
selection, and state abbreviations in code/cleaning/select_state_cities.py,
and the download-file helpers in toolkit.utils.

The inputs are small inline examples copied from the Census file, so the tests
do not depend on the data directory.

Run with: uv run pytest code/tests
"""

import importlib.util
import os
from pathlib import Path

import pandas as pd
import pytest

from toolkit.utils import find_existing_downloads, latest_download, timestamped_path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "cleaning" / "select_state_cities.py"
)


@pytest.fixture(scope="module")
def select_script():
    """Import select_state_cities.py, restoring the working directory it changes."""
    cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location("select_state_cities", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)
    return module


@pytest.mark.parametrize(
    "official, clean",
    [
        ("Houston city", "Houston"),
        ("Addison town", "Addison"),
        ("Monowi village", "Monowi"),
        ("Fenwick borough", "Fenwick"),
        ("Anchorage municipality", "Anchorage"),
        ("Juneau city and borough", "Juneau"),
        ("Ranson corporation", "Ranson"),
        ("New York city", "New York"),
        ("Kansas City city", "Kansas City"),
        ("St. Paul city", "St. Paul"),
        ("La Cañada Flintridge city", "La Cañada Flintridge"),
        ("Indianapolis city (balance)", "Indianapolis"),
        ("San Buenaventura (Ventura) city", "Ventura"),
        ("Urban Honolulu CDP", "Honolulu"),
        ("Boise City city", "Boise"),
        ("Nashville-Davidson metropolitan government (balance)", "Nashville"),
        ("Louisville/Jefferson County metro government (balance)", "Louisville"),
    ],
)
def test_clean_city_name(select_script, official, clean):
    """Official Census names map to the everyday name."""
    assert select_script.clean_city_name(official) == clean


@pytest.mark.parametrize(
    "official",
    ["Echols County consolidated government", "Webster County unified government"],
)
def test_leftover_census_wording_is_caught(select_script, official):
    """Names the rules cannot clean are flagged, so they get an override."""
    cleaned = select_script.clean_city_name(official)
    assert select_script.LEFTOVER_PATTERN.search(cleaned)


def test_select_cities_ends_and_ties(select_script):
    """Two largest and two smallest per state; ties go to the lower geoid."""
    places = pd.DataFrame(
        {
            "geoid": ["0100001", "0100002", "0100003", "0100004", "0100005", "0100006", "0200007"],
            "state": ["A"] * 6 + ["B"],
            "city_official": [f"P{i} city" for i in range(1, 8)],
            "pop_est_2025": [1000, 500, 50, 10, 10, 10, 300],
        }
    )
    selected, ties = select_script.select_cities(places, 4)
    state_a = selected[selected["state"] == "A"]
    # 1 and 2 are largest; 4, 5, 6 tie for smallest and the lower geoids win.
    assert state_a["geoid"].tolist() == ["0100001", "0100002", "0100004", "0100005"]
    assert ties == ["A (least populated): tie at population 10"]
    # A state with a single place contributes it once.
    assert selected[selected["state"] == "B"]["geoid"].tolist() == ["0200007"]


def test_select_cities_rejects_odd_n(select_script):
    """An odd number of cities per state cannot be split evenly."""
    places = pd.DataFrame(
        {"geoid": ["0100001"], "state": ["A"], "city_official": ["X city"], "pop_est_2025": [5]}
    )
    with pytest.raises(ValueError):
        select_script.select_cities(places, 3)


def test_state_abbreviations(select_script):
    """FIPS codes map to USPS abbreviations; a name mismatch is an error."""
    census = pd.DataFrame(
        {
            "STATE": ["48", "48", "15", "11"],
            "STNAME": ["Texas", "Texas", "Hawaii", "District of Columbia"],
        }
    )
    assert select_script.state_abbreviations(census) == {
        "48": "TX",
        "15": "HI",
        "11": "DC",
    }
    wrong_name = pd.DataFrame({"STATE": ["48"], "STNAME": ["Oklahoma"]})
    with pytest.raises(ValueError):
        select_script.state_abbreviations(wrong_name)


def test_download_helpers(tmp_path):
    """Earlier downloads are found whatever their timestamp; the newest wins."""
    with pytest.raises(FileNotFoundError):
        latest_download(tmp_path, "sub-est2025", ".csv")
    older = tmp_path / "sub-est2025_2026-10-05.csv"  # date-only name
    newer = tmp_path / "sub-est2025_2026-10-05_144244.csv"
    other = tmp_path / "SUB-EST2025_2026-10-05_144244.pdf"
    for path in (older, newer, other):
        path.write_text("")
    assert find_existing_downloads(tmp_path, "sub-est2025", ".csv") == [older, newer]
    assert latest_download(tmp_path, "sub-est2025", ".csv") == newer
    new_path = timestamped_path(tmp_path, "sub-est2025", ".csv")
    assert new_path.parent == tmp_path and new_path.name.startswith("sub-est2025_")
