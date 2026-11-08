"""Launch the VIRALCLIPS AI API server and record its process id.

This exists so the Windows launcher can stop exactly this server later.
The process writes its own PID to ``data/api.pid`` on startup and removes
the file on a clean shutdown.

Run it with::

    .venv\\Scripts\\python.exe run_api.py
"""
from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viralclips_app import config  # noqa: E402

PID_FILE = config.DATA_DIR / "api.pid"


def _write_pid() -> None:
    config.ensure_dirs()
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(_remove_pid)


def _remove_pid() -> None:
    try:
        if PID_FILE.is_file() and PID_FILE.read_text(
                encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except OSError:
        pass


def main() -> int:
    import uvicorn

    _write_pid()
    uvicorn.run(
        "viralclips_app.main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        log_level="info",
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
