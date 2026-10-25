"""
Utility functions for LLM search auditing.
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

#: Timestamp appended to downloaded filenames, e.g. "2026-10-05_134501".
#: Its ISO order means sorting filenames also sorts downloads by time.
TIMESTAMP_FORMAT = "%Y-%m-%d_%H%M%S"

#: Kilometers in one international mile (exact by definition). Distances are
#: computed in kilometers and reported in both units.
KM_PER_MILE = 1.609344

#: How every pilot-4cities message begins: "I live in <city>, <ST>. ...". The
#: city is matched greedily, so names with periods (St. Paul) stay whole.
CITY_MESSAGE_PATTERN = re.compile(
    r"^I live in (?P<city>.+), (?P<state_abbr>[A-Z]{2})\. "
)

#: A URL that starts with a scheme, e.g. "https://". Only a scheme at the very
#: start counts, so "a.org/x?u=https://b.org" is a URL without one.
SCHEME_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)

#: The domain extractor every function here uses. Splitting a host into
#: subdomain, name, and public suffix ("portal" + "ct" + "gov", or "" + "bbc" +
#: "co.uk") needs the Public Suffix List. By default tldextract downloads the
#: current list and caches it per machine, so results could differ across
#: machines and over time. With suffix_list_urls=() it never downloads and
#: uses the copy bundled with the installed tldextract, which uv.lock pins.
TLD_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=())


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    console_output: Optional[bool] = None,
    append_mode: bool = False,
) -> logging.Logger:
    """
    Set up logging configuration with explicit output destination requirements.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file. If provided, logs will be written to file.
        console_output: Whether to output logs to console/stdout. Must be explicitly set.
        append_mode: Whether to append to existing log file (True) or overwrite (False)

    Returns:
        Configured logger instance

    Raises:
        ValueError: If neither console_output nor log_file destination is clearly specified
    """
    # Require explicit specification of output destination
    if console_output is None and log_file is None:
        raise ValueError(
            "Must specify logging destination: either set console_output=True/False "
            "or provide log_file path, or both"
        )

    # Default console_output to False if only log_file is provided
    if console_output is None and log_file is not None:
        console_output = False

    # Require at least one output destination
    if not console_output and log_file is None:
        raise ValueError(
            "Must specify at least one logging destination: "
            "either console_output=True or provide log_file path"
        )

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper()))

    # Clear existing handlers to avoid duplicates
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Add console handler if requested
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # Add file handler if log_file is specified
    if log_file is not None:
        # Ensure the directory exists
        log_dir = os.path.dirname(os.path.abspath(log_file))
        os.makedirs(log_dir, exist_ok=True)

        # Use append mode if requested
        file_mode = "a" if append_mode else "w"
        file_handler = logging.FileHandler(log_file, mode=file_mode)
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def extract_domain(url: str) -> Optional[str]:
    """
    Extract base domain from URL using tldextract (without subdomains).

    Parameters
    ----------
    url : str
        The URL to extract domain from

    Returns
    -------
    str or None
        The extracted domain (e.g., 'example.com') or None if extraction fails
    """
    try:
        extracted = TLD_EXTRACTOR(url)
        # Combine domain and suffix (e.g., 'example' + 'co.uk' = 'example.co.uk')
        if extracted.domain and extracted.suffix:
            return f"{extracted.domain}.{extracted.suffix}".lower()
        elif extracted.domain:
            return extracted.domain.lower()
        return None
    except Exception:
        return None


def normalize_url(url: str) -> Optional[str]:
    """
    Return a normalized form of a URL, for matching the same page across sources.

    The same page is often written several ways: OpenAI appends
    ``?utm_source=openai``, one source writes ``www.`` and another does not,
    and a website named in text has no scheme at all. Normalizing removes
    those differences so the forms match. The verbatim URL should always be
    kept beside this one.

    Parameters
    ----------
    url : str or None
        A URL, or a web address without a scheme (e.g. "ineedana.com/us"),
        which is read as https. None or NaN returns None.

    Returns
    -------
    str or None
        The URL with an https scheme, a lowercase host without "www.", no
        ``utm_*`` query parameters, no fragment, and no trailing slash on the
        path. Path and remaining query keep their case and order. None if the
        URL is empty or has no host.
    """
    # Missing values from a pandas column arrive as NaN, a float.
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    if not SCHEME_PATTERN.match(url):
        url = "https://" + url
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    # Drop "www." only when it is a subdomain ("www.a.org"), not the name
    # itself ("www.com").
    if host.startswith("www.") and "." in host[len("www.") :].strip("."):
        host = host[len("www.") :]
    # A web host has at least one dot inside it ("a.org"; not "www." or "").
    if "." not in host.strip("."):
        return None
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ]
    )
    return urlunsplit(("https", host, parts.path.rstrip("/"), query, ""))


def parse_message_location(message: str) -> Optional[Dict[str, str]]:
    """
    Return the city a pilot-4cities message names, with its location slug.

    Parameters
    ----------
    message : str
        A message of the form "I live in <city>, <ST>. ...", e.g. "I live in
        St. Paul, MN. Where can I get an abortion near me? ...".

    Returns
    -------
    dict or None
        {"city": "St. Paul", "state_abbr": "MN", "location": "st-paul-mn"};
        None if the message does not follow the pattern. location lowercases
        "<city> <ST>" and joins its letters and digits with hyphens, the form
        the first pilot's audit names used (e.g. "houston-tx").
    """
    match = CITY_MESSAGE_PATTERN.match(message)
    if match is None:
        return None
    city, state_abbr = match["city"], match["state_abbr"]
    location = re.sub(r"[^a-z0-9]+", "-", f"{city} {state_abbr}".lower()).strip("-")
    return {"city": city, "state_abbr": state_abbr, "location": location}


def load_jsonl(filepath: str) -> List[str]:
    """
    Load jsonl file contents into a list.

    Args:
        filepath: Path to the jsonl file

    Returns:
        List of strings, one per line
    """
    with open(filepath, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line]


def timestamped_path(directory, stem, suffix):
    """
    Return the path for a new download, stamped with the current local time.

    Parameters
    ----------
    directory : str or pathlib.Path
        Folder the file will be written to.
    stem : str
        Filename before the timestamp (e.g. "sub-est2025").
    suffix : str
        File extension, including the dot (e.g. ".csv").

    Returns
    -------
    pathlib.Path
        `<directory>/<stem>_<YYYY-MM-DD_HHMMSS><suffix>`.
    """
    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    return Path(directory) / f"{stem}_{timestamp}{suffix}"


def find_existing_downloads(directory, stem, suffix):
    """
    Return every earlier download of a file, whatever its timestamp.

    Download scripts use this to refuse to re-download a file that is already
    saved: the timestamp is ignored, so any earlier copy counts.

    Parameters
    ----------
    directory : str or pathlib.Path
        Folder the downloads are saved in.
    stem : str
        Filename before the timestamp (e.g. "sub-est2025").
    suffix : str
        File extension, including the dot (e.g. ".csv").

    Returns
    -------
    list of pathlib.Path
        Matching files, oldest first; empty if there are none (or the folder
        does not exist yet).
    """
    return sorted(Path(directory).glob(f"{stem}_*{suffix}"))


def latest_download(directory, stem, suffix):
    """
    Return the most recent download of a file.

    Parameters
    ----------
    directory : str or pathlib.Path
        Folder the downloads are saved in.
    stem : str
        Filename before the timestamp (e.g. "sub-est2025").
    suffix : str
        File extension, including the dot (e.g. ".csv").

    Returns
    -------
    pathlib.Path
        The matching file whose name sorts last, i.e. the newest timestamp.

    Raises
    ------
    FileNotFoundError
        If no matching file exists, so the download script has not been run.
    """
    downloads = find_existing_downloads(directory, stem, suffix)
    if not downloads:
        raise FileNotFoundError(
            f"No '{stem}_*{suffix}' file in {directory}. Run the download script first."
        )
    return downloads[-1]


def km_to_miles(km):
    """
    Convert kilometers to international miles.

    Parameters
    ----------
    km : float, numpy.ndarray, or pandas.Series
        Distance in kilometers; missing values stay missing.

    Returns
    -------
    float, numpy.ndarray, or pandas.Series
        The same distance in miles (km / KM_PER_MILE), unrounded.
    """
    return km / KM_PER_MILE
