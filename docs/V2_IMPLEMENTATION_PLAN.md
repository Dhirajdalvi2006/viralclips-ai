# V2 Intelligence — Implementation Plan

Branch: `feature/v2-intelligence` (from `v2-intelligence`, which starts
from the tagged V1.0.0 baseline `3803425`).

`main` is protected and is not touched by this work.

## Phase 1 — findings from the existing code

| Area | What already exists | What is missing |
|---|---|---|
| Monitoring | `Channel`/`Episode` tables, official RSS + Data API detection, duplicate guard on `video_id`, `/api/channels` CRUD, `/api/channels/{id}/check` | Handle (`@name`) resolution needs a Data API key; **no YouTube API key is configured**, so `@handle` inputs currently fail |
| Clip media | `/media/clip/{id}` returns `FileResponse` with an `Accept-Ranges` header | **Starlette's `FileResponse` does not implement byte ranges.** The header is a lie, so seeking does not work in the browser |
| Posters | `pipeline.py` adopts `<clip>.png` if Chopify happened to write one | No guaranteed poster; no FFmpeg frame extraction; no fallback |
| Clip Library | A `clips` route renders a plain card grid | No filters, no sorting, no score/signal detail, no dedicated preview experience |
| Player | The `editor` route embeds a bare `<video controls>` | No transport controls, no speed control, no fullscreen, no time display |
| Intelligence | Upstream Chopify picks fixed windows and reranks them | No context-aware moment detection, no multi-signal score, no per-signal explanation |

## Phase 2 — monitored channels

- Add a public-page identity resolver so a `@handle` can be resolved to its
  real `UC…` id without a Data API key, and validated through the official
  RSS feed. The Data API stays preferred when a key exists.
- Seed **India's Got Latent** and **Samay Raina** through the existing
  channel-management API, using the ids resolved and validated live.
- Record the **real** channel name returned by YouTube.
- Add an explicit authorisation state to every episode: detected uploads
  are never downloaded or processed automatically. Detection is not
  permission.

## Phase 3 — V2 intelligence

New module `viralclips_app/intelligence.py`:

- Build utterance-level structure from the Whisper word timings.
- Ask Groq to identify interesting moments with their boundaries and a
  per-moment judgement of comedy, reaction, hook quality and context
  completeness.
- Compute eight named signals, combine them into a 0–100 score, and store
  the components so the score is explainable and reproducible.
- Never report the result as predicted views; it is an **estimated
  engagement potential**. `score_kind` is always `estimated`.
- Fall back to the V1 path unchanged when no provider is available.

## Phase 4 — the clip viewer

New module `viralclips_app/media.py`:

- A real byte-range media endpoint (206 + `Content-Range`, 416, streamed
  in chunks so a whole clip is never held in memory).
- Path resolution confined to the application's own clip directory.
- Guaranteed poster generation via FFmpeg, with a graceful fallback.

Frontend: upgrade the `clips` route into a Clip Library with filters and
sorting, and the `editor` route into a Clip Preview screen with a full
player (play/pause, scrub, time, volume, speed, fullscreen).

## Phase 5 — preview everywhere

A Preview action is added to every screen that shows a clip: the Clip
Library, the queue, job details, recent clips and the review queue.

## Phase 6 — tests and verification

New suites for media, intelligence and channels, plus the full V1
regression suite (646 tests) and a live browser-level playback check.

## Phase 7 — documentation

Update the README, the V2 roadmap and the development plan to describe
what is implemented and what still needs credentials or authorisation.
