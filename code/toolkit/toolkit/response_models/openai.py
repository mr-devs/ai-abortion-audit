"""
Data model for OpenAI (Responses API) taxman response records.

The payload's `output` list holds reasoning items, `web_search_call` items
(one per search action: `search` with its queries and returned `sources`, or
`open_page` with the opened URL), and one `message` item whose `output_text`
content carries the answer and its `url_citation` annotations.
"""

from typing import Any, Dict, List, Optional

from .base import BaseProviderResponse


class OpenAIResponse(BaseProviderResponse):
    """Data model for one OpenAI taxman response record."""

    PROVIDER = "openai"

    def _output_items(self, item_type: str) -> List[Dict[str, Any]]:
        """Return output items of one type, in response order."""
        return [i for i in self.raw.get("output", []) if i.get("type") == item_type]

    def _output_texts(self) -> List[Dict[str, Any]]:
        """Return every `output_text` content part of every message item."""
        return [
            part
            for message in self._output_items("message")
            for part in message.get("content") or []
            if part.get("type") == "output_text"
        ]

    def get_text(self) -> Optional[str]:
        """
        Return the answer text: every output_text part, joined with a blank
        line (the pilot has exactly one message with one part per response).
        """
        text = "\n\n".join(
            p.get("text", "") for p in self._output_texts() if p.get("text")
        )
        return text or None

    def get_text_citations(self) -> List[Dict[str, Any]]:
        """
        Return one row per `url_citation` annotation on the answer text.

        Returns
        -------
        list of dict
            Zero-indexed rows: index, url (verbatim), title, start_index,
            end_index (character offsets into the output_text part).
        """
        rows: List[Dict[str, Any]] = []
        for part in self._output_texts():
            for annotation in part.get("annotations") or []:
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

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """
        Return one row per `web_search_call` item.

        Returns
        -------
        list of dict
            Zero-indexed rows: index, tool_type ("web_search.<action type>",
            e.g. "web_search.search" or "web_search.open_page"), tool_id,
            status, search_queries (the action's queries, for searches), and
            url (the opened page, for open_page).
        """
        rows: List[Dict[str, Any]] = []
        for item in self._output_items("web_search_call"):
            action = item.get("action") or {}
            queries = action.get("queries")
            if queries is None and action.get("query") is not None:
                queries = [action["query"]]
            rows.append(
                {
                    "index": len(rows),
                    "tool_type": f"web_search.{action.get('type')}",
                    "tool_id": item.get("id"),
                    "status": item.get("status"),
                    "search_queries": queries,
                    "code": None,
                    "caller_tool_id": None,
                    "url": action.get("url"),
                }
            )
        return rows

    def get_tool_citations(self) -> List[Dict[str, Any]]:
        """
        Return one row per source a search action returned
        (`web_search_call.action.sources[]`).

        Returns
        -------
        list of dict
            Zero-indexed rows: index, url (verbatim), tool_id (the
            web_search_call that returned it). OpenAI reports no title.
        """
        rows: List[Dict[str, Any]] = []
        for item in self._output_items("web_search_call"):
            for source in (item.get("action") or {}).get("sources") or []:
                rows.append(
                    {
                        "index": len(rows),
                        "url": source.get("url"),
                        "title": None,
                        "page_age": None,
                        "tool_id": item.get("id"),
                    }
                )
        return rows

    def get_token_usage(self) -> List[Dict[str, Any]]:
        """
        Return the flattened numeric `usage` payload plus the `tool_usage`
        payload (prefixed "tool_usage.") as long rows.
        """
        rows = self._flatten_numeric_usage(self.raw.get("usage") or {})
        rows += self._flatten_numeric_usage(
            self.raw.get("tool_usage") or {}, prefix="tool_usage."
        )
        return rows

    def get_stop_info(self) -> Dict[str, Optional[str]]:
        """Return the response status and incomplete_details (as JSON)."""
        return {
            "stop_reason": self.raw.get("status"),
            "stop_detail": self._json_or_none(self.raw.get("incomplete_details")),
        }
