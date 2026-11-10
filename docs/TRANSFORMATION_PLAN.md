# Implementation Plan: VIRALCLIPS AI → Simple Video Editor + Publisher

## Goal
Transform from complex AI video editing platform to focused EDIT → CAPTION → PUBLISH application.

## Approach
1. Simplify frontend to 4 routes: Editor, Publish, History, Connections
2. Keep backend infrastructure (rendering, publishing, storage, auth)
3. Remove AI intelligence, channel monitoring, transcription, analytics
4. Reuse existing FFmpeg rendering engine and publishing APIs
5. Keep existing OAuth flows for YouTube/Instagram

## What to KEEP
- FFmpeg rendering engine (rendering/)
- Project CRUD (/api/projects)
- Export API (/api/export/*)
- Publishing API (/api/publishing/*)
- Storage/backup (/api/storage/*)
- Authentication (X-ViralClips-Token)
- OAuth flows for YouTube/Instagram
- Connected accounts management

## What to REMOVE/SIMPLIFY
- AI intelligence (intelligence.py) - keep detect_moments for auto-markers only
- Channel monitoring (monitor.py) - remove entirely
- Transcription (transcription/) - remove entirely
- Clip library/browser - simplify to single project workflow
- Dashboard/metrics - remove
- Job queue for clip generation - remove
- V2 intelligence scoring - remove

## Frontend Navigation (4 routes)
1. Editor - Upload, edit, preview, render
2. Publish - Caption, hashtags, platform selection, publish
3. History - Publishing history
4. Connections - OAuth account management

## Implementation Steps
1. Create new simplified index.html
2. Create new simplified app.js with 4 routes
3. Update main.py to remove unnecessary endpoints
4. Update tests
5. Update README

## Estimated Scope
This is a large transformation. Will implement incrementally.
