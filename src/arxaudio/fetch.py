"""Fetch recent arXiv papers via the public Atom API.

Uses only stdlib (``urllib``) and ``feedparser``; no API key required.

Public API endpoint::

    http://export.arxiv.org/api/query

arXiv API ToS requires:
- No more than one request per 3 seconds (enforced by this module).
- A descriptive User-Agent header.
- Paging in blocks of ≤100 results.

Usage::

    from arxaudio.fetch import fetch_recent_papers
    papers = fetch_recent_papers(["astro-ph.CO", "astro-ph.GA"], lookback_hours=24)
"""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Iterator

import feedparser

from arxaudio.models import Paper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_URL = "http://export.arxiv.org/api/query"
_USER_AGENT = "arxaudio/0.1 (https://github.com/jsunseri/arxaudio; educational use)"
_PAGE_SIZE = 100          # polite page size per arXiv ToS
_INTER_REQUEST_DELAY = 3  # seconds between API requests
_MAX_RETRIES = 2
_RETRY_BACKOFF = 5        # seconds between retries

# Pattern to strip "http://arxiv.org/abs/" prefix and version suffix from IDs
_ID_PREFIX_RE = re.compile(r"^https?://arxiv\.org/abs/")
_VERSION_RE = re.compile(r"v\d+$")


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------

def _build_url(category: str, start: int, max_results: int) -> str:
    """Return a fully-formed arXiv API query URL for one category page."""
    params = urllib.parse.urlencode({
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": start,
        "max_results": max_results,
    })
    return f"{_API_URL}?{params}"


def _fetch_url(url: str) -> bytes:
    """Fetch *url* with retries and a descriptive User-Agent.

    Raises
    ------
    RuntimeError
        If the URL cannot be fetched after all retries.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    last_exc: Exception | None = None
    for attempt in range(1 + _MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            # 4xx are not transient; don't retry
            if exc.code and 400 <= exc.code < 500:
                raise RuntimeError(
                    f"arXiv API returned HTTP {exc.code} for {url!r}. "
                    "Check your query parameters."
                ) from exc
            last_exc = exc
            logger.warning(
                "HTTP error %s fetching %r (attempt %d/%d)",
                exc.code,
                url,
                attempt + 1,
                1 + _MAX_RETRIES,
            )
        except urllib.error.URLError as exc:
            last_exc = exc
            logger.warning(
                "Network error fetching %r (attempt %d/%d): %s",
                url,
                attempt + 1,
                1 + _MAX_RETRIES,
                exc.reason,
            )
        if attempt < _MAX_RETRIES:
            time.sleep(_RETRY_BACKOFF * (attempt + 1))

    raise RuntimeError(
        f"arXiv API is unreachable after {1 + _MAX_RETRIES} attempts. "
        f"Last error: {last_exc}. "
        "Check your internet connection and try again later."
    ) from last_exc


# ---------------------------------------------------------------------------
# Feed parsing helpers
# ---------------------------------------------------------------------------

def _normalise_whitespace(text: str) -> str:
    """Collapse newlines and repeated whitespace into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def _parse_arxiv_id(raw_id: str) -> str:
    """Convert a raw arXiv entry id to short form, e.g. '2506.01234'.

    The feed gives URLs like ``http://arxiv.org/abs/2506.01234v2``.
    """
    short = _ID_PREFIX_RE.sub("", raw_id.strip())
    short = _VERSION_RE.sub("", short)
    return short


def _entry_published_dt(entry: object) -> datetime | None:
    """Return the UTC published datetime for a feedparser entry, or None."""
    pub = getattr(entry, "published_parsed", None)
    if pub is None:
        return None
    try:
        return datetime(*pub[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_entry(entry: object) -> Paper | None:
    """Convert one feedparser entry to a ``Paper``, or return None on failure."""
    try:
        raw_id: str = getattr(entry, "id", "") or ""
        arxiv_id = _parse_arxiv_id(raw_id)
        if not arxiv_id:
            logger.debug("Skipping entry with empty id: %r", raw_id)
            return None

        title = _normalise_whitespace(getattr(entry, "title", "") or "")
        summary = _normalise_whitespace(getattr(entry, "summary", "") or "")

        # Authors: feedparser exposes them as a list of dicts with 'name' key
        raw_authors = getattr(entry, "authors", []) or []
        authors: list[str] = [
            _normalise_whitespace(a.get("name", ""))
            for a in raw_authors
            if a.get("name")
        ]

        # Categories: feedparser exposes them as a list of dicts with 'term' key
        raw_tags = getattr(entry, "tags", []) or []
        categories: list[str] = [
            t.get("term", "")
            for t in raw_tags
            if t.get("term")
        ]

        # Published timestamp: prefer "published" over "updated"
        pub_parsed = getattr(entry, "published_parsed", None)
        if pub_parsed:
            dt = datetime(*pub_parsed[:6], tzinfo=timezone.utc)
            published = dt.isoformat()
        else:
            published = getattr(entry, "published", "") or ""

        return Paper(
            arxiv_id=arxiv_id,
            title=title,
            abstract=summary,
            authors=authors,
            categories=categories,
            published=published,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse feed entry: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Per-category page iterator
# ---------------------------------------------------------------------------

def _iter_category_pages(
    category: str,
    cutoff: datetime,
    max_results: int,
) -> Iterator[list[Paper]]:
    """Yield successive pages of ``Paper`` objects for *category*.

    Stops paging when all entries on a page are older than *cutoff* or when
    *max_results* have been yielded in total.

    Sleeps ``_INTER_REQUEST_DELAY`` seconds **before** every request to
    honour arXiv's ToS.
    """
    start = 0
    total_fetched = 0

    while True:
        page_size = min(_PAGE_SIZE, max_results - total_fetched)
        if page_size <= 0:
            break

        url = _build_url(category, start, page_size)
        logger.debug("Fetching %s", url)

        time.sleep(_INTER_REQUEST_DELAY)
        raw = _fetch_url(url)

        feed = feedparser.parse(raw)
        entries = feed.get("entries", [])

        if not entries:
            logger.debug("Empty page at start=%d for category %s — stopping.", start, category)
            break

        page_papers: list[Paper] = []
        all_old = True  # will flip to False if any entry is within cutoff

        for entry in entries:
            paper = _parse_entry(entry)
            if paper is None:
                continue

            pub_dt = _entry_published_dt(entry)
            if pub_dt is None:
                # Cannot determine age; include it conservatively
                logger.debug("No published date for %s — including conservatively.", paper.arxiv_id)
                page_papers.append(paper)
                all_old = False
                continue

            if pub_dt >= cutoff:
                page_papers.append(paper)
                all_old = False
            else:
                # This entry is too old; since the feed is sorted descending,
                # everything after it will also be too old.
                logger.debug(
                    "Entry %s published %s is before cutoff %s — stopping pagination.",
                    paper.arxiv_id,
                    pub_dt.isoformat(),
                    cutoff.isoformat(),
                )
                # Still add whatever we collected on this page and then stop
                yield page_papers
                return

        total_fetched += len(page_papers)
        yield page_papers

        if all_old or len(entries) < page_size:
            # All old → stop; short page → we've reached the end of the feed
            break

        start += page_size


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_recent_papers(
    categories: list[str],
    lookback_hours: int = 24,
    max_results: int = 500,
) -> list[Paper]:
    """Fetch arXiv papers published within *lookback_hours* of now (UTC).

    Parameters
    ----------
    categories:
        List of arXiv category strings, e.g. ``["astro-ph.CO", "astro-ph.GA"]``.
    lookback_hours:
        How far back to look.  Papers older than this window are discarded.
    max_results:
        Hard cap on how many papers to retrieve per category before stopping
        pagination.  Prevents runaway paging on very active categories.

    Returns
    -------
    list[Paper]
        De-duplicated papers (by ``arxiv_id``) sorted with most-recent first,
        limited to the look-back window.

    Raises
    ------
    RuntimeError
        If arXiv is unreachable after retries.
    ValueError
        If *categories* is empty.
    """
    if not categories:
        raise ValueError("categories must be a non-empty list.")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    logger.info(
        "Fetching papers from %d categories (lookback=%dh, cutoff=%s)",
        len(categories),
        lookback_hours,
        cutoff.isoformat(),
    )

    seen: dict[str, Paper] = {}  # arxiv_id → first-seen Paper (de-duplication)

    for category in categories:
        cat_count_before = len(seen)

        for page in _iter_category_pages(category, cutoff, max_results):
            for paper in page:
                if paper.arxiv_id not in seen:
                    seen[paper.arxiv_id] = paper

        cat_new = len(seen) - cat_count_before
        logger.info("Category %s: %d new papers within window.", category, cat_new)

    papers = list(seen.values())
    logger.info(
        "Total after de-duplication across %d categories: %d papers.",
        len(categories),
        len(papers),
    )
    return papers
