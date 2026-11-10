# V3 Editor Evaluation Report

Date: 2026-11-09
Project: VIRALCLIPS AI

## 1. Repository information

### Elah
- **URL:** https://github.com/elahlabs/elah
- **License:** Apache 2.0 (verified from LICENSE file)
- **Technologies:** React, TypeScript, monorepo (npm workspaces), Rollup, Vite
- **Description:** Motion graphics engine. "Write motion as code. It stays editable." Converts HTML/CSS scenes into native clips and keyframes on a timeline.
- **Packages:** @elah/core, @elah/react, @elah/timeline, @elah/editor, @elah/cli, @elah/react-native
- **Export:** MP4 export runs in the browser tab (no server)
- **Maintenance:** Active (version 1.0, recent commits, Discord community)

### Framecut
- **URL:** https://github.com/rogangriffin/videotimelineeditor
- **License:** NONE — no LICENSE file found
- **Technologies:** React 19, TypeScript, Vite, Node.js 22+, ffmpeg-static, ffprobe-static, mediabunny, lucide-react
- **Description:** Local video timeline editor. Arrange video, audio, and still images in the browser, save projects on disk, render MP4 through background FFmpeg queue.
- **Maintenance:** Active (recent commits)

### React Video Editor (additional candidate)
- **URL:** https://github.com/etcyl/react-video-editor
- **License:** NONE — no LICENSE file found
- **Technologies:** React 18, Vite 5, ffmpeg.wasm
- **Description:** Browser-based video editor. Drag and drop import, multi-track timeline, titles, transitions, export via ffmpeg.wasm.
- **Maintenance:** Low (0.1.0, limited commits)

## 2. License verification

| Repository | License | Can we use it? | Legal risk |
|---|---|---|---|
| Elah | Apache 2.0 | Yes | None — modification and redistribution permitted with attribution |
| Framecut | None (all rights reserved) | **No** | High — cannot copy or modify without permission |
| React Video Editor | None (all rights reserved) | **No** | High — same legal barrier |

**Critical finding:** Framecut and React Video Editor have no license. Under copyright law, code without a license is "all rights reserved." We cannot legally copy, modify, or distribute their code. Integrating them would violate the copyright holder's rights.

## 3. Feature comparison

| Feature | Elah | Framecut | React Video Editor |
|---|---|---|---|
| Full video playback | Yes (browser) | Yes (browser) | Yes (browser) |
| Video import | Yes (media files) | Yes (video, audio, images) | Yes (drag & drop) |
| Multi-track timeline | Yes (clips + keyframes) | Yes (video, audio, stills) | Yes (V/A lanes) |
| Trim | Yes (clip boundaries) | Yes | Yes |
| Split | Yes | Yes | Yes |
| Move clips | Yes | Yes | Yes |
| Crop | Limited (motion transforms) | Yes | Yes |
| Resize | Yes (keyframes) | Yes | Yes |
| Rotate | Yes (keyframes) | Yes | Yes |
| Audio controls | Yes | Yes | Yes (volume) |
| Captions/text overlays | Yes (motion text) | Limited | Yes (titles, Google Fonts) |
| Undo/redo | Yes (keyframes) | Unknown | Unknown |
| Project persistence | Yes (Project document) | Yes (disk) | No (browser only) |
| MP4 export | Yes (browser, FFmpeg) | Yes (FFmpeg queue) | Yes (ffmpeg.wasm) |
| Performance with long videos | Unknown | Unknown (needs testing) | Limited (browser WASM) |
| React integration | Native (@elah/react) | React 19 app | React 18 app |
| FFmpeg compatibility | Browser-based | Native (ffmpeg-static) | WASM (@ffmpeg/ffmpeg) |
| Long-term maintainability | Active (Discord, docs) | Unknown (single developer) | Low (0.1.0) |

## 4. What each editor actually is

### Elah
- A **motion graphics engine**, not a traditional video editor
- You write motion as code (HTML/CSS) and it converts to clips/keyframes
- Designed for creating videos programmatically, not editing existing clips
- Has a timeline UI but it's for motion keyframes, not video editing
- Apache 2.0 licensed — legally safe to use
- **Does not do what we need**: trim, split, crop existing video

### Framecut
- A **traditional video timeline editor** — this IS what we need
- Video, audio, still image tracks
- Trim, split, move clips
- Save projects to disk
- Render MP4 via FFmpeg queue
- **But has no license** — cannot legally use

### React Video Editor
- A **browser-based video editor** — also what we need
- Drag and drop import, multi-track timeline
- Titles, fades, crossfades
- Export via ffmpeg.wasm
- **But has no license** — cannot legally use
- Also uses WASM which is slower than native FFmpeg

## 5. Integration complexity assessment

### If we could use Framecut (legally)
- **Complexity:** Medium-High
- React 19 app, would need to be embedded into our existing React frontend
- Native FFmpeg (better than WASM)
- Project persistence on disk (good)
- Would require significant integration work to connect to our backend

### Elah (legally available)
- **Complexity:** High
- Monorepo with 5 packages
- Motion graphics paradigm doesn't match our clip-editing needs
- Would require rewriting our editing workflow to fit Elah's model
- Not suitable for trimming existing video clips

## 6. Security concerns

- Framecut and React Video Editor: no license = cannot use
- Elah: Apache 2.0 = safe, but wrong product fit
- Elah's browser-based export runs FFmpeg in the browser — our application
  already has native FFmpeg, so browser-based export would be a downgrade

## 7. Final recommendation

**None of the three candidates are suitable for direct integration.**

1. **Framecut** and **React Video Editor** have no license → legally cannot use
2. **Elah** is legally available (Apache 2.0) but is a motion graphics engine,
   not a video editor for trimming/clipping existing video

### Recommended path forward

Instead of integrating an external editor, enhance the existing FFmpeg-based
trim + preview + approval workflow:

1. **Trim UI**: Add draggable trim handles to the existing `clipPlayer()`
2. **Subtitle editing**: Edit SRT text in the preview modal
3. **Crop/reposition**: FFmpeg crop filters with UI controls
4. **Aspect ratio**: Already supported (9:16, 1:1, 16:9)
5. **Undo/redo**: Command pattern on the existing timeline data

This avoids legal risk, leverages the working FFmpeg infrastructure, and
builds on the V2 intelligence + Clip Library + player + preview that
already works.

The `docs/EDITING_STUDIO_DESIGN.md` document outlines the full design
for this incremental enhancement.

### No code changes were made
No files were modified. The three candidate repos were cloned to a
temporary evaluation directory outside the project:
`$LOCALAPPDATA/hermes/cache/scratch/editor_eval/`