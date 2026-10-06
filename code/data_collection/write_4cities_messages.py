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

    Message ids:
    - taxman gives each message an id from its position in the file (m0000,
      m0001, ...); the file carries no other identifier. To link responses
      back to cities, the script also writes a crosswalk. Its message_id
      values come from re-reading the written file with taxman's own parser
      (ai_taxman.core.messages.read_messages), so they match the ids in the
      collected data.
    - taxman treats lines starting with "#" as comments, so the script checks
      that no message does.

Input:
    - data/processed/census/selected_cities_4_per_state.csv, written by
      code/cleaning/select_state_cities.py.

    Usage (from anywhere):
        uv run python code/data_collection/write_4cities_messages.py

Output:
    - taxman/messages/pilot-4cities-queries.txt: one message per line, UTF-8.
    - data/processed/pilot_4cities/pilot_4cities_messages.csv: one row per message, with
      columns:
        - message_id (str): taxman message id (e.g. "m0000"); join key to the
          collected and cleaned audit data.
        - geoid (str): Census place GEOID from the cities file (7 characters,
          e.g. "4835000"); read it as text.
        - state (str): state name.
        - state_abbr (str): two-letter USPS state abbreviation.
        - city_clean (str): city name used in the message.
        - message (str): the message text.

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
CROSSWALK_PATH = Path("../../data/processed/pilot_4cities/pilot_4cities_messages.csv")
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
    pandas.DataFrame
        One row per city, in the input order, with columns geoid, state,
        state_abbr, city_clean, and message.
    """
    messages = cities[["geoid", "state", "state_abbr", "city_clean"]].copy()
    messages["message"] = [
        QUERY_TEMPLATE.format(city=city, state_abbr=abbr)
        for city, abbr in zip(messages["city_clean"], messages["state_abbr"])
    ]
    if messages["message"].str.startswith(COMMENT_PREFIX).any():
        raise ValueError("A message starts with '#', which taxman reads as a comment")
    if messages["message"].duplicated().any():
        raise ValueError("Two cities produce the same message")
    return messages


def main():
    """
    Write the message file and the message-to-city crosswalk.
    """
    # geoid is text: read as a number it would lose its leading zero.
    cities = pd.read_csv(CITIES_PATH, dtype={"geoid": str}, encoding="utf-8")
    messages = build_messages(cities)

    MESSAGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    MESSAGES_PATH.write_text("\n".join(messages["message"]) + "\n", encoding="utf-8")

    # Take the ids from taxman's parser so they match the collected data.
    parsed = read_messages(MESSAGES_PATH)
    if [m.text for m in parsed] != messages["message"].tolist():
        raise ValueError(
            "taxman reads the message file differently than it was written"
        )
    messages.insert(0, "message_id", [m.id for m in parsed])

    CROSSWALK_PATH.parent.mkdir(parents=True, exist_ok=True)
    messages.to_csv(CROSSWALK_PATH, index=False, encoding="utf-8")
    print(f"Wrote {len(messages)} messages to {MESSAGES_PATH}")
    print(f"Wrote the message crosswalk to {CROSSWALK_PATH}")


if __name__ == "__main__":
    main()
