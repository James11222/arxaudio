"""Relevance filtering stage.

For each paper we make exactly one stateless LLM call that compares the abstract
against the user's research interests (from ``preferences.md``) and answers with
a single token: ``KEEP`` or ``DISCARD``. The result is written back to
``paper.keep``.

Design constraints (idea.md, PLAN.md):
- One LLM call per abstract, context cleared between papers.
- Must work with a 0.5B-parameter model, so prompts are short, direct, and
  example-anchored.
- Never silently lose a paper: on any error or unparseable reply we default to
  ``keep=True`` and log a warning.
"""

from __future__ import annotations

import logging
import re

from arxaudio.llm.base import LLMBackend, LLMError
from arxaudio.models import Paper

logger = logging.getLogger(__name__)

# Kept deliberately terse and rule-shaped — tiny models follow short, concrete
# instructions far better than prose. ``{preferences}`` is filled per run.
_SYSTEM_TEMPLATE = """\
You are a strict relevance filter for a researcher's daily arXiv digest.

The researcher's interests:
---
{preferences}
---

You will be given the title and abstract of one paper. Decide whether it matches
the researcher's interests.

Answer with EXACTLY ONE WORD and nothing else:
KEEP   - if the paper matches the interests
DISCARD - if it does not

Examples:
Title: A new transformer architecture for language modeling
Abstract: We propose a faster attention mechanism...
Answer: DISCARD

Title: Cosmological constraints from weak lensing surveys
Abstract: We measure sigma 8 using LSST-like data...
Answer: KEEP

Do not explain. Output only KEEP or DISCARD."""

_USER_TEMPLATE = """\
Title: {title}
Abstract: {abstract}
Answer:"""

# Match a standalone KEEP/DISCARD token anywhere in the reply, case-insensitive.
_DISCARD_RE = re.compile(r"\bdiscard\b", re.IGNORECASE)
_KEEP_RE = re.compile(r"\bkeep\b", re.IGNORECASE)


def _parse_decision(reply: str) -> bool | None:
    """Return True for keep, False for discard, or None if unparseable.

    DISCARD wins if both tokens appear (the model usually leads with its real
    answer, but an explicit "not DISCARD" style reply is rare; preferring
    DISCARD avoids keeping clearly-rejected papers — yet None still defaults to
    keep upstream, so we never lose a paper on ambiguity we can't read).
    """
    has_discard = bool(_DISCARD_RE.search(reply))
    has_keep = bool(_KEEP_RE.search(reply))
    if has_discard and not has_keep:
        return False
    if has_keep and not has_discard:
        return True
    if has_keep and has_discard:
        # Ambiguous: trust whichever token appears first in the reply.
        keep_pos = _KEEP_RE.search(reply).start()  # type: ignore[union-attr]
        discard_pos = _DISCARD_RE.search(reply).start()  # type: ignore[union-attr]
        return keep_pos < discard_pos
    return None


def filter_papers(papers: list[Paper], llm: LLMBackend, preferences: str) -> None:
    """Set ``paper.keep`` for each paper via one LLM call per abstract.

    Mutates the papers in place. Never raises for a single bad paper: on an LLM
    error or an unparseable reply it defaults that paper to ``keep=True`` so the
    pipeline never silently drops research.

    Args:
        papers: papers to filter (``keep`` is overwritten on each).
        llm: stateless backend used one call per paper.
        preferences: the user's ``preferences.md`` content, embedded verbatim.
    """
    system = _SYSTEM_TEMPLATE.format(preferences=preferences.strip())

    for paper in papers:
        prompt = _USER_TEMPLATE.format(title=paper.title, abstract=paper.abstract)
        try:
            reply = llm.complete(system, prompt)
        except LLMError as exc:
            paper.keep = True
            logger.warning(
                "filter: LLM error on %s, defaulting to KEEP: %s",
                paper.arxiv_id,
                exc,
            )
            continue

        decision = _parse_decision(reply)
        if decision is None:
            paper.keep = True
            logger.warning(
                "filter: unparseable reply for %s (%r), defaulting to KEEP",
                paper.arxiv_id,
                reply[:80],
            )
        else:
            paper.keep = decision

        logger.info(
            "filter: %s -> %s",
            paper.arxiv_id,
            "KEEP" if paper.keep else "DISCARD",
        )
