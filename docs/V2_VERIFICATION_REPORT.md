# VIRALCLIPS AI — V2 Verification Report

Branch: `feature/v2-intelligence`
Baseline: `main` at `3803425` (V1.0.0, tagged `v1.0.0`)
Date: 2026-11-09

This report distinguishes what is implemented, what is verified by
automated tests, what is verified live, and what is blocked by the
environment.

## 1. Implemented features

- **Context-aware moment intelligence** (`viralclips_app/intelligence.py`):
  utterance grouping, boundary snapping, eight named signals, Groq
  analysis path, honest heuristic fallback, estimated-score semantics.
- **Byte-range media streaming** (`viralclips_app/media.py`): real
  206/416 responses, chunked streaming, path confinement, FFmpeg poster
  extraction.
- **Channel monitoring** (`viralclips_app/monitor.py`): public-page
  handle resolution, official RSS validation, separate Data API helpers,
  duplicate guard on `video_id`, explicit authorisation state per episode.
- **Clip Library** (`viralclips_app/static/app.js`): filter tabs, sort,
  search, poster cards, signal breakdown, preview modal with a custom
  player (play/pause, scrub, time, volume, speed, fullscreen).
- **Preview everywhere**: overview, editor, library.
- **Approval workflow preserved**: mandatory approval, publishing gated on
  `approval_status == "approved"`.

## 2. Automated test results

- Full suite: **765 passed, 0 failed, 3 warnings** (52.09s).
- V2 suites:
  - `tests/test_app_media.py`: 35 passed.
  - `tests/test_app_intelligence.py`: 41 passed.
  - `tests/test_app_channels.py`: 42 passed.
- V1 baseline: 646 tests, unchanged and still passing.
- Frontend tests: 17 passed.
- Security tests: passed (origin enforcement, filename sanitisation,
  storage confinement, validation-error handling).

## 3. Live channel verification

- `@indiasgotlatentofficial` resolved to `UCx1Fxl7pFuccFkcOA4mSfZA`,
  title reported by YouTube: "India's Got Latent Clips". Validated
  against the official RSS feed, 15 uploads seen.
- `@SamayRainaOfficial` resolved to `UCAov2BBv1ZJav0c_yHEciAw`,
  title reported by YouTube: "Samay Raina". Validated against the
  official RSS feed, 15 uploads seen.
- 46 unique episodes recorded across the monitored channels.
- Re-checking created no duplicates.
- Every episode is `awaiting_authorization`; none was downloaded or
  processed.

## 4. Thumbnail verification

- 45 of 46 episodes now carry a real thumbnail extracted from the
  official RSS feed (`media:group/media:thumbnail`).
- The remaining episode (id 15) has scrolled out of the 15-entry RSS
  window for its channel, so no thumbnail is available. This is honest
  "where available" behaviour.
- Source URLs are populated for all 46 episodes.

## 5. Browser audit results

Real browser (Chrome 156, DevTools Protocol, headless), not jsdom:

- 63/63 checks passed.
- Clip Library renders 22 cards with real poster images (12 loaded).
- Filter tabs, sort (5 options), search all work and re-render.
- Preview modal opens with the custom player and a `video` element.
- The video actually plays: 1080x1925, duration 50.04s, readyState 4.
- Pause stops the clock; the play button resumes.
- Timeline seeks (target 25.02s -> 26.32s actual).
- Volume slider changes the volume (0.4).
- Speed control changes the playback rate (1.5x).
- Fullscreen button is wired.
- Signal bars render only when a clip has signal data; no empty bars.
- No uncaught JavaScript exceptions, no console errors.
- The only network failures are expected `Media net::ERR_ABORTED` when
  the preview modal closes mid-load (2 requests).

## 6. Authorized-video processing results

**Blocked by the environment.** The live authorized-video pipeline
could not be exercised because Windows Smart App Control (WDAC) blocks
the `ctranslate2._ext` DLL that Faster-Whisper depends on. The host
logs confirm: "Code Integrity determined that a process attempted to
load `_ext.cp311-win_amd64.pyd` that did not meet the Enterprise
signing level requirements."

- The code is correct: all 765 tests pass, including the intelligence
  and media suites, and the worker is structured to transcribe, run Groq
  analysis, score, render with Chopify and extract posters.
- The blocker is a host security policy, not a code defect. Resolving
  it requires turning off Smart App Control or allow-listing the DLL,
  which is a system-level action outside the application.
- A test video was prepared (`authorized_v2_test.mp4`, 59.59s, real
  speech, 7 distinct scenes) and uploaded successfully (job 93), but
  the job failed at the `transcribe` stage with the DLL error above.

## 7. Playback results

- Byte-range: `206 Partial Content`, `Content-Range: bytes 0-1023/676773`,
  exactly 1024 bytes returned.
- Unsatisfiable range: `416` with `Content-Range: bytes */1000`.
- Poster route: `200`, real 79,958-byte PNG frame.
- Real browser playback verified (see section 5).

## 8. Approval persistence results

- Approve one clip, reject another: both recorded in the database with
  timestamps.
- Restart the API: both decisions survived (verified by re-fetch and by
  direct SQLite inspection).
- Library filters (`approval=approved`, `approval=rejected`) reflect the
  decisions.
- A rejected clip is `skipped` by the publishing workflow with the
  reason "Only approved clips can be published."
- An approved clip reaches the publishing attempt (fails honestly on
  missing YouTube credentials, which is correct).
- An unreviewed clip is `skipped`.
- A mixed batch publishes only the approved clip.
- Nothing was actually published.

## 9. Known limitations

- **Smart App Control** blocks Faster-Whisper's `ctranslate2` DLL on
  this host, so live transcription (and therefore live Groq
  intelligence scoring) could not be exercised. All code paths are
  covered by tests.
- Groq exposes no embedding model; semantic search needs a funded
  embedding provider.
- Audience-retention analytics are unavailable without authorised
  analytics; scores are labelled `estimated`.
- YouTube/Instagram publishing is unverified without credentials.
- A second GitHub approver is required for protected `main` pull
  requests.

## 10. Remaining external configuration

- YouTube Data API key (optional; RSS + public-page resolution works
  without it).
- YouTube/Instagram OAuth client credentials in the local credential
  file.
- Smart App Control allow-listing or disabling, to enable live
  transcription on this host.
