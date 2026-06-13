"""Core data model shared by every pipeline stage.

A single ``Paper`` record flows through the pipeline; each stage fills in the
fields it owns. Treat this module as a fixed contract between stages.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Paper:
    """One arXiv paper as it moves through the pipeline.

    Fields set by fetch:
        arxiv_id, title, abstract, authors, categories, published

    Fields set by rank (the pipeline's split after relevance ranking):
        keep (None = not yet ranked; True = selected for audio; False = not
        selected — either an email-only extra or beyond the 2N window)

    Fields set by process (only for kept papers):
        clean_title, clean_abstract
    """

    arxiv_id: str
    title: str
    abstract: str
    authors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    published: str = ""  # ISO 8601 timestamp from the arXiv feed

    keep: bool | None = None
    clean_title: str = ""
    clean_abstract: str = ""

    @property
    def first_author(self) -> str:
        return self.authors[0] if self.authors else "unknown authors"

    @property
    def url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}"

    @property
    def spoken_author(self) -> str:
        """Author phrase for narration: 'First Author et al.' / 'First Author'."""
        if not self.authors:
            return "unknown authors"
        if len(self.authors) > 1:
            return f"{self.first_author} et al."
        return self.first_author

    def spoken_text(self, position: int | None = None) -> str:
        """The full text read aloud for this paper.

        When ``position`` (1-based) is given, the text opens with a spoken
        announcement of where this paper falls in the running order so the
        listener can keep track, e.g.::

            "Paper 1: <title>, written by Hou-Zun Chen et al. The abstract
             reads: ..."

        Without ``position`` the older bare form
        ``"<title>. by <author>[ et al]. <abstract>"`` is returned.
        """
        title = self.clean_title or self.title
        abstract = self.clean_abstract or self.abstract

        if position is not None:
            author = self.spoken_author
            # spoken_author already ends with "." after "et al."; avoid "..".
            sep = "" if author.endswith(".") else "."
            return (
                f"Paper {position}: {title}, written by {author}{sep} "
                f"The abstract reads: {abstract}"
            )

        byline = f"by {self.first_author}"
        if len(self.authors) > 1:
            byline += " et al"
        return f"{title}. {byline}. {abstract}"
