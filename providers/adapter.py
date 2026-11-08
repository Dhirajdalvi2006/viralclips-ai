"""Adapter that gives the upstream Chopify AI layer an external provider.

Chopify's AI layer is Ollama-hardcoded at two seams:

  Seam A  score_clips._ollama_chat  -> POST {host}/api/chat
  Seam B  semantic.ollama_embed     -> POST {HOST}/api/embed

This module exposes ``chat()`` and ``embed()`` with the shapes upstream
already expects, then installs itself over those two functions so the
upstream checkout stays unmodified.

Provider selection is by environment variable:

  VIRALCLIPS_LLM_PROVIDER = groq | openrouter | none   (default: none)

With the provider set to ``none`` the upstream Ollama behaviour is left
completely untouched -- no network call, no key lookup.

The fallback chain is:

  Groq (primary) -> OpenRouter (optional fallback) -> local heuristic scorer

The heuristic scorer is upstream's guaranteed floor: it needs no network, so
an expired quota or a revoked key degrades output quality rather than
breaking the run.
"""
from __future__ import annotations

import json
import os
import re

from . import openai_compat

PROVIDER_ENV = "VIRALCLIPS_LLM_PROVIDER"
FALLBACK_ENV = "VIRALCLIPS_LLM_FALLBACK"

_installed = False


def configured_provider():
    """Return the primary provider config, or None.

    None means: provider not configured, key missing, or provider set to
    'none'. Callers treat None as "use upstream behaviour".
    """
    name = os.environ.get(PROVIDER_ENV, "").strip().lower()
    if not name or name == "none":
        return None
    return openai_compat.resolve(name)


def fallback_provider():
    """Return the optional fallback provider config, or None."""
    name = os.environ.get(FALLBACK_ENV, "").strip().lower()
    if not name or name == "none":
        return None
    return openai_compat.resolve(name)


def _chat_via(provider, model, messages, timeout):
    """One chat attempt against a provider. Raises ProviderError on failure."""
    return openai_compat.chat(
        messages=messages,
        model=model,
        base_url=provider["base_url"],
        api_key=provider["api_key"],
        timeout=timeout)


def chat(model, messages, timeout=120):
    """Chat completion with an upstream-compatible return value.

    Mirrors ``score_clips._ollama_chat``: returns the parsed JSON array the
    upstream reranker expects, or ``[]`` when no provider is configured or
    every attempt fails. Never raises -- upstream treats an exception here
    as "provider unavailable" and falls back to heuristic scores, so raising
    would be equivalent but noisier.
    """
    providers = [p for p in (configured_provider(), fallback_provider()) if p]
    if not providers:
        return []

    # The upstream reranker asks for a JSON array of adjustments. Ask for the
    # same shape so the response can be parsed the same way.
    system = messages[0]["content"] if messages else ""
    user = messages[1]["content"] if len(messages) > 1 else ""
    payload_messages = [
        {"role": "system",
         "content": system + "\nRespond with a JSON array only, no prose."},
        {"role": "user", "content": user},
    ]

    last_error = None
    for provider in providers:
        # Upstream passes the --llm argument through as the model name. That
        # argument normally names an Ollama model ("qwen2.5:7b"), which no
        # OpenAI-compatible provider accepts, so it is only honoured when it
        # looks like a provider model id (no Ollama-style ":tag" suffix).
        # The provider's own model variable always wins over both.
        chat_model = openai_compat.chat_model_for(provider)
        explicit = os.environ.get(provider["chat_model_env"], "").strip()
        if explicit:
            chat_model = explicit
        elif model and ":" not in model:
            chat_model = model
        try:
            content = _chat_via(provider, chat_model, payload_messages, timeout)
        except openai_compat.ProviderError as exc:
            last_error = exc
            print(f"{provider['name']} unavailable ({exc}) -> trying next provider",
                  flush=True)
            continue
        match = re.search(r"\[.*\]", content or "", re.S)
        if not match:
            last_error = openai_compat.ProviderError(
                "Chat response contained no JSON array")
            print(f"{provider['name']} returned no JSON array -> trying next provider",
                  flush=True)
            continue
        try:
            return json.loads(match.group(0))
        except ValueError as exc:
            last_error = openai_compat.ProviderError("Chat response was not valid JSON")
            print(f"{provider['name']} returned invalid JSON -> trying next provider",
                  flush=True)
            continue

    if last_error is not None:
        print(f"All AI providers unavailable ({last_error}) -> deterministic scores",
              flush=True)
    return []


def embed_model_ids():
    """Return (api_model_id, cache_namespace) for the active provider.

    ``api_model_id`` is what the provider's API expects.
    ``cache_namespace`` is provider-namespaced so upstream's on-disk
    embedding cache key differs per provider -- otherwise vectors produced
    by one provider could be silently reused for another.

    Returns (None, None) when no configured provider offers embeddings.
    """
    providers = [p for p in (configured_provider(), fallback_provider()) if p]
    if not providers:
        return None, None
    for provider in providers:
        api_model = openai_compat.embed_model_for(provider)
        if api_model:
            return api_model, f"{provider['name']}/{api_model}"
    return None, None


def embed(texts, model, timeout=180):
    """Embeddings with an upstream-compatible return value.

    Mirrors ``semantic.ollama_embed``: returns a list of vectors, or raises
    ValueError when no provider is available (upstream's semantic.search
    catches this and reports setup instructions).

    Providers whose catalogue has no embedding model are skipped rather
    than being called and failing.
    """
    providers = [p for p in (configured_provider(), fallback_provider()) if p]
    if not providers:
        raise ValueError(
            "No external embedding provider configured. Set "
            f"{PROVIDER_ENV}=groq (and GROQ_API_KEY), or use --search "
            "for keyword search instead.")

    last_error = None
    for provider in providers:
        embed_model = openai_compat.embed_model_for(provider)
        if not embed_model:
            last_error = openai_compat.ProviderError(
                f"{provider['name']} has no embedding model")
            print(f"{provider['name']} has no embedding model "
                  "-> trying next provider", flush=True)
            continue
        try:
            vectors = openai_compat.embed(
                texts=texts,
                model=embed_model,
                base_url=provider["base_url"],
                api_key=provider["api_key"],
                timeout=timeout)
        except openai_compat.ProviderError as exc:
            last_error = exc
            print(f"{provider['name']} embeddings unavailable ({exc}) "
                  "-> trying next provider", flush=True)
            continue
        return vectors

    raise ValueError(
        f"All embedding providers unavailable ({last_error})")


def install():
    """Install the adapter over the upstream Ollama seams.

    Idempotent. Returns True when the adapter is active, False when no
    provider is configured (upstream behaviour is left untouched).
    """
    global _installed
    if _installed:
        return True
    if configured_provider() is None:
        return False

    import score_clips
    import semantic

    def _patched_chat(model, host, messages, timeout=120):
        # Signature matches upstream _ollama_chat(model, host, messages, timeout).
        # The host argument is ignored: the provider decides the endpoint.
        return chat(model, messages, timeout)

    score_clips._ollama_chat = _patched_chat

    def _patched_embed(texts, model):
        # Upstream signature: ollama_embed(texts, model) -> list of vectors.
        # The passed model is ignored: the provider's configured api model
        # id is what the endpoint actually accepts.
        return embed(texts, model)

    semantic.ollama_embed = _patched_embed

    _original_search = semantic.search

    def _patched_search(sentences, query, model=None, cache_dir=None,
                        embed=None):
        # Upstream keys the on-disk embedding cache on the model name
        # and passes that same name to the embed function. Override it
        # with a provider-namespaced id: the patched embed ignores the
        # model argument anyway (the provider decides the api model),
        # and namespacing guarantees vectors from one provider can never
        # be silently reused for another.
        #
        # The namespace is resolved at call time rather than at install
        # time, because which provider actually serves the embedding
        # depends on the chain order and on which providers are usable.
        _api_model, namespace = embed_model_ids()
        if not namespace:
            return _original_search(
                sentences, query, model=model,
                cache_dir=cache_dir, embed=embed)
        return _original_search(
            sentences, query,
            model=namespace,
            cache_dir=cache_dir, embed=embed)

    semantic.search = _patched_search

    _installed = True
    return True


def status():
    """Return a key-free summary of the provider configuration."""
    primary = configured_provider()
    fallback = fallback_provider()
    return {
        "provider_env": PROVIDER_ENV,
        "primary": None if primary is None else {
            "name": primary["name"],
            "base_url": primary["base_url"],
            "key_present": True,
            "chat_model": openai_compat.chat_model_for(primary),
            "embed_model": openai_compat.embed_model_for(primary),
            "supports_embeddings": primary.get("supports_embeddings", True),
        },
        "fallback": None if fallback is None else {
            "name": fallback["name"],
            "base_url": fallback["base_url"],
            "key_present": True,
            "chat_model": openai_compat.chat_model_for(fallback),
            "embed_model": openai_compat.embed_model_for(fallback),
            "supports_embeddings": fallback.get("supports_embeddings", True),
        },
    }
