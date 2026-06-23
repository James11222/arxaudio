"""Relevance ranking stage.

Instead of one KEEP/DISCARD call per abstract (slow: one LLM round-trip per
paper), we make exactly ONE stateless LLM call that sees ALL fetched paper
*titles* at once, numbered in arrival order, with the user's research interests
(from ``preferences.txt``) as system context. The model scores each title 0–10;
papers are then sorted by score descending. The pipeline takes the top
``MAX_PAPERS`` for full audio treatment and the next block for email-only.

Design constraints (idea.md, PLAN.md):
- One LLM call for the whole batch, context cleared between runs.
- Must work with a tiny local model (qwen2.5:1.5b, 8192-token context), so the
  prompt is short, concrete, and example-anchored, and we only feed titles (not
  abstracts) to stay well inside the context window.
- Never silently lose a paper: parsing is defensive and unscored papers receive
  score 0. On any LLM error we fall back to arrival order (every paper survives,
  just unranked). This is the analogue of filter.py's "default to KEEP" policy.
"""

from __future__ import annotations

import logging
import re

from arxaudio.llm.base import LLMBackend, LLMError
from arxaudio.models import Paper

logger = logging.getLogger(__name__)

# Kept deliberately terse and rule-shaped — tiny models follow short, concrete
# instructions far better than prose. ``{preferences}`` is filled per run.
#
# The framing is field-agnostic: a small model latches onto tone and example
# shape more than on content, so the examples show only the OUTPUT FORMAT
# ("N: score") and describe papers abstractly. The only thing that defines
# "relevant" is whatever the user wrote in ``preferences.txt`` — the prompt
# works unchanged for a marine biologist or a particle theorist.
_SYSTEM_TEMPLATE = """\
You score a researcher's daily arXiv paper titles by relevance to their stated
interests.

The researcher's interests:
---
{preferences}
---

Score EVERY title from 0 to 10:
  10 = perfect match with the interests
   0 = matches the "not interested in" list, or completely unrelated

Output ONLY lines in the format "N: score". One line per paper. No explanation.
NEVER reminder: papers on excluded topics must score 0.

Example:
1: 9
2: 0
3: 7
4: 4"""

_USER_TEMPLATE = """\
Titles:
{titles}

Scores:"""

# Match lines of the form "N: score" (integer or one decimal place).
_SCORE_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+(?:\.\d+)?)", re.MULTILINE)


def _parse_scores(reply: str, n: int) -> list[float]:
    """Extract per-paper scores from the model reply.

    Returns a list of length ``n`` where index i holds the score for paper i+1
    (1-based in the prompt). Papers the model omitted receive score 0.
    """
    scores = [0.0] * n
    for match in _SCORE_RE.finditer(reply):
        idx = int(match.group(1)) - 1  # 1-based → 0-based
        if 0 <= idx < n:
            scores[idx] = min(10.0, float(match.group(2)))
    return scores


def rank_papers(
    papers: list[Paper], llm: LLMBackend, preferences: str
) -> tuple[list[Paper], str, str, str]:
    """Score ``papers`` by LLM relevance (0–10) and return them sorted by score.

    Makes exactly one stateless LLM call with all titles numbered in arrival
    order and ``preferences`` as system context. Never raises and never loses a
    paper: on an LLM error or an unusable reply it returns the papers in arrival
    order (and logs a warning). The returned list is always a permutation of the
    input. Each paper's ``relevance_score`` field is set in-place.

    Returns:
        (ranked_papers, system_prompt, user_prompt, raw_reply) — papers sorted
        by score descending, the system prompt, the user prompt (numbered
        titles), and the raw LLM response. All strings are empty when no LLM
        call was made (empty/single-paper input) or when the call failed.

    Args:
        papers: papers to rank (not mutated; a reordered new list is returned).
        llm: stateless backend used for the single scoring call.
        preferences: the user's ``preferences.txt`` content, embedded verbatim.
    """
    if not papers:
        return [], "", "", ""
    if len(papers) == 1:
        papers[0].relevance_score = None
        return list(papers), "", "", ""

    system = _SYSTEM_TEMPLATE.format(preferences=preferences.strip())
    titles_block = "\n".join(
        f"{i}. {paper.title}" for i, paper in enumerate(papers, start=1)
    )
    prompt = _USER_TEMPLATE.format(titles=titles_block)

    try:
        reply = llm.complete(system, prompt)
    except LLMError as exc:
        logger.warning("rank: LLM error, falling back to arrival order: %s", exc)
        return list(papers), system, prompt, ""

    if not any(ch.isdigit() for ch in reply):
        logger.warning(
            "rank: reply had no usable scores (%r); using arrival order",
            reply[:80],
        )
        return list(papers), system, prompt, reply

    scores = _parse_scores(reply, len(papers))

    scored = sum(1 for s in scores if s > 0)
    if scored < len(papers):
        logger.warning(
            "rank: %d of %d papers scored (rest default to 0)",
            scored, len(papers),
        )

    for paper, score in zip(papers, scores):
        paper.relevance_score = score

    ranked = sorted(papers, key=lambda p: p.relevance_score or 0.0, reverse=True)
    logger.info(
        "rank: scored %d papers; top is %s (%.1f/10)",
        len(ranked), ranked[0].arxiv_id, ranked[0].relevance_score or 0.0,
    )
    return ranked, system, prompt, reply
