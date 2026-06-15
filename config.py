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
#
# Required env vars when PAPER_SOURCE = "benty":
#   BENTY_EMAIL      your benty-fields.com login email
#   BENTY_PASSWORD   your benty-fields.com password (use a unique password,
#                    not one reused elsewhere; add as a GitHub Secret in CI)
#   BENTY_BASE_URL   (optional) override the benty-fields base URL;
#                    defaults to https://www.benty-fields.com
# =============================================================================


# ---------------------------------------------------------------------------
# Paper source
# ---------------------------------------------------------------------------
# PAPER_SOURCE controls where daily papers come from:
#
#   "arxiv"  (default) — fetch from arXiv RSS feeds for the CATEGORIES below,
#            then rank with the local LLM using your preferences.md.
#            No additional credentials needed.
#
#   "benty"  — fetch the day's papers already ML-ranked from your personal
#            benty-fields.com account (https://www.benty-fields.com).
#            In this mode CATEGORIES is IGNORED — benty uses your account's
#            subscription settings — and the LLM ranking step is skipped.
#            Requires two environment variables / GitHub Secrets:
#              BENTY_EMAIL      your benty-fields login email
#              BENTY_PASSWORD   your benty-fields password (use a UNIQUE
#                               password not reused elsewhere)
#            Optionally set BENTY_BASE_URL to override the default base URL.

PAPER_SOURCE: str = "benty"  # "arxiv" or "benty"


# ---------------------------------------------------------------------------
# arXiv category subscriptions
# ---------------------------------------------------------------------------
# Full list of arXiv categories: https://arxiv.org/category_taxonomy
# Add or remove entries to control which feeds are polled.
# (Used only when PAPER_SOURCE = "arxiv"; ignored in benty mode.)

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
# qwen2.5:0.5b is tiny (~400 MB) and fast enough for title ranking decisions.
# Larger options:  "qwen2.5:1.5b", "qwen2.5:3b", "llama3.2:1b"

OLLAMA_MODEL: str = "qwen2.5:1.5b"


# ---------------------------------------------------------------------------
# Text-to-speech backend settings
# ---------------------------------------------------------------------------
# TTS_BACKEND: which backend class to use.
#   "edge"  — Microsoft Edge TTS via edge-tts (free, no API key needed)
#   Future options: "coqui", "piper"

TTS_BACKEND: str = "notebooklm"

# TTS_VOICE: voice identifier for Edge TTS.
# Browse available voices:  edge-tts --list-voices
# Good English neural voices:  en-US-AndrewNeural, en-US-JennyNeural,
#                               en-GB-RyanNeural, en-AU-NatashaNeural

TTS_VOICE: str = "en-US-AndrewNeural"

# TTS_SPEED: narration speed multiplier relative to the voice's normal pace.
#   1.0  = normal,  0.8 = slower,  1.2 / 1.5 = faster,  2.0 = double speed.
# Applied to every paper in the audio.  Useful range is roughly 0.5–2.0.

TTS_SPEED: float = 1.2


# ---------------------------------------------------------------------------
# NotebookLM TTS backend settings
# ---------------------------------------------------------------------------
# Only used when TTS_BACKEND = "notebooklm".
#
# Required env var / GitHub Secret when notebookLM is active:
#   NOTEBOOKLM_AUTH_JSON  — JSON string containing Google session cookies.
#                          Obtain by running:  notebooklm login
#                          then copy from:     ~/.notebooklm/storage_state.json
#                          Add as a GitHub Actions Secret on your fork.
#
# notebooklm-py must be installed:  pip install ".[notebooklm]"
#   (or:  pip install "notebooklm-py>=0.8")

# NOTEBOOKLM_AUDIO_FORMAT: the style of audio overview to generate.
#   "brief"      — concise overview (recommended for daily digests)
#   "deep-dive"  — longer, more detailed conversation
#   "critique"   — critical analysis
#   "debate"     — multiple perspectives

NOTEBOOKLM_AUDIO_FORMAT: str = "brief"

# NOTEBOOKLM_AUDIO_LENGTH: length of the generated audio.
#   "short", "default", "long"

NOTEBOOKLM_AUDIO_LENGTH: str = "default"

# NOTEBOOKLM_INSTRUCTIONS: custom instructions fed to notebookLM.
# The default prompt is optimised for an expert astrophysics audience.
# Customise freely — this is the only prompt the notebookLM backend uses.

NOTEBOOKLM_INSTRUCTIONS: str = (
    "You are generating a daily arXiv digest for an expert audience of "
    "postdoctoral researchers and senior PhD students in astrophysics and "
    "cosmology. For each paper in the sources, announce the paper title and "
    "first author's name, then give the key takeaways of the abstract in 5-6 "
    "concise sentences. Each paper must get its own self-contained segment. "
    "Do NOT compare papers to each other, and do NOT group papers by theme. "
    "Be precise and technical; the audience is already familiar with standard "
    "methods and terminology in the field."
)

# NOTEBOOKLM_DELETE_NOTEBOOK: whether to delete the notebook from notebookLM
# after the audio file has been downloaded.  True keeps your notebookLM
# workspace tidy; False lets you inspect the notebook afterwards.

NOTEBOOKLM_DELETE_NOTEBOOK: bool = True

# NOTEBOOKLM_TIMEOUT: maximum seconds to wait for notebookLM to finish
# generating the audio overview.  Generation typically takes 2-5 minutes.

NOTEBOOKLM_TIMEOUT: int = 600


# ---------------------------------------------------------------------------
# Audio output limits
# ---------------------------------------------------------------------------
# MAX_MB: maximum size of the final MP3 in megabytes.
# If the generated audio exceeds this limit, audio.py will step down the
# bitrate (via ffmpeg) until it fits.

MAX_MB: int = 20

# PAUSE_SECONDS: length of the silence gap inserted between papers.

PAUSE_SECONDS: float = 1.2

# MAX_PAPERS: controls how many papers are included in each digest section.
#   - The top MAX_PAPERS ranked papers go through the full process → TTS →
#     audio pipeline and are read aloud in the MP3.
#   - The next MAX_PAPERS (ranks N+1..2N) are listed in the email only
#     (title, first author, arXiv link), below a divider, with no audio.
#   - 0 means unlimited: every fetched paper gets full audio treatment and
#     there is no email-only listing section.
# Useful if you subscribe to very active categories and want a shorter digest.

MAX_PAPERS: int = 10


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
# There is no fetch window to configure: each run pulls exactly the papers
# arXiv announced that day (the daily mailing, via rss.arxiv.org) for the
# categories above.  New submissions and cross-lists are included;
# replacements (revised versions of older papers) are skipped.


# ---------------------------------------------------------------------------
# Email subject line
# ---------------------------------------------------------------------------
# EMAIL_SUBJECT_PREFIX: prepended to every subject line.
# The pipeline appends the date and paper count automatically, e.g.:
#   "ArXaudio Digest — 2026-06-11 (7 papers)"

EMAIL_SUBJECT_PREFIX: str = "ArXaudio Digest"


# ---------------------------------------------------------------------------
# Repository link
# ---------------------------------------------------------------------------
# REPO_URL: shown in the email footer ("Sent by arxaudio").  When you fork
# this project, point it at YOUR fork so the link in your digest is correct.

REPO_URL: str = "https://github.com/James11222/arxaudio"
