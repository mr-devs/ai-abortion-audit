"""
Purpose:
    Build the lookup of neighboring states: for each state, every state it
    physically touches.

Notes:
    - Neighbors come from the Census 2025 1:500k cartographic boundary file
      of states, which is clipped to the shoreline. Two states are neighbors
      when their outlines intersect, so only land borders count: Michigan and
      Illinois meet only in Lake Michigan and are not neighbors.
    - The 50 states and DC are included; territories are not. Alaska and
      Hawaii have no neighbors and appear in the report, not in the table.
    - border_type records how two states touch:
        - "land": they share a border of some length.
        - "point": they meet at a single point. These are the Four Corners
          pairs, Arizona-Colorado and New Mexico-Utah. Keep or drop them
          depending on the analysis; a person cannot cross between them
          without passing through a third state.
    - shared_border_km is measured in the Conus Albers equal-area projection
      (EPSG:5070), which is accurate enough to compare borders; it is 0 for
      point contacts. Every pair is listed in both directions.
    - Checks: the lookup is symmetric, and the number of pairs is the known
      count for the 48 contiguous states and DC (EXPECTED_PAIRS).

Input:
    - data/raw/census/boundaries/cb_2025_us_state_500k_<timestamp>.parquet
      (newest), written by code/data_collection/download_census_boundaries.py.

    Usage (from anywhere):
        uv run python code/cleaning/build_state_neighbors.py

Output:
    - data/processed/census/state_neighbors.csv: one row per (state,
      neighbor) pair, sorted by state_abbr then neighbor_abbr, with columns:
        - state_abbr (str): two-letter USPS abbreviation (e.g. "TX"; "DC").
        - neighbor_abbr (str): abbreviation of a state it touches.
        - border_type (str): "land" or "point" (see Notes).
        - shared_border_km (float): length of the shared border, km.
    - results/reports/build_state_neighbors_report.txt: pair counts, the
      number of neighbors per state, and states with none.

Author: Matthew DeVerna
"""

import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
import us

from toolkit.utils import latest_download

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
BOUNDARIES_DIR = Path("../../data/raw/census/boundaries")
STATES_STEM = "cb_2025_us_state_500k"
OUTPUT_PATH = Path("../../data/processed/census/state_neighbors.csv")
REPORT_PATH = Path("../../results/reports/build_state_neighbors_report.txt")

EQUAL_AREA_CRS = "EPSG:5070"  # Conus Albers, meters
INCLUDED_STATES = {state.abbr for state in us.states.STATES + [us.states.DC]}
# 107 pairs among the 48 contiguous states (counting the two Four Corners
# point contacts) plus DC's two (Maryland and Virginia).
EXPECTED_PAIRS = 109


def build_table(states):
    """
    Find every pair of states whose outlines touch.

    Parameters
    ----------
    states : geopandas.GeoDataFrame
        The 1:500k state outlines.

    Returns
    -------
    pandas.DataFrame
        One row per (state, neighbor) pair, in both directions.
    """
    states = states[states["STUSPS"].isin(INCLUDED_STATES)].to_crs(EQUAL_AREA_CRS)
    outlines = states.set_index("STUSPS").geometry

    candidates = gpd.sjoin(
        states[["STUSPS", "geometry"]],
        states[["STUSPS", "geometry"]],
        predicate="intersects",
    )
    candidates = candidates[candidates["STUSPS_left"] != candidates["STUSPS_right"]]

    rows = []
    for state, neighbor in candidates[["STUSPS_left", "STUSPS_right"]].itertuples(
        index=False
    ):
        border_km = outlines[state].intersection(outlines[neighbor]).length / 1000
        rows.append(
            {
                "state_abbr": state,
                "neighbor_abbr": neighbor,
                "border_type": "land" if border_km > 0 else "point",
                "shared_border_km": round(border_km, 1),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["state_abbr", "neighbor_abbr"])
        .reset_index(drop=True)
    )


def validate(table):
    """
    Assert the lookup is symmetric and has the expected number of pairs.

    Parameters
    ----------
    table : pandas.DataFrame
        The table from ``build_table``.

    Raises
    ------
    AssertionError
        If any check fails.
    """
    forward = set(zip(table["state_abbr"], table["neighbor_abbr"]))
    backward = {(b, a) for a, b in forward}
    assert forward == backward, "The neighbor lookup is not symmetric"
    assert len(table) == len(forward), "Duplicate pairs"
    n_pairs = len(forward) // 2
    assert n_pairs == EXPECTED_PAIRS, f"{n_pairs} pairs, expected {EXPECTED_PAIRS}"


def write_report(table, states_path):
    """
    Write a short text report.

    Parameters
    ----------
    table : pandas.DataFrame
        The validated table.
    states_path : pathlib.Path
        The boundary file used.
    """
    counts = table.groupby("state_abbr").size().sort_values(ascending=False)
    lonely = sorted(INCLUDED_STATES - set(table["state_abbr"]))
    lines = [
        "build_state_neighbors.py report",
        "",
        f"Boundary file: {states_path.name}",
        f"Pairs (each listed in both directions): {len(table) // 2}",
        "Pairs by border type:",
        (table.groupby("border_type").size() // 2).to_string(),
        "",
        "Point contacts:",
        table.loc[
            table["border_type"] == "point", ["state_abbr", "neighbor_abbr"]
        ].to_string(index=False),
        "",
        f"States with no neighbor: {', '.join(lonely)}",
        "",
        "Neighbors per state:",
        counts.to_string(),
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """
    Build, validate, and write the state neighbor lookup.
    """
    states_path = latest_download(BOUNDARIES_DIR, STATES_STEM, ".parquet")
    states = gpd.read_parquet(states_path)

    table = build_table(states)
    validate(table)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT_PATH, index=False)
    write_report(table, states_path)
    print(f"Wrote {len(table) // 2} neighbor pairs to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
