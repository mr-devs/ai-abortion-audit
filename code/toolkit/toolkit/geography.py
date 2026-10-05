"""
US state names and their two-letter USPS postal abbreviations.
"""

#: Full state name (as spelled in the Census population files' STNAME column)
#: to its USPS postal abbreviation. Covers the 50 states and DC.
#: Guttmacher spells DC as "DC" rather than "District of Columbia"; map that
#: before looking it up here.
STATE_ABBREVIATIONS = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "District of Columbia": "DC",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}


def state_abbreviation(state):
    """
    Return the USPS abbreviation for a full state name.

    Parameters
    ----------
    state : str
        Full state name, e.g. "Texas".

    Returns
    -------
    str
        Two-letter abbreviation, e.g. "TX".

    Raises
    ------
    KeyError
        If the name is not one of the 50 states or "District of Columbia",
        so a misspelled name fails loudly instead of producing a bad query.
    """
    try:
        return STATE_ABBREVIATIONS[state]
    except KeyError:
        raise KeyError(
            f"Unknown state name {state!r}; not in STATE_ABBREVIATIONS"
        ) from None
