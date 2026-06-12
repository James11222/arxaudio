"""Tests for arxaudio.fetch: RSS feed parsing, announce-type filtering, de-dup.

All tests are offline — the HTTP layer is monkeypatched to return a canned
RSS XML string mirroring the real rss.arxiv.org format. No network calls.
"""
from __future__ import annotations

import pytest

import arxaudio.fetch as fetch_module
from arxaudio.fetch import (
    _normalise_whitespace,
    _parse_abstract,
    _parse_arxiv_id,
    fetch_announced_papers,
)

# ---------------------------------------------------------------------------
# Canned RSS feed (5 items), matching the live rss.arxiv.org structure:
# guid "oai:arXiv.org:<id>v<n>", comma-joined dc:creator, description with
# "arXiv:<id> Announce Type: <type> \nAbstract: <text>", arxiv:announce_type.
# ---------------------------------------------------------------------------
# Item 1: announce type "new", multi-author, multi-category, wrapped title
# Item 2: announce type "cross" (kept — new paper cross-listed here)
# Item 3: announce type "replace" (skipped)
# Item 4: announce type "replace-cross" (skipped)
# Item 5: no announce type anywhere (kept conservatively)

_PUBDATE = "Fri, 12 Jun 2026 00:00:00 -0400"

_FEED_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:arxiv="http://arxiv.org/schemas/atom">
  <channel>
    <title>astro-ph.CO updates on arXiv.org</title>
    <link>https://rss.arxiv.org/rss/astro-ph.CO</link>
    <description>astro-ph.CO updates on the arXiv.org e-print archive.</description>
    <pubDate>{_PUBDATE}</pubDate>

    <item>
      <title>Cosmological constraints from
      weak lensing with sigma eight</title>
      <link>https://arxiv.org/abs/2606.01234</link>
      <description>arXiv:2606.01234v2 Announce Type: new
Abstract:   We present new constraints on
      sigma eight from LSST Year-1 data.
      Our analysis uses a Lambda CDM model.  </description>
      <guid isPermaLink="false">oai:arXiv.org:2606.01234v2</guid>
      <category>astro-ph.CO</category>
      <category>astro-ph.GA</category>
      <pubDate>{_PUBDATE}</pubDate>
      <arxiv:announce_type>new</arxiv:announce_type>
      <dc:creator>Alice Smith, Bob Jones, Carol Kim</dc:creator>
    </item>

    <item>
      <title>Galaxy clustering in the CF4++ZOA survey</title>
      <link>https://arxiv.org/abs/2606.05678</link>
      <description>arXiv:2606.05678v1 Announce Type: cross
Abstract: We study galaxy clustering at h^-1 Mpc scales.</description>
      <guid isPermaLink="false">oai:arXiv.org:2606.05678v1</guid>
      <category>astro-ph.GA</category>
      <pubDate>{_PUBDATE}</pubDate>
      <arxiv:announce_type>cross</arxiv:announce_type>
      <dc:creator>David Patel</dc:creator>
    </item>

    <item>
      <title>A revised paper that should be skipped</title>
      <link>https://arxiv.org/abs/2506.99999</link>
      <description>arXiv:2506.99999v3 Announce Type: replace
Abstract: This is version 3 of an old paper.</description>
      <guid isPermaLink="false">oai:arXiv.org:2506.99999v3</guid>
      <category>astro-ph.CO</category>
      <pubDate>{_PUBDATE}</pubDate>
      <arxiv:announce_type>replace</arxiv:announce_type>
      <dc:creator>Old Author</dc:creator>
    </item>

    <item>
      <title>A revised cross-listed paper that should be skipped</title>
      <link>https://arxiv.org/abs/2505.11111</link>
      <description>arXiv:2505.11111v2 Announce Type: replace-cross
Abstract: Version 2 of an old cross-listed paper.</description>
      <guid isPermaLink="false">oai:arXiv.org:2505.11111v2</guid>
      <category>astro-ph.CO</category>
      <pubDate>{_PUBDATE}</pubDate>
      <arxiv:announce_type>replace-cross</arxiv:announce_type>
      <dc:creator>Other Author</dc:creator>
    </item>

    <item>
      <title>A paper with no announce type at all</title>
      <link>https://arxiv.org/abs/2606.07777</link>
      <description>We cannot tell what kind of announcement this is.</description>
      <guid isPermaLink="false">oai:arXiv.org:2606.07777v1</guid>
      <category>astro-ph.CO</category>
      <pubDate>{_PUBDATE}</pubDate>
      <dc:creator>Eve Lee</dc:creator>
    </item>
  </channel>
</rss>
"""

# A second feed variant for the de-dupe test: the same 2606.01234 paper as it
# appears in its cross-listed category's mailing.
_FEED_XML_CATEGORY2 = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:arxiv="http://arxiv.org/schemas/atom">
  <channel>
    <title>astro-ph.GA updates on arXiv.org</title>
    <link>https://rss.arxiv.org/rss/astro-ph.GA</link>
    <description>astro-ph.GA updates on the arXiv.org e-print archive.</description>
    <pubDate>{_PUBDATE}</pubDate>

    <item>
      <title>Cosmological constraints from weak lensing with sigma eight</title>
      <link>https://arxiv.org/abs/2606.01234</link>
      <description>arXiv:2606.01234v2 Announce Type: cross
Abstract: We present new constraints on sigma eight from LSST Year-1 data.</description>
      <guid isPermaLink="false">oai:arXiv.org:2606.01234v2</guid>
      <category>astro-ph.GA</category>
      <pubDate>{_PUBDATE}</pubDate>
      <arxiv:announce_type>cross</arxiv:announce_type>
      <dc:creator>Alice Smith, Bob Jones, Carol Kim</dc:creator>
    </item>
  </channel>
</rss>
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


def test_parse_arxiv_id_oai_versioned():
    assert _parse_arxiv_id("oai:arXiv.org:2606.01234v2") == "2606.01234"


def test_parse_arxiv_id_abs_url_versioned():
    assert _parse_arxiv_id("http://arxiv.org/abs/2606.01234v2") == "2606.01234"


def test_parse_arxiv_id_https():
    assert _parse_arxiv_id("https://arxiv.org/abs/2506.99999v1") == "2506.99999"


def test_parse_arxiv_id_no_version():
    assert _parse_arxiv_id("oai:arXiv.org:2506.00001") == "2506.00001"


def test_parse_arxiv_id_short_form_passthrough():
    # If the ID is already in short form, it should be returned as-is
    assert _parse_arxiv_id("2606.01234") == "2606.01234"


def test_parse_abstract_strips_preamble():
    summary = "arXiv:2606.01234v1 Announce Type: new \nAbstract: The result."
    assert _parse_abstract(summary) == "The result."


def test_parse_abstract_without_preamble_passthrough():
    assert _parse_abstract("Just an abstract.") == "Just an abstract."


# ---------------------------------------------------------------------------
# Monkeypatching helpers
# ---------------------------------------------------------------------------

def _make_fetch_url_mock(xml_bytes: bytes):
    """Return a function that replaces _fetch_url to return canned XML."""
    def _fake_fetch_url(url: str) -> bytes:
        return xml_bytes
    return _fake_fetch_url


def _fetch_main_feed(monkeypatch):
    monkeypatch.setattr(
        fetch_module, "_fetch_url", _make_fetch_url_mock(_FEED_XML.encode())
    )
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    return fetch_announced_papers(["astro-ph.CO"])


# ---------------------------------------------------------------------------
# Integration tests via fetch_announced_papers (monkeypatched HTTP)
# ---------------------------------------------------------------------------

def test_fetch_parses_id_short_form(monkeypatch):
    papers = _fetch_main_feed(monkeypatch)
    ids = {p.arxiv_id for p in papers}
    assert "2606.01234" in ids


def test_fetch_version_stripped(monkeypatch):
    papers = _fetch_main_feed(monkeypatch)
    for arxiv_id in (p.arxiv_id for p in papers):
        assert "v" not in arxiv_id or not arxiv_id[-1].isdigit()


def test_fetch_whitespace_collapsed_in_title(monkeypatch):
    papers = _fetch_main_feed(monkeypatch)
    target = next((p for p in papers if p.arxiv_id == "2606.01234"), None)
    assert target is not None
    # The title had a hard newline + indent; must be a single clean string
    assert "\n" not in target.title
    assert "  " not in target.title


def test_fetch_abstract_preamble_stripped(monkeypatch):
    """The 'arXiv:<id> Announce Type:' preamble must not leak into the abstract."""
    papers = _fetch_main_feed(monkeypatch)
    target = next((p for p in papers if p.arxiv_id == "2606.01234"), None)
    assert target is not None
    assert "Announce Type" not in target.abstract
    assert "arXiv:" not in target.abstract
    assert target.abstract.startswith("We present new constraints")


def test_fetch_whitespace_collapsed_in_abstract(monkeypatch):
    papers = _fetch_main_feed(monkeypatch)
    target = next((p for p in papers if p.arxiv_id == "2606.01234"), None)
    assert target is not None
    assert "\n" not in target.abstract
    assert "  " not in target.abstract


def test_fetch_authors_split_from_creator(monkeypatch):
    """The comma-joined dc:creator string becomes one entry per author."""
    papers = _fetch_main_feed(monkeypatch)
    target = next((p for p in papers if p.arxiv_id == "2606.01234"), None)
    assert target is not None
    assert target.authors == ["Alice Smith", "Bob Jones", "Carol Kim"]
    assert target.first_author == "Alice Smith"


def test_fetch_categories_parsed(monkeypatch):
    papers = _fetch_main_feed(monkeypatch)
    target = next((p for p in papers if p.arxiv_id == "2606.01234"), None)
    assert target is not None
    assert "astro-ph.CO" in target.categories
    assert "astro-ph.GA" in target.categories


def test_fetch_cross_listing_kept(monkeypatch):
    papers = _fetch_main_feed(monkeypatch)
    ids = {p.arxiv_id for p in papers}
    assert "2606.05678" in ids


def test_fetch_replacements_skipped(monkeypatch):
    """'replace' and 'replace-cross' items must not become papers."""
    papers = _fetch_main_feed(monkeypatch)
    ids = {p.arxiv_id for p in papers}
    assert "2506.99999" not in ids
    assert "2505.11111" not in ids


def test_fetch_missing_announce_type_kept_conservatively(monkeypatch):
    """An item with no determinable announce type is never silently dropped."""
    papers = _fetch_main_feed(monkeypatch)
    ids = {p.arxiv_id for p in papers}
    assert "2606.07777" in ids


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
    papers = fetch_announced_papers(["astro-ph.CO", "astro-ph.GA"])
    ids = [p.arxiv_id for p in papers]
    assert ids.count("2606.01234") == 1


def test_fetch_raises_on_empty_categories(monkeypatch):
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    with pytest.raises(ValueError, match="non-empty"):
        fetch_announced_papers([])
