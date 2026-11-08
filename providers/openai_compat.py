"""OpenAI-compatible chat and embeddings client.

Works unchanged against Groq and OpenRouter, both of which expose the
OpenAI request/response shape under their own base URL.

Standard library only -- no new dependencies are added to the environment.
Keys are read from the environment at call time, never at import time, and
are never included in log lines or exception messages.

Transport notes learned from live testing (2026-11-07):

* A User-Agent header is mandatory. Python's default ``Python-urllib/x.y``
  is rejected by Groq's edge with ``HTTP 403 / error code: 1010`` before
  the request ever reaches the API. Any other UA string is accepted.
* ``max_tokens`` must be sent explicitly. OpenAI-compatible servers default
  it to the model's maximum, which a metered account cannot pay for and
  which therefore fails with ``HTTP 402`` even for a trivial request.
* Rate limiting returns ``HTTP 429`` with a ``retry-after`` header.
* An exhausted metered account returns ``HTTP 402`` and states the token
  budget it can actually afford, which the client uses to retry smaller.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

#: Sent on every request. Without it Groq's edge blocks the client with
#: HTTP 403 / error code 1010 before the request reaches the API.
USER_AGENT = "ViralClipsAI/1.0 (chopify adapter)"

#: Default completion budget for a chat request. Upstream's reranker answers
#: with one small JSON object per candidate and Chopify sends at most 50.
DEFAULT_MAX_TOKENS = 2048

#: Floor for a completion budget. Below this the provider rejects it.
MIN_MAX_TOKENS = 16


class ProviderError(RuntimeError):
    """Raised when a provider request fails.

    The message never contains the API key. ``kind`` classifies the failure
    so callers can react differently to an auth problem, a rate limit, a
    timeout and a server error.

    kind: "auth" | "rate_limit" | "quota" | "timeout" | "server"
          | "network" | "bad_request" | "response" | "unknown"
    """

    def __init__(self, message, kind="unknown", status=None, affordable=None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.affordable = affordable


def _kind_for_status(code):
    if code in (401, 403):
        return "auth"
    if code == 402:
        return "quota"
    if code == 429:
        return "rate_limit"
    if code == 400:
        return "bad_request"
    if code is not None and 500 <= code < 600:
        return "server"
    return "unknown"


def _error_body(exc, limit=400):
    """Read an error response body without ever echoing request headers."""
    try:
        return exc.read().decode("utf-8", "replace")[:limit]
    except Exception:  # noqa: BLE001 - diagnostics only
        return ""


def _affordable_tokens(body):
    """Extract the token budget a metered account says it can afford.

    OpenRouter's HTTP 402 body reads: "... You requested up to 16384 tokens,
    but can only afford 190." Returns that number, or None. The count is
    not followed by a unit word in the real message, so the pattern must
    not require one.
    """
    match = re.search(r"can only afford (\d+)", body or "")
    return int(match.group(1)) if match else None


def _retry_delay(exc, attempt, backoff):
    """Seconds to wait before the next attempt."""
    header = exc.headers.get("retry-after") if exc.headers else None
    if header:
        try:
            return min(60.0, max(0.0, float(header)))
        except (TypeError, ValueError):
            pass
    return min(30.0, backoff ** attempt)


def _post_json(url, payload, api_key, timeout, max_attempts=3, backoff=2.0):
    """POST JSON and return the decoded JSON response.

    Raises ProviderError with a key-free message on any failure. Retries
    rate limits (429) and server errors (5xx) with a bounded backoff,
    honouring the ``retry-after`` header when the server sends one.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
    }
    data = json.dumps(payload).encode("utf-8")
    last_error = None

    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code = exc.code
            body = _error_body(exc)
            kind = _kind_for_status(code)

            if kind in ("rate_limit", "server") and attempt < max_attempts:
                wait = _retry_delay(exc, attempt, backoff)
                last_error = ProviderError(
                    f"HTTP {code} from {url}", kind=kind, status=code)
                print(f"provider HTTP {code}, retrying in {wait:.1f}s "
                      f"(attempt {attempt}/{max_attempts})", flush=True)
                time.sleep(wait)
                continue

            if kind == "quota":
                affordable = _affordable_tokens(body)
                raise ProviderError(
                    f"HTTP 402 from {url} (quota exhausted)",
                    kind="quota", status=402, affordable=affordable) from exc

            raise ProviderError(
                f"HTTP {code} from {url} ({kind})",
                kind=kind, status=code) from exc
        except TimeoutError as exc:
            raise ProviderError(
                f"Request to {url} timed out after {timeout}s",
                kind="timeout") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderError(
                    f"Request to {url} timed out after {timeout}s",
                    kind="timeout") from exc
            raise ProviderError(
                f"Could not reach {url} ({exc.reason})",
                kind="network") from exc
        except (OSError, ValueError) as exc:
            raise ProviderError(
                f"Request to {url} failed ({type(exc).__name__})",
                kind="network") from exc

    raise last_error or ProviderError(f"Request to {url} failed", kind="unknown")


#: Ceiling for an automatic budget escalation. A reasoning model that
#: burns its whole allowance on reasoning needs room to answer, but the
#: escalation must stay bounded so a pathological model cannot make the
#: client request an arbitrarily large completion.
MAX_ESCALATED_MAX_TOKENS = 8192

#: How many times a chat request may escalate its own token budget when
#: the provider returns an empty answer because reasoning consumed it.
MAX_BUDGET_ESCALATIONS = 3


def _extract_choice(response):
    """Return (content, finish_reason, usable) from an OpenAI-compatible
    response.

    ``usable`` is False only when the response carries no choice at all --
    a different failure from a choice whose content is null.
    """
    try:
        choice = response["choices"][0]
    except (KeyError, IndexError, TypeError):
        return None, None, False
    if not isinstance(choice, dict):
        return None, None, False
    finish = choice.get("finish_reason")
    message = choice.get("message")
    if not isinstance(message, dict):
        return None, finish, False
    content = message.get("content")
    return content, finish, True


def chat(messages, model, base_url, api_key, timeout=120, temperature=0.2,
         max_tokens=None):
    """Send a chat completion and return the assistant message content.

    Returns a string. Raises ProviderError on failure.

    Two budget problems are handled here rather than by the caller:

    * An exhausted metered account returns HTTP 402 and states the token
      budget it can afford, so the request is retried once, smaller.
    * A reasoning model can spend the entire ``max_tokens`` allowance on
      reasoning and return an empty content with ``finish_reason``
      ``"length"``. The request is then retried with a larger allowance,
      because the model did not fail -- it ran out of room.
    """
    if max_tokens is None:
        max_tokens = int(os.environ.get("VIRALCLIPS_LLM_MAX_TOKENS",
                                         DEFAULT_MAX_TOKENS))
    url = base_url.rstrip("/") + "/chat/completions"
    budget = max(MIN_MAX_TOKENS, int(max_tokens))
    attempted_affordable = False
    escalations = 0

    while True:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": budget,
        }
        try:
            response = _post_json(url, payload, api_key, timeout)
        except ProviderError as exc:
            # The provider told us what it can afford. Retry once, smaller.
            if (exc.kind == "quota" and exc.affordable
                    and not attempted_affordable):
                attempted_affordable = True
                budget = max(MIN_MAX_TOKENS, int(exc.affordable))
                print(f"provider quota exhausted, retrying with "
                      f"max_tokens={budget}", flush=True)
                continue
            raise

        content, finish, usable = _extract_choice(response)
        if not usable:
            raise ProviderError(
                "Chat response had no usable message content",
                kind="response")

        # A reasoning model that exhausted the allowance returns an empty
        # content. Escalate the budget rather than reporting a failure.
        if not content and finish == "length" and escalations < MAX_BUDGET_ESCALATIONS:
            escalations += 1
            larger = min(MAX_ESCALATED_MAX_TOKENS, budget * 4)
            if larger > budget:
                budget = larger
                print(f"provider returned no content (reasoning consumed the "
                      f"token budget), retrying with max_tokens={budget}",
                      flush=True)
                continue

        # A provider may return a null content -- some reasoning models
        # spend the whole token budget on reasoning and leave content empty.
        # Normalise it to a string so callers never see None.
        if content is None:
            return ""
        if not isinstance(content, str):
            return json.dumps(content, ensure_ascii=False)
        return content


def embed(texts, model, base_url, api_key, timeout=180):
    """Return one embedding vector per input text.

    Returns a list of lists of floats. Raises ProviderError on failure.
    """
    payload = {"model": model, "input": list(texts)}
    response = _post_json(
        base_url.rstrip("/") + "/embeddings",
        payload, api_key, timeout)
    try:
        data = response["data"]
        vectors = [item["embedding"] for item in data]
    except (KeyError, TypeError) as exc:
        raise ProviderError(
            "Embedding response had no usable data", kind="response") from exc
    if len(vectors) != len(texts):
        raise ProviderError(
            f"Embedding response returned {len(vectors)} vectors for "
            f"{len(texts)} inputs", kind="response")
    return vectors


# --- Provider registry -----------------------------------------------------
# Base URLs are the documented OpenAI-compatible endpoints. Model ids are
# overridable via environment variables so a provider can change its
# catalogue without a code edit.
#
# Model ids were checked against the providers' own listings on 2026-11-07
# (Groq: console.groq.com/docs/models and /docs/deprecations). Groq's former
# default llama-3.3-70b-versatile reached its shutdown date on 2026-08-16,
# so the default is now openai/gpt-oss-120b -- the replacement Groq
# recommends for it.

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "chat_model_env": "VIRALCLIPS_GROQ_MODEL",
        "chat_model_default": "openai/gpt-oss-120b",
        "embed_model_env": "VIRALCLIPS_GROQ_EMBED_MODEL",
        "embed_model_default": None,
        # Groq's published catalogue contains no embedding model, so the
        # embedding seam must fall through to a provider that has one.
        "supports_embeddings": False,
        "supports_chat": True,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "chat_model_env": "VIRALCLIPS_OPENROUTER_MODEL",
        "chat_model_default": "meta-llama/llama-3.3-70b-instruct",
        "embed_model_env": "VIRALCLIPS_OPENROUTER_EMBED_MODEL",
        "embed_model_default": "openai/text-embedding-3-small",
        "supports_embeddings": True,
        "supports_chat": True,
    },
}

#: Kept for backwards compatibility with the original single-variable
#: convention. A generic value applies to whichever provider is active.
LEGACY_CHAT_MODEL_ENV = "VIRALCLIPS_LLM_MODEL"
LEGACY_EMBED_MODEL_ENV = "VIRALCLIPS_EMBED_MODEL"


def provider_config(name):
    """Return the config for a provider name.

    Raises ProviderError for an unknown provider.
    """
    config = PROVIDERS.get(name)
    if not config:
        known = ", ".join(sorted(PROVIDERS))
        raise ProviderError(f"Unknown provider '{name}'. Known: {known}")
    return config


def chat_model_for(config):
    """Resolve the chat model id for a provider.

    Precedence: the provider-specific variable, then the legacy generic
    variable, then the provider default.
    """
    for env in (config["chat_model_env"], LEGACY_CHAT_MODEL_ENV):
        value = os.environ.get(env, "").strip()
        if value:
            return value
    return config["chat_model_default"]


def embed_model_for(config):
    """Resolve the embedding model id for a provider, or None.

    Precedence: the provider-specific variable, then the legacy generic
    variable, then the provider default. None means the provider has no
    embedding model and the caller should try the next provider.
    """
    for env in (config["embed_model_env"], LEGACY_EMBED_MODEL_ENV):
        value = os.environ.get(env, "").strip()
        if value:
            return value
    return config.get("embed_model_default")


def resolve(name):
    """Resolve a provider name into a usable config.

    Reads the API key at call time -- from the environment first, then the
    local credential file (see ``providers.credentials``). Returns None when
    the key is absent so callers can fall back rather than crash.
    """
    config = dict(provider_config(name))
    api_key = os.environ.get(config["key_env"], "").strip()
    if not api_key:
        try:
            from . import credentials
            api_key = (credentials.get(config["key_env"], "") or "").strip()
        except Exception:  # noqa: BLE001 - credential lookup must never raise
            api_key = ""
    if not api_key:
        return None
    config["api_key"] = api_key
    config["name"] = name
    return config
