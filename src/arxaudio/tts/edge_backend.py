"""edge-tts backend: free Microsoft neural voices, no API key.

``edge-tts`` exposes an async API; the pipeline's :class:`TTSBackend` contract is
synchronous, so :meth:`EdgeTTSBackend.synthesize` drives the coroutine with
``asyncio.run``. The Microsoft endpoint is a network service that occasionally
hiccups, so each synthesis is retried with exponential backoff and the output is
validated (non-empty file) before returning. Failures surface as ``TTSError`` so
the audio stage can skip a single paper without killing an unattended CI run.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import edge_tts

from .base import TTSBackend, TTSError

logger = logging.getLogger(__name__)

#: Default voice — a clear, neutral US English neural voice.
DEFAULT_VOICE = "en-US-AndrewNeural"


class EdgeTTSBackend(TTSBackend):
    """Synthesize speech with Microsoft Edge's free neural TTS voices.

    Args:
        default_voice: Voice used when ``synthesize`` is called with an empty
            voice argument.
        max_attempts: Total synthesis attempts before giving up (>= 1).
        backoff_base: Seconds for the first retry sleep; doubles each retry.
    """

    def __init__(
        self,
        default_voice: str = DEFAULT_VOICE,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
    ) -> None:
        self.default_voice = default_voice
        self.max_attempts = max(1, max_attempts)
        self.backoff_base = backoff_base

    def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        """Render ``text`` to an MP3 at ``out_path``.

        Args:
            text: The text to speak. Must be non-empty.
            voice: Edge voice name (e.g. ``"en-US-AndrewNeural"``); falls back to
                ``default_voice`` if empty.
            out_path: Destination MP3 path. Parent directories are created.

        Raises:
            TTSError: If ``text`` is empty, or every attempt fails / produces an
                empty file.
        """
        if not text or not text.strip():
            raise TTSError("EdgeTTSBackend.synthesize called with empty text")

        voice = voice or self.default_voice
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                asyncio.run(self._synthesize_async(text, voice, out_path))
                self._validate_output(out_path)
                logger.debug(
                    "edge-tts synthesized %d chars to %s (attempt %d)",
                    len(text),
                    out_path.name,
                    attempt,
                )
                return
            except Exception as exc:  # noqa: BLE001 - retry on any failure
                last_error = exc
                # Don't leave a partial/empty file behind between attempts.
                try:
                    out_path.unlink(missing_ok=True)
                except OSError:
                    pass
                if attempt < self.max_attempts:
                    sleep_s = self.backoff_base * (2 ** (attempt - 1))
                    logger.warning(
                        "edge-tts attempt %d/%d failed (%s); retrying in %.1fs",
                        attempt,
                        self.max_attempts,
                        exc,
                        sleep_s,
                    )
                    time.sleep(sleep_s)

        raise TTSError(
            f"edge-tts failed after {self.max_attempts} attempts for "
            f"voice {voice!r}: {last_error}"
        ) from last_error

    async def _synthesize_async(self, text: str, voice: str, out_path: Path) -> None:
        """Stream one synthesis to ``out_path`` using the async edge-tts API."""
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(out_path))

    @staticmethod
    def _validate_output(out_path: Path) -> None:
        """Raise ``TTSError`` unless ``out_path`` exists and is non-empty."""
        if not out_path.exists():
            raise TTSError(f"edge-tts produced no file at {out_path}")
        if out_path.stat().st_size == 0:
            raise TTSError(f"edge-tts produced an empty file at {out_path}")
