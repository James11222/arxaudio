"""Tests for arxaudio.settings.load_settings."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from arxaudio.settings import Settings, load_settings


# ---------------------------------------------------------------------------
# Helper: write a minimal config.py to a tmp_path
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, content: str) -> Path:
    cfg = tmp_path / "config.py"
    cfg.write_text(content)
    return cfg


MINIMAL_CONFIG = """\
CATEGORIES = ["astro-ph.CO", "astro-ph.GA"]
"""

CUSTOM_CONFIG = """\
CATEGORIES = ["astro-ph.CO", "astro-ph.HE"]
LLM_BACKEND = "custom"
OLLAMA_MODEL = "llama3.2:1b"
TTS_BACKEND = "edge"
TTS_VOICE = "en-GB-RyanNeural"
TTS_SPEED = 1.5
MAX_MB = 15
PAUSE_SECONDS = 0.8
MAX_PAPERS = 10
EMAIL_SUBJECT_PREFIX = "My Digest"
"""


# ---------------------------------------------------------------------------
# Custom values are respected
# ---------------------------------------------------------------------------

def test_custom_categories(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, CUSTOM_CONFIG)
    settings = load_settings(cfg)
    assert settings.categories == ["astro-ph.CO", "astro-ph.HE"]


def test_custom_ollama_model(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, CUSTOM_CONFIG)
    settings = load_settings(cfg)
    assert settings.ollama_model == "llama3.2:1b"


def test_custom_max_mb(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, CUSTOM_CONFIG)
    settings = load_settings(cfg)
    assert settings.max_mb == 15


def test_custom_pause_seconds(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, CUSTOM_CONFIG)
    settings = load_settings(cfg)
    assert abs(settings.pause_seconds - 0.8) < 1e-9


def test_custom_max_papers(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, CUSTOM_CONFIG)
    settings = load_settings(cfg)
    assert settings.max_papers == 10


def test_custom_email_subject_prefix(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, CUSTOM_CONFIG)
    settings = load_settings(cfg)
    assert settings.email_subject_prefix == "My Digest"


def test_custom_tts_voice(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, CUSTOM_CONFIG)
    settings = load_settings(cfg)
    assert settings.tts_voice == "en-GB-RyanNeural"


def test_custom_tts_speed(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, CUSTOM_CONFIG)
    settings = load_settings(cfg)
    assert abs(settings.tts_speed - 1.5) < 1e-9


# ---------------------------------------------------------------------------
# Defaults filled for missing keys
# ---------------------------------------------------------------------------

def test_default_ollama_model(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.ollama_model == "qwen2.5:0.5b"


def test_default_tts_voice(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.tts_voice == "en-US-AndrewNeural"


def test_default_tts_speed(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert abs(settings.tts_speed - 1.0) < 1e-9


def test_default_max_mb(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.max_mb == 20


def test_default_pause_seconds(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert abs(settings.pause_seconds - 1.2) < 1e-9


def test_default_max_papers(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.max_papers == 10


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_validation_error_empty_categories(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, "CATEGORIES = []\n")
    with pytest.raises(ValueError, match="CATEGORIES"):
        load_settings(cfg)


def test_validation_error_negative_max_mb(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, "CATEGORIES = ['astro-ph.CO']\nMAX_MB = -1\n")
    with pytest.raises(ValueError, match="MAX_MB"):
        load_settings(cfg)


def test_validation_error_zero_tts_speed(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, "CATEGORIES = ['astro-ph.CO']\nTTS_SPEED = 0\n")
    with pytest.raises(ValueError, match="TTS_SPEED"):
        load_settings(cfg)


def test_validation_error_negative_tts_speed(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, "CATEGORIES = ['astro-ph.CO']\nTTS_SPEED = -1.0\n")
    with pytest.raises(ValueError, match="TTS_SPEED"):
        load_settings(cfg)


def test_validation_error_zero_max_mb(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, "CATEGORIES = ['astro-ph.CO']\nMAX_MB = 0\n")
    with pytest.raises(ValueError, match="MAX_MB"):
        load_settings(cfg)


def test_file_not_found_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(str(tmp_path / "nonexistent.py"))


# ---------------------------------------------------------------------------
# SMTP env vars
# ---------------------------------------------------------------------------

def test_smtp_configured_true(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.delenv("EMAIL_TO", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.smtp_configured is True


def test_smtp_configured_false_missing_host(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.smtp_configured is False


def test_smtp_configured_false_missing_password(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.smtp_configured is False


def test_email_to_fallback_to_smtp_user(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.delenv("EMAIL_TO", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.effective_email_to == "user@example.com"


def test_email_to_explicit_overrides_smtp_user(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_TO", "recipient@other.com")
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.effective_email_to == "recipient@other.com"


def test_smtp_port_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_PORT", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.smtp_port == 587


def test_smtp_port_custom(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    cfg = _write_config(tmp_path, MINIMAL_CONFIG)
    settings = load_settings(cfg)
    assert settings.smtp_port == 465
