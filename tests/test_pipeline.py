from __future__ import annotations

import argparse
from pathlib import Path

from arxaudio.models import Paper
from arxaudio.settings import Settings
import arxaudio.pipeline as pipeline


def test_run_returns_success_when_tts_produces_no_audio(tmp_path, monkeypatch):
    prefs = tmp_path / "preferences.md"
    prefs.write_text("prioritize cosmology", encoding="utf-8")

    settings = Settings(max_papers=1, tts_backend="edge")
    papers = [
        Paper(
            arxiv_id="2610.00001",
            title="Test title",
            abstract="Test abstract",
            authors=["Author One"],
            categories=["astro-ph.CO"],
        )
    ]

    monkeypatch.setattr(pipeline, "load_settings", lambda _cfg: settings)
    monkeypatch.setattr(
        pipeline.fetch,
        "fetch_announced_papers",
        lambda _categories: papers,
    )
    monkeypatch.setattr(pipeline, "_save_rank_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "make_tts", lambda _settings: object())
    monkeypatch.setattr(
        pipeline.audio,
        "build_daily_audio",
        lambda *_args, **_kwargs: None,
    )

    args = argparse.Namespace(
        config=None,
        preferences=str(prefs),
        output=str(Path(tmp_path) / "digest.mp3"),
        output_text=None,
        verbose=False,
        max_papers=None,
        no_rank=True,
        no_llm_clean=True,
        no_email=False,
        dry_run=False,
    )

    assert pipeline.run(args) == 0
