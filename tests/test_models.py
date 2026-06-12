"""Tests for arxaudio.models.Paper."""
from __future__ import annotations

import pytest
from arxaudio.models import Paper


# ---------------------------------------------------------------------------
# first_author property
# ---------------------------------------------------------------------------

def test_first_author_normal():
    p = Paper("id", "T", "A", authors=["Smith, Alice", "Jones, Bob"])
    assert p.first_author == "Smith, Alice"


def test_first_author_single():
    p = Paper("id", "T", "A", authors=["Patel, David"])
    assert p.first_author == "Patel, David"


def test_first_author_empty():
    """Empty authors list must return 'unknown authors', not raise."""
    p = Paper("id", "T", "A", authors=[])
    assert p.first_author == "unknown authors"


def test_first_author_none_list(paper_noauthor):
    """Fixture paper with no authors should return 'unknown authors'."""
    assert paper_noauthor.first_author == "unknown authors"


# ---------------------------------------------------------------------------
# spoken_text composition
# ---------------------------------------------------------------------------

def test_spoken_text_uses_clean_when_set():
    p = Paper("id", "Raw Title", "Raw abstract.", authors=["Smith, A"])
    p.clean_title = "Clean Title"
    p.clean_abstract = "Clean abstract."
    text = p.spoken_text()
    assert "Clean Title" in text
    assert "Clean abstract." in text
    # Raw text should not appear
    assert "Raw Title" not in text
    assert "Raw abstract." not in text


def test_spoken_text_falls_back_to_raw():
    p = Paper("id", "Raw Title", "Raw abstract.", authors=["Smith, A"])
    # clean fields are empty strings (default)
    text = p.spoken_text()
    assert "Raw Title" in text
    assert "Raw abstract." in text


def test_spoken_text_partial_clean_title_only():
    """If only clean_title is set, abstract falls back to raw."""
    p = Paper("id", "Raw Title", "Raw abstract.", authors=["Smith, A"])
    p.clean_title = "Clean Title"
    text = p.spoken_text()
    assert "Clean Title" in text
    assert "Raw abstract." in text


def test_spoken_text_partial_clean_abstract_only():
    """If only clean_abstract is set, title falls back to raw."""
    p = Paper("id", "Raw Title", "Raw abstract.", authors=["Smith, A"])
    p.clean_abstract = "Clean abstract."
    text = p.spoken_text()
    assert "Raw Title" in text
    assert "Clean abstract." in text


def test_spoken_text_et_al_with_multiple_authors():
    p = Paper("id", "T", "A.", authors=["Smith, A", "Jones, B"])
    text = p.spoken_text()
    assert "et al" in text


def test_spoken_text_no_et_al_with_single_author():
    p = Paper("id", "T", "A.", authors=["Patel, D"])
    text = p.spoken_text()
    assert "et al" not in text


def test_spoken_text_no_et_al_with_no_authors():
    p = Paper("id", "T", "A.", authors=[])
    text = p.spoken_text()
    assert "et al" not in text
    assert "unknown authors" in text


def test_spoken_text_structure():
    """spoken_text must be '<title>. by <first_author>[ et al]. <abstract>'."""
    p = Paper("id", "My Title", "My abstract.", authors=["Smith, A", "Jones, B"])
    text = p.spoken_text()
    assert text.startswith("My Title.")
    assert ". by Smith, A et al. My abstract." in text


def test_spoken_text_structure_single_author():
    p = Paper("id", "My Title", "My abstract.", authors=["Solo, A"])
    text = p.spoken_text()
    assert ". by Solo, A. My abstract." in text
    assert "et al" not in text


def test_spoken_text_unknown_author_structure():
    """Even with no authors the sentence stays intact."""
    p = Paper("id", "My Title", "My abstract.", authors=[])
    text = p.spoken_text()
    assert "by unknown authors" in text
