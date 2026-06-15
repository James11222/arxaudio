"""Tests for the NotebookLM TTS backend.

All tests are fully offline: the notebooklm-py library is mocked at the
client level.  We never make a real network call to Google.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arxaudio.models import Paper
from arxaudio.tts.base import DirectAudioBackend, TTSError
from arxaudio.tts.notebooklm_backend import (
    NotebookLMTTSBackend,
    _format_source_text,
    _format_source_title,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(
    auth_json: str = '{"cookies": [], "origins": []}',
    audio_format: str = "brief",
    audio_length: str = "default",
    instructions: str = "Test instructions.",
    delete_notebook: bool = True,
    timeout: int = 60,
):
    """Return a minimal Settings-like object for the NotebookLM backend."""
    s = MagicMock()
    s.notebooklm_auth_json = auth_json
    s.notebooklm_audio_format = audio_format
    s.notebooklm_audio_length = audio_length
    s.notebooklm_instructions = instructions
    s.notebooklm_delete_notebook = delete_notebook
    s.notebooklm_timeout = timeout
    return s


def _make_paper(arxiv_id: str = "2606.01234", keep: bool = True) -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        title=f"Test Paper {arxiv_id}",
        abstract="This is a test abstract.",
        authors=["Smith, Alice", "Jones, Bob"],
        categories=["astro-ph.CO"],
        published="2026-06-10T00:00:00+00:00",
        keep=keep,
    )


def _make_mock_client(notebook_id: str = "nb-123"):
    """Build a fully mocked notebooklm client."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    # notebooks
    nb = MagicMock()
    nb.id = notebook_id
    client.notebooks.create = AsyncMock(return_value=nb)
    client.notebooks.delete = AsyncMock(return_value=None)

    # sources
    client.sources.add_text = AsyncMock(return_value=None)

    # artifacts
    status = MagicMock()
    status.task_id = "task-abc"
    client.artifacts.generate_audio = AsyncMock(return_value=status)

    final_status = MagicMock()
    final_status.is_complete = True
    final_status.status = "completed"
    client.artifacts.wait_for_completion = AsyncMock(return_value=final_status)

    client.artifacts.download_audio = AsyncMock(return_value=None)

    return client


def _make_mock_notebooklm_module(mock_client):
    """Create a mock notebooklm module."""
    mock_module = MagicMock()
    
    # AudioFormat enum-like
    mock_fmt = MagicMock()
    mock_fmt.__getitem__ = MagicMock(side_effect=lambda k: f"AudioFormat.{k}")
    mock_module.AudioFormat = mock_fmt
    
    # AudioLength enum-like
    mock_len = MagicMock()
    mock_len.__getitem__ = MagicMock(side_effect=lambda k: f"AudioLength.{k}")
    mock_module.AudioLength = mock_len
    
    # NotebookLMClient
    mock_cls = MagicMock()
    mock_cls.from_storage = MagicMock(return_value=mock_client)
    mock_module.NotebookLMClient = mock_cls
    
    return mock_module


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------

class TestNotebookLMTTSBackendConstruction:
    def test_is_direct_audio_backend(self):
        settings = _make_settings()
        backend = NotebookLMTTSBackend(settings)
        assert isinstance(backend, DirectAudioBackend)

    def test_raises_tts_error_when_no_auth(self):
        settings = _make_settings(auth_json="")
        with pytest.raises(TTSError, match="NOTEBOOKLM_AUTH_JSON"):
            NotebookLMTTSBackend(settings)

    def test_stores_settings(self):
        settings = _make_settings(
            audio_format="deep-dive",
            audio_length="long",
            delete_notebook=False,
            timeout=300,
        )
        backend = NotebookLMTTSBackend(settings)
        assert backend._audio_format == "deep-dive"
        assert backend._audio_length == "long"
        assert backend._delete_notebook is False
        assert backend._timeout == 300


# ---------------------------------------------------------------------------
# Source text formatting
# ---------------------------------------------------------------------------

class TestSourceFormatting:
    def test_format_source_text_includes_title(self):
        paper = _make_paper()
        text = _format_source_text(paper)
        assert "Title:" in text
        assert paper.title in text

    def test_format_source_text_includes_first_author(self):
        paper = _make_paper()
        text = _format_source_text(paper)
        assert "First Author:" in text
        assert paper.first_author in text

    def test_format_source_text_includes_abstract(self):
        paper = _make_paper()
        text = _format_source_text(paper)
        assert "Abstract:" in text
        assert paper.abstract in text

    def test_format_source_title_short_title(self):
        paper = _make_paper()
        title = _format_source_title(paper)
        assert title == paper.title

    def test_format_source_title_truncates_long_title(self):
        paper = _make_paper()
        paper.title = "A" * 250
        title = _format_source_title(paper)
        assert len(title) <= 200
        assert title.endswith("…")


# ---------------------------------------------------------------------------
# generate_audio tests (with mocked notebooklm client)
# ---------------------------------------------------------------------------

class TestGenerateAudio:
    def test_happy_path_creates_file(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings()
        backend = NotebookLMTTSBackend(settings)
        papers = [_make_paper("2606.01234"), _make_paper("2606.05678")]
        mock_client = _make_mock_client()

        # Make download_audio write a real file
        async def fake_download(nb_id, path):
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        mock_client.artifacts.download_audio = fake_download

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            backend.generate_audio(papers, out_path)

        assert out_path.exists()
        assert out_path.stat().st_size > 0

    def test_notebook_created_with_date_name(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings()
        backend = NotebookLMTTSBackend(settings)
        papers = [_make_paper()]
        mock_client = _make_mock_client()

        async def fake_download(nb_id, path):
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        mock_client.artifacts.download_audio = fake_download

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            backend.generate_audio(papers, out_path)

        # Notebook created with a name starting "arxaudio -"
        mock_client.notebooks.create.assert_awaited_once()
        args = mock_client.notebooks.create.call_args
        assert args[0][0].startswith("arxaudio -")

    def test_sources_added_for_each_paper(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings()
        backend = NotebookLMTTSBackend(settings)
        papers = [_make_paper("A"), _make_paper("B"), _make_paper("C")]
        mock_client = _make_mock_client()

        async def fake_download(nb_id, path):
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        mock_client.artifacts.download_audio = fake_download

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            backend.generate_audio(papers, out_path)

        assert mock_client.sources.add_text.await_count == 3

    def test_only_kept_papers_added(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings()
        backend = NotebookLMTTSBackend(settings)
        kept = _make_paper("keep-1", keep=True)
        discarded = _make_paper("discard-1", keep=False)
        papers = [kept, discarded]
        mock_client = _make_mock_client()

        async def fake_download(nb_id, path):
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        mock_client.artifacts.download_audio = fake_download

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            backend.generate_audio(papers, out_path)

        # Only 1 source added (the kept paper)
        assert mock_client.sources.add_text.await_count == 1

    def test_notebook_deleted_when_delete_true(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings(delete_notebook=True)
        backend = NotebookLMTTSBackend(settings)
        papers = [_make_paper()]
        mock_client = _make_mock_client()

        async def fake_download(nb_id, path):
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        mock_client.artifacts.download_audio = fake_download

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            backend.generate_audio(papers, out_path)

        mock_client.notebooks.delete.assert_awaited_once_with("nb-123")

    def test_notebook_not_deleted_when_delete_false(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings(delete_notebook=False)
        backend = NotebookLMTTSBackend(settings)
        papers = [_make_paper()]
        mock_client = _make_mock_client()

        async def fake_download(nb_id, path):
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        mock_client.artifacts.download_audio = fake_download

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            backend.generate_audio(papers, out_path)

        mock_client.notebooks.delete.assert_not_awaited()

    def test_notebook_deleted_on_failure(self, tmp_path):
        """Notebook is cleaned up even when generation fails."""
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings(delete_notebook=True)
        backend = NotebookLMTTSBackend(settings)
        papers = [_make_paper()]
        mock_client = _make_mock_client()

        # Make generation fail
        mock_client.artifacts.generate_audio = AsyncMock(
            side_effect=RuntimeError("generation failed")
        )

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            with pytest.raises(TTSError):
                backend.generate_audio(papers, out_path)

        # Notebook should still be deleted despite the error
        mock_client.notebooks.delete.assert_awaited_once_with("nb-123")

    def test_raises_tts_error_when_generation_not_complete(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings()
        backend = NotebookLMTTSBackend(settings)
        papers = [_make_paper()]
        mock_client = _make_mock_client()

        # Generation "completes" but not successfully
        failed_status = MagicMock()
        failed_status.is_complete = False
        failed_status.status = "failed"
        mock_client.artifacts.wait_for_completion = AsyncMock(
            return_value=failed_status
        )

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            with pytest.raises(TTSError, match="did not complete"):
                backend.generate_audio(papers, out_path)

    def test_raises_tts_error_when_no_papers(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings()
        backend = NotebookLMTTSBackend(settings)
        # All papers have keep=False
        papers = [_make_paper(keep=False)]

        with pytest.raises(TTSError, match="no kept papers"):
            backend.generate_audio(papers, out_path)

    def test_audio_format_brief_used(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        settings = _make_settings(audio_format="brief")
        backend = NotebookLMTTSBackend(settings)
        papers = [_make_paper()]
        mock_client = _make_mock_client()

        async def fake_download(nb_id, path):
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        mock_client.artifacts.download_audio = fake_download

        captured = {}

        async def capture_generate(nb_id, instructions=None, audio_format=None, audio_length=None):
            captured['audio_format'] = audio_format
            captured['audio_length'] = audio_length
            s = MagicMock()
            s.task_id = "task-abc"
            return s

        mock_client.artifacts.generate_audio = capture_generate

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            backend.generate_audio(papers, out_path)

        # The format map should have mapped "brief" -> "BRIEF"
        assert captured['audio_format'] == "AudioFormat.BRIEF"

    def test_instructions_passed_to_generate(self, tmp_path):
        out_path = tmp_path / "audio.mp3"
        custom_instructions = "My custom astrophysics instructions."
        settings = _make_settings(instructions=custom_instructions)
        backend = NotebookLMTTSBackend(settings)
        papers = [_make_paper()]
        mock_client = _make_mock_client()

        async def fake_download(nb_id, path):
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        mock_client.artifacts.download_audio = fake_download

        captured_instructions = []

        async def capture_generate(nb_id, instructions=None, **kwargs):
            captured_instructions.append(instructions)
            s = MagicMock()
            s.task_id = "task-abc"
            return s

        mock_client.artifacts.generate_audio = capture_generate

        mock_module = _make_mock_notebooklm_module(mock_client)
        with patch.dict(sys.modules, {"notebooklm": mock_module}):
            backend.generate_audio(papers, out_path)

        assert captured_instructions[0] == custom_instructions
