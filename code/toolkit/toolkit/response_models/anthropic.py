"""
Data model for Anthropic (Messages API) taxman response records.

With the newer web search tool versions, Claude runs web searches from inside
a code-execution container: `server_tool_use` blocks record each web_search /
code_execution invocation (a search's `caller` names the code_execution call
that launched it), `web_search_tool_result` blocks carry the returned results
(plaintext url/title/page_age alongside encrypted content), and
`code_execution_tool_result` blocks carry each execution's outcome. Text
blocks carry a `citations` array. A citation belongs to a whole text block,
not to a passage inside it, so a citation's offsets are its block's span in
the response text. In pilot-4cities only responses whose searches were
called directly (not from code execution) have citations.
"""

from typing import Any, Dict, List, Optional, Tuple

from .base import BaseProviderResponse


class AnthropicResponse(BaseProviderResponse):
    """Data model for one Anthropic taxman response record."""

    PROVIDER = "anthropic"

    def _content_blocks(self, block_type: str) -> List[Dict[str, Any]]:
        """Return content blocks of one type, in response order."""
        return [b for b in self.raw.get("content", []) if b.get("type") == block_type]

    def _text_layout(self) -> Tuple[str, Dict[int, Tuple[int, int]]]:
        """
        Return the response text and where each text block sits in it.

        ADJACENT text blocks are contiguous segments of one message (the API
        splits them around citation boundaries), so they are joined without a
        separator. Text blocks separated by tool blocks are distinct turns
        (e.g. a pre-search preamble, then the final answer), so those groups
        are joined with a blank line to avoid gluing turns mid-sentence.

        Returns
        -------
        tuple of (str, dict)
            The response text, and {content index: (start, end)} giving each
            non-empty text block's character span in it.
        """
        groups: List[List[Tuple[int, str]]] = []  # runs of adjacent text blocks
        current: List[Tuple[int, str]] = []
        for i, block in enumerate(self.raw.get("content", [])):
            if block.get("type") == "text":
                current.append((i, block.get("text", "")))
            elif current:
                groups.append(current)
                current = []
        if current:
            groups.append(current)

        text, group_starts = self._join_text_parts(
            ["".join(t for _, t in group) for group in groups]
        )
        spans: Dict[int, Tuple[int, int]] = {}
        for group, position in zip(groups, group_starts):
            if position is None:
                continue  # the whole group was empty and is not in the text
            for i, block_text in group:
                spans[i] = (position, position + len(block_text))
                position += len(block_text)
        return text, spans

    def get_text(self) -> Optional[str]:
        """
        Return the response text: all text blocks concatenated in order (see
        _text_layout for how blocks and turns are joined).
        """
        text, _ = self._text_layout()
        return text or None

    def get_text_citations(self) -> List[Dict[str, Any]]:
        """
        Return one row per citation attached to a text block.

        Returns
        -------
        list of dict
            Zero-indexed rows: index, url (verbatim), title, cited_text (the
            source passage the citation quotes), start_index, end_index (the
            character span of the cited text block in get_text()).
        """
        _, spans = self._text_layout()
        rows: List[Dict[str, Any]] = []
        for i, block in enumerate(self.raw.get("content", [])):
            if block.get("type") != "text":
                continue
            start, end = spans.get(i, (None, None))
            for citation in block.get("citations") or []:
                rows.append(
                    {
                        "index": len(rows),
                        "url": citation.get("url"),
                        "title": citation.get("title"),
                        "cited_text": citation.get("cited_text"),
                        "start_index": start,
                        "end_index": end,
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
            Zero-indexed rows: index, tool_type, tool_id, status ("error" when
            the call's result is an error, else None; Anthropic reports no
            status of its own), error_code (the result's error code, e.g.
            "invalid_tool_input"), search_queries ([query] for web_search),
            code (for code_execution), caller_tool_id (the code_execution call
            that launched a web_search), and the code-execution outcome
            columns return_code, stdout, stderr, encrypted, abort_reason
            (None for web searches).
        """
        outcomes = self._code_execution_outcomes()
        errors = self._tool_error_codes()
        rows: List[Dict[str, Any]] = []
        for block in self._content_blocks("server_tool_use"):
            tool_input = block.get("input") or {}
            # A few direct calls nest the query as {"params": {"query": ...}};
            # the API rejects them (invalid_tool_input), but the query is
            # still what Claude tried to search.
            query = tool_input.get("query")
            if query is None:
                query = (tool_input.get("params") or {}).get("query")
            outcome = outcomes.get(block.get("id"), {})
            # An error result may lack an error_code, so test membership.
            errored = block.get("id") in errors
            rows.append(
                {
                    "index": len(rows),
                    "tool_type": block.get("name"),
                    "tool_id": block.get("id"),
                    "status": "error" if errored else None,
                    "error_code": errors.get(block.get("id")),
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

    def _tool_error_codes(self) -> Dict[str, str]:
        """
        Return the error code of every tool call whose result is an error,
        keyed by its tool_use_id (None when the error reports no code).

        An error result's `content` is one object such as
        {"type": "web_search_tool_result_error", "error_code": ...} instead
        of a list of results.
        """
        errors: Dict[str, str] = {}
        for block in self.raw.get("content", []):
            content = block.get("content")
            if block.get("type", "").endswith("_tool_result") and isinstance(
                content, dict
            ):
                if content.get("type", "").endswith("_error"):
                    errors[block.get("tool_use_id")] = content.get("error_code")
        return errors

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
