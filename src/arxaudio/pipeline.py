"""arxaudio orchestrator — wires every stage into one daily run.

Runnable as a module::

    python -m arxaudio.pipeline                  # full daily run
    python -m arxaudio.pipeline --dry-run        # fetch+filter+process, no TTS/email
    python -m arxaudio.pipeline --no-email        # build the MP3 but don't send it

Flow (see idea.md / PLAN.md):
    load settings → read preferences.md → fetch recent arXiv papers →
    LLM-filter against preferences → cap to MAX_PAPERS → LLM-clean math notation →
    TTS into one MP3 → email it.

Error policy (idea.md):
    * Systemic failures exit nonzero so GitHub Actions surfaces a real problem:
      arXiv unreachable, ollama server/model missing, SMTP auth failure when the
      user clearly intended email.
    * Per-paper issues never kill the run — the stage modules already isolate
      those (filter/process/audio each guard per paper).

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
import arxaudio.filter as filter_stage
import arxaudio.process as process
from arxaudio.llm.base import LLMBackend, LLMError
from arxaudio.llm.ollama_backend import OllamaBackend
from arxaudio.models import Paper
from arxaudio.settings import Settings, load_settings
from arxaudio.tts.base import TTSBackend
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

_TTS_REGISTRY: dict[str, "callable[[Settings], TTSBackend]"] = {
    "edge": lambda s: EdgeTTSBackend(default_voice=s.tts_voice),
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


def make_tts(settings: Settings) -> TTSBackend:
    """Construct the configured TTS backend (``settings.tts_backend``)."""
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
            "Fetch new arXiv papers, LLM-filter by your preferences, clean math "
            "notation for speech, synthesize one MP3, and email it."
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
    p.add_argument(
        "--lookback-hours",
        type=int,
        metavar="N",
        default=None,
        help="Override LOOKBACK_HOURS.",
    )

    # Stage-skipping flags (debugging / testing)
    p.add_argument(
        "--no-filter",
        action="store_true",
        help="Skip the LLM relevance filter (keep every fetched paper).",
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
            "Fetch + filter + process only; print what would be synthesized and "
            "exit. No TTS, no email."
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


def _apply_cap(papers: list[Paper], max_papers: int) -> list[Paper]:
    """Trim kept papers to ``max_papers`` (0 = unlimited). Mutates keep flags.

    fetch returns most-recent-first, so the cap keeps the freshest papers.
    Papers dropped by the cap have ``keep`` cleared so downstream stages (which
    all key off ``keep``) ignore them consistently.
    """
    kept = [p for p in papers if p.keep]
    if max_papers and len(kept) > max_papers:
        for paper in kept[max_papers:]:
            paper.keep = False
        logger.info(
            "Capped kept papers from %d to MAX_PAPERS=%d.", len(kept), max_papers
        )
        kept = kept[:max_papers]
    return kept


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
    if args.lookback_hours is not None:
        settings.lookback_hours = args.lookback_hours
        logger.info("Override: lookback_hours=%d", settings.lookback_hours)
    if args.max_papers is not None:
        settings.max_papers = args.max_papers
        logger.info("Override: max_papers=%d", settings.max_papers)

    preferences_path = (
        Path(args.preferences) if args.preferences else _DEFAULT_PREFERENCES
    )
    preferences = _read_preferences(preferences_path)

    output_path = Path(args.output) if args.output else _default_output()

    needs_llm = not (args.no_filter and args.no_llm_clean)

    # --- Fetch ----------------------------------------------------------
    # A RuntimeError here (arXiv unreachable) is systemic; let it propagate.
    papers = fetch.fetch_recent_papers(
        settings.categories,
        lookback_hours=settings.lookback_hours,
    )
    if not papers:
        logger.info("nothing new today — no papers in the look-back window. Exiting.")
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

    # --- Filter ---------------------------------------------------------
    if args.no_filter:
        for paper in papers:
            paper.keep = True
        logger.info("Filter skipped (--no-filter): keeping all %d papers.", len(papers))
    else:
        assert llm is not None
        filter_stage.filter_papers(papers, llm, preferences)

    # --- Cap ------------------------------------------------------------
    kept = _apply_cap(papers, settings.max_papers)
    logger.info("%d papers kept after filter/cap.", len(kept))

    if not kept:
        logger.info("No papers survived filtering today. Nothing to synthesize.")
        return 0

    # One-line-per-paper digest record (doubles as the Actions log digest).
    for paper in kept:
        logger.info("KEEP %s — %s", paper.arxiv_id, paper.title)

    # --- Process (math cleanup) -----------------------------------------
    if args.no_llm_clean:
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
        logger.info("Dry run complete (no TTS, no email).")
        return 0

    # --- TTS / audio ----------------------------------------------------
    tts = make_tts(settings)
    today_human = date.today().strftime("%B %-d, %Y")
    intro_text = f"Arx audio digest for {today_human}. {len(kept)} papers."
    mp3_path = audio.build_daily_audio(
        kept,
        tts,
        voice=settings.tts_voice,
        out_path=output_path,
        max_mb=settings.max_mb,
        pause_seconds=settings.pause_seconds,
        intro_text=intro_text,
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
        titles = [p.clean_title or p.title for p in kept]
        try:
            emailer.send_digest(settings, mp3_path, n_papers=len(kept), paper_titles=titles)
            emailed = True
        except Exception as exc:  # SMTP auth/connect/etc. are systemic.
            logger.error("Failed to send digest email: %s", exc)
            return 1

    # --- Summary --------------------------------------------------------
    logger.info(
        "Done. fetched=%d kept=%d audio=%s (%.1f MB) emailed=%s",
        len(papers),
        len(kept),
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
