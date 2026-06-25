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
import subprocess
import time
from pathlib import Path

import edge_tts

from .base import TTSBackend, TTSError

logger = logging.getLogger(__name__)

#: Default voice — a clear, neutral US English neural voice.
DEFAULT_VOICE = "en-US-AndrewNeural"


def speed_to_rate(speed: float) -> str:
    """Convert a playback-speed multiplier to an edge-tts ``rate`` string.

    edge-tts expresses speech rate as a signed percentage relative to the
    voice's normal pace (``"+0%"`` = normal, ``"+50%"`` = 1.5x, ``"-20%"`` =
    0.8x). A multiplier of ``1.0`` maps to ``"+0%"``.

    Args:
        speed: Speed multiplier (e.g. ``0.8``, ``1.0``, ``1.5``, ``2.0``).

    Returns:
        A rate string such as ``"+50%"`` or ``"-20%"``.
    """
    percent = round((speed - 1.0) * 100)
    return f"{percent:+d}%"


class EdgeTTSBackend(TTSBackend):
    """Synthesize speech with Microsoft Edge's free neural TTS voices.

    Args:
        default_voice: Voice used when ``synthesize`` is called with an empty
            voice argument.
        speed: Playback-speed multiplier (1.0 = normal). Converted to an
            edge-tts ``rate`` percentage applied to every synthesis.
        max_attempts: Total synthesis attempts before giving up (>= 1).
        backoff_base: Seconds for the first retry sleep; doubles each retry.
    """

    def __init__(
        self,
        default_voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
    ) -> None:
        self.default_voice = default_voice
        self.rate = speed_to_rate(speed)
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
                self._validate_output(out_path, text)
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
        communicate = edge_tts.Communicate(text, voice, rate=self.rate)
        await communicate.save(str(out_path))

    @staticmethod
    def _validate_output(out_path: Path, text: str) -> None:
        """Raise ``TTSError`` if ``out_path`` is missing, empty, or suspiciously short.

        Checks that the audio duration is at least as long as it would take to
        speak ``text`` at a very fast 25 chars/second. This catches partial files
        produced when the edge-tts WebSocket closes before all audio is delivered.
        """
        if not out_path.exists():
            raise TTSError(f"edge-tts produced no file at {out_path}")
        if out_path.stat().st_size == 0:
            raise TTSError(f"edge-tts produced an empty file at {out_path}")
        min_expected_s = len(text) / 25.0
        if min_expected_s > 1.0:
            duration = EdgeTTSBackend._probe_duration(out_path)
            if duration < min_expected_s:
                raise TTSError(
                    f"edge-tts audio too short ({duration:.1f}s) for {len(text)}-char "
                    f"text (expected ≥{min_expected_s:.1f}s); likely a partial stream"
                )

    @staticmethod
    def _probe_duration(path: Path) -> float:
        """Return audio duration in seconds via ffprobe, or 0 on failure."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return float(result.stdout.strip())
        except Exception:
            return 0.0
