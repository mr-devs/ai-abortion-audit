"""
Unit tests for toolkit.response_models and toolkit.loading.parse_audit_name.

The records below are trimmed copies of the structure taxman saved in the
2026-10-04 pilot (data/raw/audits/), kept inline so the tests do not depend
on the data directory.

Run with: uv run pytest code/tests
"""

import pytest

from toolkit.loading import NO_LOCATION, parse_audit_name
from toolkit.response_models import (
    AnthropicResponse,
    GeminiResponse,
    OpenAIResponse,
    parse_record,
)


def make_record(provider, raw, audit=None, status="ok"):
    """Return a taxman response record wrapping `raw`."""
    return {
        "schema_version": 1,
        "audit": audit or f"pilot-{provider}",
        "run_id": "20261004T201940Z-abc123",
        "message_id": "m0003",
        "message_hash": "sha256:x",
        "message": "Is abortion legal?",
        "repeat": 2,
        "system_prompt_hash": None,
        "provider": provider,
        "model": "some-model",
        "requested_at": "2026-10-04T20:19:49.209765Z",
        "received_at": "2026-10-04T20:19:59.126121Z",
        "latency_ms": 9916,
        "status": status,
        "error": None if status == "ok" else {"type": "Timeout"},
        "attempts": 1,
        "raw": raw,
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
    assert meta["response_id"] == "pilot-openai__20261004T201940Z-abc123__m0003__r2"
    assert meta["repeat"] == 2
    assert meta["error"] is None


def test_failed_record_returns_empty_results():
    response = parse_record(make_record("anthropic", None, status="error"))
    assert response.get_text() is None
    assert response.get_text_citations() == []
    assert response.get_tool_calls() == []
    assert response.get_tool_citations() == []
    assert response.get_token_usage() == []
    assert response.get_metadata()["error"] == '{"type": "Timeout"}'


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
