"""Load and validate user configuration.

The user edits ``config.py`` at the repo root (plain Python).  This module
imports that file at runtime, maps every variable into the typed ``Settings``
dataclass, applies defaults for anything missing, and reads SMTP credentials
from environment variables.

Usage::

    from arxaudio.settings import load_settings
    settings = load_settings()          # uses repo-root config.py
    settings = load_settings("/path/to/config.py")  # explicit path
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults (mirror the commented defaults in config.py)
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, object] = {
    "CATEGORIES": ["astro-ph.CO", "astro-ph.GA"],
    "PAPER_SOURCE": "arxiv",
    "BENTY_BASE_URL": "https://www.benty-fields.com",
    "LLM_BACKEND": "ollama",
    "OLLAMA_MODEL": "qwen2.5:0.5b",
    "TTS_BACKEND": "edge",
    "TTS_VOICE": "en-US-AndrewNeural",
    "TTS_SPEED": 1.0,
    "MAX_MB": 20,
    "PAUSE_SECONDS": 1.2,
    "MAX_PAPERS": 10,
    "EMAIL_SUBJECT_PREFIX": "ArXaudio Digest",
    "REPO_URL": "https://github.com/James11222/arxaudio",
    "NOTEBOOKLM_AUDIO_FORMAT": "brief",
    "NOTEBOOKLM_AUDIO_LENGTH": "default",
    "NOTEBOOKLM_INSTRUCTIONS": (
        "You are generating a daily arXiv digest for an expert audience of "
        "postdoctoral researchers and senior PhD students in astrophysics and "
        "cosmology. For each paper in the sources, announce the paper title and "
        "first author's name, then give the key takeaways of the abstract in 2-4 "
        "concise sentences. Each paper must get its own self-contained segment. "
        "Do NOT compare papers to each other, and do NOT group papers by theme. "
        "Be precise and technical; the audience is already familiar with standard "
        "methods and terminology in the field."
    ),
    "NOTEBOOKLM_DELETE_NOTEBOOK": True,
    "NOTEBOOKLM_TIMEOUT": 600,
}


@dataclass
class Settings:
    """Fully-resolved, validated configuration for one pipeline run."""

    # Paper source — "arxiv" (RSS) or "benty" (benty-fields ML ranking)
    paper_source: str = "arxiv"

    # arXiv
    categories: list[str] = field(default_factory=lambda: ["astro-ph.CO", "astro-ph.GA"])

    # LLM
    llm_backend: str = "ollama"
    ollama_model: str = "qwen2.5:0.5b"

    # TTS
    tts_backend: str = "edge"
    tts_voice: str = "en-US-AndrewNeural"
    tts_speed: float = 1.0

    # Audio
    max_mb: int = 20
    pause_seconds: float = 1.2
    max_papers: int = 10  # 0 = unlimited

    # Email
    email_subject_prefix: str = "ArXaudio Digest"
    repo_url: str = "https://github.com/James11222/arxaudio"

    # benty-fields (populated from env vars — never stored in config.py)
    benty_base_url: str = "https://www.benty-fields.com"
    benty_email: str = ""
    benty_password: str = ""

    # SMTP (populated from env vars — never stored in config.py)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_to: str = ""
    email_from: str = ""

    # NotebookLM (populated from config.py + NOTEBOOKLM_AUTH_JSON env var)
    notebooklm_audio_format: str = "brief"
    notebooklm_audio_length: str = "default"
    notebooklm_instructions: str = ""
    notebooklm_delete_notebook: bool = True
    notebooklm_timeout: int = 600
    notebooklm_auth_json: str = ""  # from NOTEBOOKLM_AUTH_JSON env var

    # -----------------------------------------------------------------------
    # Derived helpers
    # -----------------------------------------------------------------------

    @property
    def benty_configured(self) -> bool:
        """Return True if benty-fields credentials are present."""
        return bool(self.benty_email and self.benty_password)

    @property
    def smtp_configured(self) -> bool:
        """Return True if all required SMTP credentials are present."""
        return bool(
            self.smtp_host
            and self.smtp_user
            and self.smtp_password
        )

    @property
    def notebooklm_configured(self) -> bool:
        """Return True if notebookLM auth credentials are present."""
        return bool(self.notebooklm_auth_json)

    @property
    def effective_email_to(self) -> str:
        """Recipient address, falling back to SMTP_USER if EMAIL_TO is unset."""
        return self.email_to or self.smtp_user

    @property
    def effective_email_from(self) -> str:
        """Sender address, falling back to SMTP_USER if EMAIL_FROM is unset."""
        return self.email_from or self.smtp_user


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _find_repo_config() -> Path:
    """Walk up from this file's location to find config.py at the repo root."""
    # src/arxaudio/settings.py  →  repo_root = ../../../
    here = Path(__file__).resolve()
    candidate = here.parent.parent.parent / "config.py"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"config.py not found at {candidate}. "
        "Make sure you have a config.py at the repository root "
        "(the repository ships with a commented template you can edit)."
    )


def _exec_config(path: Path) -> ModuleType:
    """Execute a plain-Python config file and return it as a module object."""
    spec = importlib.util.spec_from_file_location("arxaudio_user_config", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load config file: {path}")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except SyntaxError as exc:
        raise SyntaxError(
            f"Syntax error in {path}: {exc}.  "
            "Please fix the Python syntax in your config.py."
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Error while executing config file {path}: {exc}"
        ) from exc
    return mod


def _get(mod: ModuleType, name: str, default: object) -> object:
    """Get a config variable, using the default if it is not defined."""
    return getattr(mod, name, default)


def _validate(settings: Settings, config_path: Path) -> None:
    """Raise ValueError with a helpful message if configuration is invalid."""
    if settings.paper_source not in {"arxiv", "benty"}:
        raise ValueError(
            f"PAPER_SOURCE must be one of 'arxiv' or 'benty' "
            f"(got {settings.paper_source!r}).  "
            "Set PAPER_SOURCE = 'arxiv' to use the default arXiv RSS path, "
            "or PAPER_SOURCE = 'benty' to use benty-fields ML ranking."
        )
    if settings.paper_source == "benty" and not settings.benty_configured:
        raise ValueError(
            "PAPER_SOURCE is set to 'benty' but the required credentials are "
            "missing.  Set the BENTY_EMAIL and BENTY_PASSWORD environment "
            "variables (your benty-fields.com login — use a unique password not "
            "reused elsewhere).  In GitHub Actions, add them as repository "
            "Secrets.  Do NOT put credentials in config.py."
        )
    if not settings.categories:
        raise ValueError(
            f"CATEGORIES in {config_path} must be a non-empty list, "
            "e.g. CATEGORIES = ['astro-ph.CO', 'astro-ph.GA']"
        )
    if not all(isinstance(c, str) and c for c in settings.categories):
        raise ValueError(
            f"Every entry in CATEGORIES must be a non-empty string. "
            f"Got: {settings.categories!r}"
        )
    if settings.max_mb <= 0:
        raise ValueError(
            f"MAX_MB must be a positive integer (got {settings.max_mb!r}). "
            "Recommended value: 20"
        )
    if settings.pause_seconds < 0:
        raise ValueError(
            f"PAUSE_SECONDS must be non-negative (got {settings.pause_seconds!r})."
        )
    if settings.tts_speed <= 0:
        raise ValueError(
            f"TTS_SPEED must be a positive multiplier (got {settings.tts_speed!r}). "
            "Use 1.0 for normal pace; e.g. 0.8 for slower, 1.5 for faster."
        )
    if settings.max_papers < 0:
        raise ValueError(
            f"MAX_PAPERS must be 0 (unlimited) or a positive integer "
            f"(got {settings.max_papers!r})."
        )
    if settings.tts_backend == "notebooklm" and not settings.notebooklm_configured:
        raise ValueError(
            "TTS_BACKEND is set to 'notebooklm' but the required credentials are "
            "missing.  Set the NOTEBOOKLM_AUTH_JSON environment variable to the "
            "contents of your notebooklm storage_state.json file.  "
            "Obtain it by running:  notebooklm login  "
            "then reading:  ~/.notebooklm/storage_state.json  "
            "In GitHub Actions, add it as a repository Secret.  "
            "Do NOT put credentials in config.py."
        )
    valid_notebooklm_formats = {"brief", "deep-dive", "critique", "debate"}
    if settings.tts_backend == "notebooklm" and settings.notebooklm_audio_format not in valid_notebooklm_formats:
        raise ValueError(
            f"NOTEBOOKLM_AUDIO_FORMAT must be one of {sorted(valid_notebooklm_formats)} "
            f"(got {settings.notebooklm_audio_format!r})."
        )
    valid_notebooklm_lengths = {"short", "default", "long"}
    if settings.tts_backend == "notebooklm" and settings.notebooklm_audio_length not in valid_notebooklm_lengths:
        raise ValueError(
            f"NOTEBOOKLM_AUDIO_LENGTH must be one of {sorted(valid_notebooklm_lengths)} "
            f"(got {settings.notebooklm_audio_length!r})."
        )


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load, merge, validate, and return a ``Settings`` object.

    Parameters
    ----------
    config_path:
        Path to a ``config.py``-style file.  When *None*, the function walks
        up from this module's location to find ``config.py`` at the repo root.

    Returns
    -------
    Settings
        Fully populated settings including SMTP env vars.

    Raises
    ------
    FileNotFoundError
        If ``config_path`` is None and no ``config.py`` can be found.
    ValueError
        If any setting fails validation.
    """
    if config_path is None:
        resolved = _find_repo_config()
    else:
        resolved = Path(config_path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Config file not found: {resolved}")

    logger.debug("Loading config from %s", resolved)
    mod = _exec_config(resolved)

    def get(name: str) -> object:
        return _get(mod, name, _DEFAULTS[name])

    # Build the settings object from config values + defaults
    settings = Settings(
        paper_source=str(get("PAPER_SOURCE")).strip().lower(),
        categories=list(get("CATEGORIES")),           # type: ignore[arg-type]
        llm_backend=str(get("LLM_BACKEND")),
        ollama_model=str(get("OLLAMA_MODEL")),
        tts_backend=str(get("TTS_BACKEND")),
        tts_voice=str(get("TTS_VOICE")),
        tts_speed=float(get("TTS_SPEED")),          # type: ignore[arg-type]
        max_mb=int(get("MAX_MB")),                     # type: ignore[arg-type]
        pause_seconds=float(get("PAUSE_SECONDS")),     # type: ignore[arg-type]
        max_papers=int(get("MAX_PAPERS")),             # type: ignore[arg-type]
        email_subject_prefix=str(get("EMAIL_SUBJECT_PREFIX")),
        repo_url=str(get("REPO_URL")).rstrip("/"),
        # benty-fields credentials come from env vars, never from config.py
        benty_base_url=str(get("BENTY_BASE_URL")).rstrip("/"),
        benty_email=os.environ.get("BENTY_EMAIL", ""),
        benty_password=os.environ.get("BENTY_PASSWORD", ""),
        # SMTP credentials come from env vars, never from config.py
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        email_to=os.environ.get("EMAIL_TO", ""),
        email_from=os.environ.get("EMAIL_FROM", ""),
        # NotebookLM settings
        notebooklm_audio_format=str(get("NOTEBOOKLM_AUDIO_FORMAT")),
        notebooklm_audio_length=str(get("NOTEBOOKLM_AUDIO_LENGTH")),
        notebooklm_instructions=str(get("NOTEBOOKLM_INSTRUCTIONS")),
        notebooklm_delete_notebook=bool(get("NOTEBOOKLM_DELETE_NOTEBOOK")),
        notebooklm_timeout=int(get("NOTEBOOKLM_TIMEOUT")),  # type: ignore[arg-type]
        notebooklm_auth_json=os.environ.get("NOTEBOOKLM_AUTH_JSON", ""),
    )

    _validate(settings, resolved)

    if not settings.smtp_configured:
        logger.info(
            "SMTP not configured (SMTP_HOST / SMTP_USER / SMTP_PASSWORD env vars "
            "are not all set).  Email delivery will not be available."
        )
    else:
        logger.debug(
            "SMTP configured: host=%s port=%d user=%s",
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_user,
        )

    logger.info("Paper source: %s", settings.paper_source)
    logger.info(
        "Settings loaded: %d categories, model=%s, voice=%s",
        len(settings.categories),
        settings.ollama_model,
        settings.tts_voice,
    )
    return settings
