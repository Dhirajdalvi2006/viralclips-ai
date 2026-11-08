"""Credential loading for the external AI providers.

Requirement: credentials must be configurable without ever being typed into
a chat, printed, or committed. Three sources are supported, in priority
order:

1. **Process environment** -- ``GROQ_API_KEY``, ``OPENROUTER_API_KEY``.
   Highest priority, so a shell session always wins.

2. **A local credential file** -- ``%LOCALAPPDATA%\\ViralClipsAI\\credentials.env``
   by default, or the path in ``VIRALCLIPS_CREDENTIALS_FILE``. This is the
   "secure local configuration mechanism": the file lives outside the
   repository, so it can never be committed by accident, and the project
   directory stays clean.

3. **A project-local ``.env``** -- ``<repo>/.env``. Convenient for a
   workstation, and already covered by the project's ``.gitignore``.

The file format is one ``KEY=VALUE`` per line. Blank lines and lines
starting with ``#`` are ignored. Values are used verbatim.

Nothing here ever prints, logs, or returns a key to anything other than
the caller that asked for it by name.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Environment variable naming an explicit credential file.
CREDENTIALS_FILE_ENV = "VIRALCLIPS_CREDENTIALS_FILE"


def default_credentials_path() -> Path:
    """Return the default credential file location.

    Lives under LOCALAPPDATA so it is outside the repository and cannot be
    committed by accident.
    """
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(local) / "ViralClipsAI" / "credentials.env"


def project_env_path() -> Path:
    """Return the project-local .env path."""
    return Path(__file__).resolve().parent.parent / ".env"


def _parse_env_file(path: Path) -> dict:
    """Parse a KEY=VALUE file. Missing or unreadable files yield {}."""
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        values[key] = value
    return values


def _file_candidates():
    """Return the credential files to consult, in priority order."""
    explicit = os.environ.get(CREDENTIALS_FILE_ENV, "").strip()
    if explicit:
        yield Path(explicit)
        return
    yield default_credentials_path()
    yield project_env_path()


def load() -> dict:
    """Return every credential found, environment taking priority."""
    merged = {}
    for path in reversed(list(_file_candidates())):
        merged.update(_parse_env_file(path))
    for key, value in os.environ.items():
        if key.endswith("_API_KEY") and value.strip():
            merged[key] = value.strip()
    return merged


def get(name: str, default=None):
    """Return the value of a credential by name, or default."""
    return load().get(name, default)


def describe() -> dict:
    """Return a key-free description of where credentials came from.

    Reports only which credential names are present and which files
    contributed them -- never any value.
    """
    sources = {}
    for path in _file_candidates():
        parsed = _parse_env_file(path)
        if parsed:
            sources[str(path)] = sorted(parsed.keys())
    env_names = sorted(k for k in os.environ
                       if k.endswith("_API_KEY") and os.environ[k].strip())
    return {
        "files": sources,
        "environment": env_names,
    }
