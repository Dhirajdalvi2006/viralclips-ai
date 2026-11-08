"""Tests for the external AI provider adapter.

These tests use a local stub HTTP server, so no API key is needed and no
request ever leaves the machine. They verify the protocol translation that
upstream Chopify depends on:

  * the Ollama request shape is translated to an OpenAI-compatible one
  * the OpenAI response envelope is translated back to what upstream parses
  * provider failures degrade to the heuristic floor instead of raising
  * the fallback chain is tried in order
  * API keys never appear in log output or exception messages
  * the embedding cache key is namespaced per provider
"""
import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from providers import adapter, openai_compat


class _Handler(BaseHTTPRequestHandler):
    """Stub provider. Behaviour is set via class attributes per test."""

    chat_response = {"choices": [{"message": {"content": "[]"}}]}
    embed_response = {"data": [{"embedding": [0.1, 0.2]}]}
    chat_status = 200
    embed_status = 200
    requests = []
    #: Status codes to return, one per request, then the last one repeats.
    status_sequence = None
    #: Extra headers to send with the response.
    response_headers = None
    #: Body returned for a non-200 chat response.
    chat_error_body = {"error": "nope"}

    def log_message(self, *args):  # silence stderr
        pass

    def _read(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def _respond(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (type(self).response_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _next_status(self, current):
        """Return the status to use for this request."""
        sequence = type(self).status_sequence
        if not sequence:
            return current
        index = len([r for r in type(self).requests
                     if r["path"].endswith("/chat/completions")]) - 1
        if index < len(sequence):
            return sequence[index]
        return sequence[-1]

    def do_POST(self):
        body = self._read()
        type(self).requests.append({
            "path": self.path,
            "body": body,
            "headers": dict(self.headers),
        })
        if self.path.endswith("/chat/completions"):
            status = self._next_status(type(self).chat_status)
            if status != 200:
                self._respond(status, type(self).chat_error_body)
                return
            self._respond(200, type(self).chat_response)
        elif self.path.endswith("/embeddings"):
            status = self._next_status(type(self).embed_status)
            if status != 200:
                self._respond(status, {"error": "nope"})
                return
            self._respond(200, type(self).embed_response)
        else:
            self._respond(404, {"error": "unknown path"})

    def do_GET(self):
        type(self).requests.append({
            "path": self.path, "body": {}, "headers": dict(self.headers)})
        if self.path.endswith("/models"):
            self._respond(200, {"data": [{"id": "stub-model"}]})
        else:
            self._respond(404, {"error": "unknown path"})


class AdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _Handler.requests = []
        _Handler.chat_status = 200
        _Handler.embed_status = 200
        _Handler.chat_response = {"choices": [{"message": {"content": "[]"}}]}
        _Handler.embed_response = {"data": [{"embedding": [0.1, 0.2]}]}
        _Handler.status_sequence = None
        _Handler.response_headers = None
        _Handler.chat_error_body = {"error": "nope"}
        self._saved_env = dict(os.environ)
        for key in ("VIRALCLIPS_LLM_PROVIDER", "VIRALCLIPS_LLM_FALLBACK",
                    "GROQ_API_KEY", "OPENROUTER_API_KEY",
                    "VIRALCLIPS_LLM_MODEL", "VIRALCLIPS_EMBED_MODEL",
                    "VIRALCLIPS_GROQ_MODEL", "VIRALCLIPS_OPENROUTER_MODEL",
                    "VIRALCLIPS_GROQ_EMBED_MODEL",
                    "VIRALCLIPS_OPENROUTER_EMBED_MODEL",
                    "VIRALCLIPS_LLM_MAX_TOKENS",
                    "VIRALCLIPS_CREDENTIALS_FILE"):
            os.environ.pop(key, None)
        # Isolate the suite from the machine's real credential file, which
        # would otherwise satisfy "missing key" tests and make them depend
        # on whether the operator has configured a provider.
        os.environ["VIRALCLIPS_CREDENTIALS_FILE"] = os.path.join(
            tempfile.gettempdir(), "viralclips-no-such-credentials.env")
        self._saved_env.pop("VIRALCLIPS_CREDENTIALS_FILE", None)
        self._saved_env["VIRALCLIPS_CREDENTIALS_FILE"] = os.environ[
            "VIRALCLIPS_CREDENTIALS_FILE"]

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)

    def _use_stub(self, provider="groq", key="test-key-123"):
        """Point a provider at the local stub server."""
        os.environ["VIRALCLIPS_LLM_PROVIDER"] = provider
        os.environ[f"{provider.upper()}_API_KEY"] = key
        config = openai_compat.PROVIDERS[provider]
        original = config["base_url"]
        config["base_url"] = self.base_url
        self.addCleanup(config.__setitem__, "base_url", original)

    # --- config ---------------------------------------------------------

    def test_no_provider_configured_returns_none(self):
        self.assertIsNone(adapter.configured_provider())

    def test_provider_none_disables(self):
        os.environ["VIRALCLIPS_LLM_PROVIDER"] = "none"
        self.assertIsNone(adapter.configured_provider())

    def test_missing_key_yields_none(self):
        os.environ["VIRALCLIPS_LLM_PROVIDER"] = "groq"
        self.assertIsNone(adapter.configured_provider())

    def test_status_never_exposes_key(self):
        self._use_stub(key="super-secret-value")
        blob = json.dumps(adapter.status())
        self.assertNotIn("super-secret-value", blob)
        self.assertIn("groq", blob)

    def test_unknown_provider_raises(self):
        with self.assertRaises(openai_compat.ProviderError):
            openai_compat.provider_config("not-a-provider")

    # --- seam A: chat ---------------------------------------------------

    def test_chat_translates_request_and_response(self):
        self._use_stub()
        _Handler.chat_response = {"choices": [{"message": {
            "content": '[{"index": 0, "adjustment": 0.5, "reason": "strong hook"}]'}}]}
        result = adapter.chat("some-model", [
            {"role": "system", "content": "You are an editor."},
            {"role": "user", "content": "[]"},
        ])
        self.assertEqual(result, [{"index": 0, "adjustment": 0.5,
                                   "reason": "strong hook"}])
        request = _Handler.requests[-1]
        self.assertTrue(request["path"].endswith("/chat/completions"))
        # OpenAI-compatible body, not the Ollama shape.
        self.assertNotIn("format", request["body"])
        self.assertNotIn("options", request["body"])
        self.assertIn("model", request["body"])
        self.assertEqual(len(request["body"]["messages"]), 2)
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-key-123")

    def test_chat_returns_empty_list_on_provider_failure(self):
        self._use_stub()
        _Handler.chat_status = 500
        result = adapter.chat("m", [{"role": "system", "content": "s"}])
        self.assertEqual(result, [])

    def test_chat_returns_empty_list_when_no_provider(self):
        self.assertEqual(adapter.chat("m", [{"role": "system", "content": "s"}]),
                         [])

    def test_chat_handles_non_json_response(self):
        self._use_stub()
        _Handler.chat_response = {"choices": [{"message": {"content": "no json here"}}]}
        self.assertEqual(adapter.chat("m", [{"role": "system", "content": "s"}]),
                         [])

    # --- seam B: embeddings ---------------------------------------------
    # Groq's published catalogue has no embedding model, so the embedding
    # seam is exercised against OpenRouter. See docs/PROVIDER_SETUP.md.

    def test_embed_translates_request_and_response(self):
        self._use_stub("openrouter")
        _Handler.embed_response = {"data": [{"embedding": [1.0, 2.0]},
                                            {"embedding": [3.0, 4.0]}]}
        vectors = adapter.embed(["a", "b"], "ignored-model")
        self.assertEqual(vectors, [[1.0, 2.0], [3.0, 4.0]])
        request = _Handler.requests[-1]
        self.assertTrue(request["path"].endswith("/embeddings"))
        self.assertEqual(request["body"]["input"], ["a", "b"])
        # Ollama-only fields must not be sent.
        self.assertNotIn("truncate", request["body"])

    def test_embed_raises_when_no_provider(self):
        with self.assertRaises(ValueError):
            adapter.embed(["a"], "m")

    def test_embed_raises_when_all_providers_fail(self):
        self._use_stub("openrouter")
        _Handler.embed_status = 503
        with self.assertRaises(ValueError):
            adapter.embed(["a"], "m")

    def test_embed_rejects_wrong_vector_count(self):
        self._use_stub("openrouter")
        _Handler.embed_response = {"data": [{"embedding": [1.0]}]}
        # A malformed response is treated as a provider failure, so the
        # adapter falls through the chain and reports it as unavailable.
        # The specific cause is preserved in the message.
        with self.assertRaises(ValueError) as ctx:
            adapter.embed(["a", "b"], "m")
        self.assertIn("1 vectors for 2 inputs", str(ctx.exception))

    def test_provider_without_embedding_model_is_skipped(self):
        # Groq has no embedding model in its catalogue. It must be skipped
        # rather than called, so the chain continues to a provider that has
        # one. This is what makes --semantic work with Groq primary.
        self._use_stub("groq")
        os.environ["VIRALCLIPS_LLM_FALLBACK"] = "openrouter"
        os.environ["OPENROUTER_API_KEY"] = "fallback-key"
        config = openai_compat.PROVIDERS["openrouter"]
        original = config["base_url"]
        config["base_url"] = self.base_url
        self.addCleanup(config.__setitem__, "base_url", original)
        _Handler.embed_response = {"data": [{"embedding": [9.0, 8.0]}]}
        vectors = adapter.embed(["a"], "ignored")
        self.assertEqual(vectors, [[9.0, 8.0]])
        # Exactly one request: the fallback provider, never Groq.
        self.assertEqual(len(_Handler.requests), 1)

    def test_embed_model_ids_none_when_no_provider_has_embeddings(self):
        self._use_stub("groq")
        api_model, namespace = adapter.embed_model_ids()
        self.assertIsNone(api_model)
        self.assertIsNone(namespace)

    # --- fallback chain --------------------------------------------------

    def test_fallback_used_when_primary_fails(self):
        self._use_stub("groq")
        _Handler.chat_status = 500
        # Point the fallback at the same stub but with a working chat.
        os.environ["VIRALCLIPS_LLM_FALLBACK"] = "openrouter"
        os.environ["OPENROUTER_API_KEY"] = "fallback-key"
        config = openai_compat.PROVIDERS["openrouter"]
        original = config["base_url"]
        config["base_url"] = self.base_url
        self.addCleanup(config.__setitem__, "base_url", original)
        _Handler.chat_status = 200
        _Handler.chat_response = {"choices": [{"message": {
            "content": '[{"index": 1, "adjustment": -0.5, "reason": "weak"}]'}}]}
        result = adapter.chat("m", [{"role": "system", "content": "s"}])
        self.assertEqual(result, [{"index": 1, "adjustment": -0.5,
                                   "reason": "weak"}])

    def test_fallback_absent_returns_empty(self):
        self._use_stub()
        _Handler.chat_status = 500
        self.assertEqual(adapter.chat("m", [{"role": "system", "content": "s"}]),
                         [])

    # --- cache key namespacing ------------------------------------------

    def test_cache_namespace_is_provider_specific(self):
        # The namespace must identify the provider that actually produced
        # the vectors, so one provider's vectors can never be reused by
        # another. Groq has no embedding model, so with Groq alone there is
        # no namespace; with OpenRouter there is.
        self._use_stub("openrouter")
        api_model, namespace = adapter.embed_model_ids()
        self.assertEqual(namespace, f"openrouter/{api_model}")
        self.assertTrue(namespace.startswith("openrouter/"))

    def test_cache_namespace_differs_between_providers(self):
        self._use_stub("openrouter")
        _api, openrouter_ns = adapter.embed_model_ids()
        os.environ["VIRALCLIPS_OPENROUTER_EMBED_MODEL"] = "other/embed-model"
        _api2, other_ns = adapter.embed_model_ids()
        self.assertNotEqual(openrouter_ns, other_ns)

    def test_install_patches_upstream_seams(self):
        self._use_stub()
        import score_clips
        import semantic
        original_chat = score_clips._ollama_chat
        original_embed = semantic.ollama_embed
        try:
            self.assertTrue(adapter.install())
            self.assertIsNot(score_clips._ollama_chat, original_chat)
            self.assertIsNot(semantic.ollama_embed, original_embed)
        finally:
            score_clips._ollama_chat = original_chat
            semantic.ollama_embed = original_embed
            semantic.search = getattr(semantic, "search", None)
            adapter._installed = False

    def test_install_is_noop_without_provider(self):
        import score_clips
        original = score_clips._ollama_chat
        self.assertFalse(adapter.install())
        self.assertIs(score_clips._ollama_chat, original)

    # --- key hygiene -----------------------------------------------------

    def test_error_message_does_not_contain_key(self):
        # The adapter swallows provider errors by design (graceful
        # degradation to the heuristic floor), so the key-hygiene check
        # belongs at the client layer where the exception is raised.
        self._use_stub(key="leaky-secret-xyz")
        _Handler.chat_status = 401
        with self.assertRaises(openai_compat.ProviderError) as ctx:
            openai_compat.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="m", base_url=self.base_url, api_key="leaky-secret-xyz")
        self.assertNotIn("leaky-secret-xyz", str(ctx.exception))

    def test_adapter_failure_output_does_not_contain_key(self):
        # The adapter's own console output must not echo the key either.
        self._use_stub(key="leaky-secret-xyz")
        _Handler.chat_status = 401
        import io
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            adapter.chat("m", [{"role": "system", "content": "s"}])
        self.assertNotIn("leaky-secret-xyz", buffer.getvalue())

    # --- transport: User-Agent, max_tokens, retries, timeouts ------------
    # These cover the failures found during live testing. See
    # docs/PROVIDER_SETUP.md for the raw evidence.

    def test_request_sends_a_user_agent(self):
        # Groq's edge rejects Python's default "Python-urllib/x.y" with
        # HTTP 403 / error code 1010 before the request reaches the API.
        self._use_stub()
        adapter.chat("m", [{"role": "system", "content": "s"}])
        headers = _Handler.requests[-1]["headers"]
        self.assertIn("User-Agent", headers)
        self.assertNotIn("urllib", headers["User-Agent"].lower())

    def test_request_sends_explicit_max_tokens(self):
        # Without an explicit budget the server assumes the model's maximum,
        # which a metered account cannot fund (HTTP 402).
        self._use_stub()
        adapter.chat("m", [{"role": "system", "content": "s"}])
        body = _Handler.requests[-1]["body"]
        self.assertIn("max_tokens", body)
        self.assertGreater(body["max_tokens"], 0)

    def test_max_tokens_env_override_is_used(self):
        self._use_stub()
        os.environ["VIRALCLIPS_LLM_MAX_TOKENS"] = "64"
        adapter.chat("m", [{"role": "system", "content": "s"}])
        self.assertEqual(_Handler.requests[-1]["body"]["max_tokens"], 64)

    def test_rate_limit_is_retried_then_succeeds(self):
        self._use_stub()
        _Handler.status_sequence = [429, 200]
        _Handler.chat_response = {"choices": [{"message": {"content": "[]"}}]}
        result = adapter.chat("m", [{"role": "system", "content": "s"}])
        self.assertEqual(result, [])
        self.assertEqual(len(_Handler.requests), 2)

    def test_rate_limit_retries_are_bounded(self):
        self._use_stub()
        _Handler.status_sequence = [429, 429, 429, 429]
        result = adapter.chat("m", [{"role": "system", "content": "s"}])
        # Degrades to the heuristic floor rather than raising.
        self.assertEqual(result, [])
        self.assertEqual(len(_Handler.requests), 3)

    def test_invalid_key_is_reported_as_auth_failure(self):
        self._use_stub()
        _Handler.chat_status = 401
        with self.assertRaises(openai_compat.ProviderError) as ctx:
            openai_compat.chat(messages=[{"role": "user", "content": "hi"}],
                               model="m", base_url=self.base_url,
                               api_key="k", timeout=10)
        self.assertEqual(ctx.exception.kind, "auth")
        self.assertEqual(ctx.exception.status, 401)

    def test_timeout_is_reported_as_timeout(self):
        # A timeout must be distinguishable from an auth failure so the
        # caller can tell "wrong key" apart from "slow provider".
        import urllib.error
        self._use_stub()

        def _raise_timeout(request, timeout=None):
            raise TimeoutError("timed out")

        original = openai_compat.urllib.request.urlopen
        openai_compat.urllib.request.urlopen = _raise_timeout
        try:
            with self.assertRaises(openai_compat.ProviderError) as ctx:
                openai_compat.chat(messages=[{"role": "user", "content": "hi"}],
                                   model="m", base_url=self.base_url,
                                   api_key="k", timeout=1)
        finally:
            openai_compat.urllib.request.urlopen = original
        self.assertEqual(ctx.exception.kind, "timeout")

    def test_quota_error_adapts_max_tokens_and_retries(self):
        # A metered account that cannot afford the requested budget returns
        # HTTP 402 and states the budget it can afford. The client retries
        # once with that smaller budget.
        self._use_stub()
        _Handler.status_sequence = [402, 200]
        _Handler.chat_error_body = {
            "error": {"message": "This request requires more credits, or "
                                 "fewer max_tokens. You requested up to 2048 "
                                 "tokens, but can only afford 128."}}
        _Handler.chat_response = {"choices": [{"message": {"content": "ok"}}]}
        content = openai_compat.chat(
            messages=[{"role": "user", "content": "hi"}], model="m",
            base_url=self.base_url, api_key="k", timeout=10)
        self.assertEqual(content, "ok")
        self.assertEqual(len(_Handler.requests), 2)
        self.assertEqual(_Handler.requests[0]["body"]["max_tokens"], 2048)
        self.assertEqual(_Handler.requests[1]["body"]["max_tokens"], 128)

    def test_null_content_is_treated_as_empty(self):
        # Some reasoning models spend the whole token budget on reasoning
        # and return a null content. That must not crash the adapter.
        self._use_stub()
        _Handler.chat_response = {"choices": [{"message": {"content": None}}]}
        content = openai_compat.chat(
            messages=[{"role": "user", "content": "hi"}], model="m",
            base_url=self.base_url, api_key="k", timeout=10)
        self.assertEqual(content, "")

    def test_null_content_does_not_crash_the_adapter(self):
        self._use_stub()
        _Handler.chat_response = {"choices": [{"message": {"content": None}}]}
        result = adapter.chat("m", [{"role": "system", "content": "s"}])
        self.assertEqual(result, [])

    # --- reasoning-model budget escalation ------------------------------
    # A reasoning model can spend the entire max_tokens allowance on
    # reasoning and return an empty content with finish_reason "length".
    # The model did not fail -- it ran out of room -- so the client must
    # escalate the budget rather than report a failure. Verified live
    # against Groq's openai/gpt-oss-120b on 2026-11-07.

    def test_empty_content_with_length_finish_escalates_budget(self):
        self._use_stub()
        _Handler.status_sequence = None
        # First response: reasoning consumed the whole allowance.
        # Second response: the model answers normally.
        responses = [
            {"choices": [{"finish_reason": "length",
                          "message": {"content": "", "reasoning": "thinking"}}]},
            {"choices": [{"finish_reason": "stop",
                          "message": {"content": "pong"}}]},
        ]
        state = {"n": 0}

        original = openai_compat._post_json

        def _fake_post(url, payload, api_key, timeout, **kwargs):
            index = min(state["n"], len(responses) - 1)
            state["n"] += 1
            self.assertEqual(payload["max_tokens"],
                             64 * (4 ** index),
                             "budget must grow by 4x on each escalation")
            return responses[index]

        openai_compat._post_json = _fake_post
        try:
            content = openai_compat.chat(
                messages=[{"role": "user", "content": "hi"}], model="m",
                base_url=self.base_url, api_key="k", timeout=10,
                max_tokens=64)
        finally:
            openai_compat._post_json = original
        self.assertEqual(content, "pong")
        self.assertEqual(state["n"], 2)

    def test_escalation_is_bounded(self):
        # A model that never answers must not make the client request an
        # arbitrarily large completion.
        self._use_stub()
        state = {"n": 0}

        original = openai_compat._post_json

        def _always_empty(url, payload, api_key, timeout, **kwargs):
            state["n"] += 1
            return {"choices": [{"finish_reason": "length",
                                 "message": {"content": ""}}]}

        openai_compat._post_json = _always_empty
        try:
            content = openai_compat.chat(
                messages=[{"role": "user", "content": "hi"}], model="m",
                base_url=self.base_url, api_key="k", timeout=10,
                max_tokens=64)
        finally:
            openai_compat._post_json = original
        self.assertEqual(content, "")
        # One initial attempt plus MAX_BUDGET_ESCALATIONS retries.
        self.assertEqual(state["n"],
                         1 + openai_compat.MAX_BUDGET_ESCALATIONS)

    def test_escalation_ceiling_is_respected(self):
        self._use_stub()
        seen = []

        original = openai_compat._post_json

        def _always_empty(url, payload, api_key, timeout, **kwargs):
            seen.append(payload["max_tokens"])
            return {"choices": [{"finish_reason": "length",
                                 "message": {"content": ""}}]}

        openai_compat._post_json = _always_empty
        try:
            openai_compat.chat(
                messages=[{"role": "user", "content": "hi"}], model="m",
                base_url=self.base_url, api_key="k", timeout=10,
                max_tokens=openai_compat.MAX_ESCALATED_MAX_TOKENS)
        finally:
            openai_compat._post_json = original
        self.assertLessEqual(max(seen), openai_compat.MAX_ESCALATED_MAX_TOKENS)

    def test_empty_content_with_stop_finish_is_not_escalated(self):
        # A model that finished cleanly with an empty answer is a real
        # (if unhelpful) answer -- it must not trigger a retry loop.
        self._use_stub()
        state = {"n": 0}

        original = openai_compat._post_json

        def _fake_post(url, payload, api_key, timeout, **kwargs):
            state["n"] += 1
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": ""}}]}

        openai_compat._post_json = _fake_post
        try:
            content = openai_compat.chat(
                messages=[{"role": "user", "content": "hi"}], model="m",
                base_url=self.base_url, api_key="k", timeout=10,
                max_tokens=64)
        finally:
            openai_compat._post_json = original
        self.assertEqual(content, "")
        self.assertEqual(state["n"], 1)

    # --- model resolution ------------------------------------------------

    def test_provider_specific_model_wins_over_legacy(self):
        self._use_stub()
        os.environ["VIRALCLIPS_LLM_MODEL"] = "legacy-model"
        os.environ["VIRALCLIPS_GROQ_MODEL"] = "specific-model"
        provider = adapter.configured_provider()
        self.assertEqual(openai_compat.chat_model_for(provider), "specific-model")

    def test_legacy_model_variable_is_honoured(self):
        self._use_stub()
        os.environ["VIRALCLIPS_LLM_MODEL"] = "legacy-model"
        provider = adapter.configured_provider()
        self.assertEqual(openai_compat.chat_model_for(provider), "legacy-model")

    def test_groq_default_model_is_not_deprecated(self):
        # llama-3.3-70b-versatile reached its Groq shutdown date on
        # 2026-08-16. The default must be a model Groq still serves.
        config = openai_compat.provider_config("groq")
        self.assertNotEqual(config["chat_model_default"],
                            "llama-3.3-70b-versatile")
        self.assertEqual(config["chat_model_default"], "openai/gpt-oss-120b")

    def test_groq_declares_no_embedding_model(self):
        config = openai_compat.provider_config("groq")
        self.assertFalse(config["supports_embeddings"])
        self.assertIsNone(config["embed_model_default"])

    def test_ollama_style_model_argument_is_not_sent_to_provider(self):
        # Upstream's --llm argument normally names an Ollama model such as
        # "qwen2.5:7b". No OpenAI-compatible provider accepts that id.
        self._use_stub()
        adapter.chat("qwen2.5:7b", [{"role": "system", "content": "s"}])
        body = _Handler.requests[-1]["body"]
        self.assertNotEqual(body["model"], "qwen2.5:7b")
        self.assertEqual(body["model"], "openai/gpt-oss-120b")

    def test_provider_style_model_argument_is_honoured(self):
        self._use_stub()
        adapter.chat("openai/gpt-oss-20b", [{"role": "system", "content": "s"}])
        self.assertEqual(_Handler.requests[-1]["body"]["model"],
                         "openai/gpt-oss-20b")


class CredentialsTest(unittest.TestCase):
    """The credential file must work and must never leak a value."""

    def setUp(self):
        self._saved_env = dict(os.environ)
        self.tmp = tempfile.mkdtemp(prefix="viralclips-cred-")
        self.path = os.path.join(self.tmp, "credentials.env")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_reads_key_value_pairs(self):
        from providers import credentials
        self._write("GROQ_API_KEY=abc123\n# comment\nOPENROUTER_API_KEY=xyz\n")
        os.environ["VIRALCLIPS_CREDENTIALS_FILE"] = self.path
        self.assertEqual(credentials.get("GROQ_API_KEY"), "abc123")
        self.assertEqual(credentials.get("OPENROUTER_API_KEY"), "xyz")

    def test_strips_quotes_and_whitespace(self):
        from providers import credentials
        self._write('GROQ_API_KEY="  spaced  "\n')
        os.environ["VIRALCLIPS_CREDENTIALS_FILE"] = self.path
        self.assertEqual(credentials.get("GROQ_API_KEY"), "spaced")

    def test_missing_file_is_not_an_error(self):
        from providers import credentials
        os.environ["VIRALCLIPS_CREDENTIALS_FILE"] = os.path.join(
            self.tmp, "nope.env")
        self.assertIsNone(credentials.get("GROQ_API_KEY"))

    def test_describe_reports_names_not_values(self):
        from providers import credentials
        self._write("GROQ_API_KEY=super-secret-value\n")
        os.environ["VIRALCLIPS_CREDENTIALS_FILE"] = self.path
        blob = json.dumps(credentials.describe())
        self.assertNotIn("super-secret-value", blob)
        self.assertIn("GROQ_API_KEY", blob)

    def test_resolve_uses_credential_file_when_env_is_empty(self):
        self._write("GROQ_API_KEY=from-file\n")
        os.environ["VIRALCLIPS_CREDENTIALS_FILE"] = self.path
        os.environ.pop("GROQ_API_KEY", None)
        config = openai_compat.resolve("groq")
        self.assertIsNotNone(config)
        self.assertEqual(config["api_key"], "from-file")

    def test_environment_takes_priority_over_file(self):
        self._write("GROQ_API_KEY=from-file\n")
        os.environ["VIRALCLIPS_CREDENTIALS_FILE"] = self.path
        os.environ["GROQ_API_KEY"] = "from-env"
        config = openai_compat.resolve("groq")
        self.assertEqual(config["api_key"], "from-env")


if __name__ == "__main__":
    unittest.main()
