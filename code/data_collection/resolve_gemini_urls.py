"""
Purpose:
    Resolve the Google redirect URLs cited in every Gemini audit run's
    responses to the source URLs Google cited.

Notes:
    - Gemini's url_citation annotations cite Google redirect URLs
      (vertexaisearch.cloud.google.com/grounding-api-redirect/...), not the
      source URLs. This script collects the distinct redirect URLs in each
      response (via toolkit.response_models.GeminiResponse) and resolves each
      one to the URL Google cited.
    - FIRST HOP ONLY: each redirect URL gets a single HEAD request
      with allow_redirects=False, and the cited URL is read verbatim from the
      302 Location header. The cited site is never contacted, so there is no
      bot-detection/paywall exposure. Consequence: when a cited URL itself
      redirects further (moved page, http -> https), the recorded URL is the
      form Google cited, consistent with keeping URLs verbatim.
    - Transient failures (connection errors, timeouts, HTTP 4xx/5xx from
      Google) are retried with tenacity; a hard failure, or a response
      without a Location header, leaves the URL unresolved.
    - Responses are resolved in parallel on a thread pool of MAX_WORKERS
      workers, each reusing one keep-alive requests.Session. Each response's
      URLs are resolved one after another within its task. The output line
      order is therefore completion order; consumers join on response_id.
    - Idempotent: response_ids already in a run's resolved-URLs file are
      skipped, so re-running resolves only what is missing.
    - Runs are discovered through taxman's manifest.json files; only
      complete Gemini runs are processed (toolkit.loading.discover_runs).
    - No API key is needed: resolution is plain HTTP to Google's redirect
      endpoint.

Input:
    - data/raw/audits/<audit>/<run_id>/manifest.json and responses.jsonl:
      taxman output for each Gemini audit run.
    - --audit-prefix (optional): only process audits whose name starts with
      this prefix (e.g. "pilot-").

Output:
    - data/raw/audits/<audit>/<run_id>/resolved_urls.jsonl, one JSON line per
      response:
        - response_id (str): "<audit>__<run_id>__<message_id>__r<repeat>";
          join key to the cleaned tables.
        - message_id (str): taxman message id.
        - repeat (int): taxman repeat number (0-based).
        - resolved_urls (dict): {redirect_url: cited_url}, one entry per
          distinct cited redirect URL that resolved; empty when the response
          cites nothing.
        - unresolved_urls (list of str): distinct cited redirect URLs that
          could not be resolved after retries.
    - data/logs/resolve_gemini_urls/<yyyy-mm-dd>.log: run log (appended).

Author: Matthew DeVerna
"""

import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from toolkit.loading import RESOLVED_URLS_FILENAME, discover_runs, load_run_responses
from toolkit.utils import setup_logging

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
PROVIDER = "gemini"
AUDITS_DIR = Path("../../data/raw/audits")
LOG_DIR = Path("../../data/logs/resolve_gemini_urls")
REQUEST_TIMEOUT_SECONDS = 10  # per-request timeout
# Every request goes to Google's redirect endpoint only, so the limit is
# Google's per-IP tolerance. If many URLs come back unresolved, lower this.
MAX_WORKERS = 32

_THREAD_LOCAL = threading.local()


def parse_args():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        With attribute ``audit_prefix`` (str or None).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Resolve the Google redirect URLs cited in Gemini audit responses. "
            "Idempotent: already-resolved responses are skipped."
        )
    )
    parser.add_argument(
        "--audit-prefix",
        default=None,
        help="Only process audits whose name starts with this prefix.",
    )
    return parser.parse_args()


def _get_session():
    # One keep-alive Session per worker thread: requests.Session is not
    # guaranteed thread-safe, and a per-thread session still reuses the TLS
    # connection to Google's redirect endpoint across that thread's links.
    if getattr(_THREAD_LOCAL, "session", None) is None:
        _THREAD_LOCAL.session = requests.Session()
    return _THREAD_LOCAL.session


@retry(
    wait=wait_random_exponential(min=1, max=30),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(
        (requests.ConnectionError, requests.Timeout, requests.HTTPError)
    ),
    reraise=True,
)
def _first_hop(url):
    # raise_for_status turns 4xx/5xx from Google into retryable HTTPErrors.
    # A non-redirect success (no Location header) returns None.
    response = _get_session().head(
        url, allow_redirects=False, timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.headers.get("Location")


def resolve_redirect_url(url):
    """
    Return the redirect's target URL (the 302 Location header).

    Parameters
    ----------
    url : str
        A Google grounding redirect URL.

    Returns
    -------
    str or None
        The cited URL, or None if it could not be resolved after retries.
    """
    try:
        return _first_hop(url)
    except requests.RequestException:
        return None


def resolve_response_urls(redirect_urls):
    """
    Resolve one response's redirect URLs, one after another.

    Parameters
    ----------
    redirect_urls : list of str
        The response's distinct cited redirect URLs.

    Returns
    -------
    tuple of (dict, list)
        ``resolved_urls`` ({redirect_url: cited_url}) and ``unresolved_urls``
        (redirect URLs that failed after retries).
    """
    resolved_urls = {}
    unresolved_urls = []
    for url in redirect_urls:
        cited_url = resolve_redirect_url(url)
        if cited_url is None:
            unresolved_urls.append(url)
        else:
            resolved_urls[url] = cited_url
    return resolved_urls, unresolved_urls


def load_done_response_ids(resolved_path):
    """
    Return the response_ids already present in a resolved-URLs file.

    Parameters
    ----------
    resolved_path : Path
        Path to a run's resolved-URLs file.

    Returns
    -------
    set of str
        Empty when the file does not exist yet.
    """
    if not resolved_path.exists():
        return set()
    with open(resolved_path, "r", encoding="utf-8") as fh:
        return {json.loads(line)["response_id"] for line in fh if line.strip()}


def resolve_run(run, logger):
    """
    Resolve every not-yet-resolved response of one Gemini run.

    Parameters
    ----------
    run : dict
        A manifest dict from toolkit.loading.discover_runs.
    logger : logging.Logger
        Logger for progress reporting.
    """
    resolved_path = Path(run["run_dir"]) / RESOLVED_URLS_FILENAME
    done = load_done_response_ids(resolved_path)

    # Only (response, redirect URLs) is kept for the pending work.
    pending = []
    for response in load_run_responses(run):
        response_id = response.get_response_id()
        if response_id in done:
            continue
        done.add(response_id)  # guards against duplicate lines in the input
        pending.append((response, response.get_cited_redirect_urls()))

    logger.info(
        f"{run['audit']} run {run['run_id']}: {len(pending)} responses to resolve"
    )
    if not pending:
        return

    n_urls = 0
    n_failed = 0
    # Only this (main) thread writes the file; flushing each line means a
    # crash leaves only whole lines, so a re-run resumes cleanly.
    with (
        open(resolved_path, "a", encoding="utf-8") as out_fh,
        ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool,
    ):
        futures = {
            pool.submit(resolve_response_urls, urls): response
            for response, urls in pending
        }
        for future in as_completed(futures):
            response = futures[future]
            resolved_urls, unresolved_urls = future.result()
            n_urls += len(resolved_urls) + len(unresolved_urls)
            n_failed += len(unresolved_urls)
            for url in unresolved_urls:
                logger.warning(f"{response.get_response_id()}: could not resolve {url}")
            # One line per response, even when nothing was cited, so the
            # file mirrors the responses file and re-runs skip it.
            out_fh.write(
                json.dumps(
                    {
                        "response_id": response.get_response_id(),
                        "message_id": response.record["message_id"],
                        "repeat": response.record["repeat"],
                        "resolved_urls": resolved_urls,
                        "unresolved_urls": unresolved_urls,
                    }
                )
                + "\n"
            )
            out_fh.flush()

    logger.info(
        f"{run['audit']} run {run['run_id']}: resolved {n_urls - n_failed} of "
        f"{n_urls} redirect URLs ({n_failed} unresolved) -> {resolved_path}"
    )


def main():
    """
    Resolve cited redirect URLs for every complete Gemini audit run.
    """
    args = parse_args()

    log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    logger = setup_logging(
        log_level="INFO", log_file=str(log_file), console_output=True, append_mode=True
    )
    logger.info("Resolving Gemini redirect URLs")

    runs = [
        run
        for run in discover_runs(AUDITS_DIR, args.audit_prefix)
        if run["provider"] == PROVIDER
    ]
    logger.info(f"Found {len(runs)} complete Gemini runs")
    for run in runs:
        resolve_run(run, logger)
    logger.info("Done")


if __name__ == "__main__":
    main()
