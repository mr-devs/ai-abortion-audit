"""
Purpose:
    Select the cities to audit: in every state, the most populated and least
    populated incorporated places by 2025 Census population estimate.

Notes:
    Sample:
    - N_CITIES_PER_STATE (must be even) sets the number of cities per state:
      N_CITIES_PER_STATE / 2 = the number of most populated and least populated
      cities selected.
    - Only incorporated places are eligible (SUMLEV 162 in the Census file).
    - The District of Columbia is excluded (EXCLUDED_STATES), so the sample
      covers the 50 states.
    - Places with an estimated population below MIN_POPULATION (1) are
      excluded: a few places have a 2025 estimate of 0 and would otherwise be
      picked as the least populated.
    - A state with fewer than N_CITIES_PER_STATE places contributes all of
      them, each once. Hawaii has no incorporated places; the Census lists
      "Urban Honolulu CDP" as its only SUMLEV 162 row, so Hawaii contributes
      one city. Such states are listed in the report.
    - In New England, towns are minor civil divisions rather than incorporated
      places, so the least populated places there are small cities, not
      small towns.

    Ties:
    - Population ties are broken by the lower geoid, so the sample is the same on
      every run. Ties at the cut-off (the last place selected and the first
      left out have the same population) are listed in the report.

    State abbreviations:
    - state_abbr is the two-letter USPS abbreviation from the `us` package,
      looked up by the state's two-digit FIPS code (the STATE column), which
      is an exact match. Name lookups in `us` fall back to phonetic matching,
      so they are not used. The script checks that the state name `us` returns
      for each code matches the Census STNAME.

    IDs:
    - geoid is the Census Bureau's standard identifier for a place: the
      two-digit state FIPS code followed by the five-digit place FIPS code
      (STATE + PLACE), e.g. "48" + "35000" -> "4835000" for Houston, TX.
      Place codes are assigned to be unique within a state, so geoid is
      unique nationwide, and it is the key other Census products (e.g. the
      American Community Survey) use for places. The county is not part of
      it because places can cross county lines.
    - geoid is text, always seven characters. Read it back with
      dtype={"geoid": str}: read as a number, states 01-09 lose their
      leading zero.
    - STATE + PLACE is unique only among incorporated places (SUMLEV 162).
      Elsewhere in the Census file the same codes repeat: each place also
      has one row per county it spans (SUMLEV 157), and minor civil
      divisions such as New England towns (SUMLEV 061) have PLACE "00000"
      and are identified by STATE + COUNTY + COUSUB instead. A sample that
      adds other geography types needs a geoid built for each type. The
      script checks that geoids are unique.

    City names:
    - city_official is the Census NAME, verbatim (e.g. "Houston city").
    - city_clean is the name a resident would use, for the audit queries:
        1. CITY_NAME_OVERRIDES, set by hand, for consolidated governments and
           names whose official form is not the usual one (e.g. "Urban
           Honolulu CDP" -> "Honolulu", "Boise City city" -> "Boise").
        2. Otherwise, drop a trailing "(balance)" and the trailing legal
           descriptor (city, town, village, borough, CDP, ...).
        3. Then, for names of the form "Official (Common)", e.g.
           "San Buenaventura (Ventura)", keep the common name in parentheses.
      The Census capitalization is kept; str.title() would break names such
      as "McAllen". The script stops if a selected city_clean still contains
      a descriptor word, "County", or punctuation such as parentheses, so new
      cases get an override rather than a bad query.

Input:
    - data/raw/census/sub-est2025_<timestamp>.csv (newest), written by
      code/data_collection/download_census_city_populations.py.

    Usage (from anywhere):
        uv run python code/cleaning/select_state_cities.py

Output:
    - data/processed/census/selected_cities_<N>_per_state.csv: one row per selected
      city, sorted by state and then by population (largest first), with
      columns:
        - geoid (str): Census place GEOID, STATE + PLACE FIPS codes
          (7 characters, e.g. "4835000"); read it as text.
        - state (str): state name (Census STNAME).
        - state_abbr (str): two-letter USPS state abbreviation (e.g. "TX").
        - city_official (str): official Census place name (NAME).
        - city_clean (str): everyday city name used in the audit queries.
        - pop_est_2025 (int): July 1, 2025 population estimate
          (POPESTIMATE2025).
    - results/reports/select_state_cities_report.txt: counts, short states,
      ties at the cut-off, and the full list of selected cities.

Author: Matthew DeVerna
"""

import os
import re
from pathlib import Path

import pandas as pd
import us

from toolkit.utils import latest_download

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
# Sample design
N_CITIES_PER_STATE = 4  # half most populated, half least populated
SUMLEV_INCORPORATED_PLACE = "162"
EXCLUDED_STATES = {"District of Columbia"}
MIN_POPULATION = 1

# Paths
CENSUS_DIR = Path("../../data/raw/census")
CENSUS_STEM = "sub-est2025"
CENSUS_SUFFIX = ".csv"
OUTPUT_PATH = Path(
    f"../../data/processed/census/selected_cities_{N_CITIES_PER_STATE}_per_state.csv"
)
REPORT_PATH = Path("../../results/reports/select_state_cities_report.txt")

OUTPUT_COLUMNS = [
    "geoid",
    "state",
    "state_abbr",
    "city_official",
    "city_clean",
    "pop_est_2025",
]

# Official Census name -> everyday name, where the general rules below would
# give the wrong answer. Keyed on the full official name.
CITY_NAME_OVERRIDES = {
    "Athens-Clarke County unified government (balance)": "Athens",
    "Augusta-Richmond County consolidated government (balance)": "Augusta",
    "Boise City city": "Boise",
    "Butte-Silver Bow (balance)": "Butte",
    "Lexington-Fayette urban county": "Lexington",
    "Louisville/Jefferson County metro government (balance)": "Louisville",
    "Lynchburg, Moore County metropolitan government": "Lynchburg",
    "Nashville-Davidson metropolitan government (balance)": "Nashville",
    "Palmer Town city": "Palmer",  # MA city that kept "Town" in its legal name
    "Urban Honolulu CDP": "Honolulu",
}

# Trailing "(balance)": the part of a consolidated city outside its other
# incorporated places.
BALANCE_PATTERN = re.compile(r"\s+\(balance\)$")
# Trailing legal descriptor; longer alternatives first so "city and borough"
# is removed whole.
DESCRIPTOR_PATTERN = re.compile(
    r"\s+(?:city and borough|city|town|village|borough|municipality|corporation|CDP)$"
)
# "Official (Common)" -> "Common".
COMMON_NAME_PATTERN = re.compile(r"^.+\s+\((?P<common>[^()]+)\)$")
# A cleaned name matching this still carries Census wording. Descriptors are
# lowercase in Census names, so capitalized words like "Kansas City" pass.
LEFTOVER_PATTERN = re.compile(
    r"\b(?:city|town|village|borough|municipality|corporation|CDP|government"
    r"|county|County|balance)\b|[(),/]"
)


def clean_city_name(official_name):
    """
    Return the everyday name of a place from its official Census name.

    Parameters
    ----------
    official_name : str
        Census NAME, e.g. "Houston city" or "San Buenaventura (Ventura) city".

    Returns
    -------
    str
        The everyday name, e.g. "Houston" or "Ventura".
    """
    if official_name in CITY_NAME_OVERRIDES:
        return CITY_NAME_OVERRIDES[official_name]
    name = BALANCE_PATTERN.sub("", official_name)
    name = DESCRIPTOR_PATTERN.sub("", name)
    common = COMMON_NAME_PATTERN.match(name)
    if common:
        name = common.group("common")
    return name.strip()


def state_abbreviations(census):
    """
    Map each state FIPS code in the Census file to its USPS abbreviation.

    Parameters
    ----------
    census : pandas.DataFrame
        Census rows, with STATE (two-digit FIPS code) and STNAME columns.

    Returns
    -------
    dict
        {FIPS code: abbreviation}, e.g. {"48": "TX"}.

    Raises
    ------
    ValueError
        If `us` does not know a FIPS code, or its name for the state differs
        from the Census STNAME.
    """
    abbreviations = {}
    pairs = census[["STATE", "STNAME"]].drop_duplicates()
    for fips, census_name in pairs.itertuples(index=False):
        state = us.states.lookup(fips)
        if state is None or state.name != census_name:
            raise ValueError(
                f"FIPS {fips} ({census_name}) matched {state} in the `us` package"
            )
        abbreviations[fips] = state.abbr
    return abbreviations


def load_places(census_path):
    """
    Load the eligible incorporated places from the Census file.

    Parameters
    ----------
    census_path : pathlib.Path
        The UTF-8 Census CSV.

    Returns
    -------
    pandas.DataFrame
        One row per eligible place, with columns geoid, state, state_abbr,
        city_official, and pop_est_2025.
    """
    # Read everything as text so FIPS codes keep their leading zeros.
    census = pd.read_csv(census_path, dtype=str, encoding="utf-8")
    places = census[census["SUMLEV"] == SUMLEV_INCORPORATED_PLACE]
    print(f"Incorporated places (SUMLEV {SUMLEV_INCORPORATED_PLACE}): {len(places):,}")

    places = pd.DataFrame(
        {
            "geoid": places["STATE"] + places["PLACE"],
            "state": places["STNAME"],
            "state_abbr": places["STATE"].map(state_abbreviations(places)),
            "city_official": places["NAME"],
            "pop_est_2025": places["POPESTIMATE2025"].astype(int),
        }
    )
    if places["geoid"].duplicated().any():
        raise ValueError("STATE + PLACE geoids are not unique")

    excluded_state = places["state"].isin(EXCLUDED_STATES)
    too_small = places["pop_est_2025"] < MIN_POPULATION
    print(f"Dropped {excluded_state.sum()} places in {sorted(EXCLUDED_STATES)}")
    print(
        f"Dropped {(too_small & ~excluded_state).sum()} places with population "
        f"below {MIN_POPULATION}"
    )
    return places[~excluded_state & ~too_small]


def select_cities(places, n_per_state):
    """
    Select the most and least populated places in each state.

    Parameters
    ----------
    places : pandas.DataFrame
        Output of load_places().
    n_per_state : int
        Cities per state; half from each end of the population ranking.

    Returns
    -------
    selected : pandas.DataFrame
        The selected places, sorted by state and population (largest first).
    cutoff_ties : list of str
        One line per state and end where the last place selected ties with the
        first place left out.
    """
    if n_per_state % 2 != 0:
        raise ValueError(f"N_CITIES_PER_STATE must be even, got {n_per_state}")
    n_each_end = n_per_state // 2

    selected, cutoff_ties = [], []
    for state, group in places.groupby("state"):
        # Lower id breaks population ties in both rankings.
        largest = group.sort_values(["pop_est_2025", "geoid"], ascending=[False, True])
        smallest = group.sort_values(["pop_est_2025", "geoid"], ascending=[True, True])
        for end, ranked in [("most populated", largest), ("least populated", smallest)]:
            pops = ranked["pop_est_2025"].tolist()
            if len(pops) > n_each_end and pops[n_each_end - 1] == pops[n_each_end]:
                cutoff_ties.append(
                    f"{state} ({end}): tie at population {pops[n_each_end]:,}"
                )
        # A state with fewer than n_per_state places would select some twice.
        picks = pd.concat([largest.head(n_each_end), smallest.head(n_each_end)])
        selected.append(picks.drop_duplicates(subset="geoid"))

    selected = pd.concat(selected).sort_values(
        ["state", "pop_est_2025", "geoid"], ascending=[True, False, True]
    )
    return selected.reset_index(drop=True), cutoff_ties


def add_clean_names(selected):
    """
    Add city_clean and check that every cleaned name looks like a city name.

    Parameters
    ----------
    selected : pandas.DataFrame
        Output of select_cities().

    Returns
    -------
    pandas.DataFrame
        `selected` with a city_clean column.

    Raises
    ------
    ValueError
        If a cleaned name is empty or still contains Census wording; add an
        entry to CITY_NAME_OVERRIDES for it.
    """
    selected = selected.copy()
    selected["city_clean"] = selected["city_official"].map(clean_city_name)
    bad = selected[
        (selected["city_clean"] == "")
        | selected["city_clean"].str.contains(LEFTOVER_PATTERN)
    ]
    if not bad.empty:
        raise ValueError(
            "Add these to CITY_NAME_OVERRIDES:\n"
            + bad[["state", "city_official", "city_clean"]].to_string(index=False)
        )
    return selected


def write_report(selected, cutoff_ties, census_path):
    """
    Write counts, short states, cut-off ties, and the selected cities.

    Parameters
    ----------
    selected : pandas.DataFrame
        The output table.
    cutoff_ties : list of str
        From select_cities().
    census_path : pathlib.Path
        The Census file used.
    """
    per_state = selected.groupby("state").size()
    short = per_state[per_state < N_CITIES_PER_STATE]
    renamed = selected[
        selected["city_clean"]
        != selected["city_official"].str.replace(DESCRIPTOR_PATTERN, "", regex=True)
    ]
    lines = [
        "select_state_cities.py report",
        "",
        f"Census file: {census_path.name}",
        f"Cities per state: {N_CITIES_PER_STATE} "
        f"({N_CITIES_PER_STATE // 2} most + {N_CITIES_PER_STATE // 2} least populated)",
        f"Excluded states: {', '.join(sorted(EXCLUDED_STATES))}",
        f"Minimum population: {MIN_POPULATION}",
        "",
        f"Selected cities: {len(selected)}",
        f"States: {len(per_state)}",
        "",
        f"States with fewer than {N_CITIES_PER_STATE} cities:",
        short.to_string() if not short.empty else "  none",
        "",
        "Population ties at the cut-off (broken by lower geoid):",
        "\n".join(f"  {t}" for t in cutoff_ties) if cutoff_ties else "  none",
        "",
        "Cleaned names that differ from the official name minus its descriptor:",
        renamed[["state", "city_official", "city_clean"]].to_string(index=False)
        if not renamed.empty
        else "  none",
        "",
        "Selected cities:",
        selected[OUTPUT_COLUMNS].to_string(index=False),
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Select the cities and write the CSV and report.
    """
    census_path = latest_download(CENSUS_DIR, CENSUS_STEM, CENSUS_SUFFIX)
    print(f"Reading {census_path}")

    places = load_places(census_path)
    selected, cutoff_ties = select_cities(places, N_CITIES_PER_STATE)
    selected = add_clean_names(selected)[OUTPUT_COLUMNS]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(OUTPUT_PATH, index=False, encoding="utf-8")
    write_report(selected, cutoff_ties, census_path)
    print(
        f"Wrote {len(selected)} cities in {selected['state'].nunique()} states to {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
