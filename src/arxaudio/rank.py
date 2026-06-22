"""Relevance ranking stage.

Instead of one KEEP/DISCARD call per abstract (slow: one LLM round-trip per
paper), we make exactly ONE stateless LLM call that sees ALL fetched paper
*titles* at once, numbered in arrival order, with the user's research interests
(from ``preferences.txt``) as system context. The model returns the title numbers
ordered from most to least relevant. The pipeline then takes the top ``MAX_PAPERS``
for full audio treatment and the next block for an email-only listing.

Design constraints (idea.md, PLAN.md):
- One LLM call for the whole batch, context cleared between runs.
- Must work with a tiny local model (qwen2.5:1.5b, 8192-token context), so the
  prompt is short, concrete, and example-anchored, and we only feed titles (not
  abstracts) to stay well inside the context window.
- Never silently lose a paper: parsing is defensive and the returned list is
  ALWAYS a permutation of the input. This is the analogue of filter.py's
  "default to KEEP" policy — on any LLM error or an unusable reply we fall back
  to arrival order (every paper survives, just unranked).
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
# shape more than on content, so the examples show only the OUTPUT FORMAT (a bare
# comma-separated list of numbers) and describe papers abstractly as "more/less
# related to the interests" rather than naming any field. The only thing that
# defines "relevant" is whatever the user wrote in ``preferences.txt`` — the prompt
# works unchanged for a marine biologist or a particle theorist.
_SYSTEM_TEMPLATE = """\
You rank a researcher's daily arXiv titles by how well each matches their stated
interests, most relevant first.

The researcher's interests:
---
{preferences}
---

You will be given a numbered list of paper titles. Order ALL of the numbers from
the title that best matches the interests above to the one that matches least.
Judge ONLY against the interests above, including any "not interested in" notes —
do not decide on your own that a topic is interesting or boring.

Answer with ONLY a comma-separated list of the numbers, most relevant first, and
nothing else. Include every number exactly once. Do not explain.

Example: given 4 titles, if title 3 matches the interests best, then 1, then 2,
and title 4 matches least, the answer is:
3, 1, 2, 4

Output only the comma-separated numbers."""

_USER_TEMPLATE = """\
Titles:
{titles}

Answer:"""

# Pull every run of digits out of the reply, in order.
_INT_RE = re.compile(r"\d+")


def _parse_ranking(reply: str, n: int) -> list[int]:
    """Turn a model reply into a 0-based ordering of the ``n`` papers.

    Extracts integers in the order they appear, treats them as 1-based title
    numbers, dedupes keeping the first occurrence, drops anything out of range,
    then appends any indices the reply omitted (in arrival order). The result is
    always a permutation of ``range(n)``.
    """
    seen: set[int] = set()
    order: list[int] = []
    for match in _INT_RE.findall(reply):
        num = int(match)
        idx = num - 1  # titles are presented 1-based
        if idx < 0 or idx >= n or idx in seen:
            continue
        seen.add(idx)
        order.append(idx)

    if len(order) < n:
        # Partial/garbled reply: append whatever the model dropped, in order.
        missing = [i for i in range(n) if i not in seen]
        order.extend(missing)

    return order


def rank_papers(
    papers: list[Paper], llm: LLMBackend, preferences: str
) -> tuple[list[Paper], str, str, str]:
    """Return ``papers`` reordered by LLM relevance ranking of their titles.

    Makes exactly one stateless LLM call with all titles numbered in arrival
    order and ``preferences`` as system context. Never raises and never loses a
    paper: on an LLM error or an unusable reply it returns the papers in arrival
    order (and logs a warning). The returned list is always a permutation of the
    input.

    Returns:
        (ranked_papers, system_prompt, user_prompt, raw_reply) — the reordered
        list, the system prompt sent to the model, the user prompt (numbered
        titles), and the raw LLM response string. All strings are empty when no
        LLM call was made (empty/single-paper input) or when the call failed
        before a reply was received.

    Args:
        papers: papers to rank (not mutated; a reordered new list is returned).
        llm: stateless backend used for the single ranking call.
        preferences: the user's ``preferences.txt`` content, embedded verbatim.
    """
    if not papers:
        return [], "", "", ""
    if len(papers) == 1:
        return list(papers), "", "", ""

    system = _SYSTEM_TEMPLATE.format(preferences=preferences.strip())
    titles_block = "\n".join(
        f"{i}. {paper.title}" for i, paper in enumerate(papers, start=1)
    )
    prompt = _USER_TEMPLATE.format(titles=titles_block)

    try:
        reply = llm.complete(system, prompt)
    except LLMError as exc:
        logger.warning(
            "rank: LLM error, falling back to arrival order: %s", exc
        )
        return list(papers), system, prompt, ""

    # _parse_ranking always returns a full permutation, but distinguish the
    # degenerate "no usable numbers at all" and "partial" cases for clearer logs.
    if not any(ch.isdigit() for ch in reply):
        logger.warning(
            "rank: reply had no usable numbers (%r); using arrival order",
            reply[:80],
        )
        return list(papers), system, prompt, reply

    order = _parse_ranking(reply, len(papers))

    # Count distinct in-range numbers the model actually supplied.
    supplied = {
        int(m) - 1
        for m in _INT_RE.findall(reply)
        if 0 <= int(m) - 1 < len(papers)
    }
    if len(supplied) < len(papers):
        logger.warning(
            "rank: reply was partial/garbled (%r); missing ranks appended in "
            "arrival order",
            reply[:80],
        )

    ranked = [papers[i] for i in order]
    logger.info(
        "rank: ordered %d papers; top is %s",
        len(ranked),
        ranked[0].arxiv_id,
    )
    return ranked, system, prompt, reply
