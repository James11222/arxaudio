"""Tests for arxaudio.benty: parse_csrf_token, parse_latest_date_url,
parse_day_results, and fetch_benty_papers.

All tests are offline — no real HTTP.  The pure-parser tests (1–9) load real
saved fixtures from tests/benty_fixtures/.  The orchestration tests (10–11)
monkeypatch requests.Session with a URL-routing fake.
"""
from __future__ import annotations

import re
import types
from pathlib import Path

import pytest

from arxaudio.benty import (
    fetch_benty_papers,
    parse_csrf_token,
    parse_day_results,
    parse_latest_date_url,
)
from arxaudio.models import Paper

# ---------------------------------------------------------------------------
# Fixture file paths
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "benty_fixtures"
_LOGIN_HTML = (_FIXTURES / "login.html").read_text(encoding="utf-8")
_LANDING_HTML = (_FIXTURES / "daily_arxiv_landing.html").read_text(encoding="utf-8")
_DAY_HTML = (_FIXTURES / "day_results.html").read_text(encoding="utf-8")

# Pre-parse once so the per-test cases don't re-parse 72 papers each.
_PAPERS: list[Paper] = parse_day_results(_DAY_HTML, published="2026-06-12")


# ---------------------------------------------------------------------------
# 1. parse_csrf_token — real value
# ---------------------------------------------------------------------------

def test_parse_csrf_token():
    expected = (
        "IjBhMjRhOTRkODgzMjViMGI1ODllZDUxMDZiZGNkNTY1OWExYmMwYWEi"
        ".aizh6g.e_XWWhKxTsWvb2w7diXkfOuRpgM"
    )
    assert parse_csrf_token(_LOGIN_HTML) == expected


# ---------------------------------------------------------------------------
# 2. parse_csrf_token — missing token raises RuntimeError
# ---------------------------------------------------------------------------

def test_parse_csrf_token_missing():
    bare_html = "<html><body><form></form></body></html>"
    with pytest.raises(RuntimeError):
        parse_csrf_token(bare_html)


# ---------------------------------------------------------------------------
# 3. parse_latest_date_url — real value
# ---------------------------------------------------------------------------

def test_parse_latest_date_url():
    href = parse_latest_date_url(_LANDING_HTML)
    assert href == "/daily_arXiv_results?date=2026-06-12"


# ---------------------------------------------------------------------------
# 4. parse_day_results — count
# ---------------------------------------------------------------------------

def test_parse_day_results_count():
    assert len(_PAPERS) == 72


# ---------------------------------------------------------------------------
# 5. parse_day_results — order and first paper
# ---------------------------------------------------------------------------

def test_parse_day_results_order_and_first():
    paper = _PAPERS[0]
    assert paper.arxiv_id == "2606.12605"
    assert paper.title == (
        "Feedback-Free Star Formation in Clusters within a Galaxy "
        "Simulated at High Resolution in Cosmic Dawn"
    )
    assert paper.authors[0] == "Hou-Zun Chen"
    assert paper.abstract.startswith("We perform a cosmological zoom-in simulation")


# ---------------------------------------------------------------------------
# 6. parse_day_results — all arxiv_ids are clean (no version suffix, no prefix)
# ---------------------------------------------------------------------------

def test_parse_day_results_ids_are_clean():
    pattern = re.compile(r"^\d+\.\d+$")
    for paper in _PAPERS:
        assert pattern.match(paper.arxiv_id), (
            f"arxiv_id {paper.arxiv_id!r} does not match \\d+\\.\\d+"
        )


# ---------------------------------------------------------------------------
# 7. parse_cross_listing_title_cleaned — index 54
# ---------------------------------------------------------------------------

def test_parse_cross_listing_title_cleaned():
    paper = _PAPERS[54]
    title = paper.title
    # No cross-listing marker or leading number
    assert "CROSS-LISTING" not in title.upper()
    assert not title[0].isdigit(), f"Title starts with a digit: {title!r}"
    # Exact real title from the fixture
    assert title == "Directional dark matter signatures of the Large Magellanic Cloud"


# ---------------------------------------------------------------------------
# 8. parse_abstract_excludes_author_comments and decodes HTML entities
# ---------------------------------------------------------------------------

def test_parse_abstract_excludes_author_comments():
    # Paper 2606.12605 (index 0) has an "Authors' comments:" section in the
    # raw HTML, and its abstract contains &lt;10^7 which must decode to <10^7.
    paper = _PAPERS[0]

    # Author-comments content must not leak into the abstract.
    assert "Authors' comments" not in paper.abstract
    assert "Submitted to MNRAS" not in paper.abstract

    # HTML entities must be decoded: the fixture has &lt;10^7, so the parsed
    # abstract should contain the literal '<10^7' substring.
    assert "<10^7" in paper.abstract, (
        f"Expected '<10^7' in abstract (HTML entity decoded), "
        f"got: {paper.abstract[:200]!r}"
    )


# ---------------------------------------------------------------------------
# 9. parse_published_propagates
# ---------------------------------------------------------------------------

def test_parse_published_propagates():
    papers = parse_day_results(_DAY_HTML, published="2026-06-12")
    assert all(p.published == "2026-06-12" for p in papers)


# ===========================================================================
# Orchestration tests — fake requests.Session (no real HTTP)
# ===========================================================================

class _FakeResponse:
    """Minimal fake for requests.Response."""

    def __init__(self, text: str, status_code: int = 200, url: str = "") -> None:
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:  # noqa: D401
        pass  # all fakes are 200 OK


class _FakeSession:
    """Route GET/POST by URL substring.

    Ordering: '/daily_arXiv_results' is checked BEFORE '/daily_arXiv' because
    the former is a sub-path of the latter.
    """

    def __init__(
        self,
        login_html: str,
        landing_html: str,
        results_html: str,
        auth_check_html: str,
        base: str = "https://www.benty-fields.com",
    ) -> None:
        self._login_html = login_html
        self._landing_html = landing_html
        self._results_html = results_html
        self._auth_check_html = auth_check_html
        self._base = base
        self.headers: dict = {}

    def _route(self, url: str) -> _FakeResponse:
        if "/daily_arXiv_results" in url:
            return _FakeResponse(self._results_html, url=url)
        if "/daily_arXiv" in url:
            return _FakeResponse(self._auth_check_html, url=url)
        if "/login" in url:
            return _FakeResponse(self._login_html, url=url)
        # Fallback: empty page
        return _FakeResponse("", url=url)

    def get(self, url: str, **kwargs) -> _FakeResponse:
        return self._route(url)

    def post(self, url: str, **kwargs) -> _FakeResponse:
        # POST to /login returns an empty success page (credentials accepted).
        return _FakeResponse("", url=url)


def _make_settings(base: str = "https://www.benty-fields.com") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        benty_base_url=base,
        benty_email="x@y.z",
        benty_password="pw",
    )


# ---------------------------------------------------------------------------
# 10. fetch_benty_papers happy-path
# ---------------------------------------------------------------------------

def test_fetch_benty_papers_happy_path(monkeypatch):
    # The auth-check page (GET /daily_arXiv) must NOT contain name="password"
    # so the session looks authenticated.  We use the real landing page which
    # has no password field.
    fake_session = _FakeSession(
        login_html=_LOGIN_HTML,
        landing_html=_LANDING_HTML,
        results_html=_DAY_HTML,
        auth_check_html=_LANDING_HTML,  # no password field → authenticated
    )

    import arxaudio.benty as benty_mod

    monkeypatch.setattr(benty_mod.requests, "Session", lambda: fake_session)

    settings = _make_settings()
    result = fetch_benty_papers(settings)

    assert len(result) == 72
    assert result[0].arxiv_id == "2606.12605"


# ---------------------------------------------------------------------------
# 11. fetch_benty_papers login failure
# ---------------------------------------------------------------------------

def test_fetch_benty_papers_login_failure(monkeypatch):
    # Simulate bad credentials: the auth-check GET of /daily_arXiv returns the
    # login page again (still contains name="password"), so _looks_unauthenticated
    # returns True and fetch_benty_papers should raise RuntimeError.
    fake_session = _FakeSession(
        login_html=_LOGIN_HTML,
        landing_html=_LANDING_HTML,
        results_html=_DAY_HTML,
        auth_check_html=_LOGIN_HTML,  # password field present → auth failed
    )

    import arxaudio.benty as benty_mod

    monkeypatch.setattr(benty_mod.requests, "Session", lambda: fake_session)

    settings = _make_settings()
    with pytest.raises(RuntimeError):
        fetch_benty_papers(settings)
