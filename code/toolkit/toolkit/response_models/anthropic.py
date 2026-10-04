"""
Data model for Anthropic (Messages API) taxman response records.

With the newer web search tool versions, Claude runs web searches from inside
a code-execution container: `server_tool_use` blocks record each web_search /
code_execution invocation (a search's `caller` names the code_execution call
that launched it), `web_search_tool_result` blocks carry the returned results
(plaintext url/title/page_age alongside encrypted content), and
`code_execution_tool_result` blocks carry each execution's outcome. Text
blocks carry a `citations` array, which was empty for every block in the
2026-10-04 pilot; it is still extracted per the API schema.
"""

from typing import Any, Dict, List, Optional

from .base import BaseProviderResponse


class AnthropicResponse(BaseProviderResponse):
    """Data model for one Anthropic taxman response record."""

    PROVIDER = "anthropic"

    def _content_blocks(self, block_type: str) -> List[Dict[str, Any]]:
        """Return content blocks of one type, in response order."""
        return [b for b in self.raw.get("content", []) if b.get("type") == block_type]

    def get_text(self) -> Optional[str]:
        """
        Return the response text: all text blocks concatenated in order.

        ADJACENT text blocks are contiguous segments of one message (the API
        splits them around citation boundaries), so they are joined without a
        separator. Text blocks separated by tool blocks are distinct turns
        (e.g. a pre-search preamble, then the final answer), so those groups
        are joined with a blank line to avoid gluing turns mid-sentence.
        """
        groups: List[str] = []  # one entry per run of adjacent text blocks
        current: List[str] = []
        for block in self.raw.get("content", []):
            if block.get("type") == "text":
                current.append(block.get("text", ""))
            elif current:
                groups.append("".join(current))
                current = []
        if current:
            groups.append("".join(current))
        text = "\n\n".join(g for g in groups if g)
        return text or None

    def get_text_citations(self) -> List[Dict[str, Any]]:
        """
        Return one row per citation attached to a text block.

        Returns
        -------
        list of dict
            Zero-indexed rows: index, url (verbatim), title, cited_text.
        """
        rows: List[Dict[str, Any]] = []
        for block in self._content_blocks("text"):
            for citation in block.get("citations") or []:
                rows.append(
                    {
                        "index": len(rows),
                        "url": citation.get("url"),
                        "title": citation.get("title"),
                        "cited_text": citation.get("cited_text"),
                    }
                )
        return rows

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """
        Return one row per `server_tool_use` block (web_search or
        code_execution), joined with its code-execution outcome.

        Returns
        -------
        list of dict
            Zero-indexed rows: index, tool_type, tool_id, status (always None;
            Anthropic reports none), search_queries ([query] for web_search),
            code (for code_execution), caller_tool_id (the code_execution call
            that launched a web_search), and the code-execution outcome
            columns return_code, stdout, stderr, encrypted, abort_reason
            (None for web searches).
        """
        outcomes = self._code_execution_outcomes()
        rows: List[Dict[str, Any]] = []
        for block in self._content_blocks("server_tool_use"):
            tool_input = block.get("input") or {}
            query = tool_input.get("query")
            outcome = outcomes.get(block.get("id"), {})
            rows.append(
                {
                    "index": len(rows),
                    "tool_type": block.get("name"),
                    "tool_id": block.get("id"),
                    "status": None,
                    "search_queries": [query] if query is not None else None,
                    "code": tool_input.get("code"),
                    "caller_tool_id": (block.get("caller") or {}).get("tool_id"),
                    "url": None,
                    "return_code": outcome.get("return_code"),
                    "stdout": outcome.get("stdout"),
                    "stderr": outcome.get("stderr"),
                    "encrypted": outcome.get("encrypted"),
                    "abort_reason": outcome.get("abort_reason"),
                }
            )
        return rows

    def _code_execution_outcomes(self) -> Dict[str, Dict[str, Any]]:
        """
        Return each code execution's outcome, keyed by its tool_use_id.

        Most results that launch searches arrive as
        `encrypted_code_execution_result` (stdout encrypted, unreadable);
        `encrypted` is True for those and stdout is None.
        """
        outcomes: Dict[str, Dict[str, Any]] = {}
        for block in self._content_blocks("code_execution_tool_result"):
            content = block.get("content") or {}
            encrypted = content.get("type") == "encrypted_code_execution_result"
            outcomes[block.get("tool_use_id")] = {
                "return_code": content.get("return_code"),
                "stdout": None if encrypted else content.get("stdout"),
                "stderr": content.get("stderr"),
                "encrypted": encrypted,
                "abort_reason": content.get("abort_reason"),
            }
        return outcomes

    def get_tool_citations(self) -> List[Dict[str, Any]]:
        """
        Return one row per URL a web search returned
        (`web_search_tool_result` -> `content[]`).

        Returns
        -------
        list of dict
            Zero-indexed rows: index, url (verbatim), title, page_age,
            tool_id (the web_search invocation that returned the URL).
        """
        rows: List[Dict[str, Any]] = []
        for block in self._content_blocks("web_search_tool_result"):
            content = block.get("content")
            if not isinstance(content, list):
                continue  # error payloads are dicts; nothing to extract
            for item in content:
                rows.append(
                    {
                        "index": len(rows),
                        "url": item.get("url"),
                        "title": item.get("title"),
                        "page_age": item.get("page_age"),
                        "tool_id": block.get("tool_use_id"),
                    }
                )
        return rows

    def get_token_usage(self) -> List[Dict[str, Any]]:
        """Return the flattened numeric `usage` payload as long rows."""
        return self._flatten_numeric_usage(self.raw.get("usage") or {})

    def get_stop_info(self) -> Dict[str, Optional[str]]:
        """Return stop_reason and stop_details (as a JSON string)."""
        return {
            "stop_reason": self.raw.get("stop_reason"),
            "stop_detail": self._json_or_none(self.raw.get("stop_details")),
        }
