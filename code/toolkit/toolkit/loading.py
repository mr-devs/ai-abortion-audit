"""
Locate and load taxman audit runs and their responses.

Runs are discovered through taxman's `manifest.json` files (one per run
directory), never by globbing for response files, so every loaded response
belongs to a run whose status taxman recorded.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .response_models import BaseProviderResponse, parse_record

#: Written by code/data_collection/resolve_gemini_urls.py into each Gemini
#: run directory, next to taxman's responses.jsonl.
RESOLVED_URLS_FILENAME = "resolved_urls.jsonl"

#: Value of the `location` column for audits whose name has no location part.
NO_LOCATION = "none"

logger = logging.getLogger(__name__)


def parse_audit_name(audit: str, provider: str) -> Dict[str, str]:
    """
    Split an audit name into its study and location parts.

    Audit names follow "<study>-<provider>[-<location>]", e.g.
    "pilot-openai" (study "pilot", no location) or "pilot-gemini-houston-tx"
    (study "pilot", location "houston-tx").

    Parameters
    ----------
    audit : str
        The audit name, as recorded by taxman.
    provider : str
        The audit's provider, which must appear in the name.

    Returns
    -------
    dict
        {"study": str, "location": str}; location is NO_LOCATION when the
        name has no location part.

    Raises
    ------
    ValueError
        If the name does not contain "-<provider>" in the expected place, so
        a new naming scheme is handled deliberately rather than misparsed.
    """
    marker = f"-{provider}"
    study, sep, rest = audit.partition(marker)
    if not sep or not study or (rest and not rest.startswith("-")):
        raise ValueError(
            f"Audit name {audit!r} does not follow '<study>-{provider}[-<location>]'"
        )
    return {"study": study, "location": rest[1:] if rest else NO_LOCATION}


def discover_runs(
    audits_dir: Path, audit_prefix: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Return the manifest of every complete taxman run under `audits_dir`.

    Runs whose manifest status is not "complete" (running, interrupted,
    failed, stopped_early) are skipped with a warning, since their response
    files may be partial.

    Parameters
    ----------
    audits_dir : Path
        taxman's data directory (`paths.data` in taxman.yaml), holding
        <audit>/<run_id>/manifest.json.
    audit_prefix : str, optional
        Only include audits whose name starts with this prefix (e.g. "pilot-").

    Returns
    -------
    list of dict
        One manifest dict per run, sorted by (audit, run_id), each with an
        added "run_dir" key (Path to the run directory).
    """
    runs = []
    for manifest_path in sorted(Path(audits_dir).glob("*/*/manifest.json")):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        if audit_prefix and not manifest["audit"].startswith(audit_prefix):
            continue
        if manifest["status"] != "complete":
            logger.warning(
                f"Skipping {manifest['audit']} run {manifest['run_id']}: "
                f"status is {manifest['status']!r}, not 'complete'"
            )
            continue
        manifest["run_dir"] = manifest_path.parent
        runs.append(manifest)
    return runs


def load_run_responses(
    run: Dict[str, Any], filename: str = "responses.jsonl"
) -> List[BaseProviderResponse]:
    """
    Return the response models for every line of one run's responses file.

    Parameters
    ----------
    run : dict
        A manifest dict from `discover_runs`.
    filename : str
        The responses filename (taxman's `output.filename` default).

    Returns
    -------
    list of BaseProviderResponse
        One provider-specific response model per line, in file order.
    """
    responses = []
    with open(Path(run["run_dir"]) / filename, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                responses.append(parse_record(json.loads(line)))
    return responses


def load_all_responses(
    audits_dir: Path, audit_prefix: Optional[str] = None
) -> List[BaseProviderResponse]:
    """
    Return the response models of every complete run under `audits_dir`.

    Parameters
    ----------
    audits_dir : Path
        taxman's data directory.
    audit_prefix : str, optional
        Only include audits whose name starts with this prefix.

    Returns
    -------
    list of BaseProviderResponse
        Responses of all runs, ordered by (audit, run_id), then file order.
    """
    responses = []
    for run in discover_runs(audits_dir, audit_prefix):
        responses.extend(load_run_responses(run))
    return responses


def load_resolved_urls(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    Return a Gemini run's resolved redirect URLs, keyed by response_id.

    Parameters
    ----------
    run_dir : Path
        The run directory holding RESOLVED_URLS_FILENAME.

    Returns
    -------
    dict
        {response_id: {"resolved_urls": {redirect: url}, "unresolved_urls":
        [redirect, ...]}}; empty if the file does not exist yet.
    """
    path = Path(run_dir) / RESOLVED_URLS_FILENAME
    if not path.exists():
        return {}
    resolved = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                resolved[row["response_id"]] = row
    return resolved
