"""
Purpose:
    Score how accurate the places and claims in each AI chatbot response
    are, using loose, checkable definitions: is a recommended place
    locatable, is it in a state where abortion is legal, is it among the
    closest known options, does a response for a total-ban state send the
    user to a neighboring state, does the response describe the state's law
    consistently with Guttmacher, and is the distance it claims close to the
    real one.

Notes:
    Reference set of known abortion facilities ("pooled" benchmark):
    - There is no independent facility list yet (data/external/facilities/
      is empty while the Myers Abortion Facility Database is pending). The
      reference set is therefore pooled from the audit itself: every
      precisely located in-person place (primary or alternative) that any
      response presented as providing abortions (presented_as_abortion_
      provider "yes"), for any city, in a state without a total ban.
    - The same facility written by different responses is merged into one
      reference facility by its geocoded point, rounded to
      COORD_DECIMALS decimal places (about 110 m). Its name is the name
      written most often.
    - "strict" variants keep only reference facilities recommended by at
      least STRICT_MIN_RESPONSES distinct responses, which screens out
      places a single response may have invented.
    - If data/external/facilities/abortion_facilities.csv exists (with
      latitude and longitude), it replaces the pooled set; the column
      `reference_source` records which set was used.
    - Limitation: the pooled set holds only places some chatbot named. A
      closer clinic that all three chatbots missed is invisible, so the
      "among the closest" scores are an upper bound.

    Place checks (in-person places with a precise location):
    - locatable: geocode_precise (from compute_place_geography.py).
    - in_legal_state: the place is in a state without a total ban.
    - ref_rank: 1 + the number of reference facilities closer to the
      queried city than the place, by more than RANK_TOLERANCE_MI (absorbs
      the rounding used to merge facilities).
    - ratio_to_third: the place's distance divided by the distance to the
      3rd-nearest reference facility (the query asks for the three
      closest places).
    - among_closest: ratio_to_third <= CLOSEST_TOLERANCE (1.25, a 25%
      allowance for geocoding error and straight-line vs driving distance).
      The brief also shows how the share changes with the tolerance.
    - excess_mi: the place's distance minus the distance to the nearest
      reference facility.
    - Total-ban states: is_neighbor_state (from place_geography), the state
      of the nearest reference facility, whether that state neighbors the
      user's state, and whether the place is in it.

    Distance claims (distance_claim_verbatim, as written in the response):
    - claim_miles: the miles stated ("~75–80 miles" is 77.5, the midpoint).
      Claims with only a travel time, or no number, are null.
    - claim_anchor: the town a claim measures from when it says so (e.g.,
      "~12–14 miles east of Nashua"). Claims anchored on a town other than
      the queried city are not compared with the queried city's distance.
    - claim_ratio: claim_miles / distance_mi. Claims are often driving
      distances, which run longer than straight-line distances.

    State-law claims (state_law_claim, per response) against Guttmacher:
    - Total-ban states: "banned" is consistent; "restricted" or "legal" is
      inconsistent.
    - Most restrictive states without a total ban (6-week bans: FL, GA, IA,
      SC): "restricted" is consistent; "legal" or "banned" is inconsistent.
    - All other states: "legal" or "restricted" is consistent; "banned" is
      inconsistent.
    - "not_stated" and "unclear" are kept as their own outcomes: an
      omission, not an error.

Input:
    - data/processed/coding/place_geography.parquet
      (code/analysis/compute_place_geography.py).
    - data/processed/coding/place_entities.parquet and place_responses.parquet
      (code/cleaning/merge_llm_coding.py --task places).
    - data/processed/census/selected_cities_boundaries.parquet
      (code/cleaning/build_city_boundaries.py).
    - data/processed/census/state_neighbors.csv
      (code/cleaning/build_state_neighbors.py).
    - data/processed/guttmacher/guttmacher_state_categories.csv
      (code/cleaning/clean_guttmacher.py).
    - Optional: data/external/facilities/abortion_facilities.csv.

    Usage (from anywhere):
        uv run python code/analysis/compute_answer_accuracy.py

Output:
    - data/processed/coding/place_accuracy.parquet: one row per in-person
      place (primary or alternative), keyed by response_id and
      entity_index, with:
        - provider, role, list_position, name_verbatim, query_city,
          query_state_abbr, geoid, query_state_total_ban,
          place_state_abbr, distance_mi, is_neighbor_state.
        - locatable (bool); in_legal_state (bool or null).
        - reference_source (str): "pooled" or "external".
        - facility_id (str or null): the reference facility the place
          merges into (null if not in the reference set).
        - ref_rank, ratio_to_third, among_closest, excess_mi (and the same
          with a _strict suffix): see Notes; null if not locatable.
        - nearest_ref_state (str), nearest_ref_state_is_neighbor (bool),
          in_nearest_ref_state (bool or null).
        - claim_text, claim_miles, claim_anchor, claim_anchor_is_query_city
          (bool or null), claim_ratio (float or null).
    - data/processed/coding/reference_nearest.parquet: for every queried
      city and variant ("pooled", "strict"), its NEAREST_K nearest
      reference facilities: geoid, variant, rank, facility_id, name,
      state_abbr, lat, lon, distance_mi, n_responses.
    - data/processed/coding/reference_facilities.parquet: the reference
      set: facility_id, name, state_abbr, lat, lon, n_responses, n_places.
    - data/processed/coding/response_accuracy.parquet: one row per
      response: response_id, provider, query_city, query_state_abbr, geoid,
      query_state_total_ban, query_state_category_rank, state_law_claim,
      law_claim_check ("consistent", "inconsistent", "not_stated",
      "unclear"), n_primary, n_primary_locatable, n_primary_among_closest,
      n_primary_neighbor_state.
    - results/reports/compute_answer_accuracy_report.txt.

Author: Matthew DeVerna
"""

import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Geod

from toolkit.utils import km_to_miles

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
CODING_DIR = Path("../../data/processed/coding")
GEOGRAPHY_PATH = CODING_DIR / "place_geography.parquet"
ENTITIES_PATH = CODING_DIR / "place_entities.parquet"
RESPONSES_PATH = CODING_DIR / "place_responses.parquet"
CITY_BOUNDARIES_PATH = Path(
    "../../data/processed/census/selected_cities_boundaries.parquet"
)
NEIGHBORS_PATH = Path("../../data/processed/census/state_neighbors.csv")
GUTTMACHER_PATH = Path(
    "../../data/processed/guttmacher/guttmacher_state_categories.csv"
)
EXTERNAL_FACILITIES_PATH = Path(
    "../../data/external/facilities/abortion_facilities.csv"
)

PLACE_ACCURACY_PATH = CODING_DIR / "place_accuracy.parquet"
REFERENCE_NEAREST_PATH = CODING_DIR / "reference_nearest.parquet"
REFERENCE_FACILITIES_PATH = CODING_DIR / "reference_facilities.parquet"
RESPONSE_ACCURACY_PATH = CODING_DIR / "response_accuracy.parquet"
REPORT_PATH = Path("../../results/reports/compute_answer_accuracy_report.txt")

STUDY = "pilot-4cities"
COORD_DECIMALS = 3  # merge points within about 110 m into one facility
STRICT_MIN_RESPONSES = 2
RANK_TOLERANCE_MI = 0.25
CLOSEST_TOLERANCE = 1.25
NEAREST_K = 3
GEOD = Geod(ellps="WGS84")

# Distance claims: a number or range of numbers followed by miles.
NUMBER = r"(\d{1,4}(?:,\d{3})?(?:\.\d+)?)"
MILES_PATTERN = re.compile(
    NUMBER + r"(?:\s*(?:–|-|—|to)\s*" + NUMBER + r")?\s*(?:-\s*)?(?:miles?|mi\b)",
    re.IGNORECASE,
)
# The town a claim measures from: "<n> miles [direction] (from|of) <Town>".
ANCHOR_PATTERN = re.compile(
    r"(?:miles?|mi\.?)\s+(?:(?:north|south|east|west|northeast|northwest|"
    r"southeast|southwest)\s+)?(?:away\s+)?(?:from|of)\s+(?:downtown\s+|"
    r"central\s+)?([A-Z][A-Za-z.'\- ]*?[A-Za-z])(?=\s*(?:,|\.|;|\(|$|\s+via|"
    r"\s+along|\s+on|\s+off|\s+straight|\s+and|\s+by|\s+in))",
)


def load_policy():
    """
    Load each state's Guttmacher policy category, keyed by abbreviation.

    Returns
    -------
    pandas.DataFrame
        Indexed by state_abbr, with total_ban (bool) and category_rank (int).
    """
    cities = load_cities()
    policy = pd.read_csv(GUTTMACHER_PATH)
    states = cities[["state", "state_abbr"]].drop_duplicates()
    # Guttmacher slugs are lowercase hyphenated state names ("new-york").
    states["state_slug"] = states["state"].str.lower().str.replace(" ", "-")
    lookup = states.merge(policy, on="state_slug", how="left", validate="one_to_one")
    if lookup["category_rank"].isna().any():
        sys.exit("A sampled state has no Guttmacher category")
    # Every state with a total ban, sampled or not (a place can be anywhere).
    all_states = policy.assign(
        state_abbr=policy["state_slug"].map(slug_to_abbr(cities))
    )
    return lookup.set_index("state_abbr"), set(
        all_states.loc[all_states["total_ban"], "state_abbr"]
    )


def load_cities():
    """
    Read the sampled cities with their Census internal points.

    Returns
    -------
    pandas.DataFrame
        geoid, state, state_abbr, city_clean, intpt_lat, intpt_lon.
    """
    cities = pd.read_parquet(
        CITY_BOUNDARIES_PATH,
        columns=[
            "geoid",
            "state",
            "state_abbr",
            "city_clean",
            "intpt_lat",
            "intpt_lon",
        ],
    )
    return cities


def slug_to_abbr(cities):
    """
    Map Guttmacher state slugs to USPS abbreviations.

    Parameters
    ----------
    cities : pandas.DataFrame
        The sampled cities (every state but DC is sampled).

    Returns
    -------
    dict
        {state_slug: state_abbr}, with DC added by hand.
    """
    states = cities[["state", "state_abbr"]].drop_duplicates()
    mapping = dict(
        zip(states["state"].str.lower().str.replace(" ", "-"), states["state_abbr"])
    )
    mapping["dc"] = "DC"
    return mapping


def build_pooled_reference(places, total_ban_states):
    """
    Pool the reference facilities from the places the responses recommended.

    Parameters
    ----------
    places : pandas.DataFrame
        place_geography rows.
    total_ban_states : set of str
        Abbreviations of states with a total ban.

    Returns
    -------
    tuple of (pandas.DataFrame, pandas.Series)
        The reference facilities (facility_id, name, state_abbr, lat, lon,
        n_responses, n_places) and, for each place row that merges into one,
        its facility_id (indexed like ``places``).
    """
    eligible = places[
        places["geocode_precise"]
        & (places["presented_as_abortion_provider"] == "yes")
        & ~places["place_state_abbr"].isin(total_ban_states)
        & places["place_state_abbr"].notna()
    ].copy()
    eligible["point_key"] = (
        eligible["lat"].round(COORD_DECIMALS).astype(str)
        + ","
        + eligible["lon"].round(COORD_DECIMALS).astype(str)
    )
    grouped = eligible.groupby("point_key")
    facilities = pd.DataFrame(
        {
            # The name written most often (ties: first alphabetically).
            "name": grouped["name_verbatim"].agg(
                lambda s: (
                    s.value_counts()
                    .sort_index()
                    .sort_values(ascending=False, kind="stable")
                    .index[0]
                )
            ),
            "state_abbr": grouped["place_state_abbr"].agg(lambda s: s.mode().iloc[0]),
            "lat": grouped["lat"].mean(),
            "lon": grouped["lon"].mean(),
            "n_responses": grouped["response_id"].nunique(),
            "n_places": grouped.size(),
        }
    ).reset_index()
    facilities = facilities.sort_values(["state_abbr", "name", "point_key"])
    facilities["facility_id"] = [f"F{i + 1:04d}" for i in range(len(facilities))]
    ids = eligible["point_key"].map(facilities.set_index("point_key")["facility_id"])
    return facilities.drop(columns="point_key").reset_index(drop=True), ids


def load_external_reference():
    """
    Load the independent facility list, if one has been added.

    Returns
    -------
    pandas.DataFrame or None
        facility_id, name, state_abbr, lat, lon, n_responses (NaN), n_places
        (NaN); None if the file does not exist.
    """
    if not EXTERNAL_FACILITIES_PATH.exists():
        return None
    ext = pd.read_csv(EXTERNAL_FACILITIES_PATH, dtype={"facility_id": str})
    if ext[["latitude", "longitude"]].isna().any().any():
        sys.exit(
            "abortion_facilities.csv has rows without coordinates; geocode them first"
        )
    return pd.DataFrame(
        {
            "facility_id": ext["facility_id"],
            "name": ext["name"],
            "state_abbr": ext["state_abbr"],
            "lat": ext["latitude"],
            "lon": ext["longitude"],
            "n_responses": np.nan,
            "n_places": np.nan,
        }
    )


def city_distances(cities, facilities):
    """
    Distance in miles from every queried city to every reference facility.

    Parameters
    ----------
    cities : pandas.DataFrame
        geoid, intpt_lat, intpt_lon.
    facilities : pandas.DataFrame
        lat, lon.

    Returns
    -------
    numpy.ndarray
        Shape (n_cities, n_facilities), geodesic miles.
    """
    lon1 = np.repeat(cities["intpt_lon"].to_numpy(), len(facilities))
    lat1 = np.repeat(cities["intpt_lat"].to_numpy(), len(facilities))
    lon2 = np.tile(facilities["lon"].to_numpy(), len(cities))
    lat2 = np.tile(facilities["lat"].to_numpy(), len(cities))
    _, _, meters = GEOD.inv(lon1, lat1, lon2, lat2)
    return km_to_miles(np.asarray(meters) / 1000).reshape(len(cities), len(facilities))


def nearest_table(cities, facilities, dist, variant):
    """
    List each city's NEAREST_K nearest reference facilities.

    Parameters
    ----------
    cities : pandas.DataFrame
        The queried cities, in the row order of ``dist``.
    facilities : pandas.DataFrame
        The reference facilities, in the column order of ``dist``.
    dist : numpy.ndarray
        From ``city_distances``.
    variant : str
        "pooled" or "strict" (or "external").

    Returns
    -------
    pandas.DataFrame
        geoid, variant, rank, facility_id, name, state_abbr, lat, lon,
        distance_mi, n_responses.
    """
    rows = []
    order = np.argsort(dist, axis=1)[:, :NEAREST_K]
    for i, geoid in enumerate(cities["geoid"]):
        for rank, j in enumerate(order[i], start=1):
            f = facilities.iloc[j]
            rows.append(
                {
                    "geoid": geoid,
                    "variant": variant,
                    "rank": rank,
                    "facility_id": f["facility_id"],
                    "name": f["name"],
                    "state_abbr": f["state_abbr"],
                    "lat": f["lat"],
                    "lon": f["lon"],
                    "distance_mi": dist[i, j],
                    "n_responses": f["n_responses"],
                }
            )
    return pd.DataFrame(rows)


def score_places(places, cities, dist, suffix):
    """
    Add ref_rank, ratio_to_third, among_closest, and excess_mi for one variant.

    Parameters
    ----------
    places : pandas.DataFrame
        place_geography rows (modified in place and returned).
    cities : pandas.DataFrame
        The queried cities, in the row order of ``dist``.
    dist : numpy.ndarray
        City-to-facility distances for this variant.
    suffix : str
        "" for the main variant, "_strict" for the strict one.

    Returns
    -------
    pandas.DataFrame
        places with the four columns added (null where not locatable).
    """
    row_of = {g: i for i, g in enumerate(cities["geoid"])}
    sorted_dist = np.sort(dist, axis=1)
    ranks, ratios, excess = [], [], []
    for geoid, d, ok in zip(
        places["geoid"], places["distance_mi"], places["locatable"]
    ):
        if not ok or pd.isna(d):
            ranks.append(np.nan)
            ratios.append(np.nan)
            excess.append(np.nan)
            continue
        city = sorted_dist[row_of[geoid]]
        ranks.append(1 + int(np.sum(city < d - RANK_TOLERANCE_MI)))
        ratios.append(d / city[NEAREST_K - 1])
        excess.append(max(0.0, d - city[0]))
    places[f"ref_rank{suffix}"] = pd.array(ranks, dtype="Int64")
    places[f"ratio_to_third{suffix}"] = ratios
    places[f"among_closest{suffix}"] = (
        (pd.Series(ratios, index=places.index) <= CLOSEST_TOLERANCE)
        .where(places["locatable"])
        .astype("boolean")
    )
    places[f"excess_mi{suffix}"] = excess
    return places


def parse_claim(text):
    """
    Parse the miles and the anchor town from a distance claim.

    Parameters
    ----------
    text : str or None
        distance_claim_verbatim.

    Returns
    -------
    tuple of (float or None, str or None)
        Miles (the midpoint of a range) and the anchor town, if stated.
    """
    if not isinstance(text, str):
        return None, None
    match = MILES_PATTERN.search(text)
    miles = None
    if match:
        low = float(match.group(1).replace(",", ""))
        high = float(match.group(2).replace(",", "")) if match.group(2) else low
        miles = (low + high) / 2
    anchor = ANCHOR_PATTERN.search(text)
    return miles, anchor.group(1).strip() if anchor else None


def anchor_is_query_city(anchor, city):
    """
    Whether a claim's anchor town is the queried city.

    Parameters
    ----------
    anchor : str or None
        From ``parse_claim``.
    city : str
        The queried city (city_clean).

    Returns
    -------
    bool or None
        None when the claim names no anchor.
    """
    if not isinstance(anchor, str):
        return None
    a, c = anchor.lower(), city.lower()
    return a.startswith(c) or c.startswith(a)


def law_check(claim, total_ban, rank):
    """
    Compare a response's state-law claim with the state's Guttmacher category.

    Parameters
    ----------
    claim : str
        state_law_claim.
    total_ban : bool
        The user's state has a total ban.
    rank : int
        Guttmacher category rank (1 = most restrictive).

    Returns
    -------
    str
        "consistent", "inconsistent", "not_stated", or "unclear".
    """
    if claim in ("not_stated", "unclear"):
        return claim
    if total_ban:
        consistent = {"banned"}
    elif rank == 1:
        consistent = {"restricted"}
    else:
        consistent = {"legal", "restricted"}
    return "consistent" if claim in consistent else "inconsistent"


def write_report(places, responses, facilities, source):
    """
    Write the summary report.

    Parameters
    ----------
    places : pandas.DataFrame
        place_accuracy.
    responses : pandas.DataFrame
        response_accuracy.
    facilities : pandas.DataFrame
        The reference facilities.
    source : str
        "pooled" or "external".
    """
    primary = places[places["role"] == "primary"]
    located = primary[primary["locatable"]]
    ban = located[located["query_state_total_ban"]]
    claims = places[places["claim_miles"].notna()]
    comparable = claims[
        claims["claim_anchor_is_query_city"].fillna(True) & claims["locatable"]
    ]
    lines = [
        "compute_answer_accuracy.py report",
        "",
        f"Reference source: {source}",
        f"Reference facilities: {len(facilities)}",
        f"  recommended by >= {STRICT_MIN_RESPONSES} responses (strict set): "
        f"{int((facilities['n_responses'] >= STRICT_MIN_RESPONSES).sum())}",
        f"Closest tolerance: distance <= {CLOSEST_TOLERANCE} x the 3rd-nearest reference facility",
        "",
        "Primary places by provider:",
        pd.DataFrame(
            {
                "n_primary": primary.groupby("provider").size(),
                "share_locatable": primary.groupby("provider")["locatable"]
                .mean()
                .round(3),
                "share_in_legal_state": located.groupby("provider")["in_legal_state"]
                .mean()
                .round(3),
                "share_among_closest": located.groupby("provider")["among_closest"]
                .mean()
                .round(3),
                "share_among_closest_strict": located.groupby("provider")[
                    "among_closest_strict"
                ]
                .mean()
                .round(3),
                "median_ref_rank": located.groupby("provider")["ref_rank"].median(),
                "median_excess_mi": located.groupby("provider")["excess_mi"]
                .median()
                .round(1),
            }
        ).to_string(),
        "",
        "Primary places among the closest, by total-ban status:",
        located.groupby(["query_state_total_ban", "provider"])["among_closest"]
        .mean()
        .round(3)
        .to_string(),
        "",
        "Total-ban states, primary places: neighbor state and nearest-option state:",
        pd.DataFrame(
            {
                "n": ban.groupby("provider").size(),
                "share_neighbor_state": ban.groupby("provider")["is_neighbor_state"]
                .mean()
                .round(3),
                "share_in_nearest_ref_state": ban.groupby("provider")[
                    "in_nearest_ref_state"
                ]
                .mean()
                .round(3),
            }
        ).to_string(),
        "Total-ban cities whose nearest reference facility is in a neighboring state: "
        + f"{ban.drop_duplicates('geoid')['nearest_ref_state_is_neighbor'].mean():.3f}",
        "",
        f"Distance claims with miles: {len(claims)} "
        f"(anchored on another town: {int((claims['claim_anchor_is_query_city'] == False).sum())})",  # noqa: E712
        "Comparable claims, median claimed / straight-line ratio by provider:",
        comparable.groupby("provider")["claim_ratio"].median().round(2).to_string(),
        "",
        "State-law claim check by provider:",
        pd.crosstab(responses["provider"], responses["law_claim_check"]).to_string(),
        "",
        "Unparsed anchors (for review): "
        + ", ".join(sorted(claims["claim_anchor"].dropna().unique())),
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Score the places and responses and write the accuracy tables.
    """
    geography = pd.read_parquet(GEOGRAPHY_PATH)
    geography = geography[geography["study"] == STUDY].reset_index(drop=True)
    entities = pd.read_parquet(
        ENTITIES_PATH,
        columns=["response_id", "entity_index", "distance_claim_verbatim", "study"],
    )
    entities = entities[entities["study"] == STUDY].drop(columns="study")
    cities = load_cities()
    policy, total_ban_states = load_policy()
    neighbors = pd.read_csv(NEIGHBORS_PATH)
    neighbor_pairs = set(zip(neighbors["state_abbr"], neighbors["neighbor_abbr"]))

    places = geography.copy()
    places["locatable"] = places["geocode_precise"].astype(bool)
    places["in_legal_state"] = (
        (~places["place_state_abbr"].isin(total_ban_states))
        .where(places["place_state_abbr"].notna())
        .astype("boolean")
    )

    # Reference set: the pooled benchmark unless an external list exists.
    pooled, facility_ids = build_pooled_reference(places, total_ban_states)
    external = load_external_reference()
    source = "pooled" if external is None else "external"
    facilities = pooled if external is None else external
    places["reference_source"] = source
    places["facility_id"] = (
        facility_ids.reindex(places.index) if external is None else None
    )

    strict = facilities[facilities["n_responses"] >= STRICT_MIN_RESPONSES].reset_index(
        drop=True
    )
    dist = city_distances(cities, facilities)
    dist_strict = city_distances(cities, strict)
    places = score_places(places, cities, dist, "")
    places = score_places(places, cities, dist_strict, "_strict")

    nearest = pd.concat(
        [
            nearest_table(cities, facilities, dist, source),
            nearest_table(cities, strict, dist_strict, "strict"),
        ],
        ignore_index=True,
    )

    # The state of each city's nearest option, and whether it is a neighbor.
    first = nearest[(nearest["variant"] == source) & (nearest["rank"] == 1)].set_index(
        "geoid"
    )
    places["nearest_ref_state"] = places["geoid"].map(first["state_abbr"])
    places["nearest_ref_state_is_neighbor"] = [
        (q, n) in neighbor_pairs
        for q, n in zip(places["query_state_abbr"], places["nearest_ref_state"])
    ]
    places["in_nearest_ref_state"] = (
        (places["place_state_abbr"] == places["nearest_ref_state"])
        .where(places["place_state_abbr"].notna())
        .astype("boolean")
    )

    # Distance claims.
    places = places.merge(
        entities, on=["response_id", "entity_index"], how="left", validate="one_to_one"
    )
    parsed = places["distance_claim_verbatim"].map(parse_claim)
    places["claim_text"] = places["distance_claim_verbatim"]
    places["claim_miles"] = [p[0] for p in parsed]
    places["claim_anchor"] = [p[1] for p in parsed]
    places["claim_anchor_is_query_city"] = pd.array(
        [
            anchor_is_query_city(a, c)
            for a, c in zip(places["claim_anchor"], places["query_city"])
        ],
        dtype="boolean",
    )
    places["claim_ratio"] = places["claim_miles"] / places["distance_mi"].where(
        places["distance_mi"] > 0
    )

    place_columns = [
        "response_id",
        "entity_index",
        "provider",
        "role",
        "list_position",
        "name_verbatim",
        "query_city",
        "query_state_abbr",
        "geoid",
        "query_state_total_ban",
        "place_state_abbr",
        "distance_mi",
        "is_neighbor_state",
        "locatable",
        "in_legal_state",
        "reference_source",
        "facility_id",
        "ref_rank",
        "ratio_to_third",
        "among_closest",
        "excess_mi",
        "ref_rank_strict",
        "ratio_to_third_strict",
        "among_closest_strict",
        "excess_mi_strict",
        "nearest_ref_state",
        "nearest_ref_state_is_neighbor",
        "in_nearest_ref_state",
        "claim_text",
        "claim_miles",
        "claim_anchor",
        "claim_anchor_is_query_city",
        "claim_ratio",
    ]
    place_table = places[place_columns]
    assert not place_table.duplicated(["response_id", "entity_index"]).any()

    # Response-level checks.
    responses = pd.read_parquet(RESPONSES_PATH)
    responses = responses[responses["study"] == STUDY].copy()
    responses["query_state_total_ban"] = (
        responses["query_state_abbr"].map(policy["total_ban"]).astype(bool)
    )
    responses["query_state_category_rank"] = responses["query_state_abbr"].map(
        policy["category_rank"]
    )
    responses["law_claim_check"] = [
        law_check(c, b, r)
        for c, b, r in zip(
            responses["state_law_claim"],
            responses["query_state_total_ban"],
            responses["query_state_category_rank"],
        )
    ]
    primary = place_table[place_table["role"] == "primary"]
    counts = primary.groupby("response_id").agg(
        n_primary=("entity_index", "size"),
        n_primary_locatable=("locatable", "sum"),
        n_primary_among_closest=("among_closest", "sum"),
        n_primary_neighbor_state=("is_neighbor_state", "sum"),
    )
    responses = responses.join(counts, on="response_id", rsuffix="_coded")
    for col in counts.columns:
        responses[col] = responses[col].fillna(0).astype(int)
    response_table = responses[
        [
            "response_id",
            "provider",
            "query_city",
            "query_state_abbr",
            "geoid",
            "query_state_total_ban",
            "query_state_category_rank",
            "state_law_claim",
            "law_claim_check",
            *counts.columns,
        ]
    ].reset_index(drop=True)

    CODING_DIR.mkdir(parents=True, exist_ok=True)
    place_table.to_parquet(PLACE_ACCURACY_PATH, index=False)
    nearest.to_parquet(REFERENCE_NEAREST_PATH, index=False)
    facilities.to_parquet(REFERENCE_FACILITIES_PATH, index=False)
    response_table.to_parquet(RESPONSE_ACCURACY_PATH, index=False)
    write_report(place_table, response_table, facilities, source)
    print(
        f"Wrote {len(place_table)} places, {len(response_table)} responses, "
        f"{len(facilities)} reference facilities ({source})"
    )


if __name__ == "__main__":
    main()
