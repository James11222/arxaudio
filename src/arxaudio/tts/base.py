"""Pluggable text-to-speech backend interface.

To use a different engine, subclass ``TTSBackend`` and point
``config.TTS_BACKEND`` at it.

For backends that generate a single audio file for *all* papers in one call
(e.g. notebookLM), subclass ``DirectAudioBackend`` instead.  The pipeline
detects the type and routes accordingly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arxaudio.models import Paper


class TTSBackend(ABC):
    """Minimal interface the audio stage depends on."""

    @abstractmethod
    def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        """Render ``text`` to an MP3 file at ``out_path``.

        Raise ``TTSError`` on unrecoverable failures.
        """


class DirectAudioBackend(ABC):
    """Backend that generates a single audio file for all papers in one call.

    This is for services such as notebookLM that accept a batch of sources and
    return a single podcast-style MP3 rather than one segment per paper.

    The pipeline detects ``isinstance(tts, DirectAudioBackend)`` and calls
    :meth:`generate_audio` directly, bypassing ``audio.build_daily_audio``
    (and the upstream process / math-cleanup stage) entirely.
    """

    @abstractmethod
    def generate_audio(self, papers: "list[Paper]", out_path: Path) -> None:
        """Generate a single MP3 at ``out_path`` covering all ``papers``.

        Args:
            papers: The kept papers to include in the audio overview.
            out_path: Destination MP3 file path (parent dirs will be created).

        Raise ``TTSError`` on unrecoverable failures.
        """


class TTSError(RuntimeError):
    """Raised when speech synthesis fails."""
