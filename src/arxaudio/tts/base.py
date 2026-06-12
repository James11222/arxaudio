"""Pluggable text-to-speech backend interface.

To use a different engine, subclass ``TTSBackend`` and point
``config.TTS_BACKEND`` at it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSBackend(ABC):
    """Minimal interface the audio stage depends on."""

    @abstractmethod
    def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        """Render ``text`` to an MP3 file at ``out_path``.

        Raise ``TTSError`` on unrecoverable failures.
        """


class TTSError(RuntimeError):
    """Raised when speech synthesis fails."""
