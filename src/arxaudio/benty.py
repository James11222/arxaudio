"""Fetch the day's papers from benty-fields.com, already ranked.

This module is an *alternate source* that replaces BOTH the ``fetch`` and the
``rank`` pipeline stages. benty-fields runs a per-user machine-learning model
over each day's arXiv mailing and serves the papers **already sorted by
predicted relevance**, best first, in DOM order. We log in with the user's own
account, find the most recent day's results, and turn each paper block into a
``Paper``. Because benty has already done the ranking, document order *is* the
ranking — there is no separate LLM ranking call when this source is used.

Unlike ``fetch.py`` (public RSS, no auth), this hits one private account behind
a Flask-WTF login, so the flow is: GET ``/login`` to receive a session cookie
and a matching CSRF token, POST credentials, then read ``/daily_arXiv`` and the
chosen day's results page. It is a handful of requests for a single user, so no
arXiv-style rate limiting is required.

The three ``parse_*`` helpers are pure (HTML string in, no network) so the
parsing can be unit-tested offline against the saved fixtures.

Usage::

    from arxaudio.benty import fetch_benty_papers
    papers = fetch_benty_papers(settings)  # already in ranked order
"""

from __future__ import annotations

import logging
import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

from arxaudio.models import Paper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_AGENT = "arxaudio/0.1 (benty-fields personal digest)"
_TIMEOUT = 30  # seconds, applied to every request

# Title prefixes to strip: a leading "<n>. " ordinal and a "(CROSS-LISTING)"
# marker that benty prepends to cross-listed submissions.
_TITLE_NUMBER_RE = re.compile(r"^\s*\d+\.\s*")
_CROSS_LISTING_RE = re.compile(r"\(CROSS-LISTING\)", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")

# A trailing "et al" / "et al." token on the author line (it comes from a link
# that expands the full list; we only have the truncated list, so drop it).
_ET_AL_RE = re.compile(r"\bet\s+al\.?\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _normalise_whitespace(text: str) -> str:
    """Collapse newlines and repeated whitespace into single spaces."""
    return _WHITESPACE_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Pure HTML parsers (no network — unit-testable offline)
# ---------------------------------------------------------------------------

def parse_csrf_token(login_html: str) -> str:
    """Return the hidden ``csrf_token`` value from the login page HTML.

    Raises
    ------
    RuntimeError
        If the token input cannot be found.
    """
    soup = BeautifulSoup(login_html, "html.parser")
    token_input = soup.find("input", attrs={"name": "csrf_token"})
    if token_input is None or not token_input.get("value"):
        raise RuntimeError(
            "Could not find a csrf_token on the benty-fields login page. "
            "The login form may have changed."
        )
    return token_input["value"]


def parse_latest_date_url(landing_html: str) -> str:
    """Return the href of the most recent day's results from ``/daily_arXiv``.

    The landing page lists available days as
    ``<a href="/daily_arXiv_results?date=YYYY-MM-DD" class="list-group-item ...">``
    with the newest day first; we return that first link's href, e.g.
    ``'/daily_arXiv_results?date=2026-06-12'``.

    Raises
    ------
    RuntimeError
        If no day-results link is found.
    """
    soup = BeautifulSoup(landing_html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "daily_arXiv_results" in href and "date=" in href:
            return href
    raise RuntimeError(
        "No daily_arXiv results link found on the benty-fields landing page. "
        "The page may have changed, or there may be no available days."
    )


def _extract_title(paper_div) -> str:
    """Return the cleaned title from a paper block, or '' if absent.

    The ``<h4 class="paper_row">`` text looks like ``"1. \\n Title"`` or
    ``"55. \\n (CROSS-LISTING) \\n Title"``; strip the ordinal and the
    cross-listing marker, then collapse whitespace.
    """
    h4 = paper_div.find("h4", class_="paper_row")
    if h4 is None:
        return ""
    text = h4.get_text(" ", strip=True)
    text = _CROSS_LISTING_RE.sub(" ", text)
    text = _TITLE_NUMBER_RE.sub("", text)
    return _normalise_whitespace(text)


def _extract_authors(paper_div) -> list[str]:
    """Return the author list from a paper block.

    Uses the first *visible* ``<p class="paper_row">`` (the equivalent
    ``<h4>`` line directly above it is HTML-commented out, so bs4 never sees
    it). Drops a trailing "et al" token, splits on commas, strips empties.
    """
    p = paper_div.find("p", class_="paper_row")
    if p is None:
        return []
    text = _normalise_whitespace(p.get_text(" ", strip=True))
    text = _ET_AL_RE.sub("", text).strip().rstrip(",")
    authors = [a.strip() for a in text.split(",")]
    return [a for a in authors if a]


def _extract_abstract(paper_div) -> str:
    """Return the abstract text from a paper block, or '' if absent.

    The abstract lives in ``<p ... name="abstract_field">`` and may be followed
    by a ``<br><strong>Authors' comments:</strong> ...`` block. We collect only
    the text that appears *before* the first "Authors' comments" ``<strong>``,
    so the comments never leak into the spoken abstract. bs4 decodes HTML
    entities (``&lt;`` etc.) back to real characters, leaving the raw LaTeX that
    downstream processing expects.
    """
    p = paper_div.find("p", attrs={"name": "abstract_field"})
    if p is None:
        return ""

    parts: list[str] = []
    for node in p.descendants:
        name = getattr(node, "name", None)
        if name == "strong":
            label = node.get_text(strip=True)
            if label.lower().startswith("authors' comments"):
                break
            # Some other <strong> inside the abstract — keep its text.
            continue
        if name is None:  # NavigableString
            # Skip strings that live inside the "Authors' comments" strong; the
            # break above handles the common case, this guards nested strings.
            parent_names = {
                getattr(parent, "name", None) for parent in node.parents
            }
            if "strong" in parent_names:
                continue
            parts.append(str(node))

    return _normalise_whitespace("".join(parts))


def parse_day_results(html: str, published: str = "") -> list[Paper]:
    """Parse a day-results page into ``Paper`` objects in ranked order.

    Each ``<div class='paper' ...>`` is one paper; ``library-source`` is the
    clean arXiv id and document order equals benty's ML ranking (best first).
    ``published`` is stored on every returned ``Paper``; ``categories`` is left
    empty because benty does not expose a per-paper category here.

    A block missing a title or abstract is skipped with a warning rather than
    aborting the whole parse.
    """
    soup = BeautifulSoup(html, "html.parser")
    paper_divs = soup.find_all("div", class_="paper")

    papers: list[Paper] = []
    for div in paper_divs:
        arxiv_id = (div.get("library-source") or "").strip()
        if not arxiv_id:
            logger.warning("Skipping a paper block with no library-source id.")
            continue

        title = _extract_title(div)
        abstract = _extract_abstract(div)
        if not title or not abstract:
            logger.warning(
                "Skipping benty paper %s — missing %s.",
                arxiv_id,
                "title" if not title else "abstract",
            )
            continue

        papers.append(
            Paper(
                arxiv_id=arxiv_id,
                title=title,
                abstract=abstract,
                authors=_extract_authors(div),
                categories=[],
                published=published,
            )
        )

    logger.info("Parsed %d papers from benty-fields day results.", len(papers))
    return papers


# ---------------------------------------------------------------------------
# Network flow
# ---------------------------------------------------------------------------

def _looks_unauthenticated(response: requests.Response) -> bool:
    """Heuristically decide whether *response* is still the logged-out view."""
    if response.url.rstrip("/").endswith("/login"):
        return True
    body = response.text
    if 'name="password"' in body:
        return True
    if "Provide your login credentials" in body:
        return True
    return False


def fetch_benty_papers(settings) -> list[Paper]:
    """Log in to benty-fields, fetch the most recent day, and parse it.

    Parameters
    ----------
    settings:
        An ``arxaudio.settings.Settings`` exposing ``benty_base_url``,
        ``benty_email`` and ``benty_password``.

    Returns
    -------
    list[Paper]
        Papers in benty's ranked order (best first), or ``[]`` if the most
        recent day genuinely has zero papers.

    Raises
    ------
    RuntimeError
        On systemic failure: site unreachable, login rejected, or a page that
        does not look like the expected results.
    """
    base = settings.benty_base_url.rstrip("/")

    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})

    def _get(url: str) -> requests.Response:
        resp = session.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp

    try:
        # 1. GET the login page for a session cookie + matching CSRF token.
        logger.info("Logging in to benty-fields at %s", base)
        login_page = _get(f"{base}/login")
        token = parse_csrf_token(login_page.text)

        # 2. POST credentials.
        post_resp = session.post(
            f"{base}/login",
            data={
                "csrf_token": token,
                "email": settings.benty_email,
                "password": settings.benty_password,
                "next": "",
            },
            timeout=_TIMEOUT,
        )
        post_resp.raise_for_status()

        # 3. Verify we are actually logged in by reading /daily_arXiv.
        daily = _get(f"{base}/daily_arXiv")
        if _looks_unauthenticated(daily):
            raise RuntimeError(
                "benty-fields login failed — check BENTY_EMAIL / "
                "BENTY_PASSWORD."
            )

        # 4. Find the most recent day and fetch its results.
        href = parse_latest_date_url(daily.text)
        results_url = urllib.parse.urljoin(base + "/", href)
        published = _published_from_href(href)
        logger.info("Fetching benty results for %s", published or "latest day")
        results = _get(results_url)

    except requests.RequestException as exc:
        raise RuntimeError(
            f"benty-fields is unreachable or returned an error: {exc}"
        ) from exc

    if "daily_arXiv" not in results.text and "class='paper'" not in results.text:
        raise RuntimeError(
            "benty-fields results page did not look like a day-results page. "
            "The site layout may have changed."
        )

    return parse_day_results(results.text, published=published)


def _published_from_href(href: str) -> str:
    """Pull the ``date=`` query param out of a results href (ISO date or '')."""
    query = urllib.parse.urlparse(href).query
    return urllib.parse.parse_qs(query).get("date", [""])[0]
