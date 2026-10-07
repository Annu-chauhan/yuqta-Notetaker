from fastapi import HTTPException

from app.core.config import Settings, get_settings
from app.plugins.llm.base import LLMError, LLMProvider
from app.plugins.llm.mock import MockLLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockLLMProvider()
    if settings.llm_provider == "anthropic":
        from app.plugins.llm.anthropic_provider import AnthropicLLMProvider

        if "/" in settings.llm_model:
            raise LLMError(
                f"LLM_MODEL={settings.llm_model!r} is an OpenRouter id. Use LLM_PROVIDER=openrouter, "
                "or set LLM_MODEL to a Claude model (e.g. claude-opus-5-5) for LLM_PROVIDER=anthropic."
            )

        return AnthropicLLMProvider(api_key=settings.llm_api_key, model=settings.llm_model, effort=settings.llm_effort)
    if settings.llm_provider == "openrouter":
        from app.plugins.llm.openrouter_provider import OpenRouterLLMProvider

        return OpenRouterLLMProvider(api_key=settings.llm_api_key, model=settings.llm_model)
    raise LLMError(f"Unknown LLM_PROVIDER={settings.llm_provider}. Use 'mock', 'anthropic' or 'openrouter'.")


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency; override in tests to inject a fake provider."""
    try:
        return build_llm_provider(get_settings())
    except LLMError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
