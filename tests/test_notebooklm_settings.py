"""Tests for NotebookLM-specific settings."""
from __future__ import annotations

from pathlib import Path

import pytest

from arxaudio.settings import load_settings


def _write_config(tmp_path: Path, content: str) -> Path:
    cfg = tmp_path / "config.py"
    cfg.write_text(content)
    return cfg


MINIMAL_CONFIG = "CATEGORIES = ['astro-ph.CO']\n"


class TestNotebookLMSettings:
    def test_notebooklm_defaults(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", '{"cookies": []}')
        cfg = _write_config(tmp_path, MINIMAL_CONFIG + 'TTS_BACKEND = "notebooklm"\n')
        settings = load_settings(cfg)
        assert settings.notebooklm_audio_format == "brief"
        assert settings.notebooklm_audio_length == "default"
        assert settings.notebooklm_delete_notebook is True
        assert settings.notebooklm_timeout == 600

    def test_notebooklm_auth_json_from_env(self, tmp_path, monkeypatch):
        auth = '{"cookies": [{"name": "SID", "value": "test"}]}'
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", auth)
        monkeypatch.delenv("SMTP_HOST", raising=False)
        cfg = _write_config(tmp_path, MINIMAL_CONFIG + 'TTS_BACKEND = "notebooklm"\n')
        settings = load_settings(cfg)
        assert settings.notebooklm_auth_json == auth

    def test_notebooklm_configured_true(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", '{"cookies": []}')
        monkeypatch.delenv("SMTP_HOST", raising=False)
        cfg = _write_config(tmp_path, MINIMAL_CONFIG + 'TTS_BACKEND = "notebooklm"\n')
        settings = load_settings(cfg)
        assert settings.notebooklm_configured is True

    def test_notebooklm_configured_false_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NOTEBOOKLM_AUTH_JSON", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)
        cfg = _write_config(tmp_path, MINIMAL_CONFIG)
        settings = load_settings(cfg)
        assert settings.notebooklm_configured is False

    def test_notebooklm_validation_missing_auth(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NOTEBOOKLM_AUTH_JSON", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)
        cfg = _write_config(tmp_path, MINIMAL_CONFIG + 'TTS_BACKEND = "notebooklm"\n')
        with pytest.raises(ValueError, match="NOTEBOOKLM_AUTH_JSON"):
            load_settings(cfg)

    def test_notebooklm_custom_format(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", '{"cookies": []}')
        monkeypatch.delenv("SMTP_HOST", raising=False)
        cfg = _write_config(
            tmp_path,
            MINIMAL_CONFIG
            + 'TTS_BACKEND = "notebooklm"\n'
            + 'NOTEBOOKLM_AUDIO_FORMAT = "deep-dive"\n',
        )
        settings = load_settings(cfg)
        assert settings.notebooklm_audio_format == "deep-dive"

    def test_notebooklm_invalid_format_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", '{"cookies": []}')
        monkeypatch.delenv("SMTP_HOST", raising=False)
        cfg = _write_config(
            tmp_path,
            MINIMAL_CONFIG
            + 'TTS_BACKEND = "notebooklm"\n'
            + 'NOTEBOOKLM_AUDIO_FORMAT = "invalid-format"\n',
        )
        with pytest.raises(ValueError, match="NOTEBOOKLM_AUDIO_FORMAT"):
            load_settings(cfg)

    def test_notebooklm_invalid_length_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", '{"cookies": []}')
        monkeypatch.delenv("SMTP_HOST", raising=False)
        cfg = _write_config(
            tmp_path,
            MINIMAL_CONFIG
            + 'TTS_BACKEND = "notebooklm"\n'
            + 'NOTEBOOKLM_AUDIO_LENGTH = "extra-long"\n',
        )
        with pytest.raises(ValueError, match="NOTEBOOKLM_AUDIO_LENGTH"):
            load_settings(cfg)

    def test_notebooklm_custom_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", '{"cookies": []}')
        monkeypatch.delenv("SMTP_HOST", raising=False)
        cfg = _write_config(
            tmp_path,
            MINIMAL_CONFIG
            + 'TTS_BACKEND = "notebooklm"\n'
            + 'NOTEBOOKLM_TIMEOUT = 1200\n',
        )
        settings = load_settings(cfg)
        assert settings.notebooklm_timeout == 1200
