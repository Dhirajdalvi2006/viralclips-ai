# VIRALCLIPS AI -- V2 Intelligence Roadmap

> **Status: roadmap only. No V2 feature is implemented.**
> Every capability below is a *plan*. The code in this repository today is
> the verified V1.0.0 release. Nothing on the `v2-intelligence` branch
> changes how the application behaves.

---

## 1. Objective

Transform VIRALCLIPS AI from an **automatic video cutter** into an
**intelligent video moment discovery and clip-selection platform**.

V1 finds *candidate segments* by splitting a source into fixed windows and
scoring them. That is a good first cut, but it optimises for "a clip
existed here", not "this is the moment worth watching".

V2 changes the question from *"where are the cuts?"* to *"which moments
in this video are worth a person's attention, and why?"*.

The user-visible outcome is the same product -- a 1080x1920 short-form clip
with burnt-in captions -- but the selection, the boundaries, the ordering and
the captions become **informed decisions** rather than uniform defaults.

---

## 2. What V1 already does (the baseline V2 builds on)

These are verified and must not be rebuilt:

| Capability | V1 status |
|---|---|
| Chopify `1.4.0` rendering engine (9:16 H.264/AAC, poster, SRT, metadata) | Working, preserved |
| Faster-Whisper transcription with word-level timings | Working |
| Groq reranking via `openai/gpt-oss-120b`, with heuristic fallback | Working |
| FastAPI backend, SQLite (WAL) persistence, persistent worker | Working |
| SHA-256 duplicate upload rejection, FFmpeg upload validation | Working |
| Review / approval workflow, batch approval | Working |
| YouTube + Instagram publishing with approval and switch gates | Working, credentials pending |
| Channel monitoring via official YouTube RSS | Working |
| Storage backup, validated restore, cleanup | Working |
| 12-screen dashboard | Working |

V2 adds intelligence **around** the existing pipeline. The render stage does
not change.

---

## 3. Architecture constraints (non-negotiable)

V2 development must preserve all of the following:

- **The Chopify rendering engine** stays as the renderer. V2 decides *what*
  to render and *where the boundaries are*; Chopify still performs the
  transcode, the caption burn-in and the sidecar generation.
- **The FastAPI backend** stays. No rewrite into another framework.
- **SQLite and the persistent worker** stay. The queue, the job lifecycle
  and the recovery-on-restart behaviour are already correct.
- **The Groq integration** stays, including its credential lookup order and
  its honest degradation to heuristic scoring.
- **The existing frontend** is reused. V2 adds screens and fields; it does
  not replace the dashboard.
- **No n8n. No Hermes. No Ollama.** The platform is a local Python
  application and stays one.
- **No rebuilt V1 features.** If a V1 capability exists, V2 extends it.
- **Every V2 change keeps the test suite green.** V1 has 646 passing
  tests; V2 adds to that number and removes none.

### Honesty rules for V2

- **No claim of audience-retention data without authorized analytics.**
  Where no authorized analytics exist, V2 reports *estimated* engagement
  potential and labels it as such, in the UI and in the API payload, not
  only in a comment.
- **Estimated and measured never share a field.** A clip scored by a model
  carries `score_kind: "estimated"`; a clip with real analytics carries
  `score_kind: "measured"`.
- **No silent degradation.** If the AI reranker is unavailable, the clip is
  marked heuristic, exactly as V1 does today.

---

## 4. Planned capabilities

### 4.1 Context-aware moment detection

**Goal.** Find the *semantic* boundaries of a moment instead of sliding
fixed windows over the timeline.

**Approach.**
1. Build a transcript-level structure from the existing Whisper output:
   sentences, paragraphs, topic shifts.
2. Detect topic boundaries using lexical cohesion (TF-IDF over sliding
   windows) plus sentence-embedding similarity.
3. Propose candidate moments as contiguous, semantically coherent spans.
4. Discard spans that begin or end mid-utterance.

**Depends on.** 4.8 (embedding namespace). Groq publishes no embedding model,
so V2 needs either a second funded embedding provider or a local
sentence-transformer. Both remain open questions until a provider is chosen.

**Acceptance criteria.**
- A moment boundary never lands inside a spoken word.
- On a labelled sample of ten videos, boundary F1 is measured and reported
  against the label, not against the model's own output.

---

### 4.2 Comedy and punchline detection

**Goal.** Identify setup/punchline structures, which are the backbone of
short-form comedy clips.

**Approach.**
- Structure the transcript into candidate comedic units: setup, turn,
  punchline.
- Score with a mix of signals:
  - lexical: laugh tracks, "punchline markers", discourse markers
  - prosodic: energy and pitch peaks from the audio track
  - structural: a long setup followed by a short turn
  - semantic: an LLM judgement from Groq over the candidate span
- Combine into a calibrated `comedy_score` with the components exposed, so
  a reviewer can see *why* a clip was chosen.

**Depends on.** 4.1 for span boundaries.

**Acceptance criteria.**
- The score components are stored and returned by the API, not collapsed
  into a single unexplained number.
- A reviewer can override a comedy score, which feeds 4.9.

---

### 4.3 Reaction and emotional moment detection

**Goal.** Catch the human reaction, not just the spoken line. The reaction
is usually the clip.

**Approach.**
- Analyse the audio track for non-speech activity: laughter, gasps,
  screaming, overlapping speech, sudden silence.
- Align that activity to transcript spans.
- Detect visual reaction cues from the source frames: rapid motion, a
  change in shot size, a subject entering frame.
- Attach the detected cues to the enclosing moment as
  `reaction_cues: [...]`.

**Depends on.** 4.1.

**Acceptance criteria.**
- Reaction cues are timestamped against the source and are visible in the
  review screen.
- Nothing is inferred about a person's identity or attributes.

---

### 4.4 Hook detection

**Goal.** Predict whether the first few seconds of a clip will hold a
viewer, and choose the clip's opening frame deliberately.

**Approach.**
- Score the opening window of each candidate clip on:
  - speech onset timing (does the clip start mid-sentence?)
  - information density of the opening seconds
  - presence of a question, a claim, a number or a surprise
  - visual energy in the opening frames
- Where a hook candidate exists, propose a **reordered opening**: the
  strongest self-contained fragment moves to the front, and the clip's
  duration is adjusted accordingly.

**Depends on.** 4.1, 4.5.

**Acceptance criteria.**
- The hook decision is stored with its score, and the original moment
  boundaries are still recoverable.
- A clip with no detectable hook is marked as such rather than being
  silently reordered.

---

### 4.5 Intelligent clip boundaries

**Goal.** Cut on meaning, not on the clock.

**Approach.**
- Start from the moment spans produced by 4.1.
- Snap each boundary to the nearest word boundary, then to the nearest
  silence, so no cut lands mid-word or mid-syllable.
- Respect the existing `min_clip_seconds` and `max_clip_seconds` rules,
  which stay authoritative.
- Trim leading and trailing silence and filler.

**Depends on.** 4.1.

**Acceptance criteria.**
- No boundary lands inside a Whisper word span; this is asserted by a test.
- The `min_clip_seconds` behaviour that V1 already verifies is unchanged.

---

### 4.6 Multi-signal clip ranking

**Goal.** Replace the single V1 reranking score with a transparent,
multi-source ranking.

**Approach.** Combine, each with an explicit weight:
- AI rerank score (Groq)
- comedy score (4.2)
- reaction score (4.3)
- hook score (4.4)
- speech density and pacing
- visual motion energy
- keyword and topic importance
- duration fit for the target platform

**Depends on.** 4.1 to 4.4.

**Acceptance criteria.**
- The final score is a reproducible function of the stored components, with
  the weights recorded alongside the result.
- When the AI provider is unavailable, the ranking degrades to the
  non-AI signals and says so -- the same honesty contract V1 already
  meets.

---

### 4.7 Smart caption generation

**Goal.** Captions that read like a creator wrote them, not like a
transcript was dumped on screen.

**Approach.**
- Segment the caption track into *phrases*, not fixed-duration chunks, and
  keep them inside the safe area of the 1080x1920 frame.
- Apply an emphasis vocabulary to the words that carry the meaning.
- Preserve V1's existing caption style options; V2 adds a style that
  follows the detected emphasis.

**Depends on.** Nothing structural. This is the lowest-risk V2 item.

**Acceptance criteria.**
- Every caption line falls within the frame's safe area.
- Caption timing remains clip-relative, exactly as V1's verified artefacts
  are.
- The existing caption styles still render identically.

---

### 4.8 Duplicate moment detection

**Goal.** Stop the same moment appearing as several clips, and stop the
same source being processed twice in a way that produces identical output.

**Approach.**
- Embed every detected moment and compare within and across videos.
- Use a similarity threshold plus an overlap check on the source timeline.
- Present near-duplicates as a group with one representative, rather than
  silently dropping the others.

**Depends on.** An embedding provider (see 4.1). V1's SHA-256 upload
duplicate detection is separate and stays.

**Acceptance criteria.**
- Exact duplicates are always grouped.
- Near-duplicates are grouped with the similarity score shown.

---

### 4.9 Feedback-based ranking improvements

**Goal.** Let a reviewer's decision improve the next set of suggestions.

**Approach.**
- Record every approve/reject/edit decision, with the clip's feature
  components at decision time.
- Learn a per-user or per-channel weighting of the signals in 4.6 from
  those decisions.
- Apply the learned weighting to subsequent rankings, and always show
  the current weights.

**Depends on.** 4.6.

**Acceptance criteria.**
- Feedback changes ranking only after a stated minimum number of
  decisions, and the change is visible in the UI.
- The learning step is deterministic and unit-testable.
- Retraining never requires the feedback data to leave the machine.

---

### 4.10 Platform-specific clip optimization

**Goal.** Produce the right cut for the platform it is going to.

**Approach.** Per-platform profiles for YouTube Shorts and Instagram Reels:
- aspect ratio and safe area
- target duration band
- hook-length expectation
- caption density and placement
- title and hashtag generation

**Depends on.** 4.4, 4.5, 4.7.

**Depends on the existing publishing gates.** V1 already requires an
approved clip and an explicit publishing switch before anything is
published. V2 must not weaken that. **No live publish is performed during
V2 development or testing.**

**Acceptance criteria.**
- A platform profile change cannot bypass the approval gate.
- A generated title never asserts a claim that is not supported by the
  clip's own content.

---

## 5. Planned branch structure

```
main
  └── v1.0.0                       (verified V1 baseline -- frozen)

v2-intelligence                   (exists; starts from v1.0.0)
  ├── feature/moment-detection
  ├── feature/context-analysis
  ├── feature/clip-ranking
  ├── feature/hook-detection
  └── feature/smart-captions
```

Only `v2-intelligence` exists today. The five feature branches are
created when their work actually starts -- not speculatively.

**Rules.**
- `main` stays frozen at the V1.0.0 release for the whole of V2
  development.
- Feature branches are cut from `v2-intelligence`, not from `main`.
- `v2-intelligence` merges into `main` only at a V2 release, with a new
  tag.

---

## 6. Phasing

| Phase | Content | Gate |
|---|---|---|
| 0 | V1 baseline | **Done.** 646 tests, V1.0.0 tagged and pushed. |
| 1 | Transcript structure, context-aware boundaries (4.1, 4.5) | Boundary F1 measured against a labelled sample |
| 2 | Scoring signals (4.2, 4.3, 4.4) | Component scores stored and visible in review |
| 3 | Multi-signal ranking (4.6) | Reproducible from stored components; heuristic path preserved |
| 4 | Captions and duplicates (4.7, 4.8) | Safe area asserted; duplicate grouping correct |
| 5 | Feedback loop and platform profiles (4.9, 4.10) | Approval gate still enforced; no live publish |
| 6 | V2 release | Full suite green, `main` frozen, new tag |

Each phase is releasable on its own. A phase that cannot be completed
honestly is deferred, not faked.

---

## 7. Open questions

These are decisions, not implementation. They are listed because guessing
them would be the fastest way to build the wrong thing.

1. **Embedding provider.** Groq publishes no embedding model. Options: a
   second funded API provider, or a local sentence-transformer. The local
   option keeps every byte on the machine and fits the "no cloud hosting"
   constraint better, at the cost of a model download.
2. **Feedback scope.** Per-user, per-channel, or per-topic weighting? Each
   has a different privacy and cold-start story.
3. **Labeled sample.** Phases 1 and 2 are only measurable against a
   hand-labelled set of moments. Producing that sample is human work and
   has not been started.
4. **Audio feature extraction.** Emotion and reaction detection need
   consistent audio features. The dependency set for that is not yet
   chosen.
5. **Multi-language sources.** The current pipeline handles English
   transcription well. Moment detection would need to work across the
   languages a user actually uploads.

---

## 8. What V2 will not do

- It will not claim audience-retention analytics it does not have.
- It will not weaken the approval and publishing gates.
- It will not replace the Chopify renderer, the FastAPI backend, the
  SQLite store, the persistent worker, the Groq integration or the
  existing dashboard.
- It will not introduce n8n, Hermes or Ollama.
- It will not remove or weaken a single existing test.
- It will not perform a live publish during development or testing.
