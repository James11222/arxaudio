#!/usr/bin/env python3
"""Compare ranking quality of different Qwen2.5 models on a fixed paper set.

Loads paper titles from an existing rank log (the June-23 run is bundled by
default), runs one ranking call per model, then prints per-model top-10 lists
and a side-by-side score table so you can compare ranking quality at a glance.

Prerequisites:
  - ollama is installed and `ollama serve` is running
  - the arxaudio package is installed (`pip install -e .`) OR you run this
    script from the repo root (the src/ path is added automatically)

Usage:
  python compare_rankers.py
  python compare_rankers.py --models qwen2.5:0.5b qwen2.5:1.5b qwen2.5:3b qwen2.5:7b
  python compare_rankers.py --rank-file output/arxaudio_rank_2026-06-17.txt
  python compare_rankers.py --no-pull   # skip auto-pull, fail if a model is missing
  python compare_rankers.py --top-n 15  # show top 15 per model (default 10)
  python compare_rankers.py --timeout 1800  # seconds per model (default 1800)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

# Allow running without pip install -e .
sys.path.insert(0, str(Path(__file__).parent / "src"))

from arxaudio.llm.ollama_backend import OllamaBackend
from arxaudio.models import Paper
import arxaudio.rank as rank_stage

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent

DEFAULT_MODELS = [
    "qwen2.5:0.5b",
    "qwen2.5:1.5b",
    "qwen2.5:3b",
    "qwen2.5:7b",
]
DEFAULT_RANK_FILE = _REPO_ROOT / "output" / "arxaudio_rank_2026-06-23.txt"
DEFAULT_PREFS     = _REPO_ROOT / "preferences.txt"
DEFAULT_TIMEOUT   = 1800.0   # 30 min — enough for qwen2.5:7b on M1
DEFAULT_TOP_N     = 10

# Matches lines like:
#   "  1.     ?/10 [AUDIO     ] 2606.20794  Some Title Here"
#   "  42.    7/10 [UNSELECTED] 2606.99999  Another Title"
_LINE_RE = re.compile(
    r"^\s*\d+\.\s+[\d?]+(?:\.\d+)?/10\s+\[[\w\s\-]+\]\s+(\S+)\s+(.+)$"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_rank_file(path: Path) -> list[Paper]:
    """Extract (arxiv_id, title) pairs from an arxaudio rank log."""
    papers: list[Paper] = []
    with open(path) as fh:
        for line in fh:
            m = _LINE_RE.match(line)
            if m:
                arxiv_id = m.group(1).strip()
                title    = m.group(2).strip()
                papers.append(Paper(arxiv_id=arxiv_id, title=title, abstract=""))
    return papers


def model_is_present(model: str) -> bool:
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    return model in result.stdout


def pull_model(model: str) -> None:
    print(f"  pulling {model} ...", flush=True)
    r = subprocess.run(["ollama", "pull", model])
    if r.returncode != 0:
        print(f"  WARNING: 'ollama pull {model}' exited {r.returncode}. Will try anyway.")


def rank_with(
    model: str,
    papers: list[Paper],
    preferences: str,
    timeout: float,
) -> tuple[list[Paper], float]:
    """Return (ranked_papers, elapsed_seconds) for one model."""
    fresh = [Paper(arxiv_id=p.arxiv_id, title=p.title, abstract="") for p in papers]
    llm   = OllamaBackend(model=model, timeout=timeout)
    t0    = time.perf_counter()
    ranked, _, _, _ = rank_stage.rank_papers(fresh, llm, preferences)
    return ranked, time.perf_counter() - t0


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _score_str(score: float | None) -> str:
    return f"{score:.1f}" if score is not None else "?"


def print_top_n(model: str, ranked: list[Paper], n: int) -> None:
    print(f"\n  {'─' * 66}")
    print(f"  Top {n}  ·  {model}")
    print(f"  {'─' * 66}")
    for i, p in enumerate(ranked[:n], 1):
        score = _score_str(p.relevance_score)
        print(f"  {i:>2}. [{score:>4}]  {p.title[:72]}")


def print_comparison_table(
    papers: list[Paper],
    results: dict[str, list[Paper]],
    models: list[str],
    timings: dict[str, float],
    top_n: int,
) -> None:
    # score lookup: model -> arxiv_id -> score
    score_map: dict[str, dict[str, float]] = {
        m: {p.arxiv_id: (p.relevance_score or 0.0) for p in ranked}
        for m, ranked in results.items()
    }

    # Sort papers by the first (reference) model's score
    ref = models[0]
    sorted_papers = sorted(
        papers,
        key=lambda p: score_map[ref].get(p.arxiv_id, 0.0),
        reverse=True,
    )

    # Column widths
    score_col = 6   # " 7.0  "
    tag_col   = max(len(m) for m in models)

    header_scores = "  ".join(f"{m:>{score_col}}" for m in models)
    header = f"{'#':>3}  {header_scores}  Title"
    divider = "─" * min(len(header) + 20, 120)

    print(f"\n{'═' * len(divider)}")
    print(f"COMPARISON TABLE  (sorted by {ref},  showing top {top_n} of {len(papers)})")
    print(f"{'═' * len(divider)}")

    # Model legend with timing
    for m in models:
        t = timings.get(m)
        t_str = f"{t:.0f}s" if t is not None else "n/a"
        print(f"  {m:<{tag_col}}   ({t_str})")

    print(divider)
    print(f"{'#':>3}  {header_scores}  Title")
    print(divider)

    prev_block: str | None = None
    for i, p in enumerate(sorted_papers[:top_n], 1):
        row_scores = "  ".join(
            f"{score_map[m].get(p.arxiv_id, 0.0):>{score_col}.1f}"
            for m in models
        )
        # Mark a horizontal break where the reference score drops below 5
        ref_score = score_map[ref].get(p.arxiv_id, 0.0)
        block = "high" if ref_score >= 5 else "low"
        if prev_block == "high" and block == "low":
            print(f"{'─' * len(divider)}  ← below 5 (ref model)")
        prev_block = block

        print(f"{i:>3}  {row_scores}  {p.title[:70]}")

    print(divider)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--models", nargs="+", default=DEFAULT_MODELS,
        metavar="MODEL",
        help="Ollama model tags to compare (default: qwen2.5 0.5b/1.5b/3b/7b)",
    )
    parser.add_argument(
        "--rank-file", type=Path, default=DEFAULT_RANK_FILE,
        metavar="FILE",
        help="Arxaudio rank log to read paper titles from",
    )
    parser.add_argument(
        "--preferences", type=Path, default=DEFAULT_PREFS,
        metavar="FILE",
        help="preferences.txt passed to the ranking LLM",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        metavar="SECS",
        help="Per-model timeout in seconds (default 1800)",
    )
    parser.add_argument(
        "--top-n", type=int, default=DEFAULT_TOP_N,
        metavar="N",
        help="Number of top papers to display per model (default 10)",
    )
    parser.add_argument(
        "--no-pull", action="store_true",
        help="Skip 'ollama pull'; fail if a model is not already present",
    )
    args = parser.parse_args()

    # --- Load inputs ---------------------------------------------------------
    if not args.rank_file.exists():
        sys.exit(f"Rank file not found: {args.rank_file}")
    if not args.preferences.exists():
        sys.exit(f"Preferences file not found: {args.preferences}")

    papers      = parse_rank_file(args.rank_file)
    preferences = args.preferences.read_text()

    print(f"Paper set : {args.rank_file}  ({len(papers)} papers)")
    print(f"Prefs     : {args.preferences}")
    print(f"Models    : {', '.join(args.models)}")
    print(f"Timeout   : {args.timeout:.0f}s per model\n")

    if not papers:
        sys.exit("No papers parsed from rank file — check the file format.")

    # --- Ensure models are available -----------------------------------------
    if not args.no_pull:
        print("Checking / pulling models:")
        for model in args.models:
            if model_is_present(model):
                print(f"  {model}  ✓ already present")
            else:
                pull_model(model)
        print()

    # --- Run ranking ---------------------------------------------------------
    results: dict[str, list[Paper]] = {}
    timings: dict[str, float]       = {}

    for model in args.models:
        print(f"Ranking with  {model} ...", flush=True)
        try:
            ranked, elapsed = rank_with(model, papers, preferences, args.timeout)
            results[model]  = ranked
            timings[model]  = elapsed
            print(f"  → done in {elapsed:.1f}s")
            print_top_n(model, ranked, args.top_n)
        except Exception as exc:
            print(f"  ✗ FAILED: {exc}")

    if not results:
        sys.exit("\nAll models failed — is 'ollama serve' running?")

    # --- Comparison table ----------------------------------------------------
    successful = [m for m in args.models if m in results]
    if len(successful) > 1:
        print_comparison_table(papers, results, successful, timings, top_n=args.top_n * 3)

    # --- Timing summary ------------------------------------------------------
    print("\nTiming summary:")
    for model in args.models:
        if model in timings:
            print(f"  {model:<20}  {timings[model]:.1f}s")
        else:
            print(f"  {model:<20}  FAILED")


if __name__ == "__main__":
    main()
