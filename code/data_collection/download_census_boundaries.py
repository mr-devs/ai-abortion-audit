"""
Purpose:
    Download the Census Bureau's 2025 boundary files for incorporated places
    (city limits) and states, through the pygris package.

Notes:
    Why these files:
    - The places file gives each city's legal limits (its polygon) and the
      Census "internal point" (INTPTLAT, INTPTLON), the same point the Census
      Gazetteer files list for each place. Analysis uses the polygon to ask
      whether a recommended location is inside the queried city and the
      internal point as the city's location for distances.
    - The internal point is not always the geometric centroid: the Census
      moves it inside the polygon when the centroid falls outside (e.g., a
      crescent-shaped city), so it is always inside the city.
    - Two state files are kept. The full TIGER/Line file is the most precise
      outline and is used to say which state a point is in. The 1:500k
      cartographic boundary file is clipped to the shoreline, so states touch
      only where they share a land border; it is used to find neighboring
      states (the TIGER/Line file would also join states across lakes, such
      as Michigan and Illinois in Lake Michigan).

    Vintage:
    - TIGER_YEAR is 2025. The 2025 TIGER/Line boundaries are legal
      boundaries as of January 1, 2025, the same date the 2025 population
      estimates (sub-est2025.csv, which the city sample comes from) use.

    Source:
    - pygris (https://github.com/walkerke/pygris) reads the zipped shapefiles
      straight from the Census website:
        - places: https://www2.census.gov/geo/tiger/TIGER2025/PLACE/tl_2025_<SS>_place.zip
          (one per state, by two-digit FIPS code)
        - states: https://www2.census.gov/geo/tiger/TIGER2025/STATE/tl_2025_us_state.zip
        - states, 1:500k: https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_state_500k.zip
    - Places are downloaded for the 50 states and DC, one file each, and
      saved together.

    No re-downloads:
    - Each file's name gets the date and time of the download, for posterity.
    - Before downloading, the script looks for an earlier download of the
      same file (with any timestamp). If one exists, it logs a warning and
      skips that file; delete the existing file to download it again.

Input:
    - None. The Census year and file types are constants below.

    Usage (from anywhere):
        uv run python code/data_collection/download_census_boundaries.py

Output:
    - data/raw/census/boundaries/tl_2025_place_<YYYY-MM-DD_HHMMSS>.parquet:
      GeoParquet, one row per place (incorporated places and Census
      designated places) in the 50 states and DC, in NAD83 (EPSG:4269).
      Columns are as published; those used in this project:
        - GEOID (str): STATE + PLACE FIPS codes, 7 characters; joins to
          `geoid` in selected_cities_4_per_state.csv.
        - NAME, NAMELSAD (str): place name, without and with its legal
          descriptor (e.g. "Houston", "Houston city").
        - INTPTLAT, INTPTLON (str): the internal point, signed decimal
          degrees (e.g. "+32.3509575").
        - geometry: the place's legal boundary (city limits).
    - data/raw/census/boundaries/tl_2025_us_state_<YYYY-MM-DD_HHMMSS>.parquet:
      GeoParquet, one row per state and territory (TIGER/Line, full
      resolution), NAD83. Columns used: GEOID (state FIPS), STUSPS (USPS
      abbreviation), NAME, geometry.
    - data/raw/census/boundaries/cb_2025_us_state_500k_<YYYY-MM-DD_HHMMSS>.parquet:
      GeoParquet, the same states as a 1:500k cartographic boundary file,
      clipped to the shoreline, NAD83.
    - data/logs/download_census_boundaries/<YYYY-MM-DD>.log: run log (appended).

Author: Matthew DeVerna
"""

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import pygris
import us

from toolkit.utils import find_existing_downloads, setup_logging, timestamped_path

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
TIGER_YEAR = 2025
OUTPUT_DIR = Path("../../data/raw/census/boundaries")
LOG_DIR = Path("../../data/logs/download_census_boundaries")

# The 50 states and DC, by two-digit FIPS code.
STATE_FIPS = sorted(state.fips for state in us.states.STATES + [us.states.DC])


def download_places(logger):
    """
    Download every state's TIGER/Line places file and stack them.

    Parameters
    ----------
    logger : logging.Logger
        Logger for progress messages.

    Returns
    -------
    geopandas.GeoDataFrame
        One row per place in the 50 states and DC.
    """
    frames = []
    for fips in STATE_FIPS:
        places = pygris.places(state=fips, year=TIGER_YEAR)
        logger.info(f"Downloaded places for state {fips}: {len(places):,} rows")
        frames.append(places)
    return pd.concat(frames, ignore_index=True)


def download_states(cb):
    """
    Download the national states file.

    Parameters
    ----------
    cb : bool
        True for the 1:500k cartographic boundary file (clipped to the
        shoreline); False for the full-resolution TIGER/Line file.

    Returns
    -------
    geopandas.GeoDataFrame
        One row per state and territory.
    """
    return pygris.states(cb=cb, resolution="500k", year=TIGER_YEAR)


# One entry per file: the filename stem the timestamp is added to (the
# Census's own filename, without the state code for places) and how to get it.
DOWNLOADS = [
    {"stem": f"tl_{TIGER_YEAR}_place", "download": download_places},
    {
        "stem": f"tl_{TIGER_YEAR}_us_state",
        "download": lambda logger: download_states(cb=False),
    },
    {
        "stem": f"cb_{TIGER_YEAR}_us_state_500k",
        "download": lambda logger: download_states(cb=True),
    },
]


def main():
    """
    Download each file unless an earlier download of it already exists.
    """
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    logger = setup_logging(
        log_level="INFO", log_file=str(log_file), console_output=True, append_mode=True
    )
    logger.info(f"Downloading Census {TIGER_YEAR} place and state boundaries")

    for item in DOWNLOADS:
        existing = find_existing_downloads(OUTPUT_DIR, item["stem"], ".parquet")
        if existing:
            logger.warning(
                f"{item['stem']} already exists: "
                f"{', '.join(str(p) for p in existing)}. "
                "Delete the existing file if you want to re-download it. Skipping."
            )
            continue
        gdf = item["download"](logger)
        out_path = timestamped_path(OUTPUT_DIR, item["stem"], ".parquet")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(out_path, index=False)
        logger.info(f"Saved {out_path} ({len(gdf):,} rows, CRS {gdf.crs})")

    logger.info("Done")


if __name__ == "__main__":
    main()
