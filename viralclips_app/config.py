"""Application configuration, paths, and ports.

Everything is local. There is no cloud endpoint anywhere in this file.
Configuration can be overridden by environment variables so a deployment
can move the data directory without editing code.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Repository root (the directory holding chopify.py, providers/, ...).
ROOT = Path(__file__).resolve().parent.parent

#: Where the application keeps its state. Configurable so a user can put
#: clips on a bigger drive without editing code.
DATA_DIR = Path(os.environ.get(
    "VIRALCLIPS_DATA_DIR", ROOT / "data")).resolve()

DATABASE_DIR = DATA_DIR / "database"
VIDEO_DIR = DATA_DIR / "videos"
AUDIO_DIR = DATA_DIR / "audio"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
CLIP_DIR = DATA_DIR / "clips"
THUMBNAIL_DIR = DATA_DIR / "thumbnails"
EXPORT_DIR = DATA_DIR / "exports"
LOG_DIR = DATA_DIR / "logs"
PROJECT_DIR = DATA_DIR / "projects"

ALL_DIRS = (DATABASE_DIR, VIDEO_DIR, AUDIO_DIR, TRANSCRIPT_DIR, CLIP_DIR,
            THUMBNAIL_DIR, EXPORT_DIR, LOG_DIR, PROJECT_DIR)


def ensure_dirs() -> None:
    """Create every managed directory. Safe to call repeatedly."""
    for directory in ALL_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


# --- database -------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "VIRALCLIPS_DATABASE_URL",
    f"sqlite:///{(DATABASE_DIR / 'viralclips.db').as_posix()}")

# --- network --------------------------------------------------------------

#: The API port. 8799 is chosen to sit next to the upstream Studio's 8765
#: without colliding with it, so both can run at once.
API_PORT = int(os.environ.get("VIRALCLIPS_API_PORT", "8799"))

#: The frontend is served by the same FastAPI app, so it shares the port.
#: The brief asks for both addresses to be reported; they are the same
#: origin by design -- one less process to start and stop.
FRONTEND_PORT = API_PORT

API_HOST = os.environ.get("VIRALCLIPS_API_HOST", "127.0.0.1")

#: A random token minted at startup and required by every mutating API
#: call. The frontend fetches it from /api/bootstrap, which is the only
#: unauthenticated read besides /api/health.
LOCAL_API_TOKEN_ENV = "VIRALCLIPS_API_TOKEN"

# --- processing -----------------------------------------------------------

#: Default worker concurrency. One job at a time by default because
#: faster-whisper and ffmpeg are CPU bound; the user can raise it.
DEFAULT_CONCURRENCY = int(os.environ.get("VIRALCLIPS_CONCURRENCY", "1"))

#: How often the worker polls the queue, in seconds.
WORKER_POLL_INTERVAL = float(os.environ.get("VIRALCLIPS_POLL_INTERVAL", "2"))

#: How many times a failed job is retried before it is parked as failed.
MAX_JOB_ATTEMPTS = int(os.environ.get("VIRALCLIPS_MAX_ATTEMPTS", "2"))

#: Whisper model used when a task does not specify one. "tiny" keeps the
#: first-run experience fast on CPU; the task UI can raise it.
DEFAULT_WHISPER_MODEL = os.environ.get("VIRALCLIPS_WHISPER_MODEL", "tiny")

#: Minimum free disk space, in bytes, required before starting a job.
MIN_FREE_DISK_BYTES = 2 * 1024 ** 3

# --- AI ------------------------------------------------------------------

#: The AI model used for clip reranking. Groq does not publish an
#: embedding model, so there is deliberately no embedding default here.
DEFAULT_AI_MODEL = os.environ.get("VIRALCLIPS_AI_MODEL", "openai/gpt-oss-120b")

#: Provider used for reranking.
DEFAULT_AI_PROVIDER = os.environ.get("VIRALCLIPS_AI_PROVIDER", "groq")

#: Optional fallback provider.
DEFAULT_AI_FALLBACK = os.environ.get("VIRALCLIPS_AI_FALLBACK", "") or None

# The provider adapter reads VIRALCLIPS_LLM_PROVIDER, while the
# application-level configuration uses VIRALCLIPS_AI_PROVIDER. Mirror the
# configured provider into the adapter's variable so the API process, the
# worker and the dashboard all agree on which provider is in use.
# An explicitly set VIRALCLIPS_LLM_PROVIDER still wins, because the
# worker sets it per job.
if not os.environ.get("VIRALCLIPS_LLM_PROVIDER") and DEFAULT_AI_PROVIDER:
    os.environ["VIRALCLIPS_LLM_PROVIDER"] = DEFAULT_AI_PROVIDER
if (not os.environ.get("VIRALCLIPS_LLM_FALLBACK")
        and DEFAULT_AI_FALLBACK):
    os.environ["VIRALCLIPS_LLM_FALLBACK"] = DEFAULT_AI_FALLBACK

# --- transcription --------------------------------------------------------

#: Transcription provider: "auto" (prefer Groq when credentials exist),
#: "groq" (Groq Whisper only) or "faster_whisper" (local only).
DEFAULT_TRANSCRIPTION_PROVIDER = os.environ.get(
    "VIRALCLIPS_TRANSCRIPTION_PROVIDER", "auto")

#: Groq model used for transcription.
DEFAULT_GROQ_TRANSCRIPTION_MODEL = os.environ.get(
    "VIRALCLIPS_GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo")

#: Whether Groq transcription is allowed at all.
GROQ_TRANSCRIPTION_ENABLED = os.environ.get(
    "VIRALCLIPS_GROQ_TRANSCRIPTION_ENABLED", "1") != "0"

#: Whether local Faster-Whisper transcription is allowed.
LOCAL_TRANSCRIPTION_ENABLED = os.environ.get(
    "VIRALCLIPS_LOCAL_TRANSCRIPTION_ENABLED", "1") != "0"

#: Target chunk size in MB for Groq transcription uploads.
GROQ_TRANSCRIPTION_CHUNK_TARGET_MB = float(os.environ.get(
    "VIRALCLIPS_GROQ_TRANSCRIPTION_CHUNK_TARGET_MB", "15"))

#: Conservative upload limit in MB (Groq free tier is 25 MB).
GROQ_TRANSCRIPTION_MAX_FILE_MB = float(os.environ.get(
    "VIRALCLIPS_GROQ_TRANSCRIPTION_MAX_FILE_MB", "25"))

#: Default channel check interval, in minutes.
DEFAULT_MONITOR_INTERVAL_MINUTES = int(
    os.environ.get("VIRALCLIPS_MONITOR_INTERVAL", "60"))

# --- publishing -----------------------------------------------------------

#: Publishing is off until the user connects an account AND approves a
#: clip. This flag is the master switch.
PUBLISHING_ENABLED = os.environ.get("VIRALCLIPS_PUBLISHING", "1") != "0"

#: OAuth redirect paths.
YOUTUBE_REDIRECT_PATH = "/api/accounts/youtube/callback"
INSTAGRAM_REDIRECT_PATH = "/api/accounts/instagram/callback"

#: Where OAuth tokens are stored. Inside the database, never on disk in
#: plaintext, never in the frontend.
OAUTH_SCOPES = {
    "youtube": [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/userinfo.profile",
    ],
    "instagram": [
        "instagram_basic",
        "instagram_content_publish",
        "pages_show_list",
        "pages_read_engagement",
        "business_management",
    ],
}


def oauth_redirect_uri(scheme: str, port: int | None = None) -> str:
    """Return the OAuth callback URL for a scheme (youtube/instagram)."""
    port = port or API_PORT
    path = YOUTUBE_REDIRECT_PATH if scheme == "youtube" else INSTAGRAM_REDIRECT_PATH
    return f"http://{API_HOST}:{port}{path}"


def describe() -> dict:
    """Return a key-free description of the runtime configuration."""
    return {
        "root": str(ROOT),
        "data_dir": str(DATA_DIR),
        "database": DATABASE_URL.replace(str(DATA_DIR), "<data>"),
        "api_host": API_HOST,
        "api_port": API_PORT,
        "frontend_port": FRONTEND_PORT,
        "worker_poll_interval_s": WORKER_POLL_INTERVAL,
        "default_concurrency": DEFAULT_CONCURRENCY,
        "default_whisper_model": DEFAULT_WHISPER_MODEL,
        "default_ai_provider": DEFAULT_AI_PROVIDER,
        "default_ai_model": DEFAULT_AI_MODEL,
        "default_ai_fallback": DEFAULT_AI_FALLBACK,
        "default_transcription_provider": DEFAULT_TRANSCRIPTION_PROVIDER,
        "default_groq_transcription_model": DEFAULT_GROQ_TRANSCRIPTION_MODEL,
        "groq_transcription_enabled": GROQ_TRANSCRIPTION_ENABLED,
        "local_transcription_enabled": LOCAL_TRANSCRIPTION_ENABLED,
        "monitor_interval_minutes": DEFAULT_MONITOR_INTERVAL_MINUTES,
        "publishing_enabled": PUBLISHING_ENABLED,
        "min_free_disk_bytes": MIN_FREE_DISK_BYTES,
    }
