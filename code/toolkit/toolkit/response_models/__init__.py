"""
Per-provider data models for taxman response records.
"""

from typing import Any, Dict

from .anthropic import AnthropicResponse
from .base import BaseProviderResponse
from .gemini import GeminiResponse
from .openai import OpenAIResponse

#: Maps a taxman provider name to its response model class.
RESPONSE_MODELS = {
    "anthropic": AnthropicResponse,
    "gemini": GeminiResponse,
    "openai": OpenAIResponse,
}


def parse_record(record: Dict[str, Any]) -> BaseProviderResponse:
    """
    Return the response model for one taxman record, chosen by its provider.

    Parameters
    ----------
    record : dict
        One parsed line of a taxman `responses.jsonl` file.

    Returns
    -------
    BaseProviderResponse
        The provider-specific response model.

    Raises
    ------
    ValueError
        If the record's provider has no response model.
    """
    provider = record.get("provider")
    if provider not in RESPONSE_MODELS:
        raise ValueError(f"No response model for provider {provider!r}")
    return RESPONSE_MODELS[provider](record)
