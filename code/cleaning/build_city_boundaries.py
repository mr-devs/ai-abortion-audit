"""
Purpose:
    Attach each sampled city's legal boundary (city limits) and Census
    internal point to the pilot-4cities city sample.

Notes:
    - Cities are joined to the Census 2025 TIGER/Line places file on the
      7-character place GEOID, an exact match; no city name is geocoded.
      Geocoding a name such as "Portland" could return the wrong city.
    - The city's location for distances is the Census internal point
      (INTPTLAT, INTPTLON), the point the Census Gazetteer files list for each
      place. It is always inside the city limits; the geometric centroid is
      not (e.g., for a crescent-shaped city).
    - Both the places file and the population estimates use legal
      boundaries as of January 1, 2025.
    - Checks: every sampled city must match exactly one place, and the
      place's legal name (NAMELSAD) must equal the city's official name
      (city_official) in the Census population file.
    - Hawaii's one city, Urban Honolulu, is a Census designated place (CDP),
      not an incorporated place; its boundary is the CDP's statistical
      boundary.

Input:
    - data/processed/census/selected_cities_4_per_state.csv, written by
      code/cleaning/select_state_cities.py.
    - data/raw/census/boundaries/tl_2025_place_<timestamp>.parquet (newest),
      written by code/data_collection/download_census_boundaries.py.

    Usage (from anywhere):
        uv run python code/cleaning/build_city_boundaries.py

Output:
    - data/processed/census/selected_cities_boundaries.parquet: GeoParquet,
      one row per sampled city, in the order of the cities file, in NAD83
      (EPSG:4269), with columns:
        - geoid (str): Census place GEOID (7 characters).
        - state (str), state_abbr (str), city_official (str),
          city_clean (str), pop_est_2025 (int): as in the cities file.
        - lsad_name (str): the place's legal name in the boundary file
          (NAMELSAD), equal to city_official.
        - intpt_lat, intpt_lon (float): the Census internal point, decimal
          degrees (NAD83).
        - aland_m2, awater_m2 (int): land and water area, square meters.
        - geometry: the city limits (MultiPolygon or Polygon).
    - results/reports/build_city_boundaries_report.txt: row counts and the
      land-area range.

Author: Matthew DeVerna
"""

import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

from toolkit.utils import latest_download

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
CITIES_PATH = Path("../../data/processed/census/selected_cities_4_per_state.csv")
BOUNDARIES_DIR = Path("../../data/raw/census/boundaries")
PLACES_STEM = "tl_2025_place"
OUTPUT_PATH = Path("../../data/processed/census/selected_cities_boundaries.parquet")
REPORT_PATH = Path("../../results/reports/build_city_boundaries_report.txt")

# Boundary-file column -> output column
PLACE_COLUMNS = {
    "GEOID": "geoid",
    "NAMELSAD": "lsad_name",
    "INTPTLAT": "intpt_lat",
    "INTPTLON": "intpt_lon",
    "ALAND": "aland_m2",
    "AWATER": "awater_m2",
    "geometry": "geometry",
}


def build_table(cities, places):
    """
    Join the city sample to its place boundaries.

    Parameters
    ----------
    cities : pandas.DataFrame
        The city sample, with geoid read as text.
    places : geopandas.GeoDataFrame
        The TIGER/Line places file.

    Returns
    -------
    geopandas.GeoDataFrame
        One row per sampled city, with its boundary and internal point.
    """
    places = places[list(PLACE_COLUMNS)].rename(columns=PLACE_COLUMNS)
    # The internal point is stored as signed text (e.g. "+32.3509575").
    for col in ["intpt_lat", "intpt_lon"]:
        places[col] = places[col].astype(float)
    merged = cities.merge(places, on="geoid", how="left", validate="one_to_one")
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=places.crs)


def validate(table, cities):
    """
    Assert every city matched one place with the same legal name.

    Parameters
    ----------
    table : geopandas.GeoDataFrame
        The table from ``build_table``.
    cities : pandas.DataFrame
        The city sample.

    Raises
    ------
    AssertionError
        If any check fails.
    """
    assert len(table) == len(cities), "Row count changed in the join"
    unmatched = table[table["geometry"].isna()]
    assert unmatched.empty, f"Cities with no boundary: {unmatched['geoid'].tolist()}"
    mismatched = table[table["lsad_name"] != table["city_official"]]
    assert mismatched.empty, (
        "Boundary names differ from the population file:\n"
        + mismatched[["geoid", "city_official", "lsad_name"]].to_string()
    )
    # The internal point is defined to fall inside the boundary.
    points = gpd.points_from_xy(table["intpt_lon"], table["intpt_lat"], crs=table.crs)
    inside = table.geometry.covers(gpd.GeoSeries(points, index=table.index))
    assert inside.all(), (
        f"Internal point outside: {table.loc[~inside, 'geoid'].tolist()}"
    )


def write_report(table, places_path):
    """
    Write a short text report.

    Parameters
    ----------
    table : geopandas.GeoDataFrame
        The validated table.
    places_path : pathlib.Path
        The boundary file used.
    """
    area_km2 = table["aland_m2"] / 1e6
    smallest = table.loc[area_km2.idxmin()]
    largest = table.loc[area_km2.idxmax()]
    lines = [
        "build_city_boundaries.py report",
        "",
        f"Boundary file: {places_path.name}",
        f"Cities: {len(table)} in {table['state_abbr'].nunique()} states",
        "",
        "Land area (km^2):",
        area_km2.describe().round(2).to_string(),
        f"Smallest: {smallest['city_clean']}, {smallest['state_abbr']} "
        f"({smallest['aland_m2'] / 1e6:.3f} km^2)",
        f"Largest: {largest['city_clean']}, {largest['state_abbr']} "
        f"({largest['aland_m2'] / 1e6:,.0f} km^2)",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Build, validate, and write the city boundaries table.
    """
    cities = pd.read_csv(CITIES_PATH, dtype={"geoid": str})
    places_path = latest_download(BOUNDARIES_DIR, PLACES_STEM, ".parquet")
    places = gpd.read_parquet(places_path)

    table = build_table(cities, places)
    validate(table, cities)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(OUTPUT_PATH, index=False)
    write_report(table, places_path)
    print(f"Wrote {len(table)} city boundaries to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
