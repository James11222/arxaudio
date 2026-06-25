"""Tests for arxaudio.rank: score-based ranking, parse, and fallbacks."""
from __future__ import annotations

from arxaudio.models import Paper
from arxaudio.rank import _parse_scores, rank_papers

from conftest import FakeLLM

PREFS = "I care about cosmology and large-scale structure."


def _papers(n: int) -> list[Paper]:
    return [
        Paper(arxiv_id=f"id.{i}", title=f"Title {i}", abstract=f"Abstract {i}")
        for i in range(n)
    ]


def _ids(papers: list[Paper]) -> list[str]:
    return [p.arxiv_id for p in papers]


def _scores(papers: list[Paper]) -> list[float | None]:
    return [p.relevance_score for p in papers]


# ---------------------------------------------------------------------------
# _parse_scores (the pure parser)
# ---------------------------------------------------------------------------

def test_parse_scores_clean():
    assert _parse_scores("1: 9\n2: 3\n3: 7", 3) == [9.0, 3.0, 7.0]


def test_parse_scores_decimal():
    assert _parse_scores("1: 7.5\n2: 3.0", 2) == [7.5, 3.0]


def test_parse_scores_caps_at_10():
    assert _parse_scores("1: 15\n2: 8", 2) == [10.0, 8.0]


def test_parse_scores_missing_defaults_to_zero():
    # Only paper 1 scored; papers 2 and 3 default to 0.
    assert _parse_scores("1: 8", 3) == [8.0, 0.0, 0.0]


def test_parse_scores_out_of_range_ignored():
    # Index 5 is out of range for n=3.
    assert _parse_scores("5: 9\n1: 7", 3) == [7.0, 0.0, 0.0]


def test_parse_scores_no_scores_all_zero():
    assert _parse_scores("no scores here", 3) == [0.0, 0.0, 0.0]


def test_parse_scores_prose_around_scores():
    # Model adds explanation; scores still parsed.
    reply = "Paper 1 is highly relevant: 1: 9\nPaper 2 is off-topic: 2: 1"
    assert _parse_scores(reply, 2) == [9.0, 1.0]


# ---------------------------------------------------------------------------
# rank_papers integration
# ---------------------------------------------------------------------------

def test_rank_scores_sort_order():
    # Paper id.1 gets score 9, id.0 gets 3, id.2 gets 5 → sorted: 1, 2, 0.
    papers = _papers(3)
    llm = FakeLLM(responses=["1: 3\n2: 9\n3: 5"])
    ranked, _, _, _ = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.1", "id.2", "id.0"]


def test_rank_scores_set_on_papers():
    papers = _papers(3)
    llm = FakeLLM(responses=["1: 3\n2: 9\n3: 5"])
    rank_papers(papers, llm, PREFS)
    assert papers[0].relevance_score == 3.0
    assert papers[1].relevance_score == 9.0
    assert papers[2].relevance_score == 5.0


def test_rank_partial_reply_unscored_get_zero():
    # Only paper 2 scored; papers 1 and 3 get 0 and sort to the end.
    papers = _papers(3)
    llm = FakeLLM(responses=["2: 8"])
    ranked, _, _, _ = rank_papers(papers, llm, PREFS)
    assert ranked[0].arxiv_id == "id.1"
    assert ranked[0].relevance_score == 8.0


def test_rank_llm_error_arrival_order():
    papers = _papers(3)
    llm = FakeLLM(raise_mode=True)
    ranked, system, _, reply = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.0", "id.1", "id.2"]
    assert reply == ""
    assert system == ""


def test_rank_garbage_reply_arrival_order():
    papers = _papers(3)
    llm = FakeLLM(responses=["I cannot help with that."])
    ranked, _, _, reply = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.0", "id.1", "id.2"]
    assert reply == "I cannot help with that."


def test_rank_always_a_permutation():
    papers = _papers(5)
    for reply in ["1: 9\n2: 3\n3: 7\n4: 1\n5: 5", "2: 8", "nonsense", ""]:
        llm = FakeLLM(responses=[reply])
        ranked, _, _, _ = rank_papers(papers, llm, PREFS)
        assert sorted(_ids(ranked)) == sorted(_ids(papers))
        assert len(ranked) == len(papers)


def test_rank_preferences_in_system_prompt():
    papers = _papers(2)
    llm = FakeLLM(responses=["1: 4\n2: 9"])
    _, system, _, _ = rank_papers(papers, llm, "I only want papers about void statistics.")
    assert "void statistics" in system


def test_rank_titles_numbered_in_user_prompt():
    papers = _papers(3)
    llm = FakeLLM(responses=["1: 5\n2: 5\n3: 5"])
    rank_papers(papers, llm, PREFS)
    _, user_prompt = llm.calls[0]
    assert "1. Title 0" in user_prompt
    assert "2. Title 1" in user_prompt
    assert "3. Title 2" in user_prompt


def test_rank_single_paper_no_llm_call():
    papers = _papers(1)
    llm = FakeLLM(responses=["1: 9"])
    ranked, system, prompt, reply = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.0"]
    assert llm.calls == []
    assert system == ""
    assert prompt == ""
    assert reply == ""


def test_rank_empty_returns_empty():
    llm = FakeLLM(responses=["1: 9"])
    ranked, system, prompt, reply = rank_papers([], llm, PREFS)
    assert ranked == []
    assert system == ""
    assert prompt == ""
    assert reply == ""
    assert llm.calls == []


def test_rank_input_list_order_unchanged():
    # rank_papers sets relevance_score on papers but must not reorder the input list.
    papers = _papers(3)
    original_ids = _ids(papers)
    llm = FakeLLM(responses=["1: 3\n2: 9\n3: 5"])
    rank_papers(papers, llm, PREFS)
    assert _ids(papers) == original_ids
