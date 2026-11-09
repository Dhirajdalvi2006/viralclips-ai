# EDITING STUDIO DESIGN

## Status: NOT IMPLEMENTED

The editing studio is a major feature that requires significant frontend
and backend work. This document describes the design for future
implementation.

## Layout

```
+--------------------------------------------------+
|  LEFT PANEL     |  CENTER (preview)  | RIGHT PANEL |
|  - Project clips|  - Vertical video  | - Properties|
|  - Moments      |  - Timeline bar    | - Crop      |
|  - Captions     |  - Play controls   | - Subtitles |
|  - Music        |  - Fullscreen      | - Text      |
|                 |                    | - Export    |
+--------------------------------------------------+
|  BOTTOM: Timeline editor                        |
|  [Video track] [Audio track] [Subtitle track]   |
|  Playhead | Start marker | End marker            |
+--------------------------------------------------+
```

## Existing infrastructure that can be reused

- `clipPlayer()` in `app.js` — custom video player with transport controls
- `/media/clip/{id}` — byte-range streaming
- `/media/clip/{id}/poster` — real poster frames
- `openClipPreview()` — modal with player + detail + actions
- FFmpeg for rendering
- Chopify engine for clip rendering
- SQLite for persistence

## What needs to be built

1. **Timeline data model** — store trim points, crop, speed, subtitle
   overrides, text overlays as JSON in a new `editing_projects` table.
2. **Timeline UI** — draggable playhead, trim handles, track display.
3. **Subtitle editor** — edit individual subtitle text and timing.
4. **Export pipeline** — FFmpeg command builder from timeline instructions.
5. **Undo/redo** — command pattern with history stack.

## Estimated effort

This is a 4-6 week feature. The current V2 intelligence + Clip Library +
player + preview + approval workflow is the foundation. The editing
studio builds on top of it.

## Recommendation

Before building the editing studio, improve the moment detection
algorithm (Phase 1 of VIRAL_DISCOVERY_DESIGN.md). Better moment
selection will have more impact than manual editing on poor clips.
