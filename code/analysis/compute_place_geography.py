"""
Purpose:
    Locate every in-person place the AI chatbot responses recommended and
    measure it against the city in the query: is it inside the city limits,
    how far away is it, is it in another state, and is that state a
    neighbor of the user's state.

Notes:
    Which places:
    - Entities with role "primary" or "alternative" (place_entities.parquet).
      Hotlines, websites, and other resources have no location.

    Choosing a location:
    - A Census Geocoder match is used first (geocoder "census"). A Census
      non-match uses Nominatim's match (geocoder "nominatim").
    - geocode_precise is true for every Census match, and for a Nominatim
      match with place_rank >= MIN_PRECISE_PLACE_RANK (26 = a street;
      30 = a building). A coarser Nominatim match (e.g., only the town) and
      an address with no street are not precise, and every location measure
      below is null for them.
    - The address is the one the response wrote, so a wrong address yields
      a wrong location; this measures what the response told the user.

    Measures (for precise locations only):
    - place_state_abbr: the state whose Census 2025 TIGER/Line outline
      contains the point.
    - in_query_city: the point is inside the queried city's legal limits
      (Census 2025 TIGER/Line places).
    - distance_km: geodesic distance on the WGS84 ellipsoid from the queried
      city's Census internal point to the place. The Census coordinates are
      NAD83, which differs from WGS84 by about a meter in the US.
      distance_mi is the same distance in miles (toolkit.utils.km_to_miles).
    - crosses_state: place_state_abbr differs from the user's state.
    - is_neighbor_state: the place is in a state that touches the user's
      state (data/processed/census/state_neighbors.csv; Four Corners point
      contacts count, see neighbor_border_type).
    - stated_state_matches: the state the response wrote matches
      place_state_abbr (null if the response gave no state).

    The user's state:
    - query_state_total_ban is true when the user's state enforces a total
      abortion ban (Guttmacher's "Total abortion ban"); it splits the states
      into total-ban states and all others. query_state_environment_type
      and query_state_category_rank are the state's Guttmacher policy
      category (1 = most restrictive, 7 = most protective), kept for
      reference. All come from guttmacher_state_categories.csv.

Input:
    - data/processed/coding/place_entities.parquet
      (code/cleaning/merge_llm_coding.py --task places).
    - data/raw/geocoding/census_geocoder.jsonl and nominatim.jsonl
      (code/data_collection/geocode_place_addresses.py).
    - data/processed/census/selected_cities_boundaries.parquet
      (code/cleaning/build_city_boundaries.py).
    - data/processed/census/state_neighbors.csv
      (code/cleaning/build_state_neighbors.py).
    - data/raw/census/boundaries/tl_2025_us_state_<timestamp>.parquet (newest)
      (code/data_collection/download_census_boundaries.py).
    - data/processed/census/selected_cities_4_per_state.csv and
      data/processed/guttmacher/guttmacher_state_categories.csv.

    Usage (from anywhere):
        uv run python code/analysis/compute_place_geography.py

Output:
    - data/processed/coding/place_geography.parquet: one row per in-person
      entity, with:
        - response_id, entity_index (the primary key), provider, model,
          study, audit, location, query_city, query_state_abbr, geoid.
        - role, list_position, name_verbatim, entity_type,
          presented_as_abortion_provider (from place_entities).
        - query_state_total_ban (bool), query_state_environment_type (str),
          query_state_category_rank (int).
        - address_key (str or null; null if the entity has no street).
        - geocoder (str or null): "census", "nominatim", or null (no match
          or not geocoded).
        - geocode_match_type (str or null): the Census matchtype ("Exact",
          "Non_Exact") or "place_rank <n>" for Nominatim.
        - geocode_precise (bool).
        - lat, lon (float or null): the location used.
        - place_state_abbr (str or null), in_query_city (bool or null),
          distance_km, distance_mi (float or null: the same distance in
          kilometers and miles), crosses_state (bool or null),
          is_neighbor_state (bool or null), neighbor_border_type (str or
          null: "land", "point", or null when not a neighbor),
          stated_state_matches (bool or null).
    - results/reports/compute_place_geography_report.txt: geocoding rates
      and the measures by provider and by the user's state policy category.

Author: Matthew DeVerna
"""

import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod

from toolkit.utils import km_to_miles, latest_download

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_collection"))
from geocode_place_addresses import address_key  # noqa: E402

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
ENTITIES_PATH = Path("../../data/processed/coding/place_entities.parquet")
CENSUS_CACHE = Path("../../data/raw/geocoding/census_geocoder.jsonl")
NOMINATIM_CACHE = Path("../../data/raw/geocoding/nominatim.jsonl")
CITY_BOUNDARIES_PATH = Path(
    "../../data/processed/census/selected_cities_boundaries.parquet"
)
NEIGHBORS_PATH = Path("../../data/processed/census/state_neighbors.csv")
BOUNDARIES_DIR = Path("../../data/raw/census/boundaries")
STATES_STEM = "tl_2025_us_state"
CITIES_PATH = Path("../../data/processed/census/selected_cities_4_per_state.csv")
GUTTMACHER_PATH = Path(
    "../../data/processed/guttmacher/guttmacher_state_categories.csv"
)
OUTPUT_PATH = Path("../../data/processed/coding/place_geography.parquet")
REPORT_PATH = Path("../../results/reports/compute_place_geography_report.txt")

PLACE_ROLES = ("primary", "alternative")
MIN_PRECISE_PLACE_RANK = 26
GEOD = Geod(ellps="WGS84")

ENTITY_COLUMNS = [
    "response_id",
    "entity_index",
    "provider",
    "model",
    "study",
    "audit",
    "location",
    "query_city",
    "query_state_abbr",
    "geoid",
    "role",
    "list_position",
    "name_verbatim",
    "entity_type",
    "presented_as_abortion_provider",
]


def read_cache(path):
    """
    Read a geocoding cache, keeping the latest record per address.

    Parameters
    ----------
    path : pathlib.Path
        A JSONL cache.

    Returns
    -------
    pandas.DataFrame
        One row per address_key (empty if the cache does not exist).
    """
    if not path.exists():
        return pd.DataFrame(columns=["address_key", "match", "lat", "lon"])
    with open(path, encoding="utf-8") as f:
        records = pd.DataFrame([json.loads(line) for line in f if line.strip()])
    return records.drop_duplicates("address_key", keep="last")


def choose_locations(places):
    """
    Attach the location used for each place: Census first, then Nominatim.

    Parameters
    ----------
    places : pandas.DataFrame
        In-person entities, with address_key (null if no street).

    Returns
    -------
    pandas.DataFrame
        places with geocoder, geocode_match_type, geocode_precise, lat, lon.
    """
    census = read_cache(CENSUS_CACHE)
    census = census[census["match"]].set_index("address_key")
    nominatim = read_cache(NOMINATIM_CACHE)
    nominatim = nominatim[nominatim["match"]].set_index("address_key")

    def locate(key):
        if key in census.index:
            row = census.loc[key]
            return "census", row["matchtype"], True, row["lat"], row["lon"]
        if key in nominatim.index:
            row = nominatim.loc[key]
            rank = int(row["place_rank"])
            precise = rank >= MIN_PRECISE_PLACE_RANK
            return "nominatim", f"place_rank {rank}", precise, row["lat"], row["lon"]
        return None, None, False, np.nan, np.nan

    located = pd.DataFrame(
        [locate(key) for key in places["address_key"]],
        columns=["geocoder", "geocode_match_type", "geocode_precise", "lat", "lon"],
        index=places.index,
    )
    places = places.join(located)
    # Location measures are computed only for precise locations.
    places.loc[~places["geocode_precise"], ["lat", "lon"]] = np.nan
    return places


def add_measures(places):
    """
    Add the state, city-limits, distance, and neighbor measures.

    Parameters
    ----------
    places : pandas.DataFrame
        From ``choose_locations``.

    Returns
    -------
    pandas.DataFrame
        places with the measure columns described in the header.
    """
    cities = gpd.read_parquet(CITY_BOUNDARIES_PATH).set_index("geoid")
    states = gpd.read_parquet(latest_download(BOUNDARIES_DIR, STATES_STEM, ".parquet"))
    neighbors = pd.read_csv(NEIGHBORS_PATH)
    border = {
        (a, b): kind
        for a, b, kind in neighbors[
            ["state_abbr", "neighbor_abbr", "border_type"]
        ].itertuples(index=False)
    }

    has_point = places["lat"].notna()
    points = gpd.GeoDataFrame(
        places.loc[has_point, []],
        geometry=gpd.points_from_xy(
            places.loc[has_point, "lon"], places.loc[has_point, "lat"]
        ),
        crs=cities.crs,
    )

    in_state = gpd.sjoin(
        points, states[["STUSPS", "geometry"]].to_crs(cities.crs), predicate="within"
    )
    places["place_state_abbr"] = in_state["STUSPS"].reindex(places.index)

    city_shapes = cities.geometry.reindex(places.loc[has_point, "geoid"]).values
    places.loc[has_point, "in_query_city"] = (
        gpd.GeoSeries(city_shapes, crs=cities.crs)
        .covers(points.geometry.reset_index(drop=True))
        .values
    )

    origin = cities.loc[
        places.loc[has_point, "geoid"], ["intpt_lon", "intpt_lat"]
    ].to_numpy()
    _, _, meters = GEOD.inv(
        origin[:, 0],
        origin[:, 1],
        places.loc[has_point, "lon"],
        places.loc[has_point, "lat"],
    )
    places.loc[has_point, "distance_km"] = np.asarray(meters) / 1000
    places["distance_mi"] = km_to_miles(places["distance_km"])

    located = places["place_state_abbr"].notna()
    places["crosses_state"] = (
        places["place_state_abbr"] != places["query_state_abbr"]
    ).where(located)
    places["neighbor_border_type"] = [
        border.get((q, p))
        for q, p in zip(places["query_state_abbr"], places["place_state_abbr"])
    ]
    places["is_neighbor_state"] = places["neighbor_border_type"].notna().where(located)
    stated = places["state_abbr"].notna() & located
    places["stated_state_matches"] = (
        places["state_abbr"] == places["place_state_abbr"]
    ).where(stated)
    for col in [
        "in_query_city",
        "crosses_state",
        "is_neighbor_state",
        "stated_state_matches",
    ]:
        places[col] = places[col].astype("boolean")
    return places


def add_policy(places):
    """
    Add the Guttmacher policy category of the user's state.

    Parameters
    ----------
    places : pandas.DataFrame
        Places with query_state_abbr.

    Returns
    -------
    pandas.DataFrame
        places with query_state_total_ban, query_state_environment_type, and
        query_state_category_rank.
    """
    cities = pd.read_csv(CITIES_PATH, dtype={"geoid": str})
    policy = pd.read_csv(GUTTMACHER_PATH)
    # Guttmacher slugs are lowercase hyphenated state names ("new-york").
    states = cities[["state", "state_abbr"]].drop_duplicates()
    states["state_slug"] = states["state"].str.lower().str.replace(" ", "-")
    lookup = states.merge(policy, on="state_slug", how="left", validate="one_to_one")
    if lookup["environment_type"].isna().any():
        sys.exit("A sampled state has no Guttmacher category")
    lookup = lookup.set_index("state_abbr")
    places["query_state_total_ban"] = (
        places["query_state_abbr"].map(lookup["total_ban"]).astype(bool)
    )
    places["query_state_environment_type"] = places["query_state_abbr"].map(
        lookup["environment_type"]
    )
    places["query_state_category_rank"] = places["query_state_abbr"].map(
        lookup["category_rank"]
    )
    return places


def write_report(table):
    """
    Write the summary report.

    Parameters
    ----------
    table : pandas.DataFrame
        The output table.
    """
    precise = table[table["geocode_precise"]]
    summary_columns = ["in_query_city", "crosses_state", "is_neighbor_state"]

    def summarize(df, by):
        grouped = df.groupby(by)
        return pd.DataFrame(
            {
                "n_places": grouped.size(),
                **{f"share_{c}": grouped[c].mean().round(3) for c in summary_columns},
                "median_km": grouped["distance_km"].median().round(1),
                "median_mi": grouped["distance_mi"].median().round(1),
            }
        )

    crossing = precise[precise["crosses_state"].fillna(False)]
    lines = [
        "compute_place_geography.py report",
        "",
        f"In-person places: {len(table)}",
        "Geocoder used:",
        table["geocoder"].fillna("none").value_counts().to_string(),
        "Share precise by provider:",
        table.groupby("provider")["geocode_precise"].mean().round(3).to_string(),
        "",
        "Primary places, precise locations, by provider:",
        summarize(precise[precise["role"] == "primary"], "provider").to_string(),
        "",
        "Primary places, precise locations, by whether the user's state has a total ban:",
        summarize(
            precise[precise["role"] == "primary"], ["query_state_total_ban", "provider"]
        ).to_string(),
        "",
        "Primary places, precise locations, by user's state policy category:",
        summarize(
            precise[precise["role"] == "primary"],
            ["query_state_category_rank", "query_state_environment_type"],
        ).to_string(),
        "",
        "Places in another state: share in a neighboring state, by provider:",
        crossing.groupby("provider")["is_neighbor_state"].mean().round(3).to_string(),
        "",
        "Stated state matches the geocoded state (share):",
        precise.groupby("provider")["stated_state_matches"].mean().round(3).to_string(),
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Build and write the place geography table.
    """
    entities = pd.read_parquet(ENTITIES_PATH)
    places = entities[entities["role"].isin(PLACE_ROLES)].copy()
    places["address_key"] = places.apply(address_key, axis=1).where(
        places["street"].notna()
    )

    places = add_measures(choose_locations(places))
    places = add_policy(places)

    measure_columns = [
        "query_state_total_ban",
        "query_state_environment_type",
        "query_state_category_rank",
        "address_key",
        "geocoder",
        "geocode_match_type",
        "geocode_precise",
        "lat",
        "lon",
        "place_state_abbr",
        "in_query_city",
        "distance_km",
        "distance_mi",
        "crosses_state",
        "is_neighbor_state",
        "neighbor_border_type",
        "stated_state_matches",
    ]
    table = places[ENTITY_COLUMNS + measure_columns].reset_index(drop=True)
    assert not table.duplicated(["response_id", "entity_index"]).any()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(OUTPUT_PATH, index=False)
    write_report(table)
    print(f"Wrote {len(table)} places to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
