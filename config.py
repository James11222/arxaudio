# =============================================================================
# arxaudio configuration — edit this file to customise your daily digest
# =============================================================================
#
# This is plain Python. You can use lists, strings, ints, and floats.
# Do NOT put secrets here.  SMTP credentials come from environment variables
# (or GitHub Secrets when running in CI).  See the README for details.
#
# Required env vars for email delivery:
#   SMTP_HOST        e.g. smtp.gmail.com
#   SMTP_PORT        default 587 (STARTTLS); use 465 for SMTP_SSL
#   SMTP_USER        your email address (also used as sender/recipient if
#                    EMAIL_FROM / EMAIL_TO are not set)
#   SMTP_PASSWORD    app password or SMTP password
#   EMAIL_TO         recipient address (defaults to SMTP_USER)
#   EMAIL_FROM       sender address  (defaults to SMTP_USER)
# =============================================================================


# ---------------------------------------------------------------------------
# arXiv category subscriptions
# ---------------------------------------------------------------------------
# Full list of arXiv categories: https://arxiv.org/category_taxonomy
# Add or remove entries to control which feeds are polled.

CATEGORIES: list[str] = [
    "astro-ph.CO",   # Cosmology and Nongalactic Astrophysics
    "astro-ph.GA",   # Astrophysics of Galaxies
]


# ---------------------------------------------------------------------------
# LLM backend settings
# ---------------------------------------------------------------------------
# LLM_BACKEND: which backend class to use.
#   "ollama"  — local ollama server (default, works in GitHub Actions)
#   Future options:  "openai", "custom" (add a subclass in src/arxaudio/llm/)

LLM_BACKEND: str = "ollama"

# OLLAMA_MODEL: the model pulled by `ollama pull <model>`.
# qwen2.5:0.5b is tiny (~400 MB) and fast enough for keep/discard decisions.
# Larger options:  "qwen2.5:1.5b", "qwen2.5:3b", "llama3.2:1b"

OLLAMA_MODEL: str = "qwen2.5:0.5b"


# ---------------------------------------------------------------------------
# Text-to-speech backend settings
# ---------------------------------------------------------------------------
# TTS_BACKEND: which backend class to use.
#   "edge"  — Microsoft Edge TTS via edge-tts (free, no API key needed)
#   Future options: "coqui", "piper"

TTS_BACKEND: str = "edge"

# TTS_VOICE: voice identifier for Edge TTS.
# Browse available voices:  edge-tts --list-voices
# Good English neural voices:  en-US-AndrewNeural, en-US-JennyNeural,
#                               en-GB-RyanNeural, en-AU-NatashaNeural

TTS_VOICE: str = "en-US-AndrewNeural"


# ---------------------------------------------------------------------------
# Audio output limits
# ---------------------------------------------------------------------------
# MAX_MB: maximum size of the final MP3 in megabytes.
# If the generated audio exceeds this limit, audio.py will step down the
# bitrate (via ffmpeg) until it fits.

MAX_MB: int = 20

# PAUSE_SECONDS: length of the silence gap inserted between papers.

PAUSE_SECONDS: float = 1.2

# MAX_PAPERS: safety cap on how many kept papers go through TTS and into the
# final audio file.  0 means unlimited (all kept papers are included).
# Useful if you subscribe to very active categories and want a shorter digest.

MAX_PAPERS: int = 0   # 0 = unlimited


# ---------------------------------------------------------------------------
# Fetch window
# ---------------------------------------------------------------------------
# LOOKBACK_HOURS: how far back (in UTC hours) to look for new papers.
# 24 is appropriate for a daily run.  Increase to 48 if you want a weekend
# catch-up, or to 72 for a first run after a long break.

LOOKBACK_HOURS: int = 24


# ---------------------------------------------------------------------------
# Email subject line
# ---------------------------------------------------------------------------
# EMAIL_SUBJECT_PREFIX: prepended to every subject line.
# The pipeline appends the date and paper count automatically, e.g.:
#   "ArXaudio Digest — 2026-06-11 (7 papers)"

EMAIL_SUBJECT_PREFIX: str = "ArXaudio Digest"
