"""
Purpose:
    Build the data bundle read by the interactive pilot explorer
    (results/figures/interactive/pilot_explorer.html).

Notes:
    - The explorer does no analysis of its own: every count, share, and mean
      it shows is computed here (from the processed tables and the
      per-response measures) and only drawn by the page.
    - The bundle is a JavaScript file that assigns one object to
      `window.PILOT_EXPLORER_DATA`, not a .json file, because browsers block
      reading local JSON from a page opened straight from disk (file://),
      while a <script src> is allowed. The object is plain JSON.
    - Shares are "share of responses": the number of responses with the
      property divided by the responses in that cell (3 repeats per query,
      provider, and location; 30 per provider and location). Counts (k, n)
      are kept alongside shares so the page can show both.
    - Cells whose provider does not report a measure (Anthropic text
      citations, Gemini search results; see compute_response_measures.py)
      are null rather than 0, so the page can mark them "not reported".
    - Domain rankings count each domain once per response, so one response
      that cites a site five times does not dominate the ranking.
    - Highlighting in the page reuses the lexicon patterns exported here,
      so highlighted words are exactly the matches counted in the
      measures.

Input:
    - data/processed/metadata.parquet
    - data/processed/response_text.parquet
    - data/processed/tool_calls.parquet
    - data/processed/text_citations.parquet
    - data/processed/tool_citations.parquet
    - data/processed/response_measures.parquet (from
      code/analysis/compute_response_measures.py)

Output:
    - data/processed/pilot_explorer_data.js - `window.PILOT_EXPLORER_DATA =
      {...};` with keys:
        - generated_at (str): UTC build time.
        - providers (list): {id, label, model}, in display order.
        - locations (list): {id, label}; "none" is the query without a
          location.
        - queries (list): {id, text (no-location wording), variants
          {location: wording}}.
        - resources (list): {id, label, pattern} from toolkit.resources.
        - metrics (list): {id, label, unit, note} for the overview dot
          plots; each id is a field of every response record.
        - responses (list): one per response: id, provider, location,
          query, repeat, text, latency_s, stop_reason, the measures from
          response_measures (n_words, searched, n_searches, n_cited_urls,
          n_retrieved_urls, n_retrieved_domains, n_resources),
          resources (ids named), searches (list of lists of search strings,
          one list per search call), cited (list of {domain, url, title},
          distinct URLs in citation order).
        - cell_means (list): one per (query, provider, location): the mean
          of every metric over repeats (null where not reported) and n. The
          overview plots each repeat (from `responses`) next to this mean.
        - resource_shares (list): one per (scope, provider, location,
          resource): scope is a query id or "all"; k, n, share.
        - search_rates (list): one per (provider, location): k responses
          that searched, n, share, and mean searches per response.
        - domains (list): one per (kind, provider, location, domain) for
          the top TOP_DOMAINS domains: kind is "cited" or "retrieved",
          location may be "all"; k responses, n, share, rank.
        - search_queries (list): one per (query, provider, location,
          search string): the string and how many of the repeats sent it.
    - results/reports/build_pilot_explorer_data_report.txt - bundle size and
      row counts

Author: Matthew DeVerna
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from toolkit.resources import resource_table

os.chdir(Path(__file__).resolve().parent)

PROCESSED_DIR = Path("../../data/processed")
OUTPUT_PATH = PROCESSED_DIR / "pilot_explorer_data.js"
REPORT_PATH = Path("../../results/reports/build_pilot_explorer_data_report.txt")

PROVIDERS = [
    {"id": "anthropic", "label": "Anthropic"},
    {"id": "gemini", "label": "Gemini"},
    {"id": "openai", "label": "OpenAI"},
]
LOCATIONS = [
    {"id": "none", "label": "No location"},
    {"id": "houston-tx", "label": "Houston, TX"},
    {"id": "portland-or", "label": "Portland, OR"},
]

# Overview metrics: id (a field of every response record), label, unit,
# and a note shown under the dot plots. The page plots each repeat's value
# and the cell mean from build_cell_means.
METRICS = [
    {
        "id": "n_words",
        "label": "Response length",
        "unit": "words",
        "note": "Words per response; URLs removed before counting.",
    },
    {
        "id": "searched",
        "label": "Searched the web",
        "unit": "share",
        "note": "Whether a repeat ran at least one web search (0% = no, 100% = yes); "
        "the mean is the share of the 3 repeats that searched.",
    },
    {
        "id": "n_searches",
        "label": "Search calls",
        "unit": "calls",
        "note": "Web-search tool calls per response.",
    },
    {
        "id": "n_cited_urls",
        "label": "Cited sources",
        "unit": "URLs",
        "note": "Distinct URLs cited in the answer text. "
        "Anthropic attaches no text citations, so it is not reported.",
    },
    {
        "id": "n_retrieved_urls",
        "label": "Search results",
        "unit": "URLs",
        "note": "Distinct URLs returned by searches, cited or not. "
        "Gemini exposes no search results, so it is not reported.",
    },
    {
        "id": "n_resources",
        "label": "Resources named",
        "unit": "resources",
        "note": "Number of the lexicon's resources named (keyword match).",
    },
    {
        "id": "latency_s",
        "label": "Latency",
        "unit": "seconds",
        "note": "Seconds from request to response.",
    },
]

# Metrics a provider does not report (see compute_response_measures.py).
NOT_REPORTED = {
    "n_cited_urls": {"anthropic"},
    "n_retrieved_urls": {"gemini"},
}

SEARCH_TOOL_TYPES = {"web_search", "google_search", "web_search.search"}
TOP_DOMAINS = 15


def load_tables():
    """
    Return the processed tables, merged into one response frame plus the
    detail tables.

    Returns
    -------
    tuple
        (responses, tool_calls, text_citations, tool_citations), where
        responses has one row per response with metadata, text, and measures.
    """
    meta = pd.read_parquet(PROCESSED_DIR / "metadata.parquet")
    meta = meta[meta["status"] == "ok"]
    text = pd.read_parquet(PROCESSED_DIR / "response_text.parquet")
    measures = pd.read_parquet(PROCESSED_DIR / "response_measures.parquet")

    responses = meta.merge(
        text[["response_id", "text"]], on="response_id", validate="1:1"
    ).merge(
        measures.drop(columns=["provider", "location", "message_id", "repeat"]),
        on="response_id",
        validate="1:1",
    )
    responses["latency_s"] = responses["latency_ms"] / 1000
    # Mask measures a provider does not report, so they are null, not 0.
    for metric, providers in NOT_REPORTED.items():
        responses.loc[responses["provider"].isin(providers), metric] = None

    tool_calls = pd.read_parquet(PROCESSED_DIR / "tool_calls.parquet")
    text_cites = pd.read_parquet(PROCESSED_DIR / "text_citations.parquet")
    tool_cites = pd.read_parquet(PROCESSED_DIR / "tool_citations.parquet")
    return responses, tool_calls, text_cites, tool_cites


def build_queries(responses):
    """
    Return one record per query with its wording at each location.

    Parameters
    ----------
    responses : pandas.DataFrame
        The merged response frame.

    Returns
    -------
    list of dict
        {id, text, variants}, ordered by message_id.
    """
    wording = responses.drop_duplicates(["message_id", "location"])
    queries = []
    for qid, g in wording.groupby("message_id", sort=True):
        variants = dict(zip(g["location"], g["message"]))
        queries.append({"id": qid, "text": variants["none"], "variants": variants})
    return queries


def build_response_records(responses, tool_calls, text_cites):
    """
    Return one display record per response.

    Parameters
    ----------
    responses : pandas.DataFrame
        The merged response frame.
    tool_calls : pandas.DataFrame
        tool_calls.parquet.
    text_cites : pandas.DataFrame
        text_citations.parquet.

    Returns
    -------
    list of dict
        One record per response, ordered by query, provider, location, repeat.
    """
    searches = tool_calls[tool_calls["tool_type"].isin(SEARCH_TOOL_TYPES)]
    searches = searches.sort_values(["response_id", "index"])
    searches_by_id = (
        searches.groupby("response_id")["search_queries"]
        .apply(lambda s: [[] if q is None else [str(x) for x in q] for q in s])
        .to_dict()
    )

    cites = text_cites.assign(
        url=text_cites["resolved_url"].fillna(text_cites["url"])
    ).sort_values(["response_id", "index"])
    cites = cites.drop_duplicates(["response_id", "url"])
    cited_by_id = {
        rid: g[["domain", "url", "title"]].to_dict("records")
        for rid, g in cites.groupby("response_id")
    }

    resource_ids = [r["id"] for r in resource_table()]
    responses = responses.sort_values(["message_id", "provider", "location", "repeat"])
    records = []
    for row in responses.itertuples(index=False):
        records.append(
            {
                "id": row.response_id,
                "provider": row.provider,
                "location": row.location,
                "query": row.message_id,
                "repeat": int(row.repeat),
                "text": row.text,
                "latency_s": round(row.latency_s, 1),
                "stop_reason": row.stop_reason,
                "n_words": int(row.n_words),
                "searched": bool(row.searched),
                "n_searches": int(row.n_searches),
                "n_cited_urls": None
                if pd.isna(row.n_cited_urls)
                else int(row.n_cited_urls),
                "n_retrieved_urls": (
                    None if pd.isna(row.n_retrieved_urls) else int(row.n_retrieved_urls)
                ),
                "n_retrieved_domains": int(row.n_retrieved_domains),
                "n_resources": int(row.n_resources),
                "resources": [
                    rid for rid in resource_ids if getattr(row, f"res_{rid}")
                ],
                "searches": searches_by_id.get(row.response_id, []),
                "cited": cited_by_id.get(row.response_id, []),
            }
        )
    return records


def build_cell_means(responses):
    """
    Return the mean of every overview metric per (query, provider, location).

    Parameters
    ----------
    responses : pandas.DataFrame
        The merged response frame (unreported metrics already null).

    Returns
    -------
    list of dict
        {query, provider, location, n, <metric id>: mean or None}.
    """
    metric_ids = [m["id"] for m in METRICS]
    frame = responses[["message_id", "provider", "location"] + metric_ids].copy()
    frame[metric_ids] = frame[metric_ids].astype(float)
    # mean() skips nulls; a cell where every value is null stays null.
    cells = frame.groupby(["message_id", "provider", "location"])
    out = cells[metric_ids].mean().round(3)
    out["n"] = cells.size()
    out = out.reset_index().rename(columns={"message_id": "query"})
    return json.loads(out.to_json(orient="records"))


def build_resource_shares(responses):
    """
    Return the share of responses naming each resource, overall and per query.

    Parameters
    ----------
    responses : pandas.DataFrame
        The merged response frame.

    Returns
    -------
    list of dict
        {scope, provider, location, resource, k, n, share}; scope is a query
        id or "all".
    """
    res_cols = {f"res_{r['id']}": r["id"] for r in resource_table()}
    long = responses.melt(
        id_vars=["message_id", "provider", "location"],
        value_vars=list(res_cols),
        var_name="resource",
        value_name="hit",
    )
    long["resource"] = long["resource"].map(res_cols)

    rows = []
    scopes = [("all", long)] + list(long.groupby("message_id"))
    for scope, frame in scopes:
        agg = frame.groupby(["provider", "location", "resource"])["hit"].agg(
            k="sum", n="size"
        )
        agg["share"] = (agg["k"] / agg["n"]).round(3)
        agg = agg.reset_index().assign(scope=scope)
        rows.extend(json.loads(agg.to_json(orient="records")))
    return rows


def build_search_rates(responses):
    """
    Return the share of responses that searched, per provider and location.

    Parameters
    ----------
    responses : pandas.DataFrame
        The merged response frame.

    Returns
    -------
    list of dict
        {provider, location, k, n, share, mean_searches}.
    """
    agg = responses.groupby(["provider", "location"]).agg(
        k=("searched", "sum"),
        n=("searched", "size"),
        mean_searches=("n_searches", "mean"),
    )
    agg["share"] = (agg["k"] / agg["n"]).round(3)
    agg["mean_searches"] = agg["mean_searches"].round(2)
    return json.loads(agg.reset_index().to_json(orient="records"))


def rank_domains(citations, responses, kind):
    """
    Return the top domains per provider and location by share of responses.

    Parameters
    ----------
    citations : pandas.DataFrame
        text_citations (kind "cited") or tool_citations (kind "retrieved").
    responses : pandas.DataFrame
        The merged response frame, for the denominators.
    kind : str
        "cited" or "retrieved".

    Returns
    -------
    list of dict
        {kind, provider, location, domain, k, n, share, rank}; location
        "all" pools the three locations.
    """
    hits = citations.dropna(subset=["domain"]).merge(
        responses[["response_id", "location"]], on="response_id"
    )
    # Count each domain once per response.
    hits = hits.drop_duplicates(["response_id", "domain"])
    # Rank within each location, then again with the locations pooled.
    hits = pd.concat([hits, hits.assign(location="all")])
    totals = (
        pd.concat([responses, responses.assign(location="all")])
        .groupby(["provider", "location"])
        .size()
    )

    rows = []
    for (provider, location), g in hits.groupby(["provider", "location"]):
        n = int(totals.loc[(provider, location)])
        counts = g["domain"].value_counts().head(TOP_DOMAINS)
        for rank, (domain, k) in enumerate(counts.items(), start=1):
            rows.append(
                {
                    "kind": kind,
                    "provider": provider,
                    "location": location,
                    "domain": domain,
                    "k": int(k),
                    "n": n,
                    "share": round(k / n, 3),
                    "rank": rank,
                }
            )
    return rows


def build_search_queries(responses, tool_calls):
    """
    Return the distinct search strings sent for each query cell.

    Parameters
    ----------
    responses : pandas.DataFrame
        The merged response frame.
    tool_calls : pandas.DataFrame
        tool_calls.parquet.

    Returns
    -------
    list of dict
        {query, provider, location, search, k}; k is how many repeats sent
        the string (case- and whitespace-insensitive), sorted by k.
    """
    searches = tool_calls[tool_calls["tool_type"].isin(SEARCH_TOOL_TYPES)]
    searches = searches.explode("search_queries").dropna(subset=["search_queries"])
    searches = searches.merge(
        responses[["response_id", "message_id", "location"]], on="response_id"
    )
    searches["search"] = searches["search_queries"].astype(str).str.strip()
    searches["key"] = searches["search"].str.lower().str.split().str.join(" ")
    # A repeat that sends the same string twice counts once.
    searches = searches.drop_duplicates(["response_id", "key"])
    agg = (
        searches.groupby(["message_id", "provider", "location", "key"])
        .agg(search=("search", "first"), k=("response_id", "nunique"))
        .reset_index()
        .sort_values(
            ["message_id", "provider", "location", "k"], ascending=[1, 1, 1, 0]
        )
        .rename(columns={"message_id": "query"})
        .drop(columns="key")
    )
    return agg.to_dict("records")


def main():
    responses, tool_calls, text_cites, tool_cites = load_tables()

    models = responses.groupby("provider")["model"].first().to_dict()
    providers = [{**p, "model": models[p["id"]]} for p in PROVIDERS]

    cited_for_rank = text_cites.assign(
        url=text_cites["resolved_url"].fillna(text_cites["url"])
    )
    bundle = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "providers": providers,
        "locations": LOCATIONS,
        "queries": build_queries(responses),
        "resources": resource_table(),
        "metrics": METRICS,
        "responses": build_response_records(responses, tool_calls, text_cites),
        "cell_means": build_cell_means(responses),
        "resource_shares": build_resource_shares(responses),
        "search_rates": build_search_rates(responses),
        "domains": rank_domains(cited_for_rank, responses, "cited")
        + rank_domains(tool_cites, responses, "retrieved"),
        "search_queries": build_search_queries(responses, tool_calls),
    }

    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    OUTPUT_PATH.write_text(
        "// Generated by code/generate_figures/build_pilot_explorer_data.py\n"
        f"window.PILOT_EXPLORER_DATA = {payload};\n",
        encoding="utf-8",
    )

    lines = [
        "build_pilot_explorer_data.py report",
        "",
        f"Bundle: {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1e6:.2f} MB)",
        "",
        "Records per key:",
    ]
    lines += [f"  {k}: {len(v)}" for k, v in bundle.items() if isinstance(v, list)]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
