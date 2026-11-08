# VIRALCLIPS AI — Development Plan

## Goal
Turn the working Chopify-based clipping pipeline into a complete, locally
hosted autonomous clipping application with a premium dashboard, a
persistent background worker, channel monitoring, clip review, and
YouTube/Instagram publishing.

## Guiding constraints
- **Preserve the working engine.** Chopify 1.4.0, faster-whisper, FFmpeg and
  the Groq adapter stay exactly as they are. The application *calls* them.
- **No Ollama, no local LLM, no n8n, no Hermes, no cloud hosting.**
- **No fake data.** Every number on the dashboard comes from the database.
  Every "connected" badge reflects a real OAuth token, not a placeholder.
- **No placeholder buttons.** A control that cannot act is not shipped.
- **Never expose credentials.**

## Architecture decision: backend stack

The brief recommends FastAPI + SQLite + SQLAlchemy. Rationale:

- **FastAPI** — async job dispatch plus native OpenAPI docs at `/docs`,
  which the brief explicitly requires. FastAPI's dependency injection maps
  cleanly onto the existing plain-function upstream code.
- **SQLite via SQLAlchemy** — a single local file, zero server to install,
  survives restarts, and gives the migration story the brief asks for.
  SQLAlchemy (not raw sqlite3) so models are declarative and migrations
  are real.
- **SSE rather than WebSockets** — job updates are one-directional
  (server → browser). SSE needs no extra client library and survives
  reconnection natively.

### Architecture decision: frontend stack

The brief says "React/Next.js if compatible" but also "reuse the existing
frontend if one exists". The existing `assets/studio/` is a hand-written
vanilla JS/CSS app with no build step — no React, no bundler, no
`node_modules`. Introducing Next.js would mean:

- a Node toolchain the project does not currently have,
- a build step in `start.bat` (slow start, new failure mode),
- a large rewrite of working, tested UI code.

**Decision: a single-page vanilla JS/CSS frontend served by FastAPI**, in
the same idiom as the existing Studio app, with a shared design-system
stylesheet. It matches the existing codebase's conventions, starts
instantly, has no build step, and keeps the working Studio intact. The
existing `assets/studio/` app stays untouched as the upstream Studio.

### Architecture decision: worker separation

The brief requires that processing continues when the browser closes. A
worker thread inside the API process would die with it. So the worker is a
**separate OS process** (`worker.py`) polling the same SQLite database for
queued jobs. `start.bat` launches it; `stop.bat` stops it. The API and
worker share only the database, so either can be restarted independently
and the queue survives.

## Module layout

The layout below is what actually shipped. The API is a single module
rather than a package of route modules: the route count stayed under
fifty, and keeping them together made it possible to see the whole
contract in one place. Splitting it later is a mechanical change.

```
viralclips_app/
  __init__.py
  config.py         settings, paths, ports, provider/model defaults
  db.py             engine, reentrant session_scope, additive column sync
  models.py         SQLAlchemy models
  schemas.py        Pydantic request/response models
  security.py       local API token, OAuth credential access
  ai.py             provider health (wraps providers.adapter)
  pipeline.py       video processing service (wraps projects.run_project)
  publishing.py     YouTube + Instagram publishing services
  monitor.py        channel monitoring service (official RSS / Data API)
  jobs.py           durable job queue helpers
  storage.py        database backup/restore, storage cleanup, disk report
  main.py           all FastAPI routes + the served frontend
  static/
    index.html  app.js  styles.css
worker.py           standalone background worker process
run_api.py          API entry point
cleanup_orphans.py  command-line-verified cleanup of this project's orphans
```

### Architecture decision: storage management

`storage.py` was added after the initial release because a daily-use
local application needs three things the first version lacked:

- **Backup** uses SQLite's *online backup API*, not a file copy. The
  database runs in WAL mode, so the main file alone is not a consistent
  snapshot; a plain copy can silently miss recent transactions.
- **Restore** validates the candidate file before replacing anything and
  takes a safety backup of the live database first, so a restore is
  always reversible. It disposes the SQLAlchemy connection pool before
  replacing the file, because Windows refuses to unlink a file that still
  has an open handle.
- **Cleanup** removes old unpublished media only. An approved clip, a
  published clip, and anything inside the retention window are never
  deleted, and the default is a dry run.

## Architecture decision: Windows service lifecycle

On Windows the virtual environment's `python.exe` is a **launcher shim**. It
spawns the real interpreter as a *child* and then waits for it. Each service
is therefore two processes, and the service records the real child's PID,
because stopping the shim would not stop the service.

`taskkill /T` kills descendants but not parents, so stopping the recorded
child alone leaves the shim running — a stray process that outlives
`stop.bat`. `service_control._launcher_parents()` walks the parent chain
through Windows CIM to find it.

**Ownership is never decided by the parent-child relationship alone.** Before
any process is terminated, two independent facts must both hold:

1. the executable is *this project's* `.venv\Scripts\python.exe`, **and**
2. the command line names one of *this project's* service entry points
   (`worker.py` or `run_api.py`).

Another application with the same shim-and-child shape — a different virtual
environment running the same launcher — fails both tests and is never
touched. The invariant the test suite asserts is precise: *the only
processes that disappear during a stop are the application's own*.

The batch scripts avoid `timeout`, which requires a real console and answers
`Access is denied.` in a non-interactive session; the pause is taken with
Python instead. The browser launch goes through PowerShell for the same
reason.

## Build order

1. **Foundation** — config, db, models, migrations, security.
2. **API** — all REST endpoints, SSE event stream.
3. **AI service** — explicit reranker invocation (never heuristic-only
   while claiming AI success).
4. **Pipeline service** — thin wrapper over `projects.run_project`.
5. **Worker** — separate process, job queue, retry, cancellation.
6. **Publishing services** — YouTube OAuth + upload; Instagram OAuth +
   Reels. Both mark themselves "awaiting credentials" until configured.
7. **Channel monitor** — YouTube Data API RSS-based detection.
8. **Frontend** — design system + 12 screens, all wired to real data.
9. **Startup scripts** — start/stop/restart/health-check.
10. **Tests** — new functionality, keeping all 362 existing tests green.
11. **Storage management** — backup, restore, cleanup, disk reporting.
12. **Report**.

## Verification gates

All of these are met. The final figures are in
[`../FINAL_VERIFICATION_REPORT.md`](../FINAL_VERIFICATION_REPORT.md).

- Every pre-existing test still passes. Baseline 362, final **646 passed,
  0 failed, 3 warnings**. No test was weakened, skipped or removed;
  `git diff --stat` against the upstream commit shows only `.gitignore` and
  `requirements.txt` changed.
- New tests cover the API, worker, AI service, publishing guards, storage
  management, filename sanitisation and the frontend structure.
- The app starts with `start.bat`, serves the UI, processes a real video,
  and stops cleanly with `stop.bat` — over three full lifecycle cycles, with
  all four application processes exiting and no unrelated process harmed.
- A leak scan proves no credential reaches logs, responses, or the repo.
- `health-check.bat` reports the truth: `HEALTHY` and exit 0 only when the
  API and the worker are both alive.

## Rights and content policy (from the brief, §6 and §10)

The brief is explicit that a public channel URL is not permission to
download and republish. The implementation therefore:

- defaults every YouTube task to **not** ingesting third-party videos
  unless the user supplies the source file themselves or explicitly
  confirms they hold the rights,
- requires an explicit rights attestation before any automated ingestion
  of a remote channel,
- never auto-publishes without an explicit approval,
- keeps publishing disabled until OAuth is genuinely connected.

## Provider and model are separate things

The application reports the provider by name and the model by id, and
never conflates them:

- `groq` is the **provider** — the company serving the request.
- `openai/gpt-oss-120b` is the **model** Groq serves. The `openai/` prefix
  is part of the model id, not the provider.

The upstream Chopify engine writes an internal selection mode of `ollama`
for *any* LLM-reranked run, because that is the shape of the call it
makes. That string is kept as `upstream_mode` for diagnostics and is
never presented to the user as the provider. A clip's `ai_provider` is
recorded only when the provider actually returned usable reranker
adjustments; a run that degraded to the heuristic scorer records no
provider and says so in the log and on the dashboard.
