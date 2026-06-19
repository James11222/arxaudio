"""arxaudio orchestrator — wires every stage into one daily run.

Runnable as a module::

    python -m arxaudio.pipeline                  # full daily run
    python -m arxaudio.pipeline --dry-run        # fetch+rank+process, no TTS/email
    python -m arxaudio.pipeline --no-email        # build the MP3 but don't send it

Flow (see idea.md / PLAN.md):
    load settings → read preferences.md → fetch the papers arXiv announced
    today (daily RSS mailing) →
    rank all titles by relevance in ONE LLM call → top N (MAX_PAPERS) get
    LLM-clean math + TTS into one MP3, the next N are listed email-only →
    email it.

    When PAPER_SOURCE == "benty", benty-fields replaces BOTH the arXiv fetch
    and the LLM rank stage: it returns the day's papers already in benty's
    ML-ranked order (best first), so everything downstream is unchanged.

Error policy (idea.md):
    * Systemic failures exit nonzero so GitHub Actions surfaces a real problem:
      arXiv unreachable, ollama server/model missing, SMTP auth failure when the
      user clearly intended email.
    * Per-paper issues never kill the run — the stage modules already isolate
      those (rank/process/audio each guard against failure; rank never loses a
      paper).

Backends are constructed through tiny registry factories (:func:`make_llm`,
:func:`make_tts`) so a future fine-tuned model or a different TTS engine is a
one-line registration here plus a new subclass — nothing else in the pipeline
changes.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import arxaudio.audio as audio
import arxaudio.emailer as emailer
import arxaudio.fetch as fetch
import arxaudio.process as process
import arxaudio.rank as rank_stage
from arxaudio.llm.base import LLMBackend, LLMError
from arxaudio.llm.ollama_backend import OllamaBackend
from arxaudio.models import Paper
from arxaudio.settings import Settings, load_settings
from arxaudio.tts.base import DirectAudioBackend, TTSBackend
from arxaudio.tts.edge_backend import EdgeTTSBackend

logger = logging.getLogger("arxaudio")

# Repo root: src/arxaudio/pipeline.py -> parents[2]. Used to locate the default
# preferences.md and math_replacements.md regardless of the caller's CWD.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PREFERENCES = _REPO_ROOT / "preferences.md"
_DEFAULT_MATH_TABLE = _REPO_ROOT / "math_replacements.md"


# ---------------------------------------------------------------------------
# Backend factories (registry pattern)
# ---------------------------------------------------------------------------
#
# To add a future backend (e.g. a fine-tuned local model), write a new
# LLMBackend subclass and register it here:
#
#     from arxaudio.llm.my_backend import MyBackend
#     _LLM_REGISTRY["mymodel"] = lambda s: MyBackend(...)
#
# then set LLM_BACKEND = "mymodel" in config.py. The rest of the pipeline is
# untouched because every stage depends only on the LLMBackend / TTSBackend ABCs.

_LLM_REGISTRY: dict[str, "callable[[Settings], LLMBackend]"] = {
    "ollama": lambda s: OllamaBackend(model=s.ollama_model),
}


def _make_notebooklm_backend(settings: "Settings") -> "DirectAudioBackend":
    """Lazy-import factory for the optional NotebookLM backend."""
    try:
        from arxaudio.tts.notebooklm_backend import NotebookLMTTSBackend
    except ImportError as exc:
        raise ValueError(
            "TTS_BACKEND is set to 'notebooklm' but notebooklm-py is not installed. "
            "Install it with:  pip install 'notebooklm-py>=0.8'  "
            "or:  pip install '.[notebooklm]'"
        ) from exc
    return NotebookLMTTSBackend(settings)


_TTS_REGISTRY: dict[str, "callable[[Settings], TTSBackend | DirectAudioBackend]"] = {
    "edge": lambda s: EdgeTTSBackend(default_voice=s.tts_voice, speed=s.tts_speed),
    "notebooklm": lambda s: _make_notebooklm_backend(s),
}


def make_llm(settings: Settings) -> LLMBackend:
    """Construct the configured LLM backend (``settings.llm_backend``)."""
    try:
        factory = _LLM_REGISTRY[settings.llm_backend]
    except KeyError:
        raise ValueError(
            f"Unknown LLM_BACKEND {settings.llm_backend!r}. "
            f"Available: {sorted(_LLM_REGISTRY)}. "
            "Register a new backend in arxaudio.pipeline._LLM_REGISTRY."
        ) from None
    return factory(settings)


def make_tts(settings: Settings) -> "TTSBackend | DirectAudioBackend":
    """Construct the configured TTS backend (``settings.tts_backend``).
    
    Returns either a TTSBackend (for segment-by-segment synthesis) or a
    DirectAudioBackend (for batch generation of the entire audio file).
    """
    try:
        factory = _TTS_REGISTRY[settings.tts_backend]
    except KeyError:
        raise ValueError(
            f"Unknown TTS_BACKEND {settings.tts_backend!r}. "
            f"Available: {sorted(_TTS_REGISTRY)}. "
            "Register a new backend in arxaudio.pipeline._TTS_REGISTRY."
        ) from None
    return factory(settings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_output() -> Path:
    return Path("output") / f"arxaudio_{date.today().isoformat()}.mp3"


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arxaudio",
        description=(
            "Fetch new arXiv papers, rank them against your preferences in one "
            "LLM call, clean math notation for speech on the top picks, "
            "synthesize one MP3, and email it (with the next picks listed)."
        ),
    )
    p.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to config.py (default: repo-root config.py).",
    )
    p.add_argument(
        "--preferences",
        metavar="PATH",
        default=None,
        help="Path to preferences.md (default: repo-root preferences.md).",
    )
    p.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Output MP3 path (default: ./output/arxaudio_YYYY-MM-DD.mp3).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )

    # Override flags
    p.add_argument(
        "--max-papers",
        type=int,
        metavar="N",
        default=None,
        help="Override MAX_PAPERS (0 = unlimited).",
    )
    # Stage-skipping flags (debugging / testing)
    p.add_argument(
        "--no-rank",
        "--no-filter",  # backwards-compatible alias for the old flag name
        dest="no_rank",
        action="store_true",
        help="Skip the LLM ranking; use feed (arrival) order.",
    )
    p.add_argument(
        "--no-llm-clean",
        action="store_true",
        help="Skip the LLM math-cleanup polish; use regex-only replacements.",
    )
    p.add_argument(
        "--no-email",
        action="store_true",
        help="Build the audio but do not send the email.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Fetch + rank + process only; print what would be synthesized and "
            "the email-only extras, then exit. No TTS, no email."
        ),
    )
    return p


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------

def _read_preferences(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        # A missing preferences file is a systemic/config error: fail fast.
        raise RuntimeError(
            f"Could not read preferences file {path}: {exc}. "
            "Create a preferences.md describing your research interests "
            "(or pass --preferences PATH)."
        ) from exc


def _split_ranked(
    ranked: list[Paper], max_papers: int
) -> tuple[list[Paper], list[Paper]]:
    """Split a relevance-ordered list into (audio papers, email-only extras).

    ``max_papers`` (= MAX_PAPERS, ``n``) is the audio budget. With ``n == 0``
    (unlimited) every ranked paper gets audio and there are no extras. Otherwise
    the top ``n`` get audio and the next ``n`` (ranks N+1..2N) are listed in the
    email only. Sets ``keep`` to True on audio papers and False on everything
    else, since process/audio (and their tests) key off ``keep``.
    """
    if max_papers and len(ranked) > max_papers:
        audio_papers = ranked[:max_papers]
        extras = ranked[max_papers : 2 * max_papers]
        logger.info(
            "Ranked %d papers: top %d -> audio, next %d -> email-only.",
            len(ranked),
            len(audio_papers),
            len(extras),
        )
    else:
        audio_papers = list(ranked)
        extras = []

    for paper in audio_papers:
        paper.keep = True
    for paper in ranked:
        if paper not in audio_papers:
            paper.keep = False
    return audio_papers, extras


def _regex_only_clean(papers: list[Paper]) -> None:
    """Populate clean_title/clean_abstract using only the regex table (no LLM)."""
    for paper in papers:
        if not paper.keep:
            continue
        paper.clean_title = process.apply_replacements(
            paper.title, table_path=_DEFAULT_MATH_TABLE
        )
        paper.clean_abstract = process.apply_replacements(
            paper.abstract, table_path=_DEFAULT_MATH_TABLE
        )
        logger.info("process (regex-only): cleaned %s", paper.arxiv_id)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    """Execute one pipeline run. Returns a process exit code."""
    # --- Load settings --------------------------------------------------
    settings = load_settings(args.config)
    if args.max_papers is not None:
        settings.max_papers = args.max_papers
        logger.info("Override: max_papers=%d", settings.max_papers)

    preferences_path = (
        Path(args.preferences) if args.preferences else _DEFAULT_PREFERENCES
    )
    preferences = _read_preferences(preferences_path)

    output_path = Path(args.output) if args.output else _default_output()

    benty_mode = settings.paper_source == "benty"
    notebooklm_mode = settings.tts_backend == "notebooklm"

    # In notebookLM mode the TTS backend handles text formatting internally, so
    # the LLM math-cleanup pass (process stage) is skipped regardless of flags.
    # In benty mode ranking is pre-computed, so only the clean step may need LLM.
    if notebooklm_mode:
        # No LLM needed for cleanup; only arXiv mode still needs ranking.
        if benty_mode:
            needs_llm = False
        else:
            needs_llm = not args.no_rank
    elif benty_mode:
        needs_llm = not args.no_llm_clean
    else:
        needs_llm = not (args.no_rank and args.no_llm_clean)

    # --- Fetch ----------------------------------------------------------
    # A RuntimeError here (arXiv unreachable, or benty login/network) is
    # systemic; let it propagate.
    if benty_mode:
        import arxaudio.benty as benty

        logger.info(
            "Source: benty-fields (papers come pre-ranked by your account's ML model)."
        )
        papers = benty.fetch_benty_papers(settings)
    else:
        papers = fetch.fetch_announced_papers(settings.categories)
    if not papers:
        logger.info("nothing new today — no papers in today's mailing. Exiting.")
        return 0
    logger.info("Fetched %d papers.", len(papers))

    # --- LLM backend + health check (fail fast) -------------------------
    llm: LLMBackend | None = None
    if needs_llm:
        llm = make_llm(settings)
        ensure = getattr(llm, "ensure_model", None)
        if callable(ensure):
            try:
                ensure()
            except LLMError as exc:
                logger.error("LLM backend health check failed: %s", exc)
                return 1

    # --- Rank -----------------------------------------------------------
    # One LLM call orders all titles by relevance. We skip it (and use feed
    # order) when:
    #   * --no-rank is set, or
    #   * MAX_PAPERS is a real cap and we fetched no more than that many papers
    #     — ranking couldn't change membership and there are no email-only
    #     extras to order, so the call would only reshuffle audio order.
    # When MAX_PAPERS == 0 (unlimited) we still rank, so audio order reflects
    # relevance, unless --no-rank says otherwise.
    n = settings.max_papers
    if benty_mode:
        # benty already returned papers in its ML-ranked order; that order IS
        # the ranking, so the LLM rank step is skipped entirely (--no-rank is
        # irrelevant here).
        ranked = list(papers)
        logger.info("Using benty-fields ranking (LLM ranking step skipped).")
    else:
        skip_rank = args.no_rank or (n and len(papers) <= n)
        if skip_rank:
            ranked = list(papers)
            reason = "--no-rank" if args.no_rank else f"fetched <= MAX_PAPERS={n}"
            logger.info("Ranking skipped (%s): using arrival order.", reason)
        else:
            assert llm is not None
            ranked = rank_stage.rank_papers(papers, llm, preferences)

    # --- Split into audio papers + email-only extras --------------------
    kept, extras = _split_ranked(ranked, n)

    if not kept:
        logger.info("No papers to synthesize today.")
        return 0

    # One-line-per-paper digest record (doubles as the Actions log digest).
    for paper in kept:
        logger.info("AUDIO %s — %s", paper.arxiv_id, paper.title)
    for paper in extras:
        logger.info("EMAIL-ONLY %s — %s", paper.arxiv_id, paper.title)

    # --- Process (math cleanup) -----------------------------------------
    # Skipped entirely when the notebookLM backend is active: NotebookLM
    # generates audio from the raw title/author/abstract text directly (it
    # handles scientific notation internally), so math cleanup adds no value.
    if notebooklm_mode:
        logger.info(
            "Process stage skipped (TTS_BACKEND=notebooklm): "
            "NotebookLM handles text formatting."
        )
    elif args.no_llm_clean:
        logger.info("LLM clean skipped (--no-llm-clean): regex-only math cleanup.")
        _regex_only_clean(kept)
    else:
        assert llm is not None
        process.process_papers(kept, llm)

    # --- Dry run stops here ---------------------------------------------
    if args.dry_run:
        logger.info("Dry run — the following %d papers would be synthesized:", len(kept))
        for i, paper in enumerate(kept, start=1):
            print(f"\n[{i}/{len(kept)}] {paper.arxiv_id}")
            print(f"  TITLE:    {paper.clean_title or paper.title}")
            print(f"  AUTHOR:   {paper.first_author}"
                  f"{' et al' if len(paper.authors) > 1 else ''}")
            abstract = paper.clean_abstract or paper.abstract
            print(f"  ABSTRACT: {abstract}")
        if extras:
            print(f"\nEmail-only ({len(extras)} more, listed but not synthesized):")
            for i, paper in enumerate(extras, start=1):
                byline = paper.first_author + (
                    " et al" if len(paper.authors) > 1 else ""
                )
                print(f"  {i}. {paper.title} — {byline} — {paper.url}")
        logger.info("Dry run complete (no TTS, no email).")
        return 0

    # --- TTS / audio ----------------------------------------------------
    tts = make_tts(settings)
    today_human = date.today().strftime("%B %-d, %Y")

    if isinstance(tts, DirectAudioBackend):
        # Batch backends (e.g. notebookLM) generate a single audio file for
        # all papers in one call.  No per-paper segment, no intro, no ffmpeg.
        logger.info(
            "Using DirectAudioBackend (%s) to generate a single audio file "
            "for %d papers.",
            type(tts).__name__,
            len(kept),
        )
        try:
            tts.generate_audio(kept, output_path)
            mp3_path: Path | None = output_path
        except Exception as exc:  # noqa: BLE001 - surface as systemic failure
            logger.error("DirectAudioBackend failed: %s", exc)
            mp3_path = None
    else:
        intro_text = f"Ark audio digest for {today_human}. {len(kept)} papers."
        closing_text = (
            "That's all we have for today. "
            "Thanks for listening to the ark audio podcast."
        )
        mp3_path = audio.build_daily_audio(
            kept,
            tts,
            voice=settings.tts_voice,
            out_path=output_path,
            max_mb=settings.max_mb,
            pause_seconds=settings.pause_seconds,
            intro_text=intro_text,
            closing_text=closing_text,
        )

    if mp3_path is None:
        logger.warning(
            "No audio produced (all TTS segments failed). Skipping email."
        )
        # Every segment failing is effectively a systemic TTS/network failure.
        return 1

    audio_mb = mp3_path.stat().st_size / 1_000_000

    # --- Email ----------------------------------------------------------
    emailed = False
    if args.no_email:
        logger.info("Email skipped (--no-email). Audio at %s", mp3_path)
    elif not settings.smtp_configured:
        # Distinguish "user clearly intended email but mis-configured it" from
        # "email simply not set up". Partial SMTP config => exit nonzero.
        partial = any(
            [settings.smtp_host, settings.smtp_user, settings.smtp_password]
        )
        if partial:
            logger.error(
                "SMTP is only partially configured (need SMTP_HOST, SMTP_USER, "
                "and SMTP_PASSWORD). You appear to have intended email delivery; "
                "failing so the misconfiguration is visible."
            )
            return 1
        logger.warning(
            "SMTP not configured; skipping email. Audio saved at %s", mp3_path
        )
    else:
        try:
            emailer.send_digest(
                settings, mp3_path, audio_papers=kept, extra_papers=extras
            )
            emailed = True
        except Exception as exc:  # SMTP auth/connect/etc. are systemic.
            logger.error("Failed to send digest email: %s", exc)
            return 1

    # --- Summary --------------------------------------------------------
    logger.info(
        "Done. fetched=%d audio=%d email-only=%d mp3=%s (%.1f MB) emailed=%s",
        len(papers),
        len(kept),
        len(extras),
        mp3_path,
        audio_mb,
        emailed,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    configure_logging(args.verbose)
    try:
        return run(args)
    except KeyboardInterrupt:
        logger.error("Interrupted.")
        return 130
    except Exception as exc:  # systemic failure — surface it nonzero for CI.
        logger.error("Pipeline failed: %s", exc, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
