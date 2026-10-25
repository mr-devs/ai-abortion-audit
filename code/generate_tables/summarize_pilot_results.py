"""
Purpose:
    Summarize the pilot-4cities results into small CSV tables, one per
    figure of the pilot results page: what the chatbots recommend, where
    those places are, what the responses say about state law, and which
    websites they show readers.

Notes:
    Assumptions:
    - The agents' coding (place extraction and domain codes) is taken as
      accurate. It has not yet been checked by human coders (GitHub issues
      #4 and #5).
    - Locations are where the addresses the responses wrote geocode to;
      location measures use precise locations only (geocode_precise).

    Groups:
    - state_group: "Total-ban state" when the user's state enforces a total
      abortion ban (Guttmacher's "Total abortion ban"), else "Other states".
    - city_size: each state contributes its two largest and two smallest
      incorporated places by 2025 population; "Two largest" or "Two
      smallest" (Hawaii's one city is "Two largest").
    - Places: "primary" entities, the places a response gives as its
      answer to the "three closest places" request.

    Crisis pregnancy center (CPC) citations:
    - A citation of a domain coded cpc_affiliated "yes" counts as a warning
      when the cited span of response text contains warning language
      (WARNING_PATTERN: "crisis pregnancy", "pregnancy center", "do not
      provide", "avoid", "anti-abortion", "fake clinic", and similar). This is
      a keyword rule, not a coded judgment.

    Distances:
    - Reported in miles: the straight-line (geodesic) distance_mi in
      place_geography.parquet.

    Sources shown to readers:
    - Occurrences come from link_events rows with shown_to_reader, counting
      a text link once where it duplicates a citation, joined to the domain
      codes.

Input:
    - data/processed/coding/place_responses.parquet, place_entities.parquet,
      place_geography.parquet, domain_codes.parquet.
    - data/processed/audits/link_events.parquet, text_citations.parquet,
      response_text.parquet, metadata.parquet.
    - data/processed/census/selected_cities_4_per_state.csv.
    - data/processed/guttmacher/guttmacher_state_categories.csv.

    Usage (from anywhere):
        uv run python code/generate_tables/summarize_pilot_results.py

Output:
    In results/tables/pilot_results/ (one CSV per table; shares are 0-1):
    - approach_counts.csv: step (int), label, n. The size of each stage of
      the pipeline.
    - answer_overview.csv: one row per provider: n_responses,
      share_places_provided, mean_primary, mean_alternative, mean_resource,
      mean_entities, mean_domains_shown, n_cpc_named (entities coded as crisis
      pregnancy centers), n_cpc_presented_as_provider (of those, presented as
      providing abortions).
    - primary_types.csv: provider, entity_type, n, share (of the provider's
      primary places).
    - geo_by_ban.csv: provider, state_group, n_places, share_in_city,
      share_other_state, share_neighbor_of_other_state (among places in
      another state), median_mi, q25_mi, q75_mi.
    - distance_places.csv: one row per precisely located primary place:
      provider, state_group, city_size, distance_mi.
    - geo_by_category.csv: category_rank, environment_type, provider,
      n_places, share_other_state, median_mi.
    - geo_by_size.csv: provider, city_size, n_places, share_in_city,
      median_mi.
    - law_claims.csv: provider, state_group, claim, n, share (of the
      group's responses).
    - domain_categories.csv: provider, category, n_shown, share (of the
      provider's occurrences).
    - cpc_citations.csv: provider, context ("Warning about CPCs" or "Other
      text"), n_citations, n_responses.

Author: Matthew DeVerna
"""

import os
import re
from pathlib import Path

import pandas as pd

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
CODING_DIR = Path("../../data/processed/coding")
AUDITS_DIR = Path("../../data/processed/audits")
CITIES_PATH = Path("../../data/processed/census/selected_cities_4_per_state.csv")
GUTTMACHER_PATH = Path(
    "../../data/processed/guttmacher/guttmacher_state_categories.csv"
)
OUTPUT_DIR = Path("../../results/tables/pilot_results")

STUDY = "pilot-4cities"
PROVIDER_NAMES = {"anthropic": "Claude", "gemini": "Gemini", "openai": "ChatGPT"}
BAN_GROUP = {True: "Total-ban state", False: "Other states"}
N_LARGEST = 2  # per state, the rest of the sample are the smallest
WARNING_PATTERN = re.compile(
    r"crisis pregnancy|pregnancy (?:resource|center)|do(?:es)? not (?:provide|perform|offer)"
    r"|don.t (?:provide|perform|offer)|anti-abortion|fake clinic|avoid|beware",
    re.IGNORECASE,
)


def city_sizes():
    """
    Label each sampled city as one of its state's two largest or two smallest.

    Returns
    -------
    pandas.DataFrame
        query_city, query_state_abbr, city_size.
    """
    cities = pd.read_csv(CITIES_PATH, dtype={"geoid": str})
    rank = cities.groupby("state_abbr")["pop_est_2025"].rank(
        ascending=False, method="first"
    )
    cities["city_size"] = rank.le(N_LARGEST).map(
        {True: "Two largest", False: "Two smallest"}
    )
    return cities.rename(
        columns={"city_clean": "query_city", "state_abbr": "query_state_abbr"}
    )[["query_city", "query_state_abbr", "city_size"]]


def total_ban_states():
    """
    Return the set of USPS abbreviations of total-ban states.

    Returns
    -------
    set of str
        The abbreviations.
    """
    cities = pd.read_csv(CITIES_PATH, dtype={"geoid": str})
    policy = pd.read_csv(GUTTMACHER_PATH)
    states = cities[["state", "state_abbr"]].drop_duplicates()
    states["state_slug"] = states["state"].str.lower().str.replace(" ", "-")
    merged = states.merge(policy, on="state_slug", validate="one_to_one")
    return set(merged.loc[merged["total_ban"], "state_abbr"])


def share_table(df, by, col):
    """
    Count values of a column within groups and give each its share.

    Parameters
    ----------
    df : pandas.DataFrame
        The rows.
    by : list of str
        Grouping columns.
    col : str
        The column to count.

    Returns
    -------
    pandas.DataFrame
        by + [col, "n", "share"].
    """
    counts = df.groupby(by + [col]).size().rename("n").reset_index()
    counts["share"] = counts["n"] / counts.groupby(by)["n"].transform("sum")
    return counts


def location_summary(places, by):
    """
    Summarize where precisely located places are, by group.

    Parameters
    ----------
    places : pandas.DataFrame
        Precisely located places.
    by : list of str
        Grouping columns.

    Returns
    -------
    pandas.DataFrame
        One row per group with n_places, share_in_city, share_other_state,
        share_neighbor_of_other_state, median_mi, q25_mi, q75_mi.
    """
    rows = []
    for key, g in places.groupby(by):
        other = g[g["crosses_state"].astype(bool)]
        rows.append(
            {
                **dict(zip(by, key if isinstance(key, tuple) else (key,))),
                "n_places": len(g),
                "share_in_city": g["in_query_city"].astype(bool).mean(),
                "share_other_state": g["crosses_state"].astype(bool).mean(),
                "share_neighbor_of_other_state": (
                    other["is_neighbor_state"].astype(bool).mean()
                    if len(other)
                    else None
                ),
                "median_mi": g["distance_mi"].median(),
                "q25_mi": g["distance_mi"].quantile(0.25),
                "q75_mi": g["distance_mi"].quantile(0.75),
            }
        )
    return pd.DataFrame(rows)


def main():
    """
    Build and write every table.
    """
    responses = pd.read_parquet(CODING_DIR / "place_responses.parquet")
    entities = pd.read_parquet(CODING_DIR / "place_entities.parquet")
    geography = pd.read_parquet(CODING_DIR / "place_geography.parquet")
    domains = pd.read_parquet(CODING_DIR / "domain_codes.parquet")
    events = pd.read_parquet(AUDITS_DIR / "link_events.parquet")
    citations = pd.read_parquet(AUDITS_DIR / "text_citations.parquet")
    text = pd.read_parquet(AUDITS_DIR / "response_text.parquet").set_index(
        "response_id"
    )["text"]
    metadata = pd.read_parquet(AUDITS_DIR / "metadata.parquet")

    study_ids = set(metadata.loc[metadata["study"] == STUDY, "response_id"])
    responses = responses[responses["study"] == STUDY]
    entities = entities[entities["study"] == STUDY]
    geography = geography[geography["study"] == STUDY]
    events = events[events["response_id"].isin(study_ids)]
    citations = citations[citations["response_id"].isin(study_ids)]

    ban = total_ban_states()
    sizes = city_sizes()
    responses = responses.merge(
        sizes, on=["query_city", "query_state_abbr"], validate="many_to_one"
    )
    responses["state_group"] = responses["query_state_abbr"].isin(ban).map(BAN_GROUP)
    geography = geography.merge(
        sizes, on=["query_city", "query_state_abbr"], validate="many_to_one"
    )
    geography["state_group"] = geography["query_state_total_ban"].map(BAN_GROUP)

    shown = events[events["shown_to_reader"] & events["duplicate_of_citation"].isna()]
    shown = shown.merge(
        domains[["domain", "category", "cpc_affiliated"]], on="domain", how="left"
    )
    domains_per_response = shown.groupby("response_id").size()

    tables = {}
    primary_places = geography[
        (geography["role"] == "primary") & geography["geocode_precise"]
    ]
    tables["approach_counts"] = pd.DataFrame(
        [
            (1, "Responses (3 chatbots x 197 cities)", len(responses)),
            (2, "Places and resources extracted", len(entities)),
            (3, "In-person places (primary or alternative)", len(geography)),
            (
                4,
                "Located precisely from their written address",
                int(geography["geocode_precise"].sum()),
            ),
            (5, "Main recommendations located precisely", len(primary_places)),
            (6, "Distinct websites shown to readers", shown["domain"].nunique()),
        ],
        columns=["step", "label", "n"],
    )

    overview = responses.groupby("provider").agg(
        n_responses=("response_id", "size"),
        share_places_provided=(
            "answer_status",
            lambda s: (s == "places_provided").mean(),
        ),
        mean_primary=("n_primary", "mean"),
        mean_alternative=("n_alternative", "mean"),
        mean_resource=("n_resource", "mean"),
        mean_entities=("n_entities", "mean"),
    )
    overview["mean_domains_shown"] = (
        responses.set_index("response_id")["provider"]
        .to_frame()
        .assign(n=domains_per_response)
        .fillna({"n": 0})
        .groupby("provider")["n"]
        .mean()
    )
    named_cpc = entities[entities["entity_type"] == "crisis_pregnancy_center"]
    overview["n_cpc_named"] = named_cpc.groupby("provider").size()
    overview["n_cpc_presented_as_provider"] = (
        named_cpc[named_cpc["presented_as_abortion_provider"] == "yes"].groupby("provider").size()
    )
    overview = overview.fillna({"n_cpc_named": 0, "n_cpc_presented_as_provider": 0})
    tables["answer_overview"] = overview.reset_index()

    primary = entities[entities["role"] == "primary"]
    tables["primary_types"] = share_table(primary, ["provider"], "entity_type")

    tables["geo_by_ban"] = location_summary(primary_places, ["provider", "state_group"])
    tables["distance_places"] = primary_places[
        ["provider", "state_group", "city_size", "distance_mi"]
    ].round({"distance_mi": 1})
    tables["geo_by_category"] = location_summary(
        primary_places,
        ["query_state_category_rank", "query_state_environment_type", "provider"],
    ).rename(
        columns={
            "query_state_category_rank": "category_rank",
            "query_state_environment_type": "environment_type",
        }
    )[
        [
            "category_rank",
            "environment_type",
            "provider",
            "n_places",
            "share_other_state",
            "median_mi",
        ]
    ]
    tables["geo_by_size"] = location_summary(primary_places, ["provider", "city_size"])[
        ["provider", "city_size", "n_places", "share_in_city", "median_mi"]
    ]

    claims = share_table(responses, ["provider", "state_group"], "state_law_claim")
    tables["law_claims"] = claims.rename(columns={"state_law_claim": "claim"})

    tables["domain_categories"] = share_table(
        shown.dropna(subset=["category"]), ["provider"], "category"
    ).rename(columns={"n": "n_shown"})

    cpc_domains = set(domains.loc[domains["cpc_affiliated"] == "yes", "domain"])
    cpc = citations[citations["domain"].isin(cpc_domains)].copy()
    cpc["span"] = [
        text[r][s:e]
        for r, s, e in zip(cpc["response_id"], cpc["start_index"], cpc["end_index"])
    ]
    cpc["context"] = (
        cpc["span"]
        .str.contains(WARNING_PATTERN)
        .map({True: "Warning about CPCs", False: "Other text"})
    )
    tables["cpc_citations"] = (
        cpc.groupby(["provider", "context"])
        .agg(
            n_citations=("response_id", "size"), n_responses=("response_id", "nunique")
        )
        .reset_index()
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        if "provider" in table.columns:
            table["provider"] = table["provider"].map(PROVIDER_NAMES)
        table.round(4).to_csv(OUTPUT_DIR / f"{name}.csv", index=False)
        print(f"{name}: {len(table)} rows")


if __name__ == "__main__":
    main()
