"""arxaudio — daily arXiv abstracts → filtered MP3 digest, emailed automatically.

Convenience exports for embedding the pipeline in other code::

    from arxaudio import Paper, load_settings, make_llm, make_tts
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

from arxaudio.models import Paper
from arxaudio.settings import load_settings

__all__ = [
    "__version__",
    "Paper",
    "load_settings",
    "make_llm",
    "make_tts",
]


# The backend factories live in arxaudio.pipeline. We expose them here but import
# them lazily so that `python -m arxaudio.pipeline` (which runs pipeline as
# __main__) doesn't also import it through this package __init__ — that double
# import triggers a RuntimeWarning from runpy. Lazy access keeps both paths clean.
def __getattr__(name: str) -> Any:
    if name in ("make_llm", "make_tts"):
        from arxaudio import pipeline

        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # for type checkers / IDEs only
    from arxaudio.pipeline import make_llm, make_tts
