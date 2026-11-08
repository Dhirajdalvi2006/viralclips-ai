"""Service control helpers for the Windows launcher scripts.

``start.bat`` and ``stop.bat`` call this module instead of parsing
``netstat`` output in batch. Batch quoting for that is fragile, and this
way the logic is testable.

Commands::

    python -m viralclips_app.service_control status
    python -m viralclips_app.service_control stop
    python -m viralclips_app.service_control free-port 8799

Only processes this application started are touched. The service PIDs
come from ``data/api.pid`` and ``data/worker.pid``, which the services
write themselves.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import config

SERVICE_FILES = {
    "worker": config.DATA_DIR / "worker.pid",
    "api": config.DATA_DIR / "api.pid",
}


def _read_pid(name: str) -> int | None:
    path = SERVICE_FILES.get(name)
    if path is None or not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(value) if value.isdigit() else None


def _pid_alive(pid: int) -> bool:
    """True when a process with this id exists.

    ``os.kill(pid, 0)`` is NOT a safe probe on Windows: CPython maps it
    onto ``TerminateProcess``, so probing with it would kill the very
    process being inspected. The Windows implementation therefore asks
    the kernel directly through ``OpenProcess``.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int) -> bool:
    """Check a PID on Windows without disturbing the process."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5
    STILL_ACTIVE = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                  wintypes.DWORD(pid))
    if not handle:
        # Access denied means the process exists but belongs to another
        # user or is protected. That still counts as alive.
        error = ctypes.get_last_error()
        return error == ERROR_ACCESS_DENIED

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _project_processes() -> list[tuple[int, int, str, str]]:
    """Return every python process as (pid, parent_pid, executable, command).

    Uses the Windows CIM class through PowerShell. An empty list is
    returned when the query cannot be made, which is the safe answer:
    the caller then simply finds nothing to stop.
    """
    if os.name != "nt":
        return []
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "ForEach-Object { "
        "\"$($_.ProcessId)|$($_.ParentProcessId)|$($_.ExecutablePath)|"
        "$($_.CommandLine)\" }")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []

    rows = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        parts = line.split("|", 3)
        if len(parts) < 3:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), parts[2],
                         parts[3] if len(parts) > 3 else ""))
        except ValueError:
            continue
    return rows


#: The entry points this application starts. A launcher is only stopped
#: when it is running one of these.
_SERVICE_SCRIPTS = ("worker.py", "run_api.py")


def _normalise(path: str) -> str:
    """Lower-case a path and use one separator style."""
    return (path or "").lower().replace("/", "\\")


def _is_own_launcher(executable: str, command: str) -> bool:
    """True only when this process is unambiguously ours.

    A parent-child relationship on its own is never enough to justify
    killing a process. Two independent facts must both hold:

    1. The executable is *this project's* virtual environment
       interpreter -- ``<project>\\.venv\\Scripts\\python.exe``.
    2. The command line names one of *this project's* own service
       entry points, inside this project.

    A different virtual environment (BISmart, for example) can have the
    same shim-and-child shape and still fail both tests, so it is never
    touched.
    """
    root = _normalise(str(config.ROOT)).rstrip("\\")
    exe = _normalise(executable)
    cmd = _normalise(command)

    if exe != f"{root}\\.venv\\scripts\\python.exe":
        return False

    return any(f"{root}\\{script}" in cmd for script in _SERVICE_SCRIPTS)


def _launcher_parents(pid: int) -> list[int]:
    """Return the launcher parents that belong to this application.

    On Windows the virtual environment's ``python.exe`` is a shim: it
    spawns the real interpreter as a *child* and then waits for it.
    The service records the real child's PID, so stopping that PID with
    ``taskkill /T`` kills the child and its descendants but leaves the
    shim behind -- a stray process that outlives ``stop.bat``.

    The shim is the child's parent. It is only stopped when
    :func:`_is_own_launcher` confirms both the executable and the
    command line belong to this project.
    """
    if os.name != "nt":
        return []

    rows = _project_processes()
    by_pid = {row[0]: row for row in rows}

    parents = []
    current = pid
    for _ in range(3):                     # child -> shim -> launcher
        row = by_pid.get(current)
        if row is None:
            break
        parent_pid = row[1]
        parent_row = by_pid.get(parent_pid)
        if parent_row is None:
            break
        if parent_pid in parents:
            break
        if _is_own_launcher(parent_row[2], parent_row[3]):
            parents.append(parent_pid)
        current = parent_pid
    return parents


def _terminate(pid: int, timeout: float = 6.0) -> bool:
    """Stop a process, politely first, then forcibly."""
    if not _pid_alive(pid):
        return False
    try:
        if os.name == "nt":
            import subprocess
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    return not _pid_alive(pid)


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True when something is listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def status() -> dict:
    """Return the state of each service."""
    report = {}
    for name in SERVICE_FILES:
        pid = _read_pid(name)
        report[name] = {"pid": pid, "running": bool(pid and _pid_alive(pid))}
    report["api_port"] = config.API_PORT
    report["api_reachable"] = port_in_use(config.API_PORT)
    return report


def stop(services: list[str] | None = None) -> dict:
    """Stop the recorded services.

    ``services`` limits the shutdown to the named ones; by default every
    recorded service is stopped.
    """
    result = {}
    targets = services or list(SERVICE_FILES)
    for name in targets:
        path = SERVICE_FILES.get(name)
        if path is None:
            result[name] = {"stopped": False, "reason": "unknown service"}
            continue
        pid = _read_pid(name)
        if pid is None:
            result[name] = {"stopped": False, "reason": "not recorded"}
            continue

        # Collect the launcher shims before the service dies: once the
        # child is gone, its parent is no longer discoverable.
        launchers = _launcher_parents(pid)

        stopped = _terminate(pid)
        for launcher in launchers:
            if launcher != pid:
                _terminate(launcher)
        try:
            path.unlink()
        except OSError:
            pass
        result[name] = {"stopped": stopped, "pid": pid,
                        "launchers_stopped": launchers}
    return result


def free_port(port: int) -> dict:
    """Free a TCP port that is being listened on.

    Uses the Windows TCP table through PowerShell when available, and
    falls back to a socket-level check otherwise.
    """
    stopped = []
    if os.name == "nt":
        import subprocess
        # The script is built by concatenation, not by str.format: the
        # PowerShell body contains braces that format() would try to
        # interpret.
        script = (
            "$c=Get-NetTCPConnection -LocalPort " + str(port) +
            " -State Listen -ErrorAction SilentlyContinue; "
            "if($c){$c.OwningProcess | Sort-Object -Unique}")
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=20)
            for line in (result.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit() and int(line) > 0:
                    pid = int(line)
                    if _terminate(pid):
                        stopped.append(pid)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return {"port": port, "stopped": stopped,
            "still_in_use": port_in_use(port)}


def launch(services: list[str] | None = None) -> dict:
    """Start the API server and the background worker as detached processes.

    The services are started with ``DETACHED_PROCESS`` so they outlive
    this launcher and keep running after the browser is closed. Their
    real PIDs are written to the pid files, which is what ``stop`` uses.

    Output is appended to the service log files. The files are opened in
    append mode by Python rather than by shell redirection, because a
    previous run may still hold the file open.
    """
    services = services or ["worker", "api"]
    config.ensure_dirs()
    log_dir = config.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    targets = {
        "worker": [sys.executable, str(config.ROOT / "worker.py")],
        "api": [sys.executable, str(config.ROOT / "run_api.py")],
    }

    started = {}
    for name in services:
        command = targets.get(name)
        if command is None:
            continue

        # Stop any previous instance of this service first.
        existing = _read_pid(name)
        if existing and _pid_alive(existing):
            _terminate(existing)

        stdout_path = log_dir / f"{name}.out.log"
        stderr_path = log_dir / f"{name}.err.log"
        stdout_handle = open(stdout_path, "a", encoding="utf-8", buffering=1)
        stderr_handle = open(stderr_path, "a", encoding="utf-8", buffering=1)

        kwargs = {
            "cwd": str(config.ROOT),
            "stdout": stdout_handle,
            "stderr": stderr_handle,
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(command, **kwargs)
        except OSError as exc:
            stdout_handle.close()
            stderr_handle.close()
            started[name] = {"started": False, "error": str(exc)}
            continue

        started[name] = {"started": True, "pid": process.pid}

        # On Windows the venv launcher is a shim: it spawns the real
        # interpreter as a child process. The service records the real
        # PID itself once it starts, so wait for that to land rather
        # than leaving the shim's PID behind -- stopping the shim would
        # not stop the service.
        deadline = time.time() + 20
        recorded = None
        while time.time() < deadline:
            current = _read_pid(name)
            if current and current != process.pid and _pid_alive(current):
                recorded = current
                break
            if not _pid_alive(process.pid):
                break
            time.sleep(0.3)

        if recorded is None:
            try:
                SERVICE_FILES[name].write_text(str(process.pid),
                                                encoding="utf-8")
            except OSError:
                pass
            started[name]["pid"] = process.pid
            started[name]["pid_source"] = "launcher"
        else:
            started[name]["pid"] = recorded
            started[name]["pid_source"] = "service"
        # The handles are intentionally left open in the parent: the
        # child owns its own copies, and closing them here would be fine
        # too, but keeping them avoids a race on the first flush.

    return started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VIRALCLIPS AI service control")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("--services", nargs="*", default=None,
                              choices=["worker", "api"])
    start = sub.add_parser("start")
    start.add_argument("--services", nargs="*", default=None,
                       choices=["worker", "api"])
    free = sub.add_parser("free-port")
    free.add_argument("port", type=int, nargs="?", default=config.API_PORT)

    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(status()))
        return 0
    if args.command == "stop":
        print(json.dumps(stop(args.services)))
        return 0
    if args.command == "start":
        print(json.dumps(launch(args.services)))
        return 0
    if args.command == "free-port":
        print(json.dumps(free_port(args.port)))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
