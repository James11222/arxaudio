"""Tests for arxaudio.filter: KEEP/DISCARD parsing, error fallback, prompt content."""
from __future__ import annotations

import copy

import pytest

from arxaudio.filter import _parse_decision, filter_papers
from arxaudio.llm.base import LLMError
from arxaudio.models import Paper

from conftest import FakeLLM

PREFS = "I care about cosmology and large-scale structure."


def _make_paper(arxiv_id: str = "test.000") -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        title="Some Title",
        abstract="Some abstract about cosmology.",
        authors=["Author, A"],
    )


# ---------------------------------------------------------------------------
# Unit tests for _parse_decision (the pure parser)
# ---------------------------------------------------------------------------

def test_parse_keep_upper():
    assert _parse_decision("KEEP") is True


def test_parse_keep_lower():
    assert _parse_decision("keep") is True


def test_parse_keep_mixed():
    assert _parse_decision("Keep") is True


def test_parse_discard_upper():
    assert _parse_decision("DISCARD") is False


def test_parse_discard_lower():
    assert _parse_decision("discard") is False


def test_parse_keep_in_sentence():
    assert _parse_decision("I would KEEP this paper.") is True


def test_parse_discard_in_sentence():
    assert _parse_decision("This paper should be DISCARDed... DISCARD") is False


def test_parse_unparseable_returns_none():
    assert _parse_decision("I don't know") is None


def test_parse_unparseable_empty():
    assert _parse_decision("") is None


def test_parse_unparseable_gibberish():
    assert _parse_decision("Yes, maybe, perhaps.") is None


def test_parse_both_tokens_keep_first():
    """When both tokens appear, the one that appears first wins."""
    reply = "I'd KEEP it but you could also DISCARD it."
    result = _parse_decision(reply)
    # KEEP appears before DISCARD → True
    assert result is True


def test_parse_both_tokens_discard_first():
    """When DISCARD appears first, return False."""
    reply = "DISCARD this. Although some would KEEP it."
    result = _parse_decision(reply)
    # DISCARD appears before KEEP → False
    assert result is False


# ---------------------------------------------------------------------------
# filter_papers integration tests
# ---------------------------------------------------------------------------

def test_filter_keep(paper_co):
    llm = FakeLLM(responses=["KEEP"])
    filter_papers([paper_co], llm, PREFS)
    assert paper_co.keep is True


def test_filter_discard(paper_discard):
    # Reset keep so filter_papers overwrites it
    paper_discard.keep = None
    llm = FakeLLM(responses=["DISCARD"])
    filter_papers([paper_discard], llm, PREFS)
    assert paper_discard.keep is False


def test_filter_unparseable_defaults_to_keep():
    paper = _make_paper()
    llm = FakeLLM(responses=["I am unsure."])
    filter_papers([paper], llm, PREFS)
    assert paper.keep is True


def test_filter_llm_error_defaults_to_keep():
    paper = _make_paper()
    llm = FakeLLM(raise_mode=True)
    filter_papers([paper], llm, PREFS)
    assert paper.keep is True


def test_filter_multiple_papers(paper_co, paper_ga, paper_discard):
    """Each paper gets its own call; decisions mutate correctly."""
    paper_discard.keep = None
    llm = FakeLLM(responses=["KEEP", "KEEP", "DISCARD"])
    papers = [paper_co, paper_ga, paper_discard]
    filter_papers(papers, llm, PREFS)
    assert paper_co.keep is True
    assert paper_ga.keep is True
    assert paper_discard.keep is False


def test_filter_mutates_papers_in_place():
    paper = _make_paper()
    assert paper.keep is None
    llm = FakeLLM(responses=["DISCARD"])
    filter_papers([paper], llm, PREFS)
    assert paper.keep is False


def test_filter_preferences_in_system_prompt():
    """Preferences text must appear in the system prompt passed to the LLM."""
    paper = _make_paper()
    llm = FakeLLM(responses=["KEEP"])
    custom_prefs = "I only want papers about void statistics."
    filter_papers([paper], llm, custom_prefs)
    assert len(llm.calls) == 1
    system_prompt, _ = llm.calls[0]
    assert "void statistics" in system_prompt


def test_filter_title_and_abstract_in_user_prompt():
    """Title and abstract of the paper must appear in the user prompt."""
    paper = Paper(
        arxiv_id="test.001",
        title="Specific Title About Voids",
        abstract="Specific abstract content about cosmic voids.",
        authors=["A"],
    )
    llm = FakeLLM(responses=["KEEP"])
    filter_papers([paper], llm, PREFS)
    _, user_prompt = llm.calls[0]
    assert "Specific Title About Voids" in user_prompt
    assert "Specific abstract content about cosmic voids." in user_prompt


def test_filter_one_error_does_not_stop_others():
    """An LLM error on one paper must not prevent the others from being processed."""
    papers = [_make_paper(f"test.00{i}") for i in range(3)]
    llm = FakeLLM(responses=["KEEP", "KEEP", "KEEP"], error_on_call=1)
    filter_papers(papers, llm, PREFS)
    # First paper: KEEP (call 0 succeeds)
    assert papers[0].keep is True
    # Second paper: error → defaults to KEEP
    assert papers[1].keep is True
    # Third paper: KEEP (call 2 succeeds)
    assert papers[2].keep is True


def test_filter_case_insensitive_keep():
    paper = _make_paper()
    llm = FakeLLM(responses=["keep"])
    filter_papers([paper], llm, PREFS)
    assert paper.keep is True


def test_filter_case_insensitive_discard():
    paper = _make_paper()
    llm = FakeLLM(responses=["Discard"])
    filter_papers([paper], llm, PREFS)
    assert paper.keep is False
