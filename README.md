# VIRALCLIPS AI

**Turn long videos into scored, vertical, captioned clips — on your own Windows machine.**

VIRALCLIPS AI is a local desktop web application. You give it a video (a file
you own, a URL you have permission to process, or a channel you monitor), and
a persistent background worker transcribes it, finds the moments most likely
to hold attention, renders them as 1080×1920 clips with burnt-in captions,
and puts them in a review queue where you approve, reject, download or
publish them.

Nothing is uploaded anywhere. The database, the clips and the queue all live
in a folder on your disk.

> **Under the hood:** the video engine is [Chopify](https://github.com/mehbul/chopify)
> 1.4.0 (`mehbul/chopify`), used unmodified. Its engine documentation is in
> [`docs/CHOPIFY_ENGINE.md`](docs/CHOPIFY_ENGINE.md). VIRALCLIPS AI adds the
> application around it: a web dashboard, a durable job queue, a background
> worker, channel monitoring, publishing, and analytics.

---

## Table of contents

- [What it does](#what-it-does)
- [Requirements](#requirements)
- [Installation](#installation)
- [Starting and stopping](#starting-and-stopping)
- [Where your data lives](#where-your-data-lives)
- [AI provider setup](#ai-provider-setup)
- [Daily use](#daily-use)
- [Channel monitoring](#channel-monitoring)
- [Publishing](#publishing)
- [Recovery and troubleshooting](#recovery-and-troubleshooting)
- [Running the tests](#running-the-tests)
- [Backup](#backup)
- [What is verified and what is not](#what-is-verified-and-what-is-not)

---

## What it does

| Capability | Detail |
| --- | --- |
| **Local video input** | MP4, MKV, WebM, MOV, M4V, AVI. The file is validated on arrival, so a corrupt upload is refused immediately rather than failing a job minutes later. |
| **Transcription** | Faster-Whisper, running locally on the CPU. Word-level timestamps, so captions land on the words. |
| **Moment detection** | Audio and visual analysis across the *whole* video, then AI reranking. |
| **AI reranking** | Groq (`openai/gpt-oss-120b`) scores the candidates. If the provider is unavailable the run degrades to deterministic heuristic scoring and says so — it never pretends an AI ran. |
| **Rendering** | FFmpeg produces 1080×1920 H.264/AAC clips with burnt-in captions, an SRT file, a poster frame and a metadata sidecar. |
| **Background worker** | A separate OS process. Closing the browser does not stop it; a Windows restart does not lose the queue. |
| **Channel monitoring** | Official YouTube RSS (and the Data API when a key is configured) detect new uploads. Detection is separate from downloading: a remote download needs an explicit rights confirmation. |
| **Review and approval** | Approve, reject, batch-approve, download the MP4 or the SRT. |
| **Publishing** | YouTube Shorts and Instagram Reels over the official OAuth APIs, and only for clips you have approved. |
| **Analytics** | Only real, database-derived numbers. View and engagement figures are reported as unavailable unless you connect an authorized analytics account. |

---

## Requirements

| | |
| --- | --- |
| **OS** | Windows 10 or 11 (x64) |
| **Python** | 3.11 (the Python launcher, `py -3.11`, is used by `setup.bat`) |
| **FFmpeg** | 9.x recommended — must be on `PATH`, or placed in `.\ffmpeg\bin\` |
| **Disk** | ~3 GB free for the environment and models, plus room for your clips |
| **Network** | Only for the AI provider, YouTube monitoring and publishing. The video pipeline itself is fully offline. |

FFmpeg is the one hard external dependency. Everything else is installed by
`setup.bat`.

---

## Installation

From the project folder:

```bat
setup.bat
```

This will:

1. Locate Python 3.11 (via the `py` launcher, then `python`).
2. Verify FFmpeg is available.
3. Create `.venv\` and install everything from `requirements.txt`.
4. Import-check the engine and initialise the local database.

It never touches your clips, your database or your credential file.

To check the environment without changing anything:

```bat
setup.bat --check
```

### Manual installation

If you prefer to do it by hand:

```bat
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## Starting and stopping

```bat
start.bat        REM start the worker and the API, then open the browser
stop.bat         REM stop both services
restart.bat      REM stop, then start
health-check.bat REM verify every dependency and report a verdict
```

Then open **<http://127.0.0.1:8799>**.

The API reference is at <http://127.0.0.1:8799/docs>.

`health-check.bat` prints `HEALTHY` and exits 0 when the application is
running, and prints `UNHEALTHY` and exits 1 when it is not — a dead API or a
dead worker is a failure, not a warning. Only the AI provider is a warning,
because that one degrades gracefully to heuristic scoring. The check never
starts or stops anything.

### The same thing from a terminal

```bat
.venv\Scripts\python.exe -m viralclips_app.service_control start --services api worker
.venv\Scripts\python.exe -m viralclips_app.service_control status
.venv\Scripts\python.exe -m viralclips_app.service_control stop
.venv\Scripts\python.exe -m viralclips_app.service_control stop --services worker
```

Each service records its own PID in `data\api.pid` and `data\worker.pid`, so
stopping the application stops exactly those two processes and never touches
an unrelated Python or Node process on your machine.

On Windows the virtual environment's `python.exe` is a launcher shim that
spawns the real interpreter as a child, so each service is two processes.
Stopping uses the recorded PID **and** the shim's own PID. The shim is only
terminated when two independent facts hold: its executable is *this*
project's `.venv\Scripts\python.exe`, **and** its command line names one of
*this* project's service entry points (`worker.py` or `run_api.py`). A
parent-child relationship on its own is never enough to kill a process, so
another application with the same shim-and-child shape is never touched.

### Changing the port

Set `VIRALCLIPS_API_PORT` before running `start.bat`:

```bat
set VIRALCLIPS_API_PORT=9000
start.bat
```

---

## Where your data lives

```
data\
  database\viralclips.db   the queue, clips, tasks, channels, approvals
  videos\                   uploaded source files
  clips\                    rendered clips, posters, SRTs, metadata
  projects\                 per-video working folders (resumable)
  transcripts\              transcriptions
  logs\                     api.out.log, api.err.log, worker.out.log, worker.err.log
  api.pid, worker.pid       process IDs of the running services
```

The credential file lives **outside** the project, in
`%LOCALAPPDATA%\ViralClipsAI\credentials.env`, so it is never committed and
never travels with a copy of the project. Override the location with
`VIRALCLIPS_CREDENTIALS_FILE`.

---

## AI provider setup

Groq is the default provider. See [`docs/PROVIDER_SETUP.md`](docs/PROVIDER_SETUP.md)
for the full guide, including the OpenRouter fallback.

1. Create the credential file if it does not exist:

   ```bat
   if not exist "%LOCALAPPDATA%\ViralClipsAI" mkdir "%LOCALAPPDATA%\ViralClipsAI"
   notepad "%LOCALAPPDATA%\ViralClipsAI\credentials.env"
   ```

2. Put your key in it:

   ```
   GROQ_API_KEY=your-key-here
   ```

3. Verify it:

   ```bat
   .venv\Scripts\python.exe viralclips.py --provider-check
   ```

The provider name and the model name are reported separately. `groq` is the
provider; `openai/gpt-oss-120b` is the model Groq serves. The upstream
engine writes an internal selection mode of `ollama` for any LLM-reranked
run — that string is a legacy label from the engine and is never shown as
the provider.

Clip Review shows the attribution for each clip, with three distinct
answers:

| Shown | Meaning |
| --- | --- |
| `groq` + `openai/gpt-oss-120b` | An AI actually scored this clip |
| `not recorded` | The clip was AI-scored, but before provider attribution was stored |
| `none (heuristic only)` | The run degraded to the deterministic scorer |

---

## Daily use

1. **Add New Task** — choose a source (upload, URL, or channel), set the
   clip length, aspect, caption style and how many clips you want.
2. **Processing Queue** — watch real progress. The worker reports each
   stage: source, transcribe, analyse, score, render.
3. **Generated Clips** / **Clip Review** — preview each clip, read the
   transcript and the AI reasoning, approve or reject.
4. **Publishing** — publish an approved clip, or batch-approve and publish.
5. **Analytics** — real counts only.

You can close the browser at any point. The worker keeps going.

---

## Channel monitoring

**Channel Monitoring** → add a channel by its `.../channel/UC...` URL.

Monitoring uses YouTube's **official published RSS feed** (and the official
Data API when a key is configured). It does not scrape and does not bypass
any platform restriction.

Detection and ingestion are deliberately separate. Finding that a video
exists is not the same as holding the rights to download and republish it,
so automated remote ingestion requires an explicit rights confirmation on
the task. Without it, episodes are detected and listed, and nothing is
downloaded.

---

## Publishing

Publishing is off until two things are true: a platform is connected over
OAuth, and the clip is approved.

| Platform | Setup |
| --- | --- |
| **YouTube** | `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` in the credential file. Create an OAuth client in the Google Cloud console with the YouTube upload scope, and set the redirect URI to `http://127.0.0.1:8799/api/accounts/youtube/callback`. |
| **Instagram** | `INSTAGRAM_CLIENT_ID` and `INSTAGRAM_CLIENT_SECRET` in the credential file, plus `VIRALCLIPS_PUBLIC_MEDIA_URL` pointing at a publicly reachable HTTPS host for the media file. Instagram's Graph API cannot fetch a loopback address. |

Both are listed on the **Connected Accounts** screen with an honest status:
`awaiting_credentials` when the client is missing, `awaiting_authorization`
when the client is present but the account has not been authorized yet.

OAuth tokens are stored in the database and are never returned to the
browser. The frontend only ever sees a boolean saying whether a credential
exists.

---

## Recovery and troubleshooting

**The browser shows "Request rejected. Reload the application and retry."**
The API mints a fresh token when it restarts. The dashboard now refreshes
the token and replays the request automatically. If it still fails, reload
the page once.

**A job is stuck in "running".**
The worker reclaims interrupted jobs when it starts. To force it:

```bat
stop.bat
start.bat
```

**A job failed with "No candidates were found."**
The source had no moment long enough to qualify. The minimum clip length is
15 seconds, so a shorter source cannot produce a clip. This is reported
honestly rather than silently dropped.

**A job failed with "No speech and no media evidence."**
The source has neither usable speech nor usable visual activity, so there
was nothing to score.

**The worker is not running.**

```bat
.venv\Scripts\python.exe -m viralclips_app.service_control status
.venv\Scripts\python.exe -m viralclips_app.service_control start --services worker
```

**An orphan process is holding the port.**

```bat
.venv\Scripts\python.exe -m viralclips_app.service_control free-port 8799
```

**Checking what actually happened.** The service logs are the record:

```
data\logs\worker.out.log     the worker's own narration of every job
data\logs\worker.err.log      errors and FFmpeg output
data\logs\api.err.log        API errors
```

**Orphaned processes after a crash.** `cleanup_orphans.py` inspects each
Python process's command line and only terminates ones that belong to this
project. It supports `--dry-run`:

```bat
.venv\Scripts\python.exe cleanup_orphans.py --dry-run
```

---

## Running the tests

```bat
.venv\Scripts\python.exe -m pytest tests\ -q
```

The suite covers the upstream engine, the provider adapter, and the platform
(database, job queue, API routes, security, pipeline, frontend structure).
The frontend is checked with `node --check` and a structural test suite; a
separate live audit renders all twelve screens against a running API.

---

## Backup and storage management

### Back up the database from the dashboard

**Settings** → **Maintenance** → **Back up the database**.

The backup is a consistent snapshot taken with SQLite's online backup
API, not a byte-for-byte file copy — the database runs in WAL mode, so a
plain copy of the main file can miss transactions that are still in the
`-wal` sidecar. Backups are written to `data\backups\` as
`viralclips-<timestamp>-<label>.db`.

### Restore a backup

```bat
.venv\Scripts\python.exe -c "from viralclips_app import storage; print(storage.restore_database(r'<path to backup>.db'))"
```

The candidate file is validated first — it must be a readable SQLite
database containing the application's tables. A file that fails the check
is rejected and **nothing is changed**. When a restore does run, the
current database is backed up first, so a restore is always reversible.

On Windows the restore closes the database's pooled connections first,
because Windows refuses to replace a file that still has an open handle.
If the worker or the API is running and still holds the file, the
restore refuses with a clear message rather than corrupting anything.

### Clean up old media

**Settings** → **Maintenance** → **Clean up old media**.

The retention window comes from the **Keep artifacts (days)** field
(default 30). The button runs a dry run first and shows you exactly what
would be deleted; nothing is removed until you confirm.

Cleanup never deletes:

- a clip you have **approved** but not published,
- a clip that has been **published**,
- a clip inside the retention window.

It reports how many clips and videos it removed and how much space that
freed.

### Manual backup of everything

Everything worth keeping is in two places:

- `data\` — database, clips, projects, transcripts
- `%LOCALAPPDATA%\ViralClipsAI\credentials.env` — provider keys

Stop the worker first so the database is not being written while you copy
it:

```bat
stop.bat
xcopy data D:\backup\viralclips\data /E /I /H
copy "%LOCALAPPDATA%\ViralClipsAI\credentials.env" D:\backup\viralclips\
start.bat
```

The database uses SQLite in WAL mode. Copying `data\database\viralclips.db`
while the worker is running can produce a torn copy; stop the services
first.

### Disk space

The application refuses to start a job when the volume has less than
2 GB free, and says so in the job's error field rather than failing
halfway through a render. **Settings** → **Storage** shows the free
space, the per-directory sizes, and how many backups exist.

---

## What is verified and what is not

Read [`FINAL_VERIFICATION_REPORT.md`](FINAL_VERIFICATION_REPORT.md) for the
full, dated picture. In short:

**Verified by real execution:** the complete test suite (646 passed, 0
failed); the end-to-end video pipeline (transcription → Groq scoring →
rendering → database → API), worker restart and recovery, job cancellation
and retry, duplicate-upload prevention, corrupt-upload rejection, the
heartbeat, disk checks, the Windows start/stop/restart lifecycle over three
cycles, channel monitoring against a live official YouTube RSS feed, all
twelve frontend screens, provider reporting, and the publishing approval
gate.

**Not verified:** live YouTube and Instagram publishing (no OAuth
credentials are configured), and audience-retention figures (no authorized
analytics exist, so none are reported).

This application is **not** claimed to be production-ready. It is a working
local tool that has been exercised end to end.

---

## Documentation

| Document | Contents |
| --- | --- |
| [`FINAL_VERIFICATION_REPORT.md`](FINAL_VERIFICATION_REPORT.md) | What was tested, what the results were, what is still unverified |
| [`MIGRATION_REPORT.md`](MIGRATION_REPORT.md) | How the project moved from `C:\Users\dalvi\ViralClipsAI` to its current folder |
| [`docs/PROVIDER_SETUP.md`](docs/PROVIDER_SETUP.md) | Groq, the OpenRouter fallback, credentials, model selection |
| [`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md) | The platform architecture and why it is shaped this way |
| [`docs/CHOPIFY_ENGINE.md`](docs/CHOPIFY_ENGINE.md) | The upstream engine's documentation |
| [`docs/WORKFLOWS.md`](docs/WORKFLOWS.md) | The engine's workflow guide |
| [`docs/CLI.md`](docs/CLI.md) | The engine's CLI reference |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | The engine's troubleshooting guide |

## Licence

MIT. See [`LICENSE`](LICENSE).
