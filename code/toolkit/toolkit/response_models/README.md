# response_models

Data models for taxman response records: one class per provider, each built from one parsed line of a `responses.jsonl` file.
Metadata comes from taxman's shared record fields; text, citations, tool calls, token usage, and stop info come from the provider's `raw` payload.
All citation getters return zero-indexed rows with verbatim URLs and no domain extraction (domains are added by [`code/cleaning/clean_citations.py`](../../../cleaning/clean_citations.py)).

## Contents

- [`__init__.py`](__init__.py): Exports the model classes, `RESPONSE_MODELS` (provider name to class), and `parse_record()`, which picks the class from a record's provider.
- [`base.py`](base.py): `BaseProviderResponse`: the `response_id` key, taxman metadata, the extraction API each provider implements, and the usage-flattening helper; failed requests (`raw` is null) return empty results.
- [`anthropic.py`](anthropic.py): `AnthropicResponse`: text blocks (turns separated), text-block citations (empty in the pilot), web_search/code_execution tool calls with caller links and code-execution outcomes, and web-search result URLs as tool citations.
- [`openai.py`](openai.py): `OpenAIResponse`: output_text and its `url_citation` annotations, `web_search_call` items (search and open_page actions), search-action sources as tool citations, and `usage` plus `tool_usage`.
- [`gemini.py`](gemini.py): `GeminiResponse` (Interactions API): model_output text and its `url_citation` annotations (Google redirect URLs), `google_search_call` steps, and `get_cited_redirect_urls()` for the URL resolver; no tool citations.
