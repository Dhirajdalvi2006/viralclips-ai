# FINAL VERIFICATION REPORT — VIRALCLIPS AI

**Project:** `C:\Users\dalvi\OneDrive\Desktop\VIRALCLIPS-AI`
**Date of this report:** 2026-11-08
**Engine:** [Chopify](https://github.com/mehbul/chopify) 1.4.0, commit `d576927bf3b764733c97ac1ad324aa9957b0885d`, used unmodified
**Runtime:** Windows 11 (x64) · Python 3.11.9 · Node 24 · FFmpeg 9.0.2
**AI provider:** Groq, model `openai/gpt-oss-120b`
**API:** <http://127.0.0.1:8799> · API reference: <http://127.0.0.1:8799/docs>

> **This application is not claimed to be production-ready.** It is a working
> local Windows tool that has been exercised end to end, with the evidence
> recorded below. Two publishing integrations remain unverified because no
> credentials exist for them, and that gap is stated plainly rather than
> papered over.

---

## 1. How to read this report

Every claim is placed in exactly one of four buckets.

| Bucket | Meaning |
| --- | --- |
| **VERIFIED** | Tested successfully, with the command and the observed result recorded. |
| **IMPLEMENTED** | The code exists and is exercised by the automated suite, but the feature has not been driven end to end against a live external service. |
| **PENDING** | Needs a credential, an account, or an external configuration that is not present on this machine. |
| **INCOMPLETE** | Still needs development. Named explicitly so nothing is implied to be finished. |

---

## 2. Evidence summary

| Verification | Result | Command or method |
| --- | --- | --- |
| Complete test suite | **646 passed, 0 failed, 3 warnings** (45.9 s) | `.venv\Scripts\python.exe -m pytest -q` |
| Windows lifecycle | **44 passed, 0 failed** | `scratch/lifecycle.py` — 3 × start→stop→restart |
| Windows release scripts | **38 passed, 0 failed** | `scratch/release_scripts.py` |
| Final clean-state sequence | **49 passed, 0 failed** | `scratch/final_clean_state.py` — the 12-step sequence in §4 |
| Security audit | **86 passed, 0 failed** | `scratch/phase6_audit_v3.py` |
| Live end-to-end upload | **28 passed, 0 failed** | `scratch/release_upload.py` |
| Frontend audit | **16 passed, 0 failed**, all 12 screens | `scratch/frontend_audit.py` |
| Provider CLI | `groq`, `openai/gpt-oss-120b`, `ok: true`, sample `pong` | `.venv\Scripts\python.exe viralclips.py --provider-check` |
| Reliability drill | 15 passed, 0 failed | earlier run |
| Channel monitoring drill | 14 passed, 0 failed | earlier run |
| Publishing readiness drill | 15 passed, 0 failed | earlier run |
| Metric provenance drill | 7 passed, 0 failed | earlier run |
| Long-video artifact checks | 45 passed, 0 failed | earlier run |
| Operational/storage drill | 60 passed, 0 failed | earlier run |
| Storage + filename regressions | 89 + 68 passed, 0 failed | earlier run |

The three warnings are FastAPI/Starlette deprecation notices about
`@app.on_event("startup")` and an AnyIO alias. They are not test
failures and do not affect behaviour.

**No test was weakened, skipped or removed.** `git diff --stat` shows only
`.gitignore` and `requirements.txt` modified against the upstream commit;
every platform test file is new and additive.

---

## 3. VERIFIED — tested successfully with evidence

### 3.1 Installation

- `setup.bat` creates `.venv`, installs `requirements.txt`, verifies FFmpeg,
  import-checks the engine and initialises the database. It is idempotent:
  running it twice leaves a working environment. `setup.bat --check`
  inspects without changing anything.
- The engine and the platform both import cleanly (the health check runs the
  import gate on every invocation).

### 3.2 Startup and shutdown

Verified by `scratch/lifecycle.py` (**44/44**) and `scratch/release_scripts.py` (**38/38**).

- `start.bat` starts the worker and the API, waits for the API to answer, and
  prints the URLs. Exit code 0.
- `stop.bat` stops both services and **nothing else**. Exit code 0.
- `restart.bat` stops and starts. Exit code 0.
- `health-check.bat` reports `HEALTHY` and exits 0 when the application is
  running; it reports `UNHEALTHY` and exits 1 when it is not.
- Three full start → stop → restart cycles were run. In every cycle all four
  application processes (two virtual-environment launcher shims and the two
  real interpreters they spawn) exited, and the API stopped answering.
- No hanging terminal: every script returned.
- No duplicate services: the observed process set never contained two
  instances of the same service.
- **Unrelated processes were never harmed.** The precise invariant asserted
  is *"the only processes that disappear during a stop are the application's
  own"*. The unrelated BISmart application (3 processes) survived every
  cycle unchanged.

Two real defects were found and fixed during this work, both in the Windows
process handling:

1. **A stray launcher survived `stop.bat`.** On Windows the virtual
   environment's `python.exe` is a shim that spawns the real interpreter as a
   *child* and waits for it. The service recorded the child's PID, and
   `taskkill /T` kills descendants but not the parent, so the shim outlived
   the stop. `service_control._launcher_parents()` now discovers the shim by
   walking the parent chain through Windows CIM, and `stop()` terminates it.

   **Ownership is never decided by the parent-child relationship alone.** Two
   independent facts must both hold before a process is terminated: the
   executable must be *this project's* `.venv\Scripts\python.exe`, **and** the
   command line must name one of *this project's* service entry points
   (`worker.py` or `run_api.py`). BISmart's virtual environment has the same
   shim-and-child shape and fails both tests, so it is never touched.

2. **`health-check.bat` reported `HEALTHY` while the API was down.** The API
   and worker checks printed a warning but never set the failure flag. They
   now fail the check, and the worker is verified through the API's own
   `worker.alive` flag rather than by the mere presence of a stale heartbeat
   file.

Two further defects were fixed in the batch files:

3. **`timeout` needs a console.** `start.bat` and `restart.bat` used
   `timeout /t 1 /nobreak`, which answers `Access is denied.` in a
   non-interactive session (a scheduled task, a service, a CI run) and looked
   like a startup failure. The pause is now taken with Python, which the
   project already requires.
4. **The browser launch printed the same refusal.** The plain `start` command
   prints `Access is denied.` even when its own output is redirected, so the
   launch now goes through PowerShell, where the failure is caught and
   discarded. The URLs are printed either way.

### 3.3 Groq configuration

- The credential lives **outside** the project, in
  `%LOCALAPPDATA%\ViralClipsAI\credentials.env`. Lookup priority is
  **process environment → credential file → project `.env`**.
- `.venv\Scripts\python.exe viralclips.py --provider-check` returns:

  ```json
  { "role": "primary", "provider": "groq",
    "base_url": "https://api.groq.com/openai/v1",
    "checks": { "chat": { "model": "openai/gpt-oss-120b", "ok": true, "sample": "pong" },
                "embeddings": { "ok": null, "note": "provider catalogue has no embedding model" } } }
  ```

  That is a real authenticated HTTP request, not a configuration echo.
- The CLI and the application resolve credentials and provider defaults
  through the same path. This was previously broken: the CLI reported
  "provider not configured" while the application worked. Fixed by
  `viralclips.py::_apply_application_defaults()`.
- **Provider and model are reported separately.** `groq` is the provider;
  `openai/gpt-oss-120b` is the model Groq serves. The upstream engine's
  internal `ollama` mode string is a legacy engine label, kept for
  diagnostics only.
- A provider outage degrades to deterministic heuristic scoring and says so.
  The clip records no provider, the API reports it as not AI-scored, and the
  worker logs `Heuristic scoring only -- no AI reranking`.

### 3.4 Direct video processing

Verified end to end through the live HTTP API (`scratch/release_upload.py`,
**28/28**), using a distinct authorised test video so the duplicate-upload
guard could not mask the result:

1. The file is accepted by `POST /api/videos/upload`.
2. A job enters the queue and is persisted in SQLite.
3. The background worker picks it up, transcribes it, and scores the moments.
4. Groq is used — the persisted clip records provider `groq` and model
   `openai/gpt-oss-120b`.
5. FFmpeg renders a **1080×1920 H.264/AAC** clip.
6. The poster frame, the SRT and the metadata sidecar are written.
7. The clip, poster and subtitles are served through the frontend media
   routes.

Earlier long-video evidence: a 205.116 s 1280×720 source was processed in
49.19 s, producing three clips of 70.00 s / 69.96 s / 50.00 s spanning
0 → 187.5 s, with moment times, moving frames and synchronised relative
captions confirmed by 45 artifact checks and an independent 7-check
re-verification.

Additional verified behaviours:

- **Duplicate prevention.** Identical content is rejected with HTTP 409 using
  a SHA-256 content hash.
- **Corrupt uploads are refused before a job exists.** An unreadable or
  zero-duration file is rejected with HTTP 400 by an FFmpeg validation step
  at upload time, so no invalid job is ever created.
- **Uploads are validated as media, and filenames are never trusted as
  paths.** The uploaded name is untrusted display metadata only; a safe
  single filesystem component is generated. 68 filename regressions cover
  traversal, separators, null bytes, control characters, shell metacharacters,
  shell command words, Windows reserved names, Unicode, empty names and
  excessive length.

### 3.5 Channel monitoring

- Monitoring uses YouTube's **official published RSS feed**, and the official
  Data API when a key is configured. It does not scrape and does not bypass
  any platform restriction.
- Verified live against a real channel feed (`UCBR8-60-B28hp2BmDPdntcQ`):
  15 entries parsed with no Data API key. The monitoring drill passed
  **14/14**.
- Detection and ingestion are deliberately separate. Finding that a video
  exists is not the same as holding the rights to republish it, so automated
  remote ingestion requires an explicit rights confirmation on the task.
  Without it, episodes are detected and listed, and nothing is downloaded.

### 3.6 Clip review

- All twelve screens render against a live API: **16/16** frontend audit
  checks pass, and every navigation item maps to an audited screen.
- Approve, reject and batch-approve work; approval is stored canonically as
  `approved` / `rejected`.
- Provider and model are shown per clip, with an explicit distinction:
  - `groq` + `openai/gpt-oss-120b` — an AI actually scored this clip;
  - `not recorded` — the clip was AI-scored before provider attribution was
    recorded;
  - `none (heuristic only)` — the run degraded to the deterministic scorer.
- The dashboard shows no invented metrics. Every figure is derived from the
  database or from a live provider call; the provenance drill passed 7/7.

### 3.7 Storage and backups

- **Backup** uses SQLite's online backup API, not a byte-for-byte file copy.
  The database runs in WAL mode, so a plain copy of the main file can miss
  transactions still in the `-wal` sidecar. Backups land in `data\backups\`
  as `viralclips-<timestamp>-<label>.db`.
- **Restore** validates the candidate first: it must be a readable SQLite
  database containing the application's tables. A file that fails validation is
  rejected and **nothing is changed**. Before a restore runs, the current
  database is backed up, so a restore is always reversible.
- **Restore paths are confined to `data\backups\`.** A valid database
  anywhere else on the disk is refused before any replacement happens.
- **Cleanup** removes only eligible old, unpublished media. It never deletes
  an approved clip, a published clip, or a clip inside the retention window.
  It runs a dry run first and shows exactly what would go.
- On Windows the restore disposes the SQLAlchemy engine and removes stale
  `-wal` / `-shm` files first, because Windows refuses to replace a file
  that still has an open handle. If a service still holds the file, the
  restore refuses with a clear message rather than corrupting anything.
- The disk gate refuses to start a job when the volume has less than 2 GB
  free, and records that in the job's error field rather than failing
  halfway through a render.

### 3.8 Security protections

Verified by the security audit (**86/86**):

- Every state-changing route requires the local token **and** an allowed
  origin. `security.check_origin()` was previously defined and tested but
  never invoked — it is now called from `require_token()`, so all 18 mutating
  routes reject a foreign `Origin`. Legitimate local frontend requests and
  no-`Origin` clients still work; reads are unaffected.
- Media path traversal is refused. Every attempt returns 4xx with no file
  content, and the API binds to loopback only — the LAN address refuses
  connections.
- OAuth tokens and secret values are never returned to the frontend. The
  accounts endpoint returns a platform-keyed dictionary with presence
  booleans only.
- Credentials live outside the repository; no secret appeared in any of the
  17 API responses checked.
- **Publishing gates hold.** An unapproved clip is not published: the
  request returns `status: "skipped"`, no publication record is written, and
  the clip's publish status is unchanged. **Nothing was published during any
  test.**

---

## 4. The final clean-state sequence

One run, from a stopped state, taking the application through the whole
release sequence. **49 passed, 0 failed.** No publish endpoint is called
anywhere in that script.

| Step | Check | Result |
| --- | --- | --- |
| 1 | `stop.bat` exits 0 | ✅ |
| 2 | No application-owned process remains; the API is not answering | ✅ |
| 3 | `start.bat` exits 0, with no unexpected error output; 4 processes running | ✅ |
| 4 | The API answers HTTP 200 and reports the worker state | ✅ |
| 5 | The heartbeat file exists, names a worker PID, and was written recently | ✅ |
| 6 | Provider `groq`, model `openai/gpt-oss-120b`, credential present, live request OK; `health-check.bat` HEALTHY | ✅ |
| 7 | The frontend page is served (8308 bytes), `app.js` (105 277 bytes) and `styles.css` (29 992 bytes) load | ✅ |
| 8 | All twelve screens render; frontend audit 16/16 | ✅ |
| 9 | A distinct authorised 20.00 s test video is accepted and queued (HTTP 200) | ✅ |
| 10 | The worker completes the job; 1 clip; provider `groq`, model `openai/gpt-oss-120b`, AI adjustment −0.8; the rendered file probes **1080×1920, H.264 + AAC**; clip, poster and SRT all served | ✅ |
| 11 | `stop.bat` exits 0 | ✅ |
| 12 | No application-owned process survives; the API is down; `health-check.bat` reports UNHEALTHY and exits 1 | ✅ |

The application is left **stopped** at the end of that sequence.

---

## 5. IMPLEMENTED — code present, not driven end to end

These are implemented, exercised by the automated suite, and believed to
work — but no live external service was involved, so they are not called
verified.

| Feature | What is implemented | What is missing to call it verified |
| --- | --- | --- |
| YouTube Shorts publishing | OAuth client, upload path, approval guard, status reporting | A live OAuth grant and a real upload |
| Instagram Reels publishing | OAuth client, Graph API path, approval guard, status reporting | A live OAuth grant, a real upload, and a publicly reachable HTTPS media host |
| Official YouTube Data API discovery | The API path and key handling | A configured Data API key (only the official RSS path is live-verified) |
| Semantic search | The embedding seam, provider-namespaced cache keys, `embeddings` call | A funded embedding provider — **Groq publishes none** |
| `cleanup_orphans.py` | Ownership-checked termination with `--dry-run` | Only exercised against this project's own orphans |
| OpenRouter fallback | Full adapter path, fallback ordering, error classification | Not exercised live; no OpenRouter credential present |

---

## 6. PENDING — waiting on credentials or external configuration

| Item | What is needed | Effect until then |
| --- | --- | --- |
| YouTube publishing | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, a completed OAuth grant, redirect URI `http://127.0.0.1:8799/api/accounts/youtube/callback` | Status reads `awaiting_credentials` / `awaiting_authorization`; the publish button refuses |
| Instagram publishing | `INSTAGRAM_CLIENT_ID`, `INSTAGRAM_CLIENT_SECRET`, `VIRALCLIPS_PUBLIC_MEDIA_URL` on a publicly reachable HTTPS host | Same. Instagram's Graph API cannot fetch a loopback address |
| YouTube Data API discovery | A Data API key | Monitoring falls back to the official RSS feed, which is verified |
| Semantic search | An embedding-capable provider (OpenRouter) | Use keyword search (`--search`), which is fully local |
| Audience-retention and live performance metrics | An authorized analytics account | The dashboard reports these as unavailable rather than inventing them |

---

## 7. INCOMPLETE — still needs development

| Item | Status |
| --- | --- |
| Platform-level publishing scheduling (a queue of posts to publish at set times) | Not built. Publishing is manual, one clip at a time, from the review screen. |
| Per-clip editing in the browser | Not built. The "editor" screen displays a clip and its transcript; it does not re-cut or re-render in place. |
| Multi-user accounts and authentication | Not built. The application is a single-user local tool bound to loopback. |
| Automatic retention of audience metrics | Not built, and blocked on the credentials above. |
| Cross-platform (macOS / Linux) service control | Not built. The process management is Windows-specific by design. |

---

## 8. Operating instructions

### Install

```bat
cd /d C:\Users\dalvi\OneDrive\Desktop\VIRALCLIPS-AI
setup.bat
```

`setup.bat` locates Python 3.11, verifies FFmpeg, creates `.venv`, installs
dependencies, import-checks the engine and initialises the database. It is
idempotent and never touches your clips, database or credential file.
`setup.bat --check` inspects without changing anything.

### Configure the AI provider

```bat
if not exist "%LOCALAPPDATA%\ViralClipsAI" mkdir "%LOCALAPPDATA%\ViralClipsAI"
notepad "%LOCALAPPDATA%\ViralClipsAI\credentials.env"
```

```
GROQ_API_KEY=your-key-here
```

Verify it:

```bat
.venv\Scripts\python.exe viralclips.py --provider-check
```

### Start

```bat
start.bat
```

Starts the background worker and the API, waits for the API to answer, and
opens <http://127.0.0.1:8799>. The worker keeps processing while the browser
is closed.

### Stop

```bat
stop.bat
```

Stops both services and nothing else.

### Restart

```bat
restart.bat
```

Stops and starts. Queued work is stored in SQLite and survives.

### Check

```bat
health-check.bat
```

Verifies Python, FFmpeg, package imports, the AI provider (one real
authenticated request), the API, the worker and free disk space. Prints
`HEALTHY` and exits 0, or prints `UNHEALTHY` and exits 1. It never starts or
stops anything.

### From a terminal

```bat
.venv\Scripts\python.exe -m viralclips_app.service_control start --services api worker
.venv\Scripts\python.exe -m viralclips_app.service_control status
.venv\Scripts\python.exe -m viralclips_app.service_control stop
```

---

## 9. Troubleshooting

**The browser shows "Request rejected. Reload the application and retry."**
The API mints a fresh token when it restarts. The dashboard refreshes the
token and replays the request automatically. If it still fails, reload once.

**A job is stuck in "running".**
The worker reclaims interrupted jobs when it starts. To force it:
`stop.bat` then `start.bat`.

**The worker is not running.**

```bat
.venv\Scripts\python.exe -m viralclips_app.service_control status
.venv\Scripts\python.exe -m viralclips_app.service_control start --services worker
```

**A job failed with "No candidates were found."**
The source had no moment long enough to qualify. The minimum clip length is
15 seconds (`min_clip_seconds`); a shorter source cannot produce a clip. This
is reported honestly rather than silently.

**A job failed with "No speech and no media evidence."**
The source has neither usable speech nor usable visual activity, so there was
nothing to score.

**An orphan process is holding the port.**

```bat
.venv\Scripts\python.exe -m viralclips_app.service_control free-port 8799
```

**What actually happened.** The service logs are the record:

```
data\logs\worker.out.log     the worker's narration of every job
data\logs\worker.err.log      errors and FFmpeg output
data\logs\api.err.log         API errors
```

**Orphaned processes after a crash.**

```bat
.venv\Scripts\python.exe cleanup_orphans.py --dry-run
```

Inspects each Python process's command line and only terminates ones that
belong to this project.

**A database restore refuses.**
On Windows a running worker or API holds the database open and the file
cannot be replaced. Stop the services first: `stop.bat`, restore, then
`start.bat`.

---

## 10. Known limitations

1. **No live publishing has been performed.** The safety gates are verified;
   the actual upload to YouTube and Instagram has not been attempted, because
   no credentials exist. Until then the honest status is
   `awaiting_credentials`.
2. **Instagram additionally needs a public media URL.** The Graph API cannot
   fetch a file from a loopback address, so `VIRALCLIPS_PUBLIC_MEDIA_URL` must
   point at a publicly reachable HTTPS host.
3. **Groq publishes no embedding model.** The catalogue available to this key
   contains zero `text-embedding-*` entries, so semantic search needs a
   different, funded provider. Keyword search is fully local and needs none.
4. **Audience-retention and live performance metrics are not ingested.**
   Without an authorized analytics account the dashboard reports them as
   unavailable rather than fabricating them.
5. **`llama-3.3-70b-versatile` is gone from Groq** (decommissioned
   2026-08-16; it now returns `HTTP 404 model_not_found`). The default is
   `openai/gpt-oss-120b`.
6. **Enabling an external provider breaks an upstream privacy property.**
   Chopify's stated property is "no hosted inference, no API key, nothing
   uploaded". Routing the reranker through Groq means transcript and candidate
   text leave the machine. This is a deliberate decision for VIRALCLIPS AI,
   not a silent change.
7. **The application's minimum clip length is 15 seconds.** Sources shorter
   than that cannot produce a clip and are reported as such.
8. **The service control is Windows-specific.** The process model — launcher
   shims, CIM-based ownership checks, `taskkill` semantics — is Windows-only
   by design.
9. **A technical pipeline is not proof of audience appeal.** The long-video
   run proves the workflow, not that the resulting clips will perform well on
   a real platform.

---

## 11. The original project

The pre-migration project at `C:\Users\dalvi\ViralClipsAI` **has not been
deleted.** It is retained as the untouched reference copy. See
[`MIGRATION_REPORT.md`](MIGRATION_REPORT.md).

The upstream engine's own documentation is preserved verbatim in
[`docs/CHOPIFY_ENGINE.md`](docs/CHOPIFY_ENGINE.md), alongside
[`docs/WORKFLOWS.md`](docs/WORKFLOWS.md),
[`docs/CLI.md`](docs/CLI.md) and
[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

---

## 12. Related documents

| Document | Contents |
| --- | --- |
| [`README.md`](README.md) | The operating guide |
| [`MIGRATION_REPORT.md`](MIGRATION_REPORT.md) | How the project moved to its current folder, and what was preserved |
| [`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md) | The platform architecture and why it is shaped this way |
| [`docs/PROVIDER_SETUP.md`](docs/PROVIDER_SETUP.md) | Groq, the OpenRouter fallback, credentials, model selection |
| [`docs/CHOPIFY_ENGINE.md`](docs/CHOPIFY_ENGINE.md) | The upstream engine's documentation, preserved |
