# AI provider setup

Chopify's AI layer is Ollama-hardcoded. This project adds an external
provider layer (`providers/`) that routes the two AI call sites through
Groq or OpenRouter without modifying any upstream file.

> **Provider and model are different things.** `groq` is the provider —
> the company that serves the request. `openai/gpt-oss-120b` is the model
> that Groq serves; the `openai/` prefix is part of the model id, not the
> provider name. The upstream engine writes an internal selection mode of
> `ollama` for any LLM-reranked run; that string is a legacy engine label
> kept for diagnostics and is never shown as the provider.

## Quick start

```powershell
# 1. Set the provider (the key is read from the credential file, not the shell)
$env:VIRALCLIPS_LLM_PROVIDER = "groq"

# 2. Run through the launcher (not chopify.py directly)
.venv\Scripts\python.exe viralclips.py recording.mp4 --action all --llm openai/gpt-oss-120b
```

Note the `--llm` flag: upstream only calls the reranker when `--llm` is
present. Setting `VIRALCLIPS_LLM_PROVIDER` alone installs the adapter but
leaves reranking disabled, and the run produces heuristic scores.

Check what is resolved without printing keys:

```powershell
.venv\Scripts\python.exe viralclips.py --provider-status
```

The CLI resolves credentials and provider defaults through the **same**
path the application uses (`viralclips.py::_apply_application_defaults()`),
so the two can never disagree. This was previously a real bug: the CLI
reported "provider not configured" while the application worked against the
same credential file. Fixed and covered by the test suite.

Make one real authenticated request per provider:

```powershell
.venv\Scripts\python.exe viralclips.py --provider-check
```

`--provider-check` exits non-zero when no provider answers, so it works as
a gate in a script.

## Configuration inside the application

The VIRALCLIPS AI application has its own provider configuration, which
mirrors the adapter's settings so the dashboard, the API and the worker
always agree.

| Variable | Default | Purpose |
| --- | --- | --- |
| `VIRALCLIPS_AI_PROVIDER` | `groq` | The provider the application uses. |
| `VIRALCLIPS_AI_MODEL` | `openai/gpt-oss-120b` | The model that provider serves. |
| `VIRALCLIPS_AI_FALLBACK` | *(unset)* | Optional second provider. |
| `VIRALCLIPS_LLM_PROVIDER` | *mirrors the above* | The adapter's own variable. The application sets it from `VIRALCLIPS_AI_PROVIDER` unless it is already set explicitly, so a shell override still wins. |

**Settings → AI** in the dashboard shows the provider, the model, whether
a credential is present, and the result of one real authenticated
request. **AI provider** on the Clip Review screen shows the provider that
actually scored that clip.

### The three attributions the dashboard distinguishes

| Shown | Meaning |
| --- | --- |
| `groq` + `openai/gpt-oss-120b` | An AI actually scored this clip |
| `not recorded` | The clip was AI-scored, but before provider attribution was stored |
| `none (heuristic only)` | The run degraded to the deterministic scorer |

`not recorded` and `none (heuristic only)` are different facts and must not
be collapsed into one label. The first says an AI ran and the attribution
was not written; the second says no AI ran at all. Collapsing them would
claim that a heuristic run was AI-scored, which is the single most damaging
lie this pipeline could tell.

The overview's per-provider breakdown uses the same three keys and never
emits a `"null"` bucket.

### How a degraded run is reported

A provider outage degrades quality; it never breaks the pipeline. When
that happens:

- the clip records **no** `ai_provider` and **no** `ai_model`,
- the API reports the clip as not AI-scored,
- the worker logs `Heuristic scoring only -- no AI reranking` together
  with the reason,
- the dashboard shows `none (heuristic only)` rather than pretending an
  AI ran.

Reporting "AI-scored" for a heuristic run is the single most damaging
lie this pipeline could tell, so the distinction is enforced in the code,
tested, and visible in the UI.

## Credential file

The key lives outside the repository, in:

```
%LOCALAPPDATA%\ViralClipsAI\credentials.env
```

Format is one `KEY=VALUE` per line:

```
GROQ_API_KEY=<your key>
```

Override the location with `VIRALCLIPS_CREDENTIALS_FILE`. Lookup priority is
**process environment → credential file → project `.env`**, so a shell
session always wins. `providers.credentials.describe()` reports which files
contributed which key *names* — never values.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `VIRALCLIPS_LLM_PROVIDER` | no | *(unset)* | `groq`, `openrouter`, or `none`. Unset or `none` leaves upstream behaviour untouched — no network call, no key lookup. |
| `GROQ_API_KEY` | when provider is `groq` | — | Groq credential (from the environment or the credential file). |
| `OPENROUTER_API_KEY` | when provider is `openrouter` | — | OpenRouter credential. |
| `VIRALCLIPS_LLM_FALLBACK` | no | *(unset)* | Optional second provider, tried when the primary fails. |
| `VIRALCLIPS_LLM_MODEL` | no | provider default | Chat model id, applies to whichever provider is active. |
| `VIRALCLIPS_EMBED_MODEL` | no | provider default | Embedding model id. |
| `VIRALCLIPS_GROQ_MODEL` | no | `openai/gpt-oss-120b` | Groq chat model. |
| `VIRALCLIPS_OPENROUTER_MODEL` | no | `meta-llama/llama-3.3-70b-instruct` | OpenRouter chat model. |
| `VIRALCLIPS_GROQ_EMBED_MODEL` | no | *(none)* | Groq publishes no embedding model. |
| `VIRALCLIPS_OPENROUTER_EMBED_MODEL` | no | `openai/text-embedding-3-small` | OpenRouter embedding model. |
| `VIRALCLIPS_LLM_MAX_TOKENS` | no | `2048` | Completion budget for a chat request. |
| `VIRALCLIPS_CREDENTIALS_FILE` | no | `%LOCALAPPDATA%\ViralClipsAI\credentials.env` | Credential file path. |

A provider-specific variable always wins over the generic one, so a
provider changing its catalogue does not require a code edit.

## Current model defaults

Verified live against Groq on 2026-11-07 by reading the authenticated
`GET /models` response for the configured key.

**Groq default chat model: `openai/gpt-oss-120b`.**
`llama-3.3-70b-versatile` is decommissioned (shutdown 2026-08-16) and now
returns `HTTP 404 model_not_found`. The catalogue available to this key was:

```
allam-2-7b                    canopylabs/orpheus-arabic-saudi
canopylabs/orpheus-v1-english  meta-llama/llama-prompt-guard-2-22m
meta-llama/llama-prompt-guard-2-86m  openai/gpt-oss-120b
openai/gpt-oss-20b            openai/gpt-oss-safeguard-20b
qwen/qwen3.8-27b              whisper-large-v3
whisper-large-v3-turbo
```

**Groq publishes no embedding model** — the catalogue contains zero
`text-embedding-*` entries. The embedding seam therefore only works with
OpenRouter configured (directly or as the fallback). `--semantic` against
Groq alone will report that no embedding provider is available; use
`--search` (keyword search, fully local) instead.

Non-reasoning alternatives that also work well for the JSON-array
reranker contract: `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`,
`allam-2-7b`.

## Transport behaviour

Three provider quirks are handled inside `providers/openai_compat.py`.
Each was found by live testing, not by reading documentation.

**A User-Agent is mandatory.** Python's default `Python-urllib/x.y` is
rejected by Groq's edge with `HTTP 403 / error code 1010` *before* the
request reaches the API. Any other UA string is accepted. The client sends
`ViralClipsAI/1.0 (chopify adapter)`.

**`max_tokens` must be sent explicitly.** OpenAI-compatible servers default
it to the model's maximum, which a metered account cannot pay for and which
therefore fails with `HTTP 402` even for a trivial request.

**Reasoning models need budget headroom.** A reasoning model can spend the
whole `max_tokens` allowance on reasoning and return an *empty* content
with `finish_reason: "length"`. That is not a failure — the model ran out
of room. The client detects this and escalates the budget 4× (bounded at
8192 tokens, at most 3 escalations) rather than reporting an error. This
matters: `openai/gpt-oss-120b` answering "pong" needs ~256 tokens, not 32.

## How it works

```
viralclips.py
  └─ providers.adapter.install()
       ├─ score_clips._ollama_chat  →  providers.adapter.chat()  →  POST /chat/completions
       └─ semantic.ollama_embed     →  providers.adapter.embed() →  POST /embeddings
```

Both upstream functions are Ollama-shaped. The adapter translates:

| | Ollama (upstream) | OpenAI-compatible (adapter) |
|---|---|---|
| Chat endpoint | `POST {host}/api/chat` | `POST {base_url}/chat/completions` |
| Chat body | `{model, stream, format, options:{temperature}, messages}` | `{model, messages, temperature, max_tokens}` |
| Chat response | `message.content` | `choices[0].message.content` |
| Embed endpoint | `POST {HOST}/api/embed` | `POST {base_url}/embeddings` |
| Embed body | `{model, input[], truncate}` | `{model, input[]}` |
| Embed response | `embeddings[]` | `data[].embedding[]` |

The upstream reranker asks for a JSON array of score adjustments:

```json
[{"index": 0, "adjustment": -1.0, "reason": "short reason"}]
```

The adapter asks the provider for the same shape and extracts it with the
same regular expression upstream uses, so `score_clips.py` needs no change.

Note which candidate list upstream sends: `select()` reranks the
**deduplicated** candidates (typically 2–3 after dedupe), not the raw
candidate set. Every candidate in that list gets an adjustment, and
upstream records `llm_adjustment`, `llm_model`, and appends the AI reason
to the existing heuristic reason.

## Fallback behaviour

```
Groq (primary) → OpenRouter (optional) → local heuristic scorer
```

The heuristic scorer is upstream's guaranteed floor and needs no network.
If every provider fails, the adapter prints a diagnostic and returns an
empty result; upstream then uses its deterministic scores and the run
completes normally. A provider outage degrades quality, never breaks the
pipeline.

Verified by test: `tests/test_providers.py::test_fallback_used_when_primary_fails`
and `::test_chat_returns_empty_list_on_provider_failure`.

## Failure classes

`ProviderError.kind` distinguishes the cases so the right fix can be
applied:

| kind | HTTP | Meaning | Fix |
|---|---|---|---|
| `auth` | 401 / 403 | Key rejected or missing | Supply a valid key |
| `quota` | 402 | Account cannot afford the budget | Add credit; the client retries once with the affordable budget the provider states |
| `rate_limit` | 429 | Throttled | The client retries with `Retry-After` honoured |
| `timeout` | — | Request exceeded its deadline | Increase the timeout or use a faster model |
| `network` | — | Host unreachable | Check connectivity/DNS |
| `bad_request` | 400 | Malformed request | Check the model id and payload |
| `server` | 5xx | Provider-side fault | Retried with bounded backoff |
| `response` | — | Response shape unusable | Investigate the provider's response format |

No error message ever contains the key.

## Embedding cache

Upstream caches sentence embeddings on disk, keyed by the model name.
Because the adapter overrides that key with a provider-namespaced id
(`openrouter/openai/text-embedding-3-small`), vectors produced by one
provider can never be silently reused for another.

If you change embedding models, delete the old `embeddings.json` in the
project work directory — the key changes, so a stale file is simply
ignored rather than reused.

## Semantic search caveat

`--semantic` requires a live embedding endpoint at query time. It is
mutually exclusive with `--search` (keyword search), which is fully local
and needs no provider at all.

Since Groq publishes no embedding model, `--semantic` needs OpenRouter
configured as the provider or fallback.

If you do not want transcripts leaving the machine at all, use `--search`
and leave the provider unset. The heuristic scorer still runs.

## Key handling rules

- Keys are read from the environment or the credential file **at call
  time**, never at import time.
- Keys never appear in log output, exception messages, or HTTP error text.
  Verified by `tests/test_providers.py::test_error_message_does_not_contain_key`
  and `::test_adapter_failure_output_does_not_contain_key`.
- The credential file lives outside the repository. `.env`, `*.key`,
  `*.pem`, and `secrets.json` are gitignored.
- Do not pass a key on the command line — it lands in shell history.

## Privacy deviation

Upstream Chopify's stated property is "no hosted inference, no API key,
nothing uploaded". Enabling an external provider breaks that property:
**transcript text and candidate text are what leave the machine.**

This is a deliberate decision for VIRALCLIPS AI, not a silent change. Keep
it deliberate.

## Verifying without a real key

The adapter test suite runs a local stub HTTP server — no key, no network:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_providers.py -v
```

The suite isolates itself from the machine's real credential file by
pointing `VIRALCLIPS_CREDENTIALS_FILE` at a non-existent path, so it
passes whether or not a provider is configured.

To confirm the wiring end to end without a valid key (expect a clean
`HTTP 401`, then graceful fallback to heuristic scores):

```powershell
$env:VIRALCLIPS_LLM_PROVIDER = "groq"
$env:GROQ_API_KEY = "invalid"
.venv\Scripts\python.exe viralclips.py recording.mp4 --action prepare --llm openai/gpt-oss-120b
```


## Speech-to-text provider selection

Speech transcription is separate from the chat/reasoning provider described
above. The application supports Groq Whisper and local Faster-Whisper.

Set `VIRALCLIPS_TRANSCRIPTION_PROVIDER` before launching both the API and
worker:

| Value | Behaviour |
|---|---|
| `auto` (default) | Prefer Groq when a Groq credential is available. Otherwise use local Faster-Whisper. |
| `groq` | Groq only. Missing credentials or API errors are reported; it does not silently switch to local transcription. |
| `faster_whisper` | Local Faster-Whisper only. A local dependency failure is reported; it does not silently switch to Groq. |

Example for a Groq-first setup:

```powershell
$env:VIRALCLIPS_TRANSCRIPTION_PROVIDER = "auto"
$env:VIRALCLIPS_GROQ_TRANSCRIPTION_ENABLED = "1"
$env:VIRALCLIPS_LOCAL_TRANSCRIPTION_ENABLED = "1"
.estart.bat
```

For a Groq-only setup:

```powershell
$env:VIRALCLIPS_TRANSCRIPTION_PROVIDER = "groq"
.estart.bat
```

Available controls:

| Variable | Default | Purpose |
|---|---|---|
| `VIRALCLIPS_TRANSCRIPTION_PROVIDER` | `auto` | `auto`, `groq`, or `faster_whisper`. |
| `VIRALCLIPS_GROQ_TRANSCRIPTION_ENABLED` | `1` | Set to `0` to disable Groq speech-to-text. |
| `VIRALCLIPS_LOCAL_TRANSCRIPTION_ENABLED` | `1` | Set to `0` to disable local Faster-Whisper. |
| `VIRALCLIPS_GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` | Groq speech-to-text model. |
| `VIRALCLIPS_GROQ_TRANSCRIPTION_MAX_FILE_MB` | `25` | Conservative maximum file size per transcription request. |
| `VIRALCLIPS_GROQ_TRANSCRIPTION_CHUNK_TARGET_MB` | `15` | Target size for split audio chunks. |

Groq transcription sends the extracted audio to Groq. Groq chat reasoning
sends transcript/candidate text to the configured chat provider. These
are separate external data flows. Local Faster-Whisper does not send audio
to Groq. Do not describe a Groq-enabled run as fully offline.

In Groq mode, the transcription dispatcher checks credentials and routes
directly to the cloud adapter before importing Faster-Whisper or CTranslate2.
This avoids loading the native CTranslate2 extension on Windows hosts where
Smart App Control or Code Integrity blocks it. The application does not
disable or bypass Windows security controls.

Chunked Faster-Whisper transcripts record `transcription_provider` and
`transcription_model`, just like Groq transcripts, so the UI and reports
can distinguish which backend actually ran.
