"""Fetch the papers arXiv announced today via the public RSS feeds.

Uses only stdlib (``urllib``) and ``feedparser``; no API key required.

Feed endpoint (one per category)::

    https://rss.arxiv.org/rss/<category>

Why RSS and not the Atom search API: the search API can only window on
*submission* date, but papers become visible there one to three days after
submission (and weekend submissions only on Monday/Tuesday), so any
hours-based lookback both misses announced papers and can never see the most
recent ones. The RSS feed is exactly one daily mailing — the same set of
papers that appears on arxiv.org/list/<category>/new that morning — so a run
at any time of day sees precisely what arXiv announced that day.

Each feed item carries an ``arxiv:announce_type``:

* ``new``           — a brand-new submission (kept)
* ``cross``         — a new submission cross-listed into this category (kept)
* ``replace`` / ``replace-cross`` — a revised version of an older paper
  (skipped: the digest is about new research, not updates)

arXiv ToS still applies: no more than one request per 3 seconds (enforced
here) and a descriptive User-Agent header.

Usage::

    from arxaudio.fetch import fetch_announced_papers
    papers = fetch_announced_papers(["astro-ph.CO", "astro-ph.GA"])
"""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import feedparser

from arxaudio.models import Paper
from arxaudio.process import decode_latex_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FEED_URL = "https://rss.arxiv.org/rss/{category}"
_API_URL = "https://export.arxiv.org/api/query"
_USER_AGENT = "arxaudio/0.1 (https://github.com/jsunseri/arxaudio; educational use)"
_INTER_REQUEST_DELAY = 3  # seconds between feed requests (arXiv ToS)
_MAX_RETRIES = 2
_RETRY_BACKOFF = 5        # seconds between retries
_API_MAX_RESULTS = 200    # per-category cap when querying by date

# Announce types that count as "a paper that appeared today".
_KEEP_ANNOUNCE_TYPES = {"new", "cross"}

# Feed ids look like "oai:arXiv.org:2606.12519v1"; links like
# "https://arxiv.org/abs/2606.12519". Strip either prefix plus any version.
_ID_PREFIX_RE = re.compile(r"^(oai:arXiv\.org:|https?://arxiv\.org/abs/)")
_VERSION_RE = re.compile(r"v\d+$")

# The RSS description is "arXiv:<id> Announce Type: <type>\nAbstract: <text>".
_ABSTRACT_RE = re.compile(r"Abstract:\s*", re.IGNORECASE)
_ANNOUNCE_TYPE_RE = re.compile(r"Announce Type:\s*([\w-]+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------

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
                    f"arXiv RSS returned HTTP {exc.code} for {url!r}. "
                    "Check the category name against "
                    "https://arxiv.org/category_taxonomy."
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
        f"arXiv RSS feed is unreachable after {1 + _MAX_RETRIES} attempts. "
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
    """Convert a raw feed id to short form, e.g. '2606.12519'.

    Handles both the RSS guid form ``oai:arXiv.org:2606.12519v1`` and the
    abs-URL form ``http://arxiv.org/abs/2606.12519v1``.
    """
    short = _ID_PREFIX_RE.sub("", raw_id.strip())
    short = _VERSION_RE.sub("", short)
    return short


def _entry_announce_type(entry: object) -> str:
    """Return the announce type for a feed entry ('' if undeterminable).

    feedparser exposes ``<arxiv:announce_type>`` as ``arxiv_announce_type``;
    the same token also appears in the description preamble, which we use as a
    fallback in case the namespaced element is missing or renamed.
    """
    announce = getattr(entry, "arxiv_announce_type", "") or ""
    if announce:
        return announce.strip().lower()
    match = _ANNOUNCE_TYPE_RE.search(getattr(entry, "summary", "") or "")
    return match.group(1).lower() if match else ""


def _parse_abstract(summary: str) -> str:
    """Extract the abstract from the RSS description.

    The description is ``arXiv:<id> Announce Type: <type>\\nAbstract: <text>``;
    if the preamble is ever absent, the whole description is used as-is.
    """
    match = _ABSTRACT_RE.search(summary)
    text = summary[match.end():] if match else summary
    return _normalise_whitespace(text)


def _parse_authors(entry: object) -> list[str]:
    """Return author names for a feed entry.

    The RSS feed packs all names into one comma-separated ``dc:creator``
    string ("Lei Ming, Marco Drewes"), which feedparser may expose as one or
    several author dicts — split each on commas to be safe either way.
    """
    raw_authors = getattr(entry, "authors", []) or []
    authors: list[str] = []
    for raw in raw_authors:
        name = raw.get("name", "") or ""
        for part in name.split(","):
            part = decode_latex_name(_normalise_whitespace(part))
            if part:
                authors.append(part)
    return authors


def _parse_entry(entry: object) -> Paper | None:
    """Convert one feedparser RSS entry to a ``Paper``, or None on failure."""
    try:
        raw_id: str = getattr(entry, "id", "") or getattr(entry, "link", "") or ""
        arxiv_id = _parse_arxiv_id(raw_id)
        if not arxiv_id:
            logger.debug("Skipping entry with empty id: %r", raw_id)
            return None

        title = _normalise_whitespace(getattr(entry, "title", "") or "")
        abstract = _parse_abstract(getattr(entry, "summary", "") or "")

        # Categories: feedparser exposes them as a list of dicts with 'term' key
        raw_tags = getattr(entry, "tags", []) or []
        categories: list[str] = [
            t.get("term", "")
            for t in raw_tags
            if t.get("term")
        ]

        # Published timestamp = the announcement date (same for every item in
        # one day's mailing).
        pub_parsed = getattr(entry, "published_parsed", None)
        if pub_parsed:
            dt = datetime(*pub_parsed[:6], tzinfo=timezone.utc)
            published = dt.isoformat()
        else:
            published = getattr(entry, "published", "") or ""

        return Paper(
            arxiv_id=arxiv_id,
            title=title,
            abstract=abstract,
            authors=_parse_authors(entry),
            categories=categories,
            published=published,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse feed entry: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_announced_papers(categories: list[str]) -> list[Paper]:
    """Fetch the papers arXiv announced today in *categories*.

    One RSS request per category (3 s apart, per arXiv ToS). Each feed is
    exactly the current day's mailing; items with announce type ``new`` or
    ``cross`` are kept, ``replace``/``replace-cross`` are skipped. An entry
    whose announce type cannot be determined is kept conservatively — papers
    are never silently dropped.

    Parameters
    ----------
    categories:
        List of arXiv category strings, e.g. ``["astro-ph.CO", "astro-ph.GA"]``.

    Returns
    -------
    list[Paper]
        De-duplicated papers (by ``arxiv_id``) in feed order.

    Raises
    ------
    RuntimeError
        If a feed is unreachable after retries.
    ValueError
        If *categories* is empty.
    """
    if not categories:
        raise ValueError("categories must be a non-empty list.")

    logger.info(
        "Fetching today's arXiv announcements for %d categories.", len(categories)
    )

    seen: dict[str, Paper] = {}  # arxiv_id → first-seen Paper (de-duplication)

    for category in categories:
        url = _FEED_URL.format(category=category)
        logger.debug("Fetching %s", url)

        time.sleep(_INTER_REQUEST_DELAY)
        raw = _fetch_url(url)

        feed = feedparser.parse(raw)
        entries = feed.get("entries", [])

        cat_new = 0
        skipped_replacements = 0
        for entry in entries:
            announce = _entry_announce_type(entry)
            if announce and announce not in _KEEP_ANNOUNCE_TYPES:
                skipped_replacements += 1
                continue
            if not announce:
                logger.debug(
                    "No announce type for %r — including conservatively.",
                    getattr(entry, "id", "?"),
                )

            paper = _parse_entry(entry)
            if paper is None:
                continue
            if paper.arxiv_id not in seen:
                seen[paper.arxiv_id] = paper
                cat_new += 1

        logger.info(
            "Category %s: %d entries in today's mailing — %d new papers kept, "
            "%d replacements skipped.",
            category,
            len(entries),
            cat_new,
            skipped_replacements,
        )

    papers = list(seen.values())
    logger.info(
        "Total after de-duplication across %d categories: %d papers.",
        len(categories),
        len(papers),
    )
    return papers


# ---------------------------------------------------------------------------
# Date-specific fetch (arXiv search API, for testing / past dates)
# ---------------------------------------------------------------------------

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"


def _parse_atom_entry(elem: ET.Element) -> Paper | None:
    """Convert one Atom <entry> element from the arXiv API to a Paper."""
    try:
        def tag(ns: str, name: str) -> str:
            return f"{{{ns}}}{name}"

        raw_id = (elem.findtext(tag(_ATOM_NS, "id")) or "").strip()
        arxiv_id = _parse_arxiv_id(raw_id)
        if not arxiv_id:
            return None

        title = _normalise_whitespace(elem.findtext(tag(_ATOM_NS, "title")) or "")
        abstract = _normalise_whitespace(elem.findtext(tag(_ATOM_NS, "summary")) or "")
        published = (elem.findtext(tag(_ATOM_NS, "published")) or "").strip()

        authors: list[str] = [
            _normalise_whitespace(a.findtext(tag(_ATOM_NS, "name")) or "")
            for a in elem.findall(tag(_ATOM_NS, "author"))
            if a.findtext(tag(_ATOM_NS, "name"))
        ]

        categories: list[str] = [
            c.get("term", "")
            for c in elem.findall(tag(_ATOM_NS, "category"))
            if c.get("term")
        ]

        return Paper(
            arxiv_id=arxiv_id,
            title=title,
            abstract=abstract,
            authors=authors,
            categories=categories,
            published=published,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse API entry: %s", exc)
        return None


def fetch_papers_for_date(categories: list[str], target_date: date) -> list[Paper]:
    """Fetch papers submitted on *target_date* using the arXiv search API.

    Uses submission date, not announcement date — papers submitted on day X
    are typically announced on day X+1 (next business day). This is intended
    for testing and back-filling, not the live daily pipeline.

    Parameters
    ----------
    categories:
        List of arXiv category strings, e.g. ``["astro-ph.CO", "astro-ph.GA"]``.
    target_date:
        The submission date to query.

    Returns
    -------
    list[Paper]
        De-duplicated papers (by ``arxiv_id``) across all categories.
    """
    if not categories:
        raise ValueError("categories must be a non-empty list.")

    date_str = target_date.strftime("%Y%m%d")
    date_range = f"[{date_str}0000+TO+{date_str}2359]"

    logger.info(
        "Fetching arXiv papers submitted on %s for %d categories (API mode).",
        target_date.isoformat(),
        len(categories),
    )

    seen: dict[str, Paper] = {}

    for i, category in enumerate(categories):
        if i > 0:
            time.sleep(_INTER_REQUEST_DELAY)

        query = f"cat:{category}+AND+submittedDate:{date_range}"
        url = (
            f"{_API_URL}?search_query={query}"
            f"&max_results={_API_MAX_RESULTS}"
            f"&sortBy=submittedDate&sortOrder=descending"
        )
        logger.debug("Querying arXiv API: %s", url)

        raw = _fetch_url(url)

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise RuntimeError(
                f"arXiv API returned unparseable XML for category {category!r}: {exc}"
            ) from exc

        entries = root.findall(f"{{{_ATOM_NS}}}entry")
        cat_new = 0
        for elem in entries:
            paper = _parse_atom_entry(elem)
            if paper is None:
                continue
            if paper.arxiv_id not in seen:
                seen[paper.arxiv_id] = paper
                cat_new += 1

        logger.info(
            "Category %s: %d papers submitted on %s.",
            category,
            cat_new,
            target_date.isoformat(),
        )

    papers = list(seen.values())
    logger.info(
        "Total after de-duplication across %d categories: %d papers.",
        len(categories),
        len(papers),
    )
    return papers
