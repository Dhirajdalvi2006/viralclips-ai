# Migration Report

**Project:** VIRALCLIPS AI
**Migration date:** 7 November 2026
**From:** `C:\Users\dalvi\ViralClipsAI`
**To:** `C:\Users\dalvi\OneDrive\Desktop\VIRALCLIPS-AI`

---

## 1. Why the project moved

The original working copy lived at `C:\Users\dalvi\ViralClipsAI`. The
intended destination was on a `D:` drive, but **this machine has no `D:`
drive** — the volume does not exist and cannot be created without a
physical disk. Two `D:` locations were inspected and both were absent.

`C:\Users\dalvi\OneDrive\Desktop\VIRALCLIPS-AI` was chosen as the
destination instead: it is on the same volume, it is on the Desktop where
the user expects to find the application, and it is inside OneDrive, so the
project is backed up and synchronised with the rest of the user's files.

The migration was done as a **copy**, not a move. The original was left
completely intact and is still there today.

---

## 2. What was migrated

Everything that constitutes the project:

| Item | Migrated | Notes |
| --- | --- | --- |
| Git history | Yes | The full history is intact. `git log` shows the same commits in both locations. |
| Working tree | Yes | Every source file: the Chopify engine, `providers/`, `viralclips_app/`, `tests/`, `docs/`, `assets/`, `examples/`. |
| Upstream commit | Yes | `d576927` — `docs: link the CLI flag reference from the live site and llms.txt` |
| Engine version | Yes | Chopify `1.4.0` (`mehbul/chopify`), unmodified. |
| Tests | Yes | The upstream suite and the new platform suite both pass at the destination. |
| Provider integration | Yes | The Groq adapter and the credential loader, unchanged. |
| Documentation | Yes | `docs/`, `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `INSTALLATION_REPORT.md`. |
| Upstream README | Yes | Moved to `docs/CHOPIFY_ENGINE.md` with `git mv`, so the engine's documentation is preserved and the project root has its own `README.md`. |
| Configuration | Yes | The credential file lives outside the repository and was **not** copied into it — it stays at `%LOCALAPPDATA%\ViralClipsAI\credentials.env` and is found from either location. |

### What was deliberately *not* copied

- **`.venv\`** — a virtual environment contains absolute paths to the
  interpreter and to the packages it installed. Copying it to a different
  folder produces a broken environment. It was **recreated from scratch**
  at the destination with the same Python version and the same package
  versions.
- **Generated output** — `data\`, `projects\`, `clips\` and any downloaded
  media were not carried over. The application regenerates them.
- **Caches** — `__pycache__`, `.pytest_cache` and similar are machine
  specific.

---

## 3. The virtual environment

The environment was rebuilt rather than copied:

```
Python 3.11.9
```

Package versions were pinned from the destination environment and recorded
in `requirements-lock.txt`, so the environment can be reproduced exactly:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

Verified at the destination after the rebuild:

- Chopify `1.4.0` imports and reports its version correctly.
- FFmpeg `9.0.2` with `ffprobe`, `libx264`, AAC and `libass`.
- Faster-Whisper, CTranslate2, ONNX Runtime, Hugging Face Hub, NumPy,
  yt-dlp, OpenCV.
- The upstream and provider suites pass at the destination.
- Groq authenticates and answers a live request.

---

## 4. Verification performed at the destination

| Check | Result |
| --- | --- |
| Upstream engine tests | Pass |
| Provider adapter tests | Pass |
| Groq live authentication | HTTP 200, `"ok": true` |
| FFmpeg and ffprobe | Present, `9.0.2` |
| Chopify version | `1.4.0` |
| Git history | Identical to the source |
| Real end-to-end video run | Passes — transcribe, score, render, persist |

At the end of the release closeout (2026-11-08) the destination was
re-verified from scratch: **646 tests passed, 0 failed**, the Windows
start/stop/restart lifecycle passed over three cycles, the security audit
passed 86 checks, the live upload path passed 28 checks, and all twelve
frontend screens rendered. The full evidence is in
[`FINAL_VERIFICATION_REPORT.md`](FINAL_VERIFICATION_REPORT.md).

---

## 5. The original was kept

`C:\Users\dalvi\ViralClipsAI` still exists in full (495 MB) and was **not**
deleted. It is the reference copy: if anything about the destination is
suspect, the original is still there and still works.

**The original is still retained after the release closeout.** The migration
and the final verification are complete, and the destination has been
exercised end to end, but deleting the reference copy is the owner's
decision and was deliberately left to them.

**Recommendation:** keep it until the destination has been used for real
work — a few processed videos, a day of normal use — and only then delete
it. There is no rush, and nothing is at risk from keeping it.

To remove it later:

```bat
rmdir /s /q "C:\Users\dalvi\ViralClipsAI"
```

Do that only after confirming the destination is good. Nothing in the
destination depends on the original: the project is self-contained and the
credential file is shared from `%LOCALAPPDATA%`.

---

## 6. Consequences of the move

**Nothing functional changed.** The paths that matter are computed at
runtime, not hard-coded:

- The project root comes from `Path(__file__).resolve().parent.parent`.
- The data directory comes from `VIRALCLIPS_DATA_DIR`, defaulting to
  `<project>\data`.
- The credential file comes from `VIRALCLIPS_CREDENTIALS_FILE`, defaulting
  to `%LOCALAPPDATA%\ViralClipsAI\credentials.env`.

The one practical consequence: **the two copies have separate data
directories.** They do not share a library. If you find clips in one that
you expected in the other, that is why — the video library is per-folder,
while the AI provider key is machine-wide.

---

## 7. Summary

| Question | Answer |
| --- | --- |
| Where is the final project? | `C:\Users\dalvi\OneDrive\Desktop\VIRALCLIPS-AI` |
| Was the original deleted? | **No.** It is still at `C:\Users\dalvi\ViralClipsAI`, complete and working. |
| Is the migration complete? | Yes. History, source, tests, providers, docs and configuration all moved; the environment was recreated; the suite passes at the destination. |
| Was anything overwritten? | No. The destination did not exist before the migration. |
| Was the engine replaced? | No. Chopify `1.4.0` runs unmodified inside the new application. |
| Was the original deleted after the release closeout? | **No.** It remains as the reference copy. |
| Where is the final verification report? | [`FINAL_VERIFICATION_REPORT.md`](FINAL_VERIFICATION_REPORT.md) |
