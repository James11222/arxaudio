"""Tests for arxaudio.rank: title-scoring parse, fallbacks, permutation guarantee."""
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


# ---------------------------------------------------------------------------
# _parse_scores (the pure parser)
# ---------------------------------------------------------------------------

def test_parse_scores_basic():
    """Parses "N: score" lines correctly."""
    scores = _parse_scores("1: 8\n2: 5\n3: 10", 3)
    assert scores == [8.0, 5.0, 10.0]


def test_parse_scores_decimal():
    scores = _parse_scores("1: 7.5\n2: 3.0", 2)
    assert scores[0] == 7.5
    assert scores[1] == 3.0


def test_parse_scores_missing_paper_gets_zero():
    """Papers the model omits receive score 0."""
    scores = _parse_scores("2: 9", 3)
    assert scores == [0.0, 9.0, 0.0]


def test_parse_scores_out_of_range_ignored():
    """Indices outside 1..n are silently dropped."""
    scores = _parse_scores("0: 10\n1: 7\n99: 8", 2)
    assert scores == [7.0, 0.0]


def test_parse_scores_clamps_to_10():
    """Scores above 10 are clamped to 10."""
    scores = _parse_scores("1: 15", 1)
    assert scores == [10.0]


def test_parse_scores_empty_reply_all_zeros():
    scores = _parse_scores("", 3)
    assert scores == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# rank_papers integration
# ---------------------------------------------------------------------------

def test_rank_orders_by_score_descending():
    """Papers are returned sorted by score, highest first."""
    papers = _papers(3)
    llm = FakeLLM(responses=["1: 5\n2: 9\n3: 2"])
    ranked, _, _, _ = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.1", "id.0", "id.2"]


def test_rank_sets_relevance_score():
    """Each paper's relevance_score field is populated after ranking."""
    papers = _papers(3)
    llm = FakeLLM(responses=["1: 8\n2: 4\n3: 6"])
    ranked, _, _, _ = rank_papers(papers, llm, PREFS)
    scores = {p.arxiv_id: p.relevance_score for p in ranked}
    assert scores["id.0"] == 8.0
    assert scores["id.1"] == 4.0
    assert scores["id.2"] == 6.0


def test_rank_missing_indices_default_to_zero():
    """Papers not scored by the model receive score 0 and end up last."""
    papers = _papers(4)
    llm = FakeLLM(responses=["2: 8\n4: 7"])  # papers 1 and 3 omitted
    ranked, _, _, _ = rank_papers(papers, llm, PREFS)
    # id.1 (score 8) and id.3 (score 7) first, then id.0 and id.2 (score 0)
    assert ranked[0].arxiv_id == "id.1"
    assert ranked[1].arxiv_id == "id.3"
    assert set(_ids(ranked[2:])) == {"id.0", "id.2"}


def test_rank_llm_error_arrival_order():
    papers = _papers(3)
    llm = FakeLLM(raise_mode=True)
    ranked, _, _, _ = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.0", "id.1", "id.2"]


def test_rank_garbage_reply_arrival_order():
    papers = _papers(3)
    llm = FakeLLM(responses=["I cannot help with that."])
    ranked, _, _, _ = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.0", "id.1", "id.2"]


def test_rank_always_a_permutation():
    """Result is always a permutation of the input regardless of reply."""
    papers = _papers(5)
    for reply in ["1:8\n2:7\n3:6\n4:5\n5:4", "1:0\n2:0", "nonsense", "1:10"]:
        llm = FakeLLM(responses=[reply])
        ranked, _, _, _ = rank_papers(papers, llm, PREFS)
        assert sorted(_ids(ranked)) == sorted(_ids(papers))
        assert len(ranked) == len(papers)


def test_rank_preferences_in_system_prompt():
    papers = _papers(2)
    llm = FakeLLM(responses=["1: 8\n2: 3"])
    rank_papers(papers, llm, "I only want papers about void statistics.")
    assert len(llm.calls) == 1
    system_prompt, _ = llm.calls[0]
    assert "void statistics" in system_prompt


def test_rank_titles_numbered_in_user_prompt():
    papers = _papers(3)
    llm = FakeLLM(responses=["1: 5\n2: 7\n3: 9"])
    rank_papers(papers, llm, PREFS)
    _, user_prompt = llm.calls[0]
    assert "1. Title 0" in user_prompt
    assert "2. Title 1" in user_prompt
    assert "3. Title 2" in user_prompt


def test_rank_single_paper_no_llm_call():
    papers = _papers(1)
    llm = FakeLLM(responses=["1: 8"])
    ranked, _, _, _ = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.0"]
    assert llm.calls == []


def test_rank_empty_returns_empty():
    llm = FakeLLM(responses=["1: 8"])
    result, _, _, _ = rank_papers([], llm, PREFS)
    assert result == []
    assert llm.calls == []


def test_rank_does_not_mutate_input_list():
    papers = _papers(3)
    original = list(papers)
    llm = FakeLLM(responses=["1: 3\n2: 9\n3: 6"])
    rank_papers(papers, llm, PREFS)
    assert papers == original  # input list order untouched


def test_rank_returns_prompts_and_reply():
    """rank_papers returns the system prompt, user prompt, and raw reply."""
    papers = _papers(2)
    reply = "1: 7\n2: 4"
    llm = FakeLLM(responses=[reply])
    ranked, system, user, raw = rank_papers(papers, llm, PREFS)
    assert len(ranked) == 2
    assert PREFS in system
    assert "Title 0" in user
    assert raw == reply

