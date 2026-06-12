"""Tests for arxaudio.fetch: Atom feed parsing, cutoff, de-duplication.

All tests are offline — the HTTP layer is monkeypatched to return a canned
Atom XML string. No real arXiv API calls are made.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import arxaudio.fetch as fetch_module
from arxaudio.fetch import (
    _normalise_whitespace,
    _parse_arxiv_id,
    _parse_entry,
    fetch_recent_papers,
)

# ---------------------------------------------------------------------------
# Canned Atom XML feed (3 entries)
# ---------------------------------------------------------------------------
# Entry 1: recent paper, hard-wrapped title/abstract, multiple categories
# Entry 2: same paper appearing in a second category (de-dupe test)
# Entry 3: an older paper that should be excluded by the cutoff

_NOW = datetime.now(tz=timezone.utc)
_RECENT = (_NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
_OLD = (_NOW - timedelta(hours=96)).strftime("%Y-%m-%dT%H:%M:%SZ")

# We use entry id "2606.01234v2" to test version stripping
_FEED_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query</title>
  <id>http://arxiv.org/api/query?results</id>
  <updated>{_RECENT}</updated>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">3</opensearch:totalResults>
  <opensearch:startIndex xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:startIndex>
  <opensearch:itemsPerPage xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">100</opensearch:itemsPerPage>

  <entry>
    <id>http://arxiv.org/abs/2606.01234v2</id>
    <updated>{_RECENT}</updated>
    <published>{_RECENT}</published>
    <title>Cosmological constraints from
    weak lensing with sigma eight</title>
    <summary>  We present new constraints on
    sigma eight from LSST Year-1 data.
    Our analysis uses a Lambda CDM model.
    The chi-squared per degree of freedom is 1.05.  </summary>
    <author><name>Smith, Alice</name></author>
    <author><name>Jones, Bob</name></author>
    <author><name>Kim, Carol</name></author>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="astro-ph.CO" scheme="http://arxiv.org/schemas/atom"/>
    <category term="astro-ph.CO" scheme="http://arxiv.org/schemas/atom"/>
    <category term="astro-ph.GA" scheme="http://arxiv.org/schemas/atom"/>
  </entry>

  <entry>
    <id>http://arxiv.org/abs/2606.05678v1</id>
    <updated>{_RECENT}</updated>
    <published>{_RECENT}</published>
    <title>Galaxy clustering in the CF4++ZOA survey</title>
    <summary>We study galaxy clustering at h^-1 Mpc scales.</summary>
    <author><name>Patel, David</name></author>
    <category term="astro-ph.GA" scheme="http://arxiv.org/schemas/atom"/>
  </entry>

  <entry>
    <id>http://arxiv.org/abs/2506.99999v3</id>
    <updated>{_OLD}</updated>
    <published>{_OLD}</published>
    <title>An old paper outside the lookback window</title>
    <summary>This paper was published 96 hours ago and should be excluded.</summary>
    <author><name>Old, Author</name></author>
    <category term="astro-ph.CO" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""

# A second feed variant that only contains entry 2606.01234 (for de-dupe test)
_FEED_XML_CATEGORY2 = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query</title>
  <id>http://arxiv.org/api/query?results</id>
  <updated>{_RECENT}</updated>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">1</opensearch:totalResults>
  <opensearch:startIndex xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:startIndex>
  <opensearch:itemsPerPage xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">100</opensearch:itemsPerPage>

  <entry>
    <id>http://arxiv.org/abs/2606.01234v2</id>
    <updated>{_RECENT}</updated>
    <published>{_RECENT}</published>
    <title>Cosmological constraints from weak lensing with sigma eight</title>
    <summary>We present new constraints on sigma eight from LSST Year-1 data.</summary>
    <author><name>Smith, Alice</name></author>
    <category term="astro-ph.GA" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""


# ---------------------------------------------------------------------------
# Unit tests for pure helpers
# ---------------------------------------------------------------------------

def test_normalise_whitespace_newlines():
    assert _normalise_whitespace("a\nb\nc") == "a b c"


def test_normalise_whitespace_multiple_spaces():
    assert _normalise_whitespace("a   b   c") == "a b c"


def test_normalise_whitespace_tabs():
    assert _normalise_whitespace("a\tb") == "a b"


def test_normalise_whitespace_leading_trailing():
    assert _normalise_whitespace("  hello  ") == "hello"


def test_parse_arxiv_id_versioned():
    raw = "http://arxiv.org/abs/2606.01234v2"
    assert _parse_arxiv_id(raw) == "2606.01234"


def test_parse_arxiv_id_https():
    raw = "https://arxiv.org/abs/2506.99999v1"
    assert _parse_arxiv_id(raw) == "2506.99999"


def test_parse_arxiv_id_no_version():
    raw = "http://arxiv.org/abs/2506.00001"
    assert _parse_arxiv_id(raw) == "2506.00001"


def test_parse_arxiv_id_short_form_passthrough():
    # If the ID is already in short form, it should be returned as-is
    assert _parse_arxiv_id("2606.01234") == "2606.01234"


# ---------------------------------------------------------------------------
# Monkeypatching helpers
# ---------------------------------------------------------------------------

def _make_fetch_url_mock(xml_bytes: bytes):
    """Return a function that replaces _fetch_url to return canned XML."""
    def _fake_fetch_url(url: str) -> bytes:
        return xml_bytes
    return _fake_fetch_url


# ---------------------------------------------------------------------------
# Integration tests via fetch_recent_papers (monkeypatched HTTP)
# ---------------------------------------------------------------------------

def test_fetch_parses_id_short_form(monkeypatch):
    monkeypatch.setattr(fetch_module, "_fetch_url", _make_fetch_url_mock(_FEED_XML.encode()))
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    papers = fetch_recent_papers(["astro-ph.CO"], lookback_hours=24)
    ids = {p.arxiv_id for p in papers}
    assert "2606.01234" in ids


def test_fetch_version_stripped(monkeypatch):
    monkeypatch.setattr(fetch_module, "_fetch_url", _make_fetch_url_mock(_FEED_XML.encode()))
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    papers = fetch_recent_papers(["astro-ph.CO"], lookback_hours=24)
    ids = [p.arxiv_id for p in papers]
    # No "v2" or "v1" suffix should appear
    for arxiv_id in ids:
        assert "v" not in arxiv_id or not arxiv_id[-1].isdigit()


def test_fetch_whitespace_collapsed_in_title(monkeypatch):
    monkeypatch.setattr(fetch_module, "_fetch_url", _make_fetch_url_mock(_FEED_XML.encode()))
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    papers = fetch_recent_papers(["astro-ph.CO"], lookback_hours=24)
    target = next((p for p in papers if p.arxiv_id == "2606.01234"), None)
    assert target is not None
    # The title had a hard newline + indent; must be a single clean string
    assert "\n" not in target.title
    assert "  " not in target.title


def test_fetch_whitespace_collapsed_in_abstract(monkeypatch):
    monkeypatch.setattr(fetch_module, "_fetch_url", _make_fetch_url_mock(_FEED_XML.encode()))
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    papers = fetch_recent_papers(["astro-ph.CO"], lookback_hours=24)
    target = next((p for p in papers if p.arxiv_id == "2606.01234"), None)
    assert target is not None
    assert "\n" not in target.abstract
    assert "  " not in target.abstract


def test_fetch_authors_parsed(monkeypatch):
    monkeypatch.setattr(fetch_module, "_fetch_url", _make_fetch_url_mock(_FEED_XML.encode()))
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    papers = fetch_recent_papers(["astro-ph.CO"], lookback_hours=24)
    target = next((p for p in papers if p.arxiv_id == "2606.01234"), None)
    assert target is not None
    assert "Smith, Alice" in target.authors
    assert "Jones, Bob" in target.authors
    assert "Kim, Carol" in target.authors


def test_fetch_categories_parsed(monkeypatch):
    monkeypatch.setattr(fetch_module, "_fetch_url", _make_fetch_url_mock(_FEED_XML.encode()))
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    papers = fetch_recent_papers(["astro-ph.CO"], lookback_hours=24)
    target = next((p for p in papers if p.arxiv_id == "2606.01234"), None)
    assert target is not None
    assert "astro-ph.CO" in target.categories


def test_fetch_cutoff_applied(monkeypatch):
    """The old paper (96h ago) must not appear when lookback_hours=24."""
    monkeypatch.setattr(fetch_module, "_fetch_url", _make_fetch_url_mock(_FEED_XML.encode()))
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    papers = fetch_recent_papers(["astro-ph.CO"], lookback_hours=24)
    ids = {p.arxiv_id for p in papers}
    assert "2506.99999" not in ids


def test_fetch_dedupe_across_categories(monkeypatch):
    """The same paper appearing in two categories must only be returned once."""
    call_count = [0]

    def _rotating_feed(url: str) -> bytes:
        call_count[0] += 1
        # First call returns the main feed, second returns the category-2 feed
        # (which has the same 2606.01234 paper again)
        if call_count[0] == 1:
            return _FEED_XML.encode()
        return _FEED_XML_CATEGORY2.encode()

    monkeypatch.setattr(fetch_module, "_fetch_url", _rotating_feed)
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    papers = fetch_recent_papers(["astro-ph.CO", "astro-ph.GA"], lookback_hours=24)
    ids = [p.arxiv_id for p in papers]
    # 2606.01234 should appear exactly once
    assert ids.count("2606.01234") == 1


def test_fetch_raises_on_empty_categories(monkeypatch):
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    with pytest.raises(ValueError, match="non-empty"):
        fetch_recent_papers([], lookback_hours=24)
