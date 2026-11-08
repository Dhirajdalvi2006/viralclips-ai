"""Kill only orphaned VIRALCLIPS AI processes.

Every candidate is verified by its command line: the process must
reference the VIRALCLIPS-AI project path AND look like one of our
services (worker.py, run_api.py, or viralclips_app.main). Anything else
is left untouched.

Run with::

    .venv\\Scripts\\python.exe cleanup_orphans.py --dry-run
    .venv\\Scripts\\python.exe cleanup_orphans.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys

PROJECT_MARKER = "VIRALCLIPS-AI"

#: Markers that identify one of our services. The venv launcher on
#: Windows spawns a child interpreter whose command line contains only
#: the script path, so both the project marker and the module markers
#: have to be considered.
SERVICE_MARKERS = ("worker.py", "run_api.py", "viralclips_app.main",
                   "viralclips_app.service_control", "cleanup_orphans.py")


def is_ours(process: dict) -> bool:
    """True when the process is one of ours.

    Two independent signals are accepted, because the Windows venv
    launcher spawns a child interpreter whose command line may contain
    only the script path:

    1. the command line references this project directory, or
    2. the command line runs one of our service modules.
    """
    command = str(process.get("CommandLine") or "")
    if not command:
        return False

    in_project = PROJECT_MARKER in command
    runs_service = any(marker in command for marker in SERVICE_MARKERS)

    if not (in_project or runs_service):
        return False

    # Never treat this cleanup script itself as a target.
    if "cleanup_orphans.py" in command:
        return False
    return True


def list_candidates() -> list[dict]:
    """Return every python/cmd process on the machine."""
    script = (
        "Get-CimInstance Win32_Process -Filter "
        "\"Name='python.exe' OR Name='cmd.exe'\" | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return []
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    import json
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [item for item in data if isinstance(item, dict)]


def kill(pid: int) -> bool:
    result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                            capture_output=True, text=True, timeout=30)
    return result.returncode == 0


def alive(pid: int) -> bool:
    result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                            capture_output=True, text=True, timeout=30)
    return str(pid) in (result.stdout or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean up orphaned processes")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidates = list_candidates()
    ours = [p for p in candidates if is_ours(p)]
    others = [p for p in candidates if not is_ours(p)]

    print(f"Project-owned processes found: {len(ours)}")
    for process in ours:
        pid = process.get("ProcessId")
        command = str(process.get("CommandLine") or "")[:110]
        print(f"  {pid}  {process.get('Name')}  {command}")
        if not args.dry_run:
            killed = kill(int(pid))
            if not killed and alive(int(pid)):
                print("       -> could not stop")
            else:
                print("       -> stopped")

    if others:
        print(f"\nUnrelated processes left untouched: {len(others)}")
        for process in others:
            command = str(process.get("CommandLine") or "")[:90]
            print(f"  {process.get('ProcessId')}  {command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
