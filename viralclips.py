#!/usr/bin/env python
"""ViralClipsAI launcher.

Runs the unmodified upstream Chopify CLI with the external AI provider
adapter installed.

Why a launcher rather than an edit to chopify.py: the upstream checkout is
kept pristine so `git pull` updates stay clean. This launcher installs the
adapter over the two upstream AI seams before handing control to Chopify.

Examples:

    # Local only -- no external provider, upstream heuristic scoring.
    python viralclips.py recording.mp4 --action prepare

    # Groq as the LLM reranker (key read from env or the credential file).
    set VIRALCLIPS_LLM_PROVIDER=groq
    python viralclips.py recording.mp4 --llm openai/gpt-oss-120b

    # Groq primary, OpenRouter fallback.
    set VIRALCLIPS_LLM_FALLBACK=openrouter

    # Show the resolved provider configuration (never prints keys).
    python viralclips.py --provider-status

    # Make one real authenticated request to each configured provider.
    python viralclips.py --provider-check
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _apply_application_defaults():
    """Apply the application's provider defaults to this process.

    The application (``viralclips_app.config``) mirrors
    ``VIRALCLIPS_AI_PROVIDER`` into the adapter's ``VIRALCLIPS_LLM_PROVIDER``
    and loads the credential file. The command line is a second entry
    point into the same application, so it must resolve the provider the
    same way -- otherwise ``--provider-check`` reports "not configured"
    while the running application is happily scoring clips with Groq.
    """
    try:
        from viralclips_app import config  # noqa: F401
    except Exception:                                    # noqa: BLE001
        # The engine must still run on its own, without the platform
        # package present.
        pass


def _provider_check():
    """Make one real request to each configured provider.

    Prints a key-free report. Exits non-zero when no provider answered.
    """
    from providers import adapter, openai_compat

    _apply_application_defaults()

    results = []
    for role, getter in (("primary", adapter.configured_provider),
                         ("fallback", adapter.fallback_provider)):
        provider = getter()
        if provider is None:
            results.append({"role": role, "provider": None,
                            "status": "not configured"})
            continue

        entry = {"role": role, "provider": provider["name"],
                 "base_url": provider["base_url"], "checks": {}}

        # --- chat -------------------------------------------------------
        model = openai_compat.chat_model_for(provider)
        try:
            # A reasoning model needs room for both its reasoning and its
            # answer, so the check uses a budget that a reasoning model can
            # actually complete inside.
            content = openai_compat.chat(
                messages=[{"role": "user",
                           "content": "Reply with the single word: pong"}],
                model=model, base_url=provider["base_url"],
                api_key=provider["api_key"], timeout=45, max_tokens=256)
            entry["checks"]["chat"] = {
                "model": model,
                "ok": bool(content and content.strip()),
                "sample": (content or "").strip()[:40],
            }
        except openai_compat.ProviderError as exc:
            entry["checks"]["chat"] = {
                "model": model, "ok": False,
                "error": str(exc), "kind": exc.kind, "status": exc.status}

        # --- embeddings -------------------------------------------------
        embed_model = openai_compat.embed_model_for(provider)
        if not embed_model:
            entry["checks"]["embeddings"] = {
                "ok": None,
                "note": "provider catalogue has no embedding model"}
        else:
            try:
                vectors = openai_compat.embed(
                    texts=["viral clips pipeline check"],
                    model=embed_model, base_url=provider["base_url"],
                    api_key=provider["api_key"], timeout=45)
                entry["checks"]["embeddings"] = {
                    "model": embed_model, "ok": bool(vectors),
                    "dimensions": len(vectors[0]) if vectors else 0}
            except openai_compat.ProviderError as exc:
                entry["checks"]["embeddings"] = {
                    "model": embed_model, "ok": False,
                    "error": str(exc), "kind": exc.kind, "status": exc.status}

        results.append(entry)

    print(json.dumps(results, indent=2))
    answered = any(
        check.get("ok")
        for entry in results
        for check in entry.get("checks", {}).values()
    )
    return 0 if answered else 1


def main():
    # The command line is a second entry point into the same
    # application, so it resolves the provider exactly the way the
    # running application does.
    _apply_application_defaults()

    if "--provider-status" in sys.argv:
        from providers import adapter
        print(json.dumps(adapter.status(), indent=2))
        return 0

    if "--provider-check" in sys.argv:
        return _provider_check()

    from providers import adapter
    active = adapter.install()
    if active:
        status = adapter.status()
        primary = status["primary"]["name"] if status["primary"] else "?"
        fallback = (status["fallback"]["name"]
                    if status["fallback"] else "none")
        print(f"AI provider: {primary} (fallback: {fallback})", flush=True)
    else:
        print("AI provider: local heuristic only "
              "(set VIRALCLIPS_LLM_PROVIDER=groq to enable an external one)",
              flush=True)

    import chopify
    chopify.main()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
