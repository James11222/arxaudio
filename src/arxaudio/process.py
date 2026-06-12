"""Math-notation → spoken-text cleaning stage.

Two layers, deterministic-first:

1. **Regex/literal fast path** (:func:`apply_replacements`) driven by the table
   in ``math_replacements.md``. Loaded once and cached. Handles the bulk of
   LaTeX, units, exponents, subscripts, and fractions with zero LLM calls.
2. **LLM polish pass** (:func:`clean_paper`) that runs the fast path first, then
   makes ONE stateless, few-shot-primed LLM call to catch the long tail —
   instructed to ONLY replace remaining hard-to-pronounce math and to NEVER
   paraphrase. A safety valve discards the LLM output if it looks like the tiny
   model misbehaved (wrong length, empty, or chattered), keeping the regex-only
   version so audio is always sane.

The replacement table lives entirely in ``math_replacements.md`` so users extend
it by editing markdown — see that file's header for the column contract.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from functools import lru_cache
from pathlib import Path

from arxaudio.llm.base import LLMBackend, LLMError
from arxaudio.models import Paper

logger = logging.getLogger(__name__)

# Default location: repo-root math_replacements.md (../../../ from this file:
# src/arxaudio/process.py -> repo root).
_DEFAULT_TABLE_PATH = Path(__file__).resolve().parents[2] / "math_replacements.md"

# How far the LLM output may differ from the regex-pass length before we reject
# it as paraphrasing/chatter. 0.20 == 20%.
_LENGTH_TOLERANCE = 0.20

# Prefixes that betray a chatty tiny model instead of a clean rewrite.
_CHATTER_PREFIXES = (
    "here is",
    "here's",
    "sure",
    "certainly",
    "the cleaned",
    "cleaned text",
    "rewritten",
    "output:",
    "answer:",
    "i have",
    "i've",
    "note:",
    "as an ai",
)


# --- Few-shot examples used to prime the LLM (before/after, astro abstracts) ---
# Each pair shows: only symbols swapped, wording otherwise identical.
_FEWSHOT_EXAMPLES = [
    (
        "We constrain $\\sigma_8$ to within 5% using $\\Lambda$CDM.",
        "We constrain sigma eight to within 5 percent using Lambda C D M.",
    ),
    (
        "The halo mass is $10^{12}\\,M_\\odot$ within a radius of 200 kpc.",
        "The halo mass is ten to the twelve solar masses within a radius of "
        "200 kiloparsecs.",
    ),
    (
        "We find $H_0 \\approx 70$ km/s/Mpc with $\\chi^2 < 1$.",
        "We find H naught approximately equal to 70 kilometers per second per "
        "megaparsec with chi squared less than 1.",
    ),
    (
        "Velocity dispersions span $\\sim 200$ to $400$ km/s.",
        "Velocity dispersions span approximately 200 to 400 kilometers per "
        "second.",
    ),
]

_LLM_SYSTEM = """\
You convert science text into a form a text-to-speech engine can read aloud.

RULES — follow exactly:
- Replace only math symbols, LaTeX, and units that are hard to pronounce with
  plain spoken English words.
- Keep every word, sentence, and number otherwise EXACTLY as given.
- Do NOT paraphrase, summarize, reorder, translate, add, or remove anything.
- Do NOT add commentary. Output ONLY the converted text, nothing else.

Examples:
{examples}"""


def _build_system_prompt() -> str:
    examples = "\n".join(
        f"Input: {before}\nOutput: {after}" for before, after in _FEWSHOT_EXAMPLES
    )
    return _LLM_SYSTEM.format(examples=examples)


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


def _strip_cell(cell: str) -> str:
    """Strip whitespace and surrounding markdown backticks/escapes from a cell."""
    cell = cell.strip()
    if cell.startswith("`") and cell.endswith("`") and len(cell) >= 2:
        cell = cell[1:-1]
    return cell.replace("\\|", "|")


def _split_row(line: str) -> list[str] | None:
    """Split a markdown table row into cells, or None if it isn't a table row."""
    line = line.strip()
    if not line.startswith("|"):
        return None
    # Drop the leading/trailing empty cells produced by the bounding pipes.
    cells = line.split("|")[1:-1]
    return [c.strip() for c in cells]


def _is_separator_row(cells: list[str]) -> bool:
    """True for the ``|---|---|`` divider row under a header."""
    return all(set(c) <= {"-", ":", " "} and c for c in cells)


# Heading that marks the start of the real replacement sections. Tables before
# this (format docs / examples) are ignored by the parser.
_RULES_START_RE = re.compile(r"^#+\s*1\.\s*Literal replacements", re.IGNORECASE)


def _parse_with_reset(text: str, path: Path) -> tuple[list[tuple[re.Pattern[str], str]], list[tuple[str, str]]]:
    """Robust parse that resets table state on blank lines between tables."""
    regex_rules: list[tuple[re.Pattern[str], str]] = []
    literal_rules: list[tuple[str, str]] = []

    mode: str | None = None
    in_table = False  # True once we've passed a separator row for the current table
    # Only consume tables once we reach the real content sections. Everything
    # before the "1. Literal replacements" heading (the format documentation,
    # including its illustrative example table) is ignored.
    active = False

    for raw in text.splitlines():
        if not active:
            if _RULES_START_RE.match(raw):
                active = True
            continue
        cells = _split_row(raw)
        if cells is None:
            # Non-table line ends the current table.
            in_table = False
            mode = None
            continue
        if _is_separator_row(cells):
            in_table = True
            continue
        if not in_table:
            # Header row: classify this table.
            joined = " ".join(c.lower() for c in cells)
            mode = "regex" if "regex" in joined else "literal"
            continue

        # Data row.
        if mode == "regex" and len(cells) >= 2:
            pattern_src = _strip_cell(cells[0])
            replacement = _strip_cell(cells[1])
            if not pattern_src:
                continue
            try:
                regex_rules.append((re.compile(pattern_src), replacement))
            except re.error as exc:
                logger.warning(
                    "process: skipping bad regex %r in %s: %s",
                    pattern_src,
                    path.name,
                    exc,
                )
        elif mode == "literal" and len(cells) >= 2:
            match = _strip_cell(cells[0])
            spoken = _strip_cell(cells[1])
            if match:
                literal_rules.append((match, spoken))

    return regex_rules, literal_rules


@lru_cache(maxsize=4)
def _load_rules(
    path_str: str,
) -> tuple[tuple[tuple[re.Pattern[str], str], ...], tuple[tuple[str, str], ...]]:
    """Load and cache (regex_rules, literal_rules) for a given table path."""
    path = Path(path_str)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("process: could not read replacement table %s: %s", path, exc)
        text = ""
    regex_rules, literal_rules = _parse_with_reset(text, path)
    logger.info(
        "process: loaded %d regex and %d literal replacements from %s",
        len(regex_rules),
        len(literal_rules),
        path_str,
    )
    return tuple(regex_rules), tuple(literal_rules)


# ---------------------------------------------------------------------------
# Final cleanup (applied after all table rules)
# ---------------------------------------------------------------------------

_BRACE_MACRO_RE = re.compile(r"\\(?:text|mathrm|mathbf|mathcal|mathit|mathsf)\{([^{}]*)\}")
_REMAINING_DOLLAR_RE = re.compile(r"\$")
_LEFTOVER_BACKSLASH_CMD_RE = re.compile(r"\\(?:left|right|!|,|;|:|quad|qquad)")
_BRACE_RE = re.compile(r"[{}]")
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")


def _final_cleanup(text: str) -> str:
    """Strip leftover delimiters/macros and normalize whitespace."""
    # Unwrap any \text{...}/\mathrm{...} etc. that survived (one nesting level).
    prev = None
    while prev != text:
        prev = text
        text = _BRACE_MACRO_RE.sub(r"\1", text)
    text = _LEFTOVER_BACKSLASH_CMD_RE.sub(" ", text)
    text = _REMAINING_DOLLAR_RE.sub("", text)
    text = _BRACE_RE.sub("", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _MULTISPACE_RE.sub(" ", text)
    # Collapse runs of blank space across newlines but keep single spaces.
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip()


def apply_replacements(text: str, table_path: str | Path | None = None) -> str:
    """Deterministically convert math/LaTeX notation to spoken text.

    Applies the regex table (top to bottom), then the literal table, then a
    final cleanup that strips leftover ``$`` delimiters, ``\\text{}``/``\\mathrm{}``
    wrappers, stray braces, and collapses whitespace.

    Args:
        text: input title or abstract.
        table_path: override the ``math_replacements.md`` path (mainly for tests).

    Returns:
        The spoken-text version. Never raises on a single bad rule.
    """
    if not text:
        return ""
    path = Path(table_path) if table_path is not None else _DEFAULT_TABLE_PATH
    regex_rules, literal_rules = _load_rules(str(path))

    for pattern, replacement in regex_rules:
        try:
            text = pattern.sub(replacement, text)
        except re.error as exc:  # pragma: no cover - bad backref etc.
            logger.warning("process: regex %r failed at apply time: %s", pattern.pattern, exc)

    for match, spoken in literal_rules:
        text = _apply_literal(text, match, spoken)

    return _final_cleanup(text)


# A literal that is a pure LaTeX command (backslash + letters, e.g. ``\in``) must
# match only when not followed by another letter, so ``\in`` never fires inside
# ``\infty`` or ``\notin``. We cache one compiled matcher per such literal.
_LATEX_CMD_RE = re.compile(r"\\[A-Za-z]+$")


@lru_cache(maxsize=512)
def _command_matcher(match: str) -> re.Pattern[str]:
    return re.compile(re.escape(match) + r"(?![A-Za-z])")


def _apply_literal(text: str, match: str, spoken: str) -> str:
    """Apply one literal replacement, boundary-guarding bare LaTeX commands."""
    if _LATEX_CMD_RE.fullmatch(match):
        return _command_matcher(match).sub(lambda _m: spoken, text)
    return text.replace(match, spoken)


# ---------------------------------------------------------------------------
# LLM polish pass + validation
# ---------------------------------------------------------------------------


def _looks_like_chatter(output: str) -> bool:
    """Heuristic: did the tiny model preface its answer with filler?"""
    lowered = output.lstrip().lower()
    return any(lowered.startswith(p) for p in _CHATTER_PREFIXES)


def _validate_llm_output(candidate: str, baseline: str) -> bool:
    """Decide whether to trust the LLM output over the regex-only ``baseline``.

    Rejects empty output, chatter prefixes, and length drift beyond
    ``_LENGTH_TOLERANCE`` (a proxy for paraphrasing/summarizing/expanding).
    """
    candidate = candidate.strip()
    if not candidate:
        return False
    if _looks_like_chatter(candidate):
        return False
    base_len = max(len(baseline), 1)
    drift = abs(len(candidate) - len(baseline)) / base_len
    if drift > _LENGTH_TOLERANCE:
        return False
    return True


def _llm_polish(text: str, llm: LLMBackend, *, field: str, arxiv_id: str) -> str:
    """Run one LLM pass over already-regex-cleaned ``text``; fall back on doubt.

    Returns the LLM output if it passes validation, else the regex-only ``text``.
    """
    if not text.strip():
        return text
    try:
        candidate = llm.complete(_build_system_prompt(), f"Input: {text}\nOutput:")
    except LLMError as exc:
        logger.warning(
            "process: LLM error cleaning %s %s, keeping regex-only version: %s",
            arxiv_id,
            field,
            exc,
        )
        return text

    # Models sometimes echo the "Output:" lead-in; strip a single such prefix.
    stripped = candidate.strip()
    if stripped.lower().startswith("output:"):
        stripped = stripped[len("output:"):].strip()

    if _validate_llm_output(stripped, text):
        return stripped

    logger.warning(
        "process: LLM output for %s %s failed validation "
        "(len %d vs %d), keeping regex-only version",
        arxiv_id,
        field,
        len(stripped),
        len(text),
    )
    return text


def clean_paper(paper: Paper, llm: LLMBackend) -> None:
    """Populate ``paper.clean_title`` and ``paper.clean_abstract``.

    Runs the deterministic regex pass first, then a single LLM polish call per
    field with a safety valve that reverts to the regex-only version when the
    LLM output looks wrong. Mutates ``paper`` in place.
    """
    regex_title = apply_replacements(paper.title)
    regex_abstract = apply_replacements(paper.abstract)

    paper.clean_title = _llm_polish(
        regex_title, llm, field="title", arxiv_id=paper.arxiv_id
    )
    paper.clean_abstract = _llm_polish(
        regex_abstract, llm, field="abstract", arxiv_id=paper.arxiv_id
    )
    logger.info("process: cleaned %s", paper.arxiv_id)


def process_papers(papers: list[Paper], llm: LLMBackend) -> None:
    """Clean every kept paper, isolating failures per paper.

    Only papers with ``keep`` truthy are processed. A failure on one paper is
    logged and the regex-only fallback is applied so the pipeline still produces
    sane audio for it; one bad paper never aborts the run.
    """
    for paper in papers:
        if not paper.keep:
            continue
        try:
            clean_paper(paper, llm)
        except Exception as exc:  # noqa: BLE001 - last-resort per-paper guard
            logger.warning(
                "process: unexpected error cleaning %s, using regex-only: %s",
                paper.arxiv_id,
                exc,
            )
            # Guarantee something speakable even on an unexpected failure.
            if not paper.clean_title:
                paper.clean_title = apply_replacements(paper.title)
            if not paper.clean_abstract:
                paper.clean_abstract = apply_replacements(paper.abstract)


# ---------------------------------------------------------------------------
# CLI: process a plain text file
# ---------------------------------------------------------------------------

def _cli_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="arxaudio-process",
        description="Run the math-notation → spoken-text pass on a plain text file.",
    )
    p.add_argument("input", metavar="INPUT", help="Path to input text file.")
    p.add_argument(
        "output",
        metavar="OUTPUT",
        nargs="?",
        default=None,
        help="Path to write cleaned text (default: print to stdout).",
    )
    p.add_argument(
        "--table",
        metavar="PATH",
        default=None,
        help="Override path to math_replacements.md.",
    )
    args = p.parse_args(argv)

    try:
        text = Path(args.input).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    cleaned = apply_replacements(text, table_path=args.table)

    if args.output:
        try:
            Path(args.output).write_text(cleaned, encoding="utf-8")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    else:
        print(cleaned)

    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
