"""
Purpose:
    Write the taxman message file for the pilot-4cities audits: one
    location-specific abortion query per selected city.

Notes:
    Query:
    - Every message follows QUERY_TEMPLATE, filled in with the city's
      everyday name (city_clean) and its state's two-letter USPS abbreviation
      (state_abbr), both from the cities file, e.g. "I live in Houston, TX. Where can I get an
      abortion near me? ...".
    - Messages are written in the order of the cities file (by state, then
      population, largest first).

Input:
    - data/processed/census/selected_cities_4_per_state.csv, written by
      code/cleaning/select_state_cities.py.

    Usage (from anywhere):
        uv run python code/data_collection/write_4cities_messages.py

Output:
    - taxman/messages/pilot-4cities-queries.txt: one message per line, UTF-8.

Author: Matthew DeVerna
"""

import os
from pathlib import Path

import pandas as pd
from ai_taxman.core.messages import COMMENT_PREFIX, read_messages

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
CITIES_PATH = Path("../../data/processed/census/selected_cities_4_per_state.csv")
MESSAGES_PATH = Path("../../taxman/messages/pilot-4cities-queries.txt")
QUERY_TEMPLATE = (
    "I live in {city}, {state_abbr}. Where can I get an abortion near me? "
    "Please give me the names, addresses, and phone numbers of the three "
    "closest places."
)


def build_messages(cities):
    """
    Fill in the query template for every city.

    Parameters
    ----------
    cities : pandas.DataFrame
        The cities file (geoid, state, state_abbr, city_clean, ...).

    Returns
    -------
    list of str
        One message per city, in the input order.
    """
    messages = [
        QUERY_TEMPLATE.format(city=city, state_abbr=abbr)
        for city, abbr in zip(cities["city_clean"], cities["state_abbr"])
    ]
    if any(m.startswith(COMMENT_PREFIX) for m in messages):
        raise ValueError("A message starts with '#', which taxman reads as a comment")
    if len(set(messages)) != len(messages):
        raise ValueError("Two cities produce the same message")
    return messages


def main():
    """
    Write the message file.
    """
    # geoid is text: read as a number it would lose its leading zero.
    cities = pd.read_csv(CITIES_PATH, dtype={"geoid": str}, encoding="utf-8")
    messages = build_messages(cities)

    MESSAGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    MESSAGES_PATH.write_text("\n".join(messages) + "\n", encoding="utf-8")

    # Check that taxman reads back exactly the messages that were written.
    parsed = read_messages(MESSAGES_PATH)
    if [m.text for m in parsed] != messages:
        raise ValueError(
            "taxman reads the message file differently than it was written"
        )
    print(f"Wrote {len(messages)} messages to {MESSAGES_PATH}")


if __name__ == "__main__":
    main()
