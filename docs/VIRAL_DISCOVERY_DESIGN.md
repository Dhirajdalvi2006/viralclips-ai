# VIRAL DISCOVERY DESIGN

## Problem: why the current clips are poor

The existing intelligence layer (`viralclips_app/intelligence.py`) has these
weaknesses:

1. **The whole transcript is sent in one request.** For a 60-minute video
   the transcript is ~12,000 tokens. The model's attention degrades on
   long inputs and it picks moments near the end less reliably.

2. **No chunking with overlap.** A joke's setup and punchline can span
   two chunks. Without overlap the punchline is lost.

3. **No duplicate detection.** The same moment can be returned twice
   (once by the AI, once by the offline fallback) and both are rendered.

4. **Boundary snapping is naive.** `snap_to_utterance` moves boundaries
   to the nearest utterance edge within 1.5s, but does not check whether
   the resulting range contains a complete exchange.

5. **No quality gate.** Every candidate moment is rendered, including
   weak ones. The user asked for "fewer results rather than filling a
   quota with bad clips."

6. **No category diversity.** All moments are scored the same way; there
   is no preference for a mix of comedy, reaction, story, etc.

7. **No multi-pass ranking.** A single LLM call both discovers and ranks.
   A separate ranking pass over the candidates would improve quality.

## Improved design

### Phase 1 — Chunked analysis with overlap

Split the transcript into chunks of ~30 utterances with 5 utterances of
overlap. Analyse each chunk independently, then merge and deduplicate.

### Phase 2 — Multi-pass ranking

1. Discovery pass: find candidate moments in each chunk.
2. Enrichment pass: for each candidate, score the eight signals.
3. Ranking pass: sort by combined score, apply diversity (no two moments
   within 60s of each other), apply quality gate (minimum combined
   score of 40).

### Phase 3 — Boundary refinement

For each candidate:
- Snap start to the nearest utterance boundary within 2s.
- Snap end to the nearest utterance boundary within 2s.
- Ensure the range contains at least one complete exchange.
- Trim leading/trailing silence.

### Phase 4 — Quality gate

Reject a candidate if:
- Combined score < 40
- Duration < 12s or > 90s
- Transcript has fewer than 8 words
- Start or end falls inside a sentence

### Phase 5 — Duplicate detection

Two candidates are duplicates if:
- Their time ranges overlap by > 50%
- OR their transcript similarity (Jaccard on word sets) > 0.7

Keep the higher-scoring one.

## Implementation status

- Phase 1 (chunking): NOT YET IMPLEMENTED
- Phase 2 (multi-pass): NOT YET IMPLEMENTED
- Phase 3 (boundary refinement): PARTIALLY IMPLEMENTED (snap_to_utterance exists)
- Phase 4 (quality gate): PARTIALLY IMPLEMENTED (length checks exist)
- Phase 5 (duplicate detection): NOT YET IMPLEMENTED (repetition_penalty exists but is different)
