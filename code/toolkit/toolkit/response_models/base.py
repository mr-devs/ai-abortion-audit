"""
Shared base class for the provider response data models.

Every line of a taxman `responses.jsonl` file is one response record with the
same top-level fields for every provider (audit, run_id, message_id, repeat,
status, timestamps, ...) plus `raw`, the provider's verbatim API payload. All
metadata getters therefore live here, and each provider subclass implements
only the extraction of its own `raw` payload.
"""

import json
from typing import Any, Dict, List, Optional


class BaseProviderResponse:
    """
    Base data model for one taxman response record.

    Parameters
    ----------
    record : dict
        One parsed line of a taxman `responses.jsonl` file.

    Notes
    -----
    A record whose request failed (status "error") has `raw` set to None.
    Every extraction method then returns an empty result (None or []), so
    callers can process failed and successful records the same way.
    """

    #: Overridden by each subclass; validated against the record's provider.
    PROVIDER: Optional[str] = None

    def __init__(self, record: Dict[str, Any]):
        if "raw" not in record or "audit" not in record:
            raise ValueError("Record must be a taxman response record with 'raw'")
        if self.PROVIDER is not None and record.get("provider") != self.PROVIDER:
            raise ValueError(
                f"Record provider {record.get('provider')!r} does not match "
                f"{type(self).__name__} (expects {self.PROVIDER!r})"
            )
        self.record = record
        # Empty dict for failed requests so subclass lookups need no None checks.
        self.raw = record.get("raw") or {}

    @classmethod
    def from_json_line(cls, line: str) -> "BaseProviderResponse":
        """
        Construct a response model from one raw JSONL line.

        Parameters
        ----------
        line : str
            One line of a taxman `responses.jsonl` file.

        Returns
        -------
        BaseProviderResponse
            The constructed provider-specific response model.
        """
        return cls(json.loads(line))

    # ------------------------------------------------------------------
    # taxman record metadata (identical structure for every provider)
    # ------------------------------------------------------------------

    def get_response_id(self) -> str:
        """
        Return the unique key for this response.

        Format: "<audit>__<run_id>__<message_id>__r<repeat>". A taxman run is
        identified by (audit, run_id), and within a run each response by
        (message_id, repeat), so this string is unique across all audits.
        """
        r = self.record
        return f"{r['audit']}__{r['run_id']}__{r['message_id']}__r{r['repeat']}"

    def get_metadata(self) -> Dict[str, Any]:
        """
        Return the taxman record metadata as one flat dict (one metadata row).

        Returns
        -------
        dict
            Keys: response_id, audit, run_id, message_id, repeat, message,
            provider, model, requested_at, received_at, latency_ms, status,
            error, attempts, message_hash, system_prompt_hash.
        """
        r = self.record
        return {
            "response_id": self.get_response_id(),
            "audit": r.get("audit"),
            "run_id": r.get("run_id"),
            "message_id": r.get("message_id"),
            "repeat": r.get("repeat"),
            "message": r.get("message"),
            "provider": r.get("provider"),
            "model": r.get("model"),
            "requested_at": r.get("requested_at"),
            "received_at": r.get("received_at"),
            "latency_ms": r.get("latency_ms"),
            "status": r.get("status"),
            # taxman stores error details as a dict; keep it as a JSON string
            # so the column has one type.
            "error": json.dumps(r["error"]) if r.get("error") is not None else None,
            "attempts": r.get("attempts"),
            "message_hash": r.get("message_hash"),
            "system_prompt_hash": r.get("system_prompt_hash"),
        }

    # ------------------------------------------------------------------
    # Extraction API implemented by each provider subclass
    # ------------------------------------------------------------------

    def get_text(self) -> Optional[str]:
        """Return the final response text shown to a user (None if absent)."""
        raise NotImplementedError

    def get_text_citations(self) -> List[Dict[str, Any]]:
        """
        Return the citations attached to the response text a user sees.

        Returns
        -------
        list of dict
            Zero-indexed rows with at least: index, url (verbatim), title.
            Providers add start_index/end_index or cited_text where reported.
        """
        raise NotImplementedError

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """
        Return server-side tool invocations as ordered rows.

        Returns
        -------
        list of dict
            Zero-indexed rows with: index, tool_type, tool_id, status,
            search_queries (list of str or None), plus provider-specific
            keys (e.g. code, caller_tool_id, url).
        """
        raise NotImplementedError

    def get_tool_citations(self) -> List[Dict[str, Any]]:
        """
        Return URLs a search tool returned in the payload, whether or not
        the response cited them.

        Returns
        -------
        list of dict
            Zero-indexed rows with: index, url (verbatim), tool_id, plus
            provider-specific keys (e.g. title, page_age).
        """
        raise NotImplementedError

    def get_token_usage(self) -> List[Dict[str, Any]]:
        """
        Return token usage as long/tidy rows.

        Returns
        -------
        list of dict
            One dict per usage metric: {"token_type": str, "value": float}.
            Nested dicts are flattened with dot notation.
        """
        raise NotImplementedError

    def get_stop_info(self) -> Dict[str, Optional[str]]:
        """
        Return why/how the response ended.

        Returns
        -------
        dict
            {"stop_reason": str or None, "stop_detail": str or None};
            stop_detail is a JSON string when the API reports a structure.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared helpers for subclasses
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_numeric_usage(
        usage: Dict[str, Any], prefix: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Flatten a nested usage dict into long rows, keeping numeric values.

        Strings and lists are skipped: strings are labels (e.g. service tier),
        and the lists in these payloads (Gemini's per-modality breakdowns)
        repeat totals that are already reported as numbers.

        Parameters
        ----------
        usage : dict
            The provider's usage payload (possibly nested).
        prefix : str
            Dot-notation prefix accumulated during recursion.

        Returns
        -------
        list of dict
            Rows of {"token_type": str, "value": float}.
        """
        rows: List[Dict[str, Any]] = []
        for key, value in usage.items():
            name = f"{prefix}{key}"
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                rows.append({"token_type": name, "value": float(value)})
            elif isinstance(value, dict):
                rows.extend(
                    BaseProviderResponse._flatten_numeric_usage(value, f"{name}.")
                )
        return rows

    @staticmethod
    def _json_or_none(value: Any) -> Optional[str]:
        """Return `value` as a JSON string, or None when it is None."""
        return json.dumps(value) if value is not None else None
