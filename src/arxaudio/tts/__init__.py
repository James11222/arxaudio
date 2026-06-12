"""Text-to-speech backends and the audio-stage interface."""

from __future__ import annotations

from .base import TTSBackend, TTSError
from .edge_backend import DEFAULT_VOICE, EdgeTTSBackend

__all__ = [
    "TTSBackend",
    "TTSError",
    "EdgeTTSBackend",
    "DEFAULT_VOICE",
]
