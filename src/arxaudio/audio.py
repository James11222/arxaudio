"""Audio assembly stage: per-paper TTS segments -> one daily MP3.

Each kept paper's :meth:`Paper.spoken_text` is synthesized to its own temporary
MP3, the segments are concatenated with a short silence between papers, and the
result is bitrate-stepped-down if it overshoots the size budget. ffmpeg/ffprobe
do the heavy lifting via ``subprocess``.

Design notes:
  * edge-tts emits 24 kHz mono MP3. We standardize every segment, the silence
    filler, and the final mix on **mono / 24 kHz / libmp3lame** so the concat
    demuxer never has to reconcile mismatched stream parameters.
  * Concatenation uses the ffmpeg ``concat`` demuxer with a full re-encode
    (``-c:a libmp3lame``) rather than stream-copy: stitched MP3 frames from
    separate encodes glitch on copy, and re-encoding lets us hit a target
    bitrate in the same pass.
  * Size budget: if the mix exceeds ``max_mb`` we re-encode the *final* file at
    progressively lower bitrates (48k -> 32k -> 24k). If even the floor is too
    big we keep that smallest version and warn — size never fails the pipeline.

One paper failing TTS is logged and skipped; the run continues.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from .models import Paper
from .tts.base import TTSBackend

logger = logging.getLogger(__name__)

# --- Encoding parameters (match edge-tts output: 24 kHz mono) ---------------
SAMPLE_RATE = 24000
CHANNELS = 1
DEFAULT_BITRATE = "64k"
#: Bitrates tried, in order, when shrinking an over-budget mix.
FALLBACK_BITRATES = ("48k", "32k", "24k")

_FFMPEG = "ffmpeg"
_FFPROBE = "ffprobe"


def probe_duration(path: Path | str) -> float:
    """Return the duration of an audio file in seconds via ffprobe.

    Args:
        path: Path to an audio file.

    Returns:
        Duration in seconds (0.0 if ffprobe cannot determine it).
    """
    result = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = result.stdout.strip()
    try:
        return float(raw)
    except ValueError:
        logger.warning("ffprobe returned non-numeric duration %r for %s", raw, path)
        return 0.0


def _make_silence(out_path: Path, seconds: float, bitrate: str) -> None:
    """Generate a silent MP3 of ``seconds`` length matching the segment format."""
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={SAMPLE_RATE}:cl=mono",
            "-t",
            f"{seconds:.3f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            str(out_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def _concat(segments: Sequence[Path], out_path: Path, bitrate: str) -> None:
    """Concatenate ``segments`` into ``out_path`` (re-encoded at ``bitrate``)."""
    list_file = out_path.with_suffix(".concat.txt")
    # The concat demuxer needs single-quoted, escaped absolute paths.
    lines = [f"file '{seg.resolve()}'\n" for seg in segments]
    list_file.write_text("".join(lines))
    try:
        subprocess.run(
            [
                _FFMPEG,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c:a",
                "libmp3lame",
                "-b:a",
                bitrate,
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                str(CHANNELS),
                str(out_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        list_file.unlink(missing_ok=True)


def _reencode(src: Path, dst: Path, bitrate: str) -> None:
    """Re-encode ``src`` to ``dst`` at ``bitrate`` (mono / 24 kHz mp3)."""
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-i",
            str(src),
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            str(dst),
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def _size_mb(path: Path) -> float:
    """File size in megabytes (1 MB = 1e6 bytes)."""
    return path.stat().st_size / 1_000_000


def build_daily_audio(
    papers: Sequence[Paper],
    tts: TTSBackend,
    voice: str,
    out_path: Path | str,
    max_mb: float = 20,
    pause_seconds: float = 1.2,
    intro_text: str | None = None,
    closing_text: str | None = None,
) -> Path | None:
    """Build the single daily MP3 from kept papers.

    Only papers with ``keep is True`` are spoken. Each paper is synthesized
    independently; a single TTS failure is logged and that paper is skipped.
    Segments are joined with ``pause_seconds`` of silence and the result is
    shrunk to fit ``max_mb`` if needed.

    Args:
        papers: Papers to consider; only those flagged ``keep`` are included.
        tts: A :class:`TTSBackend` implementation.
        voice: Voice name passed to the backend.
        out_path: Destination path for the final MP3.
        max_mb: Soft size budget in megabytes. Over-budget output is re-encoded
            at lower bitrates; the pipeline never fails purely on size.
        pause_seconds: Silence inserted between consecutive papers (and after
            the intro segment).
        intro_text: Optional spoken intro rendered before the first paper. The
            caller supplies the text (e.g. ``"ArXaudio digest for ... N papers."``).
        closing_text: Optional spoken closing rendered after the final paper.

    Returns:
        The path to the final MP3, or ``None`` if no segments were produced.
    """
    out_path = Path(out_path)
    kept = [p for p in papers if p.keep]
    if not kept:
        logger.info("No kept papers to synthesize; producing no audio.")
        return None

    with tempfile.TemporaryDirectory(prefix="arxaudio_") as tmp:
        tmp_dir = Path(tmp)
        segments: list[Path] = []

        # Optional intro segment first.
        if intro_text and intro_text.strip():
            intro_path = tmp_dir / "intro.mp3"
            try:
                tts.synthesize(intro_text, voice, intro_path)
                segments.append(intro_path)
            except Exception as exc:  # noqa: BLE001 - intro is best-effort
                logger.warning("Intro synthesis failed (%s); skipping intro.", exc)

        # Per-paper segments; one failure skips that paper only.
        for idx, paper in enumerate(kept):
            seg_path = tmp_dir / f"paper_{idx:03d}.mp3"
            try:
                tts.synthesize(paper.spoken_text(position=idx + 1), voice, seg_path)
                segments.append(seg_path)
            except Exception as exc:  # noqa: BLE001 - skip-and-continue
                logger.warning(
                    "TTS failed for %s (%s); skipping this paper.",
                    paper.arxiv_id,
                    exc,
                )

        # Optional closing segment last.
        if closing_text and closing_text.strip():
            closing_path = tmp_dir / "closing.mp3"
            try:
                tts.synthesize(closing_text, voice, closing_path)
                segments.append(closing_path)
            except Exception as exc:  # noqa: BLE001 - optional closing must not block digest
                logger.warning(
                    "Closing synthesis failed (%s); digest will proceed without closing segment.",
                    exc,
                )

        if not segments:
            logger.info("No segments synthesized successfully; producing no audio.")
            return None

        # Interleave silence between segments (and after the intro).
        silence_path = tmp_dir / "silence.mp3"
        _make_silence(silence_path, pause_seconds, DEFAULT_BITRATE)
        joined: list[Path] = []
        for i, seg in enumerate(segments):
            if i > 0:
                joined.append(silence_path)
            joined.append(seg)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        _concat(joined, out_path, DEFAULT_BITRATE)

        # Size budget: step bitrate down until it fits (or we hit the floor).
        size_mb = _size_mb(out_path)
        if size_mb > max_mb:
            logger.info(
                "Audio %.1f MB exceeds budget %.1f MB; reducing bitrate.",
                size_mb,
                max_mb,
            )
            tmp_out = tmp_dir / "shrunk.mp3"
            for bitrate in FALLBACK_BITRATES:
                _reencode(out_path, tmp_out, bitrate)
                candidate_mb = _size_mb(tmp_out)
                tmp_out.replace(out_path)
                size_mb = candidate_mb
                logger.info("Re-encoded at %s -> %.1f MB", bitrate, size_mb)
                if size_mb <= max_mb:
                    break
            else:
                logger.warning(
                    "Audio still %.1f MB at minimum bitrate %s (budget %.1f MB); "
                    "keeping smallest version.",
                    size_mb,
                    FALLBACK_BITRATES[-1],
                    max_mb,
                )

        duration = probe_duration(out_path)
        logger.info(
            "Built daily audio: %s (%d segments, %.1fs, %.1f MB)",
            out_path,
            len(segments),
            duration,
            _size_mb(out_path),
        )
        return out_path
