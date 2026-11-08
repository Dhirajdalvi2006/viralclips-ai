"""External AI provider support for Chopify.

Importing this package does not change any upstream behaviour. Call
``adapter.install()`` to route Chopify's LLM rerank and embedding calls
through an OpenAI-compatible provider (Groq, OpenRouter).

Usage:

    from providers import adapter
    adapter.install()          # no-op when no provider is configured
    print(adapter.status())    # key-free configuration summary
"""
from . import adapter, credentials, openai_compat

__all__ = ["adapter", "credentials", "openai_compat"]
