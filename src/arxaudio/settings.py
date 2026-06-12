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
    "LLM_BACKEND": "ollama",
    "OLLAMA_MODEL": "qwen2.5:0.5b",
    "TTS_BACKEND": "edge",
    "TTS_VOICE": "en-US-AndrewNeural",
    "MAX_MB": 20,
    "PAUSE_SECONDS": 1.2,
    "MAX_PAPERS": 0,
    "LOOKBACK_HOURS": 24,
    "EMAIL_SUBJECT_PREFIX": "ArXaudio Digest",
}


@dataclass
class Settings:
    """Fully-resolved, validated configuration for one pipeline run."""

    # arXiv
    categories: list[str] = field(default_factory=lambda: ["astro-ph.CO", "astro-ph.GA"])
    lookback_hours: int = 24

    # LLM
    llm_backend: str = "ollama"
    ollama_model: str = "qwen2.5:0.5b"

    # TTS
    tts_backend: str = "edge"
    tts_voice: str = "en-US-AndrewNeural"

    # Audio
    max_mb: int = 20
    pause_seconds: float = 1.2
    max_papers: int = 0  # 0 = unlimited

    # Email
    email_subject_prefix: str = "ArXaudio Digest"

    # SMTP (populated from env vars — never stored in config.py)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_to: str = ""
    email_from: str = ""

    # -----------------------------------------------------------------------
    # Derived helpers
    # -----------------------------------------------------------------------

    @property
    def smtp_configured(self) -> bool:
        """Return True if all required SMTP credentials are present."""
        return bool(
            self.smtp_host
            and self.smtp_user
            and self.smtp_password
        )

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
    if settings.lookback_hours <= 0:
        raise ValueError(
            f"LOOKBACK_HOURS must be a positive integer (got {settings.lookback_hours!r})."
        )
    if settings.max_papers < 0:
        raise ValueError(
            f"MAX_PAPERS must be 0 (unlimited) or a positive integer "
            f"(got {settings.max_papers!r})."
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
        categories=list(get("CATEGORIES")),           # type: ignore[arg-type]
        lookback_hours=int(get("LOOKBACK_HOURS")),     # type: ignore[arg-type]
        llm_backend=str(get("LLM_BACKEND")),
        ollama_model=str(get("OLLAMA_MODEL")),
        tts_backend=str(get("TTS_BACKEND")),
        tts_voice=str(get("TTS_VOICE")),
        max_mb=int(get("MAX_MB")),                     # type: ignore[arg-type]
        pause_seconds=float(get("PAUSE_SECONDS")),     # type: ignore[arg-type]
        max_papers=int(get("MAX_PAPERS")),             # type: ignore[arg-type]
        email_subject_prefix=str(get("EMAIL_SUBJECT_PREFIX")),
        # SMTP credentials come from env vars, never from config.py
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        email_to=os.environ.get("EMAIL_TO", ""),
        email_from=os.environ.get("EMAIL_FROM", ""),
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

    logger.info(
        "Settings loaded: %d categories, lookback_hours=%d, model=%s, voice=%s",
        len(settings.categories),
        settings.lookback_hours,
        settings.ollama_model,
        settings.tts_voice,
    )
    return settings
