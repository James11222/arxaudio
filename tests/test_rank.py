"""Tests for arxaudio.rank: title-ranking parse, fallbacks, permutation guarantee."""
from __future__ import annotations

from arxaudio.models import Paper
from arxaudio.rank import _parse_ranking, rank_papers

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
# _parse_ranking (the pure parser)
# ---------------------------------------------------------------------------

def test_parse_clean_order():
    assert _parse_ranking("3, 1, 2", 3) == [2, 0, 1]


def test_parse_prose_around_numbers():
    reply = "Sure! The ranking is: 2, then 3, and finally 1."
    assert _parse_ranking(reply, 3) == [1, 2, 0]


def test_parse_dedupes_keeping_first():
    # 1 appears twice; second occurrence ignored.
    assert _parse_ranking("1, 1, 2, 3", 3) == [0, 1, 2]


def test_parse_drops_out_of_range():
    # 9 and 0 are out of range for n=3 (titles are 1..3).
    assert _parse_ranking("9, 2, 0, 1, 3", 3) == [1, 0, 2]


def test_parse_appends_missing_in_arrival_order():
    # Only 2 supplied; 1 and 3 missing -> appended as arrival indices 0, 2.
    assert _parse_ranking("2", 3) == [1, 0, 2]


def test_parse_empty_is_full_arrival_order():
    assert _parse_ranking("no numbers here", 3) == [0, 1, 2]


def test_parse_always_a_permutation():
    for reply in ["3,2,1", "1 1 1", "garbage", "5,5,5", "2"]:
        order = _parse_ranking(reply, 4)
        assert sorted(order) == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# rank_papers integration
# ---------------------------------------------------------------------------

def test_rank_clean_reorders():
    papers = _papers(3)
    llm = FakeLLM(responses=["3, 1, 2"])
    ranked = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.2", "id.0", "id.1"]


def test_rank_prose_reply_parses():
    papers = _papers(3)
    llm = FakeLLM(responses=["I think the order is 2, 3, 1 — hope that helps!"])
    ranked = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.1", "id.2", "id.0"]


def test_rank_duplicate_and_out_of_range():
    papers = _papers(3)
    llm = FakeLLM(responses=["2, 2, 99, 1, 3"])
    ranked = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.1", "id.0", "id.2"]


def test_rank_missing_indices_appended_arrival_order():
    papers = _papers(4)
    llm = FakeLLM(responses=["3"])  # only one supplied
    ranked = rank_papers(papers, llm, PREFS)
    # 3 first (index 2), then missing 0,1,3 in arrival order.
    assert _ids(ranked) == ["id.2", "id.0", "id.1", "id.3"]


def test_rank_llm_error_arrival_order():
    papers = _papers(3)
    llm = FakeLLM(raise_mode=True)
    ranked = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.0", "id.1", "id.2"]


def test_rank_garbage_reply_arrival_order():
    papers = _papers(3)
    llm = FakeLLM(responses=["I cannot help with that."])
    ranked = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.0", "id.1", "id.2"]


def test_rank_always_a_permutation():
    papers = _papers(5)
    for reply in ["5,4,3,2,1", "2,2,2", "nonsense", "99,1", "1,2,3,4,5,6,7"]:
        llm = FakeLLM(responses=[reply])
        ranked = rank_papers(papers, llm, PREFS)
        assert sorted(_ids(ranked)) == sorted(_ids(papers))
        assert len(ranked) == len(papers)


def test_rank_preferences_in_system_prompt():
    papers = _papers(2)
    llm = FakeLLM(responses=["1, 2"])
    rank_papers(papers, llm, "I only want papers about void statistics.")
    assert len(llm.calls) == 1
    system_prompt, _ = llm.calls[0]
    assert "void statistics" in system_prompt


def test_rank_titles_numbered_in_user_prompt():
    papers = _papers(3)
    llm = FakeLLM(responses=["1, 2, 3"])
    rank_papers(papers, llm, PREFS)
    _, user_prompt = llm.calls[0]
    assert "1. Title 0" in user_prompt
    assert "2. Title 1" in user_prompt
    assert "3. Title 2" in user_prompt


def test_rank_single_paper_no_llm_call():
    papers = _papers(1)
    llm = FakeLLM(responses=["1"])
    ranked = rank_papers(papers, llm, PREFS)
    assert _ids(ranked) == ["id.0"]
    assert llm.calls == []


def test_rank_empty_returns_empty():
    llm = FakeLLM(responses=["1"])
    assert rank_papers([], llm, PREFS) == []
    assert llm.calls == []


def test_rank_does_not_mutate_input_list():
    papers = _papers(3)
    original = list(papers)
    llm = FakeLLM(responses=["3, 2, 1"])
    rank_papers(papers, llm, PREFS)
    assert papers == original  # input list order untouched
