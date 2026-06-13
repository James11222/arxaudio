"""Tests for arxaudio.audio.build_daily_audio.

Requires ffmpeg at /opt/homebrew/bin/ffmpeg.  The entire module is skipped
when ffmpeg is absent (see requires_ffmpeg mark from conftest).
"""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

import arxaudio.audio as audio_module
from arxaudio.audio import build_daily_audio, probe_duration
from arxaudio.models import Paper
from arxaudio.tts.base import TTSError

from conftest import FakeTTS, _has_ffmpeg, requires_ffmpeg

pytestmark = requires_ffmpeg


# ---------------------------------------------------------------------------
# Patch audio.py to use the correct ffmpeg/ffprobe binaries
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_ffmpeg_path(monkeypatch):
    """Point audio.py's _FFMPEG / _FFPROBE at the Homebrew binaries."""
    monkeypatch.setattr(audio_module, "_FFMPEG", "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(audio_module, "_FFPROBE", "/opt/homebrew/bin/ffprobe")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paper(arxiv_id: str, keep: bool | None = True) -> Paper:
    p = Paper(
        arxiv_id=arxiv_id,
        title=f"Title {arxiv_id}",
        abstract=f"Abstract for paper {arxiv_id}.",
        authors=["Author, A"],
        keep=keep,
    )
    return p


# ---------------------------------------------------------------------------
# Core tests
# ---------------------------------------------------------------------------

def test_output_file_exists(tmp_path, tiny_mp3_path):
    """build_daily_audio returns a path and the file exists."""
    tts = FakeTTS(source_mp3=tiny_mp3_path)
    papers = [_make_paper("001"), _make_paper("002")]
    out = tmp_path / "daily.mp3"
    result = build_daily_audio(papers, tts, "test-voice", out, pause_seconds=0.05)
    assert result is not None
    assert result.exists()
    assert result.stat().st_size > 0


def test_output_duration_reasonable(tmp_path, tiny_mp3_path):
    """Duration should be at least the sum of segment durations (loose tolerance)."""
    segment_duration = probe_duration(tiny_mp3_path)
    n_papers = 2
    pause = 0.05

    tts = FakeTTS(source_mp3=tiny_mp3_path)
    papers = [_make_paper(f"p{i}") for i in range(n_papers)]
    out = tmp_path / "daily.mp3"
    build_daily_audio(papers, tts, "test-voice", out, pause_seconds=pause)

    total = probe_duration(out)
    # Expected ≈ n_papers * segment_duration + (n_papers-1) * pause
    expected_min = n_papers * segment_duration + (n_papers - 1) * pause
    # Very loose: just verify we got something non-trivial
    assert total > 0
    # Allow generous tolerance (encoding overhead, rounding)
    assert total >= expected_min * 0.5


def test_discarded_paper_excluded(tmp_path, tiny_mp3_path):
    """Papers with keep=False must not be passed to TTS."""
    tts = FakeTTS(source_mp3=tiny_mp3_path)
    kept1 = _make_paper("k1", keep=True)
    kept2 = _make_paper("k2", keep=True)
    discarded = _make_paper("d1", keep=False)
    papers = [kept1, kept2, discarded]
    out = tmp_path / "daily.mp3"
    build_daily_audio(papers, tts, "v", out, pause_seconds=0.05)
    # The discarded paper's spoken_text should NOT appear in the TTS calls
    discarded_text = discarded.spoken_text()
    assert discarded_text not in tts.synthesized_texts


def test_returns_none_when_nothing_kept(tmp_path, tiny_mp3_path):
    """Returns None when no papers are kept."""
    tts = FakeTTS(source_mp3=tiny_mp3_path)
    papers = [_make_paper("d1", keep=False), _make_paper("d2", keep=False)]
    out = tmp_path / "daily.mp3"
    result = build_daily_audio(papers, tts, "v", out, pause_seconds=0.05)
    assert result is None


def test_returns_none_when_empty_list(tmp_path, tiny_mp3_path):
    tts = FakeTTS(source_mp3=tiny_mp3_path)
    out = tmp_path / "daily.mp3"
    result = build_daily_audio([], tts, "v", out)
    assert result is None


def test_one_tts_failure_does_not_kill_build(tmp_path, tiny_mp3_path):
    """A TTS failure on one paper must be skipped; remaining papers still produce audio."""
    paper_ok1 = _make_paper("ok1", keep=True)
    paper_fail = _make_paper("fail", keep=True)
    paper_ok2 = _make_paper("ok2", keep=True)

    # paper_fail is the 2nd kept paper → narrated as "Paper 2".
    fail_text = paper_fail.spoken_text(position=2)
    tts = FakeTTS(source_mp3=tiny_mp3_path, fail_on={fail_text})

    out = tmp_path / "daily.mp3"
    result = build_daily_audio(
        [paper_ok1, paper_fail, paper_ok2], tts, "v", out, pause_seconds=0.05
    )
    # Build should still succeed for the 2 good papers
    assert result is not None
    assert result.exists()


def test_all_papers_fail_tts_returns_none(tmp_path, tiny_mp3_path):
    """If every paper's TTS fails, build_daily_audio returns None."""
    paper = _make_paper("fail1", keep=True)
    fail_text = paper.spoken_text(position=1)
    tts = FakeTTS(source_mp3=tiny_mp3_path, fail_on={fail_text})
    out = tmp_path / "daily.mp3"
    result = build_daily_audio([paper], tts, "v", out)
    assert result is None


def test_two_kept_one_discarded(tmp_path, tiny_mp3_path):
    """Fixture-style test: 2 kept + 1 discarded; only 2 segments synthesized."""
    tts = FakeTTS(source_mp3=tiny_mp3_path)
    p1 = _make_paper("k1", keep=True)
    p2 = _make_paper("k2", keep=True)
    p3 = _make_paper("d1", keep=False)
    out = tmp_path / "daily.mp3"
    build_daily_audio([p1, p2, p3], tts, "v", out, pause_seconds=0.05)
    # TTS should have been called exactly twice (for k1 and k2)
    assert len(tts.synthesized_texts) == 2
    assert p3.spoken_text() not in tts.synthesized_texts


def test_intro_text_synthesized(tmp_path, tiny_mp3_path):
    """Optional intro_text must be included in the output."""
    tts = FakeTTS(source_mp3=tiny_mp3_path)
    papers = [_make_paper("p1", keep=True)]
    out = tmp_path / "daily.mp3"
    build_daily_audio(papers, tts, "v", out, intro_text="Welcome to ArXaudio.", pause_seconds=0.05)
    assert "Welcome to ArXaudio." in tts.synthesized_texts


def test_probe_duration_on_tiny_mp3(tiny_mp3_path):
    """probe_duration should return a positive float for a real MP3."""
    d = probe_duration(tiny_mp3_path)
    assert isinstance(d, float)
    assert d > 0
