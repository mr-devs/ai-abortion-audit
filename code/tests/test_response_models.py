"""
Unit tests for toolkit.response_models and toolkit.loading (audit-name parsing
and one-row-per-pair loading).

The raw payloads below are trimmed copies of the structure taxman saved in the
2026-10-04 pilot (data/raw/archive-taxman-0.1.1/); taxman 0.2.0 saves them
unchanged. The record envelope follows taxman 0.2.0. Everything is inline so
the tests do not depend on the data directory.

Run with: uv run pytest code/tests
"""

import json

import pytest

from toolkit.loading import NO_LOCATION, load_run_responses, parse_audit_name
from toolkit.response_models import (
    AnthropicResponse,
    GeminiResponse,
    OpenAIResponse,
    parse_record,
)


MESSAGE_ID = "2ebdff37-21ca-5927-8f87-d593b1ec0f4f"


def make_record(provider, raw, audit=None, status="ok", message_id=MESSAGE_ID):
    """Return a taxman 0.2.0 response record wrapping `raw`."""
    return {
        "schema_version": 1,
        "audit": audit or f"pilot-{provider}",
        "run_id": "20261023T101502-abc123",
        "message_id": message_id,
        "message": "Is abortion legal?",
        "repeat": 2,
        "provider": provider,
        "model": "some-model",
        "requested_at": "2026-10-23T10:15:02.123456-07:00",
        "received_at": "2026-10-23T10:15:12.039812-07:00",
        "latency_ms": 9916,
        "status": status,
        "error": None if status == "ok" else "APITimeoutError: Request timed out.",
        "attempts": 1,
        "raw": raw if raw is not None else {},
    }


ANTHROPIC_RAW = {
    "content": [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "Let me look that up.", "citations": None},
        {
            "type": "server_tool_use",
            "id": "code_1",
            "name": "code_execution",
            "input": {"code": "search()"},
        },
        {
            "type": "server_tool_use",
            "id": "ws_1",
            "name": "web_search",
            "input": {"query": "abortion law texas"},
            "caller": {"tool_id": "code_1", "type": "code_execution_20260120"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "ws_1",
            "content": [
                {
                    "type": "web_search_result",
                    "url": "https://a.org/x",
                    "title": "A",
                    "page_age": "2 days ago",
                    "encrypted_content": "e",
                },
                {
                    "type": "web_search_result",
                    "url": "https://b.org/y",
                    "title": "B",
                    "page_age": None,
                    "encrypted_content": "e",
                },
            ],
        },
        {
            "type": "code_execution_tool_result",
            "tool_use_id": "code_1",
            "content": {
                "type": "encrypted_code_execution_result",
                "encrypted_stdout": "zzz",
                "stderr": "",
                "return_code": 0,
                "content": [],
            },
        },
        {"type": "text", "text": "Abortion is ", "citations": []},
        {
            "type": "text",
            "text": "banned in Texas.",
            "citations": [
                {
                    "type": "web_search_result_location",
                    "url": "https://a.org/x",
                    "title": "A",
                    "cited_text": "banned",
                }
            ],
        },
    ],
    "stop_reason": "end_turn",
    "stop_details": None,
    "usage": {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_creation": {"ephemeral_5m_input_tokens": 0},
        "service_tier": "standard",
        "server_tool_use": {"web_search_requests": 1},
    },
}

OPENAI_RAW = {
    "status": "completed",
    "incomplete_details": None,
    "output": [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "q1",
                "queries": ["q1", "q2"],
                "sources": [
                    {"type": "url", "url": "https://a.org"},
                    {"type": "url", "url": "https://b.org"},
                ],
            },
        },
        {
            "type": "web_search_call",
            "id": "ws_2",
            "status": "completed",
            "action": {"type": "open_page", "url": "https://a.org/page"},
        },
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "Yes, in Oregon.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://a.org/?utm_source=openai",
                            "title": "A",
                            "start_index": 0,
                            "end_index": 15,
                        }
                    ],
                }
            ],
        },
    ],
    "usage": {
        "input_tokens": 50,
        "output_tokens": 10,
        "input_tokens_details": {"cached_tokens": 5},
    },
    "tool_usage": {"web_search": {"num_requests": 1}},
}

GEMINI_RAW = {
    "status": "completed",
    "steps": [
        {"type": "thought", "signature": "sig"},
        {
            "type": "google_search_call",
            "id": "call_1",
            "arguments": {"queries": ["abortion portland"]},
            "search_type": "web_search",
        },
        {
            "type": "google_search_result",
            "call_id": "call_1",
            "is_error": False,
            "result": [{"search_suggestions": "<html>"}],
        },
        {
            "type": "model_output",
            "content": [
                {
                    "type": "text",
                    "text": "Clinics exist in Portland.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://redir/1",
                            "title": "oregon.gov",
                            "start_index": 0,
                            "end_index": 26,
                        },
                        {
                            "type": "url_citation",
                            "url": "https://redir/2",
                            "title": "ohsu.edu",
                            "start_index": 0,
                            "end_index": 26,
                        },
                        {
                            "type": "url_citation",
                            "url": "https://redir/1",
                            "title": "oregon.gov",
                            "start_index": 0,
                            "end_index": 26,
                        },
                    ],
                }
            ],
        },
    ],
    "usage": {
        "total_tokens": 300,
        "total_input_tokens": 8,
        "input_tokens_by_modality": [{"modality": "text", "tokens": 8}],
    },
}


def test_parse_record_dispatches_by_provider():
    assert isinstance(
        parse_record(make_record("anthropic", ANTHROPIC_RAW)), AnthropicResponse
    )
    assert isinstance(parse_record(make_record("openai", OPENAI_RAW)), OpenAIResponse)
    assert isinstance(parse_record(make_record("gemini", GEMINI_RAW)), GeminiResponse)
    with pytest.raises(ValueError):
        parse_record(make_record("grok", {}))


def test_provider_mismatch_raises():
    with pytest.raises(ValueError):
        OpenAIResponse(make_record("gemini", GEMINI_RAW))


def test_metadata_and_response_id():
    response = parse_record(make_record("openai", OPENAI_RAW))
    meta = response.get_metadata()
    assert meta["response_id"] == (
        f"pilot-openai__20261023T101502-abc123__{MESSAGE_ID}__r2"
    )
    assert meta["repeat"] == 2
    assert meta["error"] is None


def test_failed_record_returns_empty_results():
    response = parse_record(make_record("anthropic", None, status="error"))
    assert response.get_text() is None
    assert response.get_text_citations() == []
    assert response.get_tool_calls() == []
    assert response.get_tool_citations() == []
    assert response.get_token_usage() == []
    assert response.get_metadata()["error"] == "APITimeoutError: Request timed out."


def test_load_run_responses_keeps_final_row_per_pair(tmp_path):
    # A resumed run appends a new row for each failed pair: "a" failed and
    # then succeeded, "b" succeeded at once, "c" failed in both collects.
    rows = [
        make_record("openai", None, status="error", message_id="a"),
        make_record("openai", OPENAI_RAW, message_id="b"),
        make_record("openai", None, status="error", message_id="c"),
        make_record("openai", OPENAI_RAW, message_id="a"),
        make_record("openai", None, status="error", message_id="c"),
    ]
    rows[-1]["error"] = "RateLimitError: second failure"
    (tmp_path / "responses.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    responses = load_run_responses({"run_dir": tmp_path})
    assert [(r.record["message_id"], r.record["status"]) for r in responses] == [
        ("a", "ok"),
        ("b", "ok"),
        ("c", "error"),
    ]
    assert responses[2].record["error"] == "RateLimitError: second failure"


def test_anthropic_extraction():
    response = parse_record(make_record("anthropic", ANTHROPIC_RAW))
    # Adjacent text blocks join directly; tool blocks separate turns.
    assert response.get_text() == "Let me look that up.\n\nAbortion is banned in Texas."

    citations = response.get_text_citations()
    assert [c["cited_text"] for c in citations] == ["banned"]

    calls = response.get_tool_calls()
    assert [c["tool_type"] for c in calls] == ["code_execution", "web_search"]
    code, search = calls
    assert code["encrypted"] is True and code["stdout"] is None
    assert code["return_code"] == 0
    assert search["caller_tool_id"] == "code_1"
    assert search["search_queries"] == ["abortion law texas"]

    tool_citations = response.get_tool_citations()
    assert [c["index"] for c in tool_citations] == [0, 1]
    assert {c["tool_id"] for c in tool_citations} == {"ws_1"}

    usage = {u["token_type"]: u["value"] for u in response.get_token_usage()}
    assert usage["cache_creation.ephemeral_5m_input_tokens"] == 0.0
    assert usage["server_tool_use.web_search_requests"] == 1.0
    assert "service_tier" not in usage  # strings are skipped
    assert response.get_stop_info()["stop_reason"] == "end_turn"


def test_openai_extraction():
    response = parse_record(make_record("openai", OPENAI_RAW))
    assert response.get_text() == "Yes, in Oregon."

    (citation,) = response.get_text_citations()
    assert citation["url"] == "https://a.org/?utm_source=openai"  # verbatim
    assert (citation["start_index"], citation["end_index"]) == (0, 15)

    search, open_page = response.get_tool_calls()
    assert search["tool_type"] == "web_search.search"
    assert search["search_queries"] == ["q1", "q2"]
    assert open_page["tool_type"] == "web_search.open_page"
    assert open_page["url"] == "https://a.org/page"
    assert open_page["search_queries"] is None

    assert [c["url"] for c in response.get_tool_citations()] == [
        "https://a.org",
        "https://b.org",
    ]
    usage = {u["token_type"] for u in response.get_token_usage()}
    assert "tool_usage.web_search.num_requests" in usage


def test_gemini_extraction():
    response = parse_record(make_record("gemini", GEMINI_RAW))
    assert response.get_text() == "Clinics exist in Portland."
    assert len(response.get_text_citations()) == 3
    # Redirect URLs are deduplicated in first-seen order for the resolver.
    assert response.get_cited_redirect_urls() == ["https://redir/1", "https://redir/2"]

    (call,) = response.get_tool_calls()
    assert call["tool_type"] == "google_search"
    assert call["search_queries"] == ["abortion portland"]
    assert call["status"] is None
    assert response.get_tool_citations() == []

    usage = {u["token_type"] for u in response.get_token_usage()}
    assert usage == {"total_tokens", "total_input_tokens"}  # lists skipped


@pytest.mark.parametrize(
    "audit, provider, expected",
    [
        ("pilot-openai", "openai", {"study": "pilot", "location": NO_LOCATION}),
        (
            "pilot-gemini-houston-tx",
            "gemini",
            {"study": "pilot", "location": "houston-tx"},
        ),
        (
            "main-study-anthropic-portland-or",
            "anthropic",
            {"study": "main-study", "location": "portland-or"},
        ),
    ],
)
def test_parse_audit_name(audit, provider, expected):
    assert parse_audit_name(audit, provider) == expected


@pytest.mark.parametrize(
    "audit, provider",
    [("openai-pilot", "openai"), ("pilot-openaix", "openai"), ("pilot", "openai")],
)
def test_parse_audit_name_rejects_unexpected_names(audit, provider):
    with pytest.raises(ValueError):
        parse_audit_name(audit, provider)


def test_anthropic_citation_offsets_are_the_cited_block():
    response = parse_record(make_record("anthropic", ANTHROPIC_RAW))
    text = response.get_text()
    (citation,) = response.get_text_citations()
    # Claude cites whole text blocks, so the span is the cited block.
    assert text[citation["start_index"] : citation["end_index"]] == "banned in Texas."


def test_anthropic_malformed_direct_search_is_an_error():
    # Copied from pilot-4cities: a direct call that nests the query under
    # "params", which the API rejects.
    raw = {
        "content": [
            {
                "type": "server_tool_use",
                "id": "ws_bad",
                "name": "web_search",
                "input": {"params": {"query": "Granite OR to Walla Walla WA distance"}},
                "caller": None,
            },
            {
                "type": "web_search_tool_result",
                "tool_use_id": "ws_bad",
                "content": {
                    "type": "web_search_tool_result_error",
                    "error_code": "invalid_tool_input",
                },
                "caller": {"type": "direct"},
            },
            {"type": "text", "text": "Here is what I found.", "citations": None},
        ]
    }
    response = parse_record(make_record("anthropic", raw))
    (call,) = response.get_tool_calls()
    assert call["search_queries"] == ["Granite OR to Walla Walla WA distance"]
    assert call["status"] == "error"
    assert call["error_code"] == "invalid_tool_input"
    assert response.get_tool_citations() == []

    # A successful search has no status or error code.
    for call in parse_record(make_record("anthropic", ANTHROPIC_RAW)).get_tool_calls():
        assert call["status"] is None and call["error_code"] is None


def test_gemini_byte_offsets_become_character_offsets():
    # Gemini counts UTF-8 bytes: "’" is one character but three bytes, so
    # every offset after it is two bytes ahead of the character position.
    text = "Planned Parenthood’s clinic is open. Call today."
    cited = "Call today."
    byte_start = len(text.encode("utf-8")) - len(cited.encode("utf-8"))
    raw = {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://redir/1",
                                "title": "a.org",
                                "start_index": byte_start,
                                "end_index": len(text.encode("utf-8")),
                            }
                        ],
                    }
                ],
            }
        ]
    }
    (citation,) = parse_record(make_record("gemini", raw)).get_text_citations()
    assert citation["start_index"] == byte_start - 2
    assert text[citation["start_index"] : citation["end_index"]] == cited


def test_anthropic_error_without_a_code_is_still_an_error():
    raw = {
        "content": [
            {"type": "server_tool_use", "id": "ws_1", "name": "web_search", "input": {"query": "q"}},
            {
                "type": "web_search_tool_result",
                "tool_use_id": "ws_1",
                "content": {"type": "web_search_tool_result_error"},
            },
        ]
    }
    (call,) = parse_record(make_record("anthropic", raw)).get_tool_calls()
    assert call["status"] == "error"
    assert call["error_code"] is None


def test_gemini_bad_offsets_raise_but_do_not_block_url_resolution():
    raw = {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": "abc’def",  # 7 characters, 9 bytes
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://redir/1",
                                "title": "a.org",
                                "start_index": 0,
                                "end_index": 100,  # past the end of the text
                            }
                        ],
                    }
                ],
            }
        ]
    }
    response = parse_record(make_record("gemini", raw))
    with pytest.raises(ValueError, match="outside"):
        response.get_text_citations()
    # The resolver reads the URLs without the offsets.
    assert response.get_cited_redirect_urls() == ["https://redir/1"]
