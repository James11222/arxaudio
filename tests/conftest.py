"""Shared pytest fixtures for the arxaudio test suite.

All fixtures here are offline — no network, no ollama, no edge-tts, no SMTP.
The only external binary used is ffmpeg (session-scoped, guarded by a skipif).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from arxaudio.llm.base import LLMBackend, LLMError
from arxaudio.models import Paper
from arxaudio.tts.base import TTSBackend

# ---------------------------------------------------------------------------
# Sample Paper objects with realistic astro LaTeX abstracts
# ---------------------------------------------------------------------------

PAPER_CO = Paper(
    arxiv_id="2606.01234",
    title=r"Cosmological constraints from weak lensing with $\sigma_8$ and $\Omega_m$",
    abstract=(
        r"We present new constraints on $\sigma_8$ and $\Omega_m$ from a "
        r"cosmic-shear analysis of the LSST Year-1 data. Using $\Lambda$CDM "
        r"we find $\sigma_8 = 0.82 \pm 0.03$ and $H_0 \approx 70$ km/s/Mpc. "
        r"The chi-squared statistic is $\chi^2 / \nu = 1.05$. "
        r"Halo masses span $10^{12}$ to $10^{14}\,M_\odot$."
    ),
    authors=["Smith, Alice", "Jones, Bob", "Kim, Carol"],
    categories=["astro-ph.CO"],
    published="2026-06-10T00:00:00+00:00",
    keep=True,
)

PAPER_GA = Paper(
    arxiv_id="2606.05678",
    title=r"Galaxy clustering in the CF4++ZOA survey: $h^{-1}$ Mpc scales",
    abstract=(
        r"We study galaxy clustering at scales of 1–100 $h^{-1}$ Mpc in the "
        r"CF4++ZOA survey. The power spectrum $P(k)$ is measured to "
        r"$k = 0.3\,h\,\text{Mpc}^{-1}$. "
        r"Velocity dispersions span $\sim 200$ to $400$ km/s. "
        r"We report $\sigma_8 \Omega_m^{0.55} = 0.43 \pm 0.04$."
    ),
    authors=["Patel, David"],
    categories=["astro-ph.GA"],
    published="2026-06-10T12:00:00+00:00",
    keep=True,
)

PAPER_DISCARD = Paper(
    arxiv_id="2606.09999",
    title="Fast Radio Bursts as cosmological probes",
    abstract="We use FRBs to probe the intergalactic medium at z > 1.",
    authors=["Lee, Eve", "Park, Frank"],
    categories=["astro-ph.HE"],
    published="2026-06-09T00:00:00+00:00",
    keep=False,
)

PAPER_NOAUTHOR = Paper(
    arxiv_id="2606.00001",
    title="A paper with no authors",
    abstract="An abstract with no authors listed.",
    authors=[],
    categories=["astro-ph.CO"],
    published="2026-06-10T00:00:00+00:00",
)


@pytest.fixture
def paper_co() -> Paper:
    """A cosmology paper kept through filtering."""
    import copy
    return copy.deepcopy(PAPER_CO)


@pytest.fixture
def paper_ga() -> Paper:
    """A galaxy paper kept through filtering (single author)."""
    import copy
    return copy.deepcopy(PAPER_GA)


@pytest.fixture
def paper_discard() -> Paper:
    """A paper flagged for discard."""
    import copy
    return copy.deepcopy(PAPER_DISCARD)


@pytest.fixture
def paper_noauthor() -> Paper:
    """A paper with empty authors list."""
    import copy
    return copy.deepcopy(PAPER_NOAUTHOR)


@pytest.fixture
def sample_papers(paper_co, paper_ga, paper_discard) -> list[Paper]:
    """Three papers: two kept, one discarded."""
    return [paper_co, paper_ga, paper_discard]


# ---------------------------------------------------------------------------
# FakeLLM: scripted per-call responses
# ---------------------------------------------------------------------------

class FakeLLM(LLMBackend):
    """Scripted LLM backend for testing.

    Args:
        responses: Ordered list of strings to return on successive complete()
            calls.  Cycles (using modulo) if there are more calls than responses.
        error_on_call: If non-negative, raise LLMError on that call index
            (0-based).  Negative means never error.
        raise_mode: If True, every call raises LLMError.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        error_on_call: int = -1,
        raise_mode: bool = False,
    ) -> None:
        self.responses: list[str] = responses or ["KEEP"]
        self.error_on_call = error_on_call
        self.raise_mode = raise_mode
        self.calls: list[tuple[str, str]] = []  # (system, prompt) pairs

    def complete(self, system: str, prompt: str) -> str:
        idx = len(self.calls)
        self.calls.append((system, prompt))
        if self.raise_mode or idx == self.error_on_call:
            raise LLMError("FakeLLM simulated error")
        resp = self.responses[idx % len(self.responses)]
        return resp

    def reset(self) -> None:
        self.calls.clear()


@pytest.fixture
def fake_llm_keep() -> FakeLLM:
    return FakeLLM(responses=["KEEP"])


@pytest.fixture
def fake_llm_discard() -> FakeLLM:
    return FakeLLM(responses=["DISCARD"])


@pytest.fixture
def fake_llm_error() -> FakeLLM:
    return FakeLLM(raise_mode=True)


# ---------------------------------------------------------------------------
# FakeTTS: writes tiny fake MP3 bytes (or a real MP3 copy)
# ---------------------------------------------------------------------------

# Minimal ID3v2 header + empty MP3 frame so the file is non-empty
_TINY_MP3_BYTES = (
    b"ID3\x03\x00\x00\x00\x00\x00\x00"   # ID3v2.3 header (10 bytes, no tag)
    + b"\xff\xfb\x90\x00"                  # MP3 sync + header bytes
    + b"\x00" * 400                        # zero-padded frame data
)

FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg"
FFPROBE_BIN = "/opt/homebrew/bin/ffprobe"

_has_ffmpeg = shutil.which(FFMPEG_BIN) is not None or Path(FFMPEG_BIN).exists()


def _generate_real_tiny_mp3(out_path: Path, duration: float = 0.1) -> None:
    """Use ffmpeg to generate a real tiny silent MP3 (for audio tests)."""
    subprocess.run(
        [
            FFMPEG_BIN,
            "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=24000:cl=mono",
            "-t", str(duration),
            "-c:a", "libmp3lame",
            "-b:a", "64k",
            "-ar", "24000",
            "-ac", "1",
            str(out_path),
        ],
        capture_output=True,
        check=True,
    )


@pytest.fixture(scope="session")
def tiny_mp3_path(tmp_path_factory) -> Path:
    """Session-scoped real tiny MP3 (0.1 s silence) for audio tests."""
    if not _has_ffmpeg:
        pytest.skip("ffmpeg not available")
    p = tmp_path_factory.mktemp("audio") / "tiny.mp3"
    _generate_real_tiny_mp3(p, duration=0.1)
    return p


class FakeTTS(TTSBackend):
    """Fake TTS backend that copies a pre-generated tiny MP3 to out_path.

    Args:
        source_mp3: Path to an existing MP3 to copy on each synthesize call.
            When None, writes _TINY_MP3_BYTES (not a valid decodable MP3 but
            sufficient for non-audio tests).
        fail_on: Set of text strings (or None) for which synthesize should raise.
    """

    def __init__(
        self,
        source_mp3: Path | None = None,
        fail_on: set[str] | None = None,
    ) -> None:
        self.source_mp3 = source_mp3
        self.fail_on = fail_on or set()
        self.synthesized_texts: list[str] = []

    def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        from arxaudio.tts.base import TTSError
        self.synthesized_texts.append(text)
        if text in self.fail_on:
            raise TTSError(f"FakeTTS simulated failure for: {text[:40]!r}")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if self.source_mp3 is not None:
            import shutil as _shutil
            _shutil.copy2(self.source_mp3, out_path)
        else:
            out_path.write_bytes(_TINY_MP3_BYTES)

    def reset(self) -> None:
        self.synthesized_texts.clear()


@pytest.fixture
def fake_tts_bytes() -> FakeTTS:
    """FakeTTS that writes raw bytes (sufficient for non-audio tests)."""
    return FakeTTS(source_mp3=None)


@pytest.fixture
def fake_tts_real(tiny_mp3_path) -> FakeTTS:
    """FakeTTS that copies a real tiny MP3 (requires ffmpeg session fixture)."""
    return FakeTTS(source_mp3=tiny_mp3_path)


# ---------------------------------------------------------------------------
# pytest marks / skipif helpers
# ---------------------------------------------------------------------------

requires_ffmpeg = pytest.mark.skipif(
    not _has_ffmpeg,
    reason="ffmpeg not available at /opt/homebrew/bin/ffmpeg",
)
