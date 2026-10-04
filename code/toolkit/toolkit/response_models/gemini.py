"""
Data model for Gemini (Interactions API) taxman response records.

The payload's `steps` list holds `thought` steps (signatures only, no
readable text), `google_search_call` / `google_search_result` pairs, and a
`model_output` step whose `content[]` text items carry the answer and its
`url_citation` annotations. Annotation URLs are Google redirect links
(vertexaisearch.cloud.google.com/grounding-api-redirect/...); they are kept
verbatim here and resolved by code/data_collection/resolve_gemini_urls.py.
Search results carry only Google's rendered search-suggestion HTML, so
Gemini contributes no tool citations.
"""

from typing import Any, Dict, List, Optional

from .base import BaseProviderResponse


class GeminiResponse(BaseProviderResponse):
    """Data model for one Gemini taxman response record."""

    PROVIDER = "gemini"

    def _steps(self, step_type: str) -> List[Dict[str, Any]]:
        """Return steps of one type, in response order."""
        return [s for s in self.raw.get("steps", []) if s.get("type") == step_type]

    def _output_texts(self) -> List[Dict[str, Any]]:
        """Return every text content item of every model_output step."""
        return [
            item
            for step in self._steps("model_output")
            for item in step.get("content") or []
            if item.get("type") == "text"
        ]

    def get_text(self) -> Optional[str]:
        """
        Return the answer text: every model_output text item, joined with a
        blank line (the pilot has exactly one item per response).
        """
        text = "\n\n".join(
            i.get("text", "") for i in self._output_texts() if i.get("text")
        )
        return text or None

    def get_text_citations(self) -> List[Dict[str, Any]]:
        """
        Return one row per `url_citation` annotation on the answer text.

        Returns
        -------
        list of dict
            Zero-indexed rows: index, url (verbatim Google redirect URL),
            title (the cited site's domain, as Gemini reports it),
            start_index, end_index (offsets into the text item).
        """
        rows: List[Dict[str, Any]] = []
        for item in self._output_texts():
            for annotation in item.get("annotations") or []:
                if annotation.get("type") != "url_citation":
                    continue
                rows.append(
                    {
                        "index": len(rows),
                        "url": annotation.get("url"),
                        "title": annotation.get("title"),
                        "start_index": annotation.get("start_index"),
                        "end_index": annotation.get("end_index"),
                    }
                )
        return rows

    def get_cited_redirect_urls(self) -> List[str]:
        """
        Return the distinct cited redirect URLs, in first-seen order.

        Used by the URL resolver; dict.fromkeys deduplicates while keeping
        order.
        """
        urls = [row["url"] for row in self.get_text_citations() if row["url"]]
        return list(dict.fromkeys(urls))

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """
        Return one row per `google_search_call` step.

        Returns
        -------
        list of dict
            Zero-indexed rows: index, tool_type ("google_search"), tool_id,
            status (None, or "error" when the matching search result is
            flagged as an error), search_queries.
        """
        errored = {
            step.get("call_id")
            for step in self._steps("google_search_result")
            if step.get("is_error")
        }
        rows: List[Dict[str, Any]] = []
        for step in self._steps("google_search_call"):
            rows.append(
                {
                    "index": len(rows),
                    "tool_type": "google_search",
                    "tool_id": step.get("id"),
                    "status": "error" if step.get("id") in errored else None,
                    "search_queries": (step.get("arguments") or {}).get("queries"),
                    "code": None,
                    "caller_tool_id": None,
                    "url": None,
                }
            )
        return rows

    def get_tool_citations(self) -> List[Dict[str, Any]]:
        """Return no rows: Gemini search results expose no source URLs."""
        return []

    def get_token_usage(self) -> List[Dict[str, Any]]:
        """
        Return the flattened numeric `usage` payload as long rows (the
        per-modality and per-invocation lists are skipped; see the base
        class).
        """
        return self._flatten_numeric_usage(self.raw.get("usage") or {})

    def get_stop_info(self) -> Dict[str, Optional[str]]:
        """Return the interaction status; Gemini reports no further detail."""
        return {"stop_reason": self.raw.get("status"), "stop_detail": None}
