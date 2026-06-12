"""Fetch sample abstracts from arXiv and save them to tests/shrihan_tests/.

Usage:
    python fetch_samples.py
    python fetch_samples.py --count 20 --lookback 48 --categories astro-ph.CO astro-ph.HE
"""

import argparse
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

_NS = {"atom": "http://www.w3.org/2005/Atom"}
_API = "http://export.arxiv.org/api/query"
_OUT_DIR = Path(__file__).parent / "tests" / "shrihan_tests"


def fetch_abstracts(categories: list[str], limit: int = 10) -> list[tuple[str, str, str]]:
    results = []
    seen: set[str] = set()

    for cat in categories:
        if len(results) >= limit:
            break
        params = urllib.parse.urlencode({
            "search_query": f"cat:{cat}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": max(limit * 2, 50),
        })
        print(f"Fetching {cat} ...")
        time.sleep(3)  # arXiv ToS: >= 1 request / 3 s
        req = urllib.request.Request(
            f"{_API}?{params}",
            headers={"User-Agent": "arxaudio-fetch-samples/0.1 (educational)"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()

        root = ET.fromstring(data)
        for entry in root.findall("atom:entry", _NS):
            if len(results) >= limit:
                break
            raw_id = (entry.findtext("atom:id", "", _NS) or "").strip()
            arxiv_id = re.sub(r"v\d+$", "", re.sub(r"^https?://arxiv\.org/abs/", "", raw_id))
            if not arxiv_id or arxiv_id in seen:
                continue
            title = re.sub(r"\s+", " ", (entry.findtext("atom:title", "", _NS) or "").strip())
            abstract = re.sub(r"\s+", " ", (entry.findtext("atom:summary", "", _NS) or "").strip())
            seen.add(arxiv_id)
            results.append((arxiv_id, title, abstract))

    return results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--count", type=int, default=10, help="Number of abstracts to save (default: 10)")
    p.add_argument("--categories", nargs="+", default=["astro-ph.CO", "astro-ph.GA"],
                   help="arXiv categories to fetch from")
    args = p.parse_args()

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    papers = fetch_abstracts(args.categories, limit=args.count)

    for i, (arxiv_id, title, abstract) in enumerate(papers, 1):
        out = _OUT_DIR / f"{arxiv_id}.txt"
        out.write_text(abstract, encoding="utf-8")
        print(f"[{i}/{len(papers)}] {arxiv_id} — {title[:70]}")

    print(f"\nSaved {len(papers)} abstracts to {_OUT_DIR}/")


if __name__ == "__main__":
    main()
