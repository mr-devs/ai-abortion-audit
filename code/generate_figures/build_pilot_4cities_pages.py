"""
Purpose:
    Build the three shareable pilot-4cities pages: the approach walkthrough,
    the response explorer, and the data brief. Each page is one
    self-contained HTML file (data, styles, and the D3, marked, and
    DOMPurify libraries all inlined) that opens with a double-click, with no
    server and no internet connection.

Notes:
    How the pages are made:
    - The page sources are templates in templates/pilot-4cities/. A
      template marks where shared files go with `<!-- @inline path -->`
      (a .css file becomes a <style> block, a .js file a <script> block;
      paths are relative to templates/) and where the data goes with
      `<!-- @data -->`, which becomes `<script>window.PAGE_DATA = {...}`.
    - The tables and aggregates the pages show are computed here, in Python.
      The pages filter and draw; the brief also takes simple summaries
      (medians, shares, cumulative distributions) of the points it plots,
      and the explorer filters and searches the responses in the browser.

    Crisis pregnancy center citations (brief, websites tab):
    - A citation of a CPC-affiliated domain counts as backing a warning when
      the cited span matches WARNING_PATTERN, imported from
      code/generate_tables/summarize_pilot_results.py so both use one rule.

    Groups and definitions (the same as summarize_pilot_results.py):
    - Total-ban state: Guttmacher's "Total abortion ban" label.
    - City size: each state contributes its two largest and two smallest
      incorporated places by 2025 population ("Two largest" / "Two
      smallest"; Hawaii's one city is "Two largest").
    - Main recommendations: "primary" entities, the places a response gives
      as its answer to the "three closest places" request. Distances use
      precisely located places only, in straight-line (geodesic) miles.
    - Websites shown to readers: link_events rows with shown_to_reader,
      counting a text link once where it duplicates a citation.
    - Accuracy: the definitions in code/analysis/compute_answer_accuracy.py.

    Citations in the explorer:
    - Anthropic and Gemini attach citations to spans of the text. The
      explorer shows them as numbered markers at the end of each span: the
      marker is inserted into the text here, at the span's end offset,
      as private-use characters (U+E000 n,n U+E001) that the page turns
      into links after rendering the markdown. OpenAI's citations are
      already markdown links in its text and are left as they are.

    Map:
    - State outlines are the Census 2025 1:500k cartographic boundaries,
      simplified (SIMPLIFY_DEGREES) and rounded to keep the files small;
      the 50 states and DC only.

Input:
    - data/processed/audits/metadata.parquet, response_text.parquet,
      text_citations.parquet, link_events.parquet, tool_calls.parquet,
      audit_runs.parquet.
    - data/processed/coding/place_responses.parquet, place_entities.parquet,
      place_geography.parquet, place_accuracy.parquet,
      reference_nearest.parquet, reference_facilities.parquet,
      response_accuracy.parquet, domain_codes.parquet.
    - data/processed/census/selected_cities_boundaries.parquet,
      state_neighbors.csv.
    - data/processed/guttmacher/guttmacher_state_categories.csv.
    - data/raw/census/boundaries/cb_2025_us_state_500k_<timestamp>.parquet.
    - code/generate_figures/templates/ (page templates and vendored
      libraries).

    Usage (from anywhere), after code/analysis/compute_answer_accuracy.py:
        uv run python code/generate_figures/build_pilot_4cities_pages.py

Output:
    In results/figures/interactive/pilot-4cities/:
    - pilot_4cities_approach.html: how the pilot was designed and run.
    - pilot_4cities_explorer.html: every response, with filters, search,
      and highlighting of the coded places, resources, and claims.
    - pilot_4cities_brief.html: one tab per research question, each with a
      figure and caption.
    Each file embeds `window.PAGE_DATA`; the script prints each file's size.

Author: Matthew DeVerna
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import MultiPolygon
from shapely.geometry.polygon import orient

from toolkit.utils import latest_download

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generate_tables"))
from summarize_pilot_results import WARNING_PATTERN  # noqa: E402

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
AUDITS_DIR = Path("../../data/processed/audits")
CODING_DIR = Path("../../data/processed/coding")
CITY_BOUNDARIES_PATH = Path(
    "../../data/processed/census/selected_cities_boundaries.parquet"
)
NEIGHBORS_PATH = Path("../../data/processed/census/state_neighbors.csv")
GUTTMACHER_PATH = Path(
    "../../data/processed/guttmacher/guttmacher_state_categories.csv"
)
BOUNDARIES_DIR = Path("../../data/raw/census/boundaries")
STATES_STEM = "cb_2025_us_state_500k"
TEMPLATES_DIR = Path("templates")
OUTPUT_DIR = Path("../../results/figures/interactive/pilot-4cities")

PAGES = {
    "approach": "pilot_4cities_approach.html",
    "explorer": "pilot_4cities_explorer.html",
    "brief": "pilot_4cities_brief.html",
}

STUDY = "pilot-4cities"
PROVIDERS = [
    {
        "id": "anthropic",
        "label": "Claude",
        "model": "claude-sonnet-5-5",
        "model_label": "Sonnet 5.5",
    },
    {
        "id": "gemini",
        "label": "Gemini",
        "model": "gemini-3.8-flash",
        "model_label": "3.8 Flash",
    },
    {
        "id": "openai",
        "label": "ChatGPT",
        "model": "gpt-6.1-sol",
        "model_label": "GPT-6.1 Sol",
    },
]
N_LARGEST = 2  # per state; the rest of the sample are the smallest
SIMPLIFY_DEGREES = 0.03
COORD_DIGITS = 2
MIN_PART_DEG2 = 0.002  # smallest island kept on the maps, in square degrees
EXAMPLE_RESPONSE = ("anthropic", "Oak Hill", "AL")  # the codebook's worked example
CITE_OPEN, CITE_CLOSE = chr(0xE000), chr(0xE001)  # private-use characters
GUIDANCE_FLAGS = [
    ("says_travel_needed", "Says travel to another state may be needed"),
    ("mentions_gestational_limits", "Mentions a gestational (weeks) limit"),
    ("mentions_financial_help", "Mentions help paying (funds, Medicaid)"),
    ("mentions_telehealth", "Mentions pills by mail or telehealth"),
    ("asks_follow_up", "Asks the user a follow-up question"),
    ("law_stated", "States the law in the user's state"),
]
# The audits were run from California; taxman's run ids use local time, and
# the project reports collection dates in it (2026-10-23, not 10-24 UTC).
LOCAL_TZ = "America/Los_Angeles"
TOLERANCES = [round(x, 2) for x in np.arange(1.0, 3.001, 0.05)]


def clean(value):
    """
    Turn a pandas or numpy value into a plain JSON value.

    Parameters
    ----------
    value : object
        Any cell value.

    Returns
    -------
    object
        None for missing values; Python int, float, bool, str, or list.
    """
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else round(float(value), 4)
    if isinstance(value, float):
        return round(value, 4)
    return value


def drop_missing(item):
    """
    Clean every value of a dict and leave out the missing ones.

    Parameters
    ----------
    item : dict
        Any values.

    Returns
    -------
    dict
        Plain JSON values, without keys whose value is missing.
    """
    item = {k: clean(v) for k, v in item.items()}
    return {k: v for k, v in item.items() if v is not None}


def records(df, drop_none=True):
    """
    Convert a DataFrame to a list of plain dicts.

    Parameters
    ----------
    df : pandas.DataFrame
        The rows.
    drop_none : bool
        Leave out keys whose value is missing, to keep the files small.

    Returns
    -------
    list of dict
        One dict per row.
    """
    out = []
    for row in df.to_dict(orient="records"):
        row = {k: clean(v) for k, v in row.items()}
        out.append({k: v for k, v in row.items() if not (drop_none and v is None)})
    return out


def load_inputs():
    """
    Read every input table, limited to the pilot-4cities study.

    Returns
    -------
    dict of pandas.DataFrame
        Keyed by short table name.
    """
    t = {}
    t["metadata"] = pd.read_parquet(AUDITS_DIR / "metadata.parquet")
    ids = set(t["metadata"].loc[t["metadata"]["study"] == STUDY, "response_id"])
    t["metadata"] = t["metadata"][t["metadata"]["response_id"].isin(ids)]
    for name in ["response_text", "text_citations", "link_events"]:
        df = pd.read_parquet(AUDITS_DIR / f"{name}.parquet")
        t[name] = df[df["response_id"].isin(ids)].copy()
    runs = pd.read_parquet(AUDITS_DIR / "audit_runs.parquet")
    t["audit_runs"] = runs[runs["study"] == STUDY]
    for name in [
        "place_responses",
        "place_entities",
        "place_geography",
        "place_accuracy",
        "response_accuracy",
    ]:
        df = pd.read_parquet(CODING_DIR / f"{name}.parquet")
        t[name] = df[df["response_id"].isin(ids)].copy()
    t["reference_nearest"] = pd.read_parquet(CODING_DIR / "reference_nearest.parquet")
    t["reference_facilities"] = pd.read_parquet(
        CODING_DIR / "reference_facilities.parquet"
    )
    t["domain_codes"] = pd.read_parquet(CODING_DIR / "domain_codes.parquet")
    t["neighbors"] = pd.read_csv(NEIGHBORS_PATH)
    t["cities"] = load_cities()
    return t


def load_cities():
    """
    Read the sampled cities with their size group and state policy.

    Returns
    -------
    pandas.DataFrame
        geoid, city, state, state_abbr, pop, size_group, lat, lon,
        category_rank, environment_type, total_ban, policy_as_of.
    """
    cities = pd.read_parquet(
        CITY_BOUNDARIES_PATH,
        columns=[
            "geoid",
            "state",
            "state_abbr",
            "city_clean",
            "city_official",
            "pop_est_2025",
            "intpt_lat",
            "intpt_lon",
        ],
    )
    rank = cities.groupby("state_abbr")["pop_est_2025"].rank(
        ascending=False, method="first"
    )
    cities["size_group"] = rank.le(N_LARGEST).map(
        {True: "Two largest", False: "Two smallest"}
    )
    policy = pd.read_csv(GUTTMACHER_PATH)
    cities["state_slug"] = cities["state"].str.lower().str.replace(" ", "-")
    cities = cities.merge(policy, on="state_slug", how="left", validate="many_to_one")
    assert cities["category_rank"].notna().all()
    return cities.rename(
        columns={
            "city_clean": "city",
            "pop_est_2025": "pop",
            "intpt_lat": "lat",
            "intpt_lon": "lon",
            "as_of": "policy_as_of",
        }
    )[
        [
            "geoid",
            "city",
            "city_official",
            "state",
            "state_abbr",
            "pop",
            "size_group",
            "lat",
            "lon",
            "category_rank",
            "environment_type",
            "total_ban",
            "policy_as_of",
        ]
    ]


def rewind_clockwise(geom):
    """
    Orient a (multi)polygon's outer rings clockwise, as d3-geo expects.

    Parameters
    ----------
    geom : shapely.geometry.base.BaseGeometry
        A Polygon or MultiPolygon.

    Returns
    -------
    shapely.geometry.base.BaseGeometry
        The same shape with clockwise outer rings.
    """
    parts = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    # Islands smaller than MIN_PART_DEG2 collapse at this precision.
    parts = [orient(g, sign=-1.0) for g in parts if g.area >= MIN_PART_DEG2]
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def state_shapes():
    """
    Simplified outlines of the 50 states and DC, as GeoJSON.

    Returns
    -------
    dict
        A GeoJSON FeatureCollection with properties abbr and name.
    """
    states = gpd.read_parquet(latest_download(BOUNDARIES_DIR, STATES_STEM, ".parquet"))
    states = states[states["STATEFP"].astype(int) <= 56].to_crs(4326)
    states["geometry"] = states.geometry.simplify(
        SIMPLIFY_DEGREES, preserve_topology=True
    )
    # d3-geo reads polygons on the sphere and needs clockwise outer rings;
    # shapely writes counterclockwise ones, which d3 would fill as
    # everything outside the state.
    # Snap to the output precision first so rounding cannot flip a ring.
    states["geometry"] = shapely.set_precision(
        states.geometry.values, 10**-COORD_DIGITS
    )
    states["geometry"] = states.geometry.apply(rewind_clockwise)
    geo = json.loads(states[["STUSPS", "NAME", "geometry"]].to_json())

    def round_coords(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], COORD_DIGITS), round(c[1], COORD_DIGITS)]
        return [round_coords(x) for x in c]

    for f in geo["features"]:
        f["geometry"]["coordinates"] = round_coords(f["geometry"]["coordinates"])
        f["properties"] = {
            "abbr": f["properties"]["STUSPS"],
            "name": f["properties"]["NAME"],
        }
        f.pop("id", None)
        f.pop("bbox", None)
    geo.pop("bbox", None)
    return geo


def shown_links(t):
    """
    Website appearances shown to readers, joined to the domain codes.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        From ``load_inputs``.

    Returns
    -------
    pandas.DataFrame
        One row per appearance: response_id, provider, channel, domain,
        category, stance_on_abortion_access, cpc_affiliated.
    """
    events = t["link_events"]
    shown = events[events["shown_to_reader"] & events["duplicate_of_citation"].isna()]
    return shown.merge(
        t["domain_codes"][
            ["domain", "category", "stance_on_abortion_access", "cpc_affiliated"]
        ],
        on="domain",
        how="left",
    )


def common_meta(t):
    """
    Facts every page shares: chatbots, counts, and the build date.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        From ``load_inputs``.

    Returns
    -------
    dict
        providers, generated_at, collected_on, counts.
    """
    geo = t["place_geography"]
    shown = shown_links(t)
    runs = t["audit_runs"]
    return {
        "providers": PROVIDERS,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "collected_on": runs["started_at"]
        .min()
        .tz_convert(LOCAL_TZ)
        .strftime("%Y-%m-%d"),
        "counts": {
            "states": int(t["cities"]["state_abbr"].nunique()),
            "cities": len(t["cities"]),
            "responses": len(t["place_responses"]),
            "entities": len(t["place_entities"]),
            "primary": int((t["place_entities"]["role"] == "primary").sum()),
            "alternative": int((t["place_entities"]["role"] == "alternative").sum()),
            "resource": int((t["place_entities"]["role"] == "resource").sum()),
            "in_person": len(geo),
            "precise": int(geo["geocode_precise"].sum()),
            "primary_precise": int(
                ((geo["role"] == "primary") & geo["geocode_precise"]).sum()
            ),
            "addresses": int(geo["address_key"].nunique()),
            "domains": int(shown["domain"].nunique()),
            "appearances": len(shown),
            "reference_facilities": len(t["reference_facilities"]),
            "total_ban_states": int(
                t["cities"].drop_duplicates("state_abbr")["total_ban"].sum()
            ),
        },
    }


def build_approach(t, meta, shapes):
    """
    Data for the approach walkthrough.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        From ``load_inputs``.
    meta : dict
        From ``common_meta``.
    shapes : dict
        From ``state_shapes``.

    Returns
    -------
    dict
        meta, shapes, cities, policy (one row per state), runs, example.
    """
    cities = t["cities"]
    policy = cities.drop_duplicates("state_abbr")[
        [
            "state",
            "state_abbr",
            "category_rank",
            "environment_type",
            "total_ban",
            "policy_as_of",
        ]
    ].sort_values(["category_rank", "state"])
    runs = t["audit_runs"].assign(
        started=lambda d: (
            d["started_at"].dt.tz_convert(LOCAL_TZ).dt.strftime("%Y-%m-%d %H:%M %Z")
        ),
        minutes=lambda d: (d["duration_seconds"] / 60).round(1),
    )[["provider", "model", "started", "minutes", "n_ok", "n_error", "taxman_versions"]]

    provider, city, state = EXAMPLE_RESPONSE
    pr = t["place_responses"]
    row = pr[
        (pr["provider"] == provider)
        & (pr["query_city"] == city)
        & (pr["query_state_abbr"] == state)
    ].iloc[0]
    text = t["response_text"].set_index("response_id").loc[row["response_id"], "text"]
    ents = t["place_entities"]
    ents = ents[ents["response_id"] == row["response_id"]].sort_values("entity_index")
    geo = t["place_accuracy"].set_index(["response_id", "entity_index"])
    example_entities = []
    for e in ents.itertuples():
        g = (
            geo.loc[(e.response_id, e.entity_index)]
            if (e.response_id, e.entity_index) in geo.index
            else None
        )
        example_entities.append(
            drop_missing(
                {
                    "role": e.role,
                    "type": e.entity_type,
                    "name": e.name_verbatim,
                    "address": e.address_verbatim,
                    "phones": clean(e.phones_verbatim),
                    "distance_mi": clean(g["distance_mi"]) if g is not None else None,
                    "place_state": clean(g["place_state_abbr"])
                    if g is not None
                    else None,
                }
            )
        )
    example = {
        "city": city,
        "state_abbr": state,
        "provider": provider,
        "message": t["metadata"]
        .set_index("response_id")
        .loc[row["response_id"], "message"],
        "text": text,
        "state_law_claim": row["state_law_claim"],
        "state_law_quote": row["state_law_quote_verbatim"],
        "says_travel_needed": bool(row["says_travel_needed"]),
        "entities": example_entities,
    }
    # What each chatbot did: searches that ran, words, and response time.
    calls = pd.read_parquet(AUDITS_DIR / "tool_calls.parquet")
    calls = calls[calls["response_id"].isin(t["metadata"]["response_id"])]
    searches = (
        calls[calls["tool_type"].str.contains("search") & calls["ran"]]
        .groupby("response_id")
        .size()
    )
    md = t["metadata"].merge(
        t["response_text"][["response_id", "text"]], on="response_id"
    )
    md["n_searches"] = md["response_id"].map(searches).fillna(0)
    md["n_words"] = md["text"].str.split().str.len()
    behavior = (
        md.groupby("provider")
        .agg(
            median_searches=("n_searches", "median"),
            median_words=("n_words", "median"),
            median_seconds=("latency_ms", lambda s: s.median() / 1000),
        )
        .reset_index()
    )
    return {
        "meta": meta,
        "shapes": shapes,
        "behavior": records(behavior),
        "policy_as_of": [
            t["cities"]["policy_as_of"].min(),
            t["cities"]["policy_as_of"].max(),
        ],
        "cities": records(cities.drop(columns=["policy_as_of"])),
        "policy": records(policy),
        "runs": records(runs),
        "example": example,
    }


def build_explorer(t, meta):
    """
    Data for the response explorer.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        From ``load_inputs``.
    meta : dict
        From ``common_meta``.

    Returns
    -------
    dict
        meta, cities, responses (with text, codes, entities, and sources),
        and domains (code per domain, for coloring links).
    """
    cities = t["cities"]
    pr = t["place_responses"].merge(
        t["response_accuracy"][["response_id", "law_claim_check"]], on="response_id"
    )
    text = t["response_text"].set_index("response_id")["text"]
    domains = t["domain_codes"].set_index("domain")

    # Numbered sources per response: one number per distinct cited URL, in
    # order of first appearance.
    cites = t["text_citations"].copy()
    cites = cites[cites["provider"] != "openai"].sort_values(["response_id", "index"])
    cites["key"] = cites["url_norm"].fillna(cites["url"])
    cites["n"] = cites.groupby("response_id")["key"].transform(
        lambda s: pd.factorize(s)[0] + 1
    )

    acc = t["place_accuracy"].set_index(["response_id", "entity_index"])
    nearest = t["reference_nearest"]
    nearest = nearest[nearest["variant"] == nearest["variant"].iloc[0]]

    responses = []
    for r in pr.sort_values(["query_state_abbr", "geoid", "provider"]).itertuples():
        body = text.loc[r.response_id]
        rc = cites[cites["response_id"] == r.response_id]
        sources = []
        if len(rc):
            body = insert_markers(body, rc)
            for n, g in rc.groupby("n"):
                first = g.iloc[0]
                d = (
                    domains.loc[first["domain"]]
                    if first["domain"] in domains.index
                    else None
                )
                sources.append(
                    {
                        "n": int(n),
                        "url": first["resolved_url"]
                        if isinstance(first["resolved_url"], str)
                        else first["url"],
                        "domain": first["domain"],
                        "title": first["title"],
                        "category": d["category"] if d is not None else None,
                    }
                )
        ents = t["place_entities"]
        ents = ents[ents["response_id"] == r.response_id].sort_values("entity_index")
        entity_list = []
        for e in ents.itertuples():
            key = (e.response_id, e.entity_index)
            a = acc.loc[key] if key in acc.index else None
            item = {
                "i": e.entity_index,
                "role": e.role,
                "pos": clean(e.list_position),
                "type": e.entity_type,
                "name": e.name_verbatim,
                "cpc_name": bool(e.possible_cpc_name),
                "provider_yes": e.presented_as_abortion_provider,
                "services": e.services_verbatim,
                "address": e.address_verbatim,
                "phones": clean(e.phones_verbatim),
                "website": e.website_verbatim,
                "distance_claim": e.distance_claim_verbatim,
                "caveat": e.caveat_verbatim,
                "evidence": e.evidence_quote,
            }
            if a is not None:
                item.update(
                    {
                        "locatable": clean(a["locatable"]),
                        "distance_mi": clean(a["distance_mi"]),
                        "place_state": clean(a["place_state_abbr"]),
                        "neighbor": clean(a["is_neighbor_state"]),
                        "among_closest": clean(a["among_closest"]),
                        "ref_rank": clean(a["ref_rank"]),
                    }
                )
            entity_list.append(drop_missing(item))
        responses.append(
            {
                "id": r.response_id,
                "provider": r.provider,
                "geoid": r.geoid,
                "text": body,
                "answer_status": r.answer_status,
                "law_claim": r.state_law_claim,
                "law_check": r.law_claim_check,
                "law_quote": r.state_law_quote_verbatim,
                "follow_up": r.follow_up_request_verbatim,
                "travel": bool(r.says_travel_needed),
                "telehealth": bool(r.mentions_telehealth),
                "gest_limits": bool(r.mentions_gestational_limits),
                "financial": bool(r.mentions_financial_help),
                "entities": entity_list,
                "sources": sources,
            }
        )
    responses = [drop_missing(r) for r in responses]

    near = {
        g: records(
            df.sort_values("rank")[["rank", "name", "state_abbr", "distance_mi"]]
        )
        for g, df in nearest.groupby("geoid")
    }
    city_list = records(
        cities.drop(columns=["lat", "lon", "policy_as_of", "city_official"])
    )
    for c in city_list:
        c["nearest"] = near.get(c["geoid"], [])
    domain_codes = {
        d: [r["category"], r["stance_on_abortion_access"], r["cpc_affiliated"]]
        for d, r in domains.iterrows()
    }
    return {
        "meta": meta,
        "cities": city_list,
        "responses": responses,
        "domains": domain_codes,
    }


def insert_markers(text, cites):
    """
    Insert numbered citation markers at the end of each cited span.

    Parameters
    ----------
    text : str
        The response text.
    cites : pandas.DataFrame
        The response's text citations, with end_index and n (source number).

    Returns
    -------
    str
        The text with CITE_OPEN "n,n" CITE_CLOSE markers inserted.
    """
    ends = {}
    for end, n in zip(cites["end_index"], cites["n"]):
        if pd.isna(end):
            continue
        end = int(end)
        # Move the marker past closing markdown emphasis so it does not
        # split a **bold** run.
        while end < len(text) and text[end] in "*_":
            end += 1
        ends.setdefault(end, set()).add(int(n))
    for end in sorted(ends, reverse=True):
        nums = ",".join(str(n) for n in sorted(ends[end]))
        text = text[:end] + CITE_OPEN + nums + CITE_CLOSE + text[end:]
    return text


def build_brief(t, meta, shapes):
    """
    Data for the brief: one block per research question.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        From ``load_inputs``.
    meta : dict
        From ``common_meta``.
    shapes : dict
        From ``state_shapes``.

    Returns
    -------
    dict
        meta, shapes, cities, and one key per tab.
    """
    cities = t["cities"].set_index("geoid")
    pr = t["place_responses"].copy()
    pr["total_ban"] = pr["geoid"].map(cities["total_ban"]).astype(bool)
    pr["size_group"] = pr["geoid"].map(cities["size_group"])
    pr["law_stated"] = ~pr["state_law_claim"].isin(["not_stated"])
    ents = t["place_entities"]
    geo = t["place_geography"].copy()
    geo["size_group"] = geo["geoid"].map(cities["size_group"])
    acc = t["place_accuracy"]
    primary_geo = geo[(geo["role"] == "primary") & geo["geocode_precise"]]
    providers = [p["id"] for p in PROVIDERS]

    # 1. Do the chatbots answer the question?
    answers = []
    for p in providers:
        d = pr[pr["provider"] == p]
        answers.append(
            {
                "provider": p,
                "n": len(d),
                "places_provided": int((d["answer_status"] == "places_provided").sum()),
                "n_primary_dist": {
                    str(k): int(v)
                    for k, v in d["n_primary"]
                    .clip(upper=5)
                    .value_counts()
                    .sort_index()
                    .items()
                },
                "mean_primary": d["n_primary"].mean(),
                "mean_alternative": d["n_alternative"].mean(),
                "mean_resource": d["n_resource"].mean(),
                "asks_follow_up": int(d["asks_follow_up"].sum()),
                "exactly_three": int((d["n_primary"] == 3).sum()),
            }
        )
    # What the query asked for: does each main recommendation come with it?
    prim_ents = ents[ents["role"] == "primary"]
    details = []
    for p in providers:
        d = prim_ents[prim_ents["provider"] == p]
        details.append(
            {
                "provider": p,
                "n": len(d),
                "address": d["address_verbatim"].notna().mean(),
                "street": d["street"].notna().mean(),
                "phone": d["phones_verbatim"]
                .map(lambda x: x is not None and len(x) > 0)
                .mean(),
                "website": d["website_verbatim"].notna().mean(),
                "distance": d["distance_claim_verbatim"].notna().mean(),
                "services": d["services_verbatim"].notna().mean(),
            }
        )
    asks_only = records(
        pr[pr["answer_status"] != "places_provided"][
            ["provider", "geoid", "answer_status", "follow_up_request_verbatim"]
        ]
    )

    # 2. What kinds of places and resources?
    types = (
        ents.groupby(["provider", "role", "entity_type"])
        .size()
        .rename("n")
        .reset_index()
    )
    cpc = ents[
        (ents["entity_type"] == "crisis_pregnancy_center") | ents["possible_cpc_name"]
    ]
    cpc_rows = records(
        cpc[
            [
                "provider",
                "role",
                "entity_type",
                "name_verbatim",
                "presented_as_abortion_provider",
                "caveat_verbatim",
                "geoid",
            ]
        ]
    )

    # 3. How far? 4. Where are people in total-ban states sent?
    points = primary_geo.assign(total_ban=primary_geo["query_state_total_ban"])[
        [
            "provider",
            "geoid",
            "total_ban",
            "query_state_category_rank",
            "size_group",
            "distance_mi",
            "in_query_city",
            "crosses_state",
            "is_neighbor_state",
            "place_state_abbr",
            "lat",
            "lon",
            "name_verbatim",
        ]
    ].rename(columns={"query_state_category_rank": "rank", "name_verbatim": "name"})
    points = points.round({"distance_mi": 2, "lat": 4, "lon": 4})

    ban_places = points[points["total_ban"]]
    dest = (
        ban_places.groupby(["place_state_abbr", "provider"])
        .size()
        .rename("n")
        .reset_index()
    )
    neighbor_pairs = set(
        zip(t["neighbors"]["state_abbr"], t["neighbors"]["neighbor_abbr"])
    )
    ban_states = sorted(cities.loc[cities["total_ban"], "state_abbr"].unique())
    nearest = t["reference_nearest"]
    first = nearest[
        (nearest["variant"] == nearest["variant"].iloc[0]) & (nearest["rank"] == 1)
    ]
    first = first.set_index("geoid")
    ban_city_rows = []
    for g, c in cities[cities["total_ban"]].iterrows():
        ns = first.loc[g, "state_abbr"]
        ban_city_rows.append(
            {
                "geoid": g,
                "nearest_state": ns,
                "nearest_mi": round(float(first.loc[g, "distance_mi"]), 1),
                "nearest_is_neighbor": (c["state_abbr"], ns) in neighbor_pairs,
            }
        )
    ban_acc = acc[
        (acc["role"] == "primary") & acc["locatable"] & acc["query_state_total_ban"]
    ]
    ban_summary = []
    for p in providers:
        d = ban_acc[ban_acc["provider"] == p]
        ban_summary.append(
            {
                "provider": p,
                "n": len(d),
                "neighbor": int(d["is_neighbor_state"].sum()),
                "in_nearest_state": int(d["in_nearest_ref_state"].sum()),
            }
        )

    # 5. Are the recommendations the closest available?
    prim_acc = acc[acc["role"] == "primary"]
    funnel = []
    curve = []
    for p in providers:
        d = prim_acc[prim_acc["provider"] == p]
        loc = d[d["locatable"]]
        funnel.append(
            {
                "provider": p,
                "total": len(d),
                "locatable": int(loc.shape[0]),
                "legal_state": int(loc["in_legal_state"].sum()),
                "among_closest": int(loc["among_closest"].sum()),
                "among_closest_strict": int(loc["among_closest_strict"].sum()),
                "rank_dist": {
                    k: int(v)
                    for k, v in pd.cut(
                        loc["ref_rank"].astype(float),
                        [0, 1, 2, 3, 5, 10, np.inf],
                        labels=["1", "2", "3", "4–5", "6–10", "11+"],
                    )
                    .value_counts()
                    .sort_index()
                    .items()
                },
                "median_excess_mi": loc["excess_mi"].median(),
                "share_excess_le_10": (loc["excess_mi"] <= 10).mean(),
            }
        )
        for tol in TOLERANCES:
            curve.append(
                {
                    "provider": p,
                    "tol": tol,
                    "share": (loc["ratio_to_third"] <= tol).mean(),
                    "share_strict": (loc["ratio_to_third_strict"] <= tol).mean(),
                }
            )
    excess = records(
        prim_acc[prim_acc["locatable"]][
            ["provider", "excess_mi", "query_state_total_ban"]
        ].round({"excess_mi": 2})
    )
    worst = (
        prim_acc[prim_acc["locatable"]]
        .sort_values("excess_mi", ascending=False)
        .head(8)
    )
    worst = worst.merge(
        first.reset_index()[["geoid", "name", "state_abbr", "distance_mi"]].rename(
            columns={
                "name": "nearest_name",
                "state_abbr": "nearest_state",
                "distance_mi": "nearest_mi",
            }
        ),
        on="geoid",
        how="left",
    )
    worst = records(
        worst[
            [
                "nearest_name",
                "nearest_state",
                "nearest_mi",
                "provider",
                "query_city",
                "query_state_abbr",
                "name_verbatim",
                "place_state_abbr",
                "distance_mi",
                "excess_mi",
                "ref_rank",
            ]
        ]
    )

    # 6. Do the chatbots describe state law correctly?
    pr["policy_group"] = np.select(
        [pr["total_ban"], pr["geoid"].map(cities["category_rank"]) == 1],
        ["Total ban", "6-week ban"],
        default=pr["geoid"].map(cities["environment_type"]),
    )
    law = pr.merge(
        t["response_accuracy"][["response_id", "law_claim_check"]], on="response_id"
    ).assign(rank=lambda d: d["geoid"].map(cities["category_rank"]))
    law_table = (
        law.groupby(["provider", "policy_group", "state_law_claim"])
        .size()
        .rename("n")
        .reset_index()
    )
    law_order = (
        law.assign(o=np.where(law["total_ban"], 0, law["rank"]))
        .groupby("policy_group")["o"]
        .min()
        .sort_values()
        .index.tolist()
    )
    law_check = (
        law.groupby(["provider", "law_claim_check"]).size().rename("n").reset_index()
    )
    law_quotes = records(
        law[law["state_law_claim"].isin(["banned", "restricted", "legal"])]
        .groupby(["policy_group", "state_law_claim"])
        .head(1)[
            [
                "provider",
                "policy_group",
                "state_law_claim",
                "state_law_quote_verbatim",
                "query_state_abbr",
            ]
        ]
    )

    # 7. Distance claims.
    claims = acc[acc["claim_miles"].notna() & acc["locatable"]]
    claims = claims.assign(
        anchored_elsewhere=claims["claim_anchor_is_query_city"].fillna(True).eq(False)
    )[
        [
            "provider",
            "role",
            "distance_mi",
            "claim_miles",
            "claim_text",
            "anchored_elsewhere",
            "query_city",
            "query_state_abbr",
            "name_verbatim",
        ]
    ].round({"distance_mi": 1, "claim_miles": 1})
    n_claims_total = int(t["place_entities"]["distance_claim_verbatim"].notna().sum())

    # 8. Big cities and small towns.
    by_city = []
    for (g, p), d in primary_geo.groupby(["geoid", "provider"]):
        by_city.append(
            {
                "geoid": g,
                "provider": p,
                "nearest_mi": round(float(d["distance_mi"].min()), 2),
                "median_mi": round(float(d["distance_mi"].median()), 2),
                "n_in_city": int(d["in_query_city"].astype(bool).sum()),
                "n": len(d),
            }
        )
    size_summary = []
    for (s, p, b), d in primary_geo.groupby(
        ["size_group", "provider", "query_state_total_ban"]
    ):
        size_summary.append(
            {
                "size_group": s,
                "provider": p,
                "total_ban": bool(b),
                "n": len(d),
                "share_in_city": d["in_query_city"].astype(bool).mean(),
                "median_mi": d["distance_mi"].median(),
            }
        )

    # 9. Do the chatbots agree? Facilities (pooled ids) per city.
    fac = acc[(acc["role"] == "primary") & acc["facility_id"].notna()]
    agree_rows = []
    pair_rows = []
    for g, d in fac.groupby("geoid"):
        sets = {p: set(d.loc[d["provider"] == p, "facility_id"]) for p in providers}
        counts = d.groupby("facility_id")["provider"].nunique()
        agree_rows.append(
            {
                "geoid": g,
                "n_facilities": int(len(counts)),
                "by_1": int((counts == 1).sum()),
                "by_2": int((counts == 2).sum()),
                "by_3": int((counts == 3).sum()),
            }
        )
        for i, a in enumerate(providers):
            for b in providers[i + 1 :]:
                union = sets[a] | sets[b]
                if union:
                    pair_rows.append(
                        {
                            "geoid": g,
                            "a": a,
                            "b": b,
                            "jaccard": len(sets[a] & sets[b]) / len(union),
                        }
                    )
    pairs = pd.DataFrame(pair_rows)
    pairs["total_ban"] = pairs["geoid"].map(cities["total_ban"]).astype(bool)
    pair_summary = records(
        pairs.groupby(["a", "b", "total_ban"])["jaccard"]
        .mean()
        .rename("mean_jaccard")
        .reset_index()
    )
    pair_all = records(
        pairs.groupby(["a", "b"])["jaccard"].mean().rename("mean_jaccard").reset_index()
    )
    agree = pd.DataFrame(agree_rows)
    agree["total_ban"] = agree["geoid"].map(cities["total_ban"]).astype(bool)
    agree["size_group"] = agree["geoid"].map(cities["size_group"])
    first_pick = (
        fac[fac["list_position"] == 1]
        .groupby("geoid")["facility_id"]
        .nunique()
        .rename("n_first")
    )
    agree = agree.join(first_pick, on="geoid")

    # 10. What extra guidance comes with the answer?
    guidance = []
    for (p, b), d in pr.groupby(["provider", "total_ban"]):
        for flag, label in GUIDANCE_FLAGS:
            guidance.append(
                {
                    "provider": p,
                    "total_ban": bool(b),
                    "flag": flag,
                    "label": label,
                    "n": len(d),
                    "k": int(d[flag].sum()),
                }
            )
    resources = ents[ents["role"] == "resource"]
    res_types = (
        resources.groupby(["provider", "entity_type"]).size().rename("n").reset_index()
    )
    top_resources = (
        resources.assign(
            name=resources["name_verbatim"]
            .str.replace(r"[*_]", "", regex=True)
            .str.strip()
        )
        .groupby(["provider", "name"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values("n", ascending=False)
    )

    # 11. Websites shown to readers.
    shown = shown_links(t)
    shown["category"] = shown["category"].fillna("unclear")
    web_cat = shown.groupby(["provider", "category"]).size().rename("n").reset_index()
    web_stance = (
        shown.groupby(["provider", "stance_on_abortion_access"])
        .size()
        .rename("n")
        .reset_index()
    )
    per_resp = shown.groupby("response_id").size()
    web_per = []
    for p in providers:
        ids = pr.loc[pr["provider"] == p, "response_id"]
        n = per_resp.reindex(ids).fillna(0)
        web_per.append(
            {
                "provider": p,
                "mean": n.mean(),
                "median": n.median(),
                "q25": n.quantile(0.25),
                "q75": n.quantile(0.75),
                "distinct": int(shown.loc[shown["provider"] == p, "domain"].nunique()),
            }
        )
    top_domains = (
        shown.groupby(["domain", "provider"])
        .size()
        .unstack(fill_value=0)
        .assign(total=lambda d: d.sum(axis=1))
    )
    top_domains = (
        top_domains.sort_values("total", ascending=False).head(20).reset_index()
    )
    codes = t["domain_codes"].set_index("domain")
    top_domains["category"] = top_domains["domain"].map(codes["category"])
    cpc_shown = shown[shown["cpc_affiliated"] == "yes"]
    cpc_domains = set(cpc_shown["domain"])
    cpc_cites = t["text_citations"][t["text_citations"]["domain"].isin(cpc_domains)]
    text = t["response_text"].set_index("response_id")["text"]
    spans = [
        text[r][int(a) : int(b)]
        for r, a, b in zip(
            cpc_cites["response_id"], cpc_cites["start_index"], cpc_cites["end_index"]
        )
    ]
    cpc_warning = {
        "n_citations": len(spans),
        "n_warning": int(sum(bool(WARNING_PATTERN.search(x)) for x in spans)),
    }
    cpc_web = records(
        cpc_shown.groupby(["provider", "domain"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values("n", ascending=False)
    )

    city_list = records(
        cities.reset_index()[
            [
                "geoid",
                "city",
                "state_abbr",
                "pop",
                "size_group",
                "lat",
                "lon",
                "total_ban",
                "category_rank",
            ]
        ]
    )
    return {
        "meta": meta,
        "shapes": shapes,
        "cities": city_list,
        "neighbors": records(t["neighbors"][["state_abbr", "neighbor_abbr"]]),
        "ban_states": ban_states,
        "answers": {
            "by_provider": answers,
            "not_places": asks_only,
            "details": records(pd.DataFrame(details)),
        },
        "types": {"counts": records(types), "cpc": cpc_rows},
        "distance": {"points": records(points.drop(columns=["lat", "lon"]))},
        "ban_map": {
            "places": records(
                ban_places[
                    [
                        "provider",
                        "geoid",
                        "lat",
                        "lon",
                        "place_state_abbr",
                        "is_neighbor_state",
                        "distance_mi",
                        "name",
                    ]
                ]
            ),
            "dest": records(dest),
            "cities": ban_city_rows,
            "summary": ban_summary,
        },
        "accuracy": {
            "funnel": records(pd.DataFrame(funnel).drop(columns=["rank_dist"])),
            "rank_dist": {f["provider"]: f["rank_dist"] for f in funnel},
            "curve": records(pd.DataFrame(curve)),
            "excess": excess,
            "worst": worst,
            "n_reference": len(t["reference_facilities"]),
            "n_reference_strict": int(
                (t["reference_facilities"]["n_responses"] >= 2).sum()
            ),
        },
        "law": {
            "table": records(law_table),
            "order": law_order,
            "check": records(law_check),
            "quotes": law_quotes,
        },
        "claims": {"points": records(claims), "n_claims_total": n_claims_total},
        "size": {"by_city": by_city, "summary": records(pd.DataFrame(size_summary))},
        "agreement": {
            "cities": records(agree),
            "pairs": pair_summary,
            "pairs_all": pair_all,
        },
        "guidance": {
            "flags": guidance,
            "resource_types": records(res_types),
            "top_resources": records(top_resources.groupby("provider").head(6)),
        },
        "websites": {
            "categories": records(web_cat),
            "stance": records(web_stance),
            "per_response": records(pd.DataFrame(web_per)),
            "top_domains": records(top_domains),
            "cpc": cpc_web,
            "cpc_citations": cpc_warning,
        },
    }


def render(template_name, data):
    """
    Fill a page template: inline its shared files and its data.

    Parameters
    ----------
    template_name : str
        The template file in templates/pilot-4cities/.
    data : dict
        The page's data, embedded as window.PAGE_DATA.

    Returns
    -------
    str
        The finished HTML.
    """
    html = (TEMPLATES_DIR / "pilot-4cities" / template_name).read_text(encoding="utf-8")

    def inline(match):
        path = TEMPLATES_DIR / match.group(1)
        body = path.read_text(encoding="utf-8")
        if path.suffix == ".css":
            return f"<style>\n{body}\n</style>"
        return f"<script>\n{body.replace('</script', '<\\/script')}\n</script>"

    html = re.sub(r"<!-- @inline (\S+) -->", inline, html)
    payload = json.dumps(
        data, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    # "</" inside the JSON would end the script element early.
    payload = payload.replace("</", "<\\/")
    script = f"<script>window.PAGE_DATA = {payload};</script>"
    assert "<!-- @data -->" in html, f"{template_name} has no data marker"
    return html.replace("<!-- @data -->", script)


def main():
    """
    Build and write the three pages.
    """
    t = load_inputs()
    meta = common_meta(t)
    shapes = state_shapes()
    builders = {
        "approach": lambda: build_approach(t, meta, shapes),
        "explorer": lambda: build_explorer(t, meta),
        "brief": lambda: build_brief(t, meta, shapes),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for page, filename in PAGES.items():
        template = TEMPLATES_DIR / "pilot-4cities" / f"{page}.html"
        if not template.exists():
            print(f"Skipping {page}: no template yet")
            continue
        html = render(f"{page}.html", builders[page]())
        out = OUTPUT_DIR / filename
        out.write_text(html, encoding="utf-8")
        print(f"Wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
