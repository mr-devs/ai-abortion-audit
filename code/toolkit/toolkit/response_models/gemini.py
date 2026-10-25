"""
Data model for Gemini (Interactions API) taxman response records.

The payload's `steps` list holds `thought` steps (signatures only, no
readable text), `google_search_call` / `google_search_result` pairs, and a
`model_output` step whose `content[]` text items carry the answer and its
`url_citation` annotations. Annotation URLs are Google redirect links
(vertexaisearch.cloud.google.com/grounding-api-redirect/...); they are kept
verbatim here and resolved by code/data_collection/resolve_gemini_urls.py.
Annotation offsets count UTF-8 bytes, not characters; they are converted to
character offsets here, so they line up with the text like the other
providers' offsets.
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
        text, _ = self._join_text_parts([i.get("text", "") for i in self._output_texts()])
        return text or None

    @staticmethod
    def _char_offset(text: str, byte_offset: Optional[int]) -> Optional[int]:
        """
        Convert a UTF-8 byte offset into `text` to a character offset.

        Gemini counts bytes, so after a character such as "’" (three bytes)
        its offsets run ahead of the character positions. Raises ValueError
        if the offset is outside the text, and UnicodeDecodeError if it falls
        inside a character; either would mean the offsets are not byte
        offsets into this text after all. (Slicing alone would hide an
        out-of-range offset by clamping it to the end.)
        """
        if byte_offset is None:
            return None
        encoded = text.encode("utf-8")
        if not 0 <= byte_offset <= len(encoded):
            raise ValueError(
                f"Byte offset {byte_offset} is outside a {len(encoded)}-byte text"
            )
        return len(encoded[:byte_offset].decode("utf-8"))

    def get_text_citations(self) -> List[Dict[str, Any]]:
        """
        Return one row per `url_citation` annotation on the answer text.

        Returns
        -------
        list of dict
            Zero-indexed rows: index, url (verbatim Google redirect URL),
            title (the cited site's domain, as Gemini reports it),
            start_index, end_index (character offsets of the cited span in
            get_text(), converted from Gemini's byte offsets).
        """
        items = self._output_texts()
        _, item_starts = self._join_text_parts([i.get("text", "") for i in items])
        rows: List[Dict[str, Any]] = []
        for item, item_start in zip(items, item_starts):
            text = item.get("text", "")
            for annotation in item.get("annotations") or []:
                if annotation.get("type") != "url_citation":
                    continue
                start = self._char_offset(text, annotation.get("start_index"))
                end = self._char_offset(text, annotation.get("end_index"))
                if item_start is not None:
                    start = None if start is None else item_start + start
                    end = None if end is None else item_start + end
                rows.append(
                    {
                        "index": len(rows),
                        "url": annotation.get("url"),
                        "title": annotation.get("title"),
                        "start_index": start,
                        "end_index": end,
                    }
                )
        return rows

    def get_cited_redirect_urls(self) -> List[str]:
        """
        Return the distinct cited redirect URLs, in first-seen order.

        Used by the URL resolver. It reads the annotations directly rather
        than through get_text_citations, so a bad offset cannot stop URL
        resolution. dict.fromkeys deduplicates while keeping order.
        """
        urls = [
            annotation.get("url")
            for item in self._output_texts()
            for annotation in item.get("annotations") or []
            if annotation.get("type") == "url_citation" and annotation.get("url")
        ]
        return list(dict.fromkeys(urls))

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """
        Return one row per `google_search_call` step.

        Returns
        -------
        list of dict
            Zero-indexed rows: index, tool_type ("google_search"), tool_id,
            status (None, or "error" when the matching search result is
            flagged as an error), error_code (always None; Gemini reports
            none), search_queries.
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
                    "error_code": None,
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
