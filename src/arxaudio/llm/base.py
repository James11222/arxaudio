"""Pluggable LLM backend interface.

Every LLM call in the pipeline is stateless and one-shot: a fresh context per
call, by design, so tiny models never accumulate context across abstracts.

To swap in a different model (e.g. a future fine-tuned one), subclass
``LLMBackend`` and point ``config.LLM_BACKEND`` at it. Nothing else in the
pipeline changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMBackend(ABC):
    """Minimal interface the filter and process stages depend on."""

    @abstractmethod
    def complete(self, system: str, prompt: str) -> str:
        """Run one stateless completion and return the model's text response.

        Implementations must not carry conversation state between calls.
        Raise ``LLMError`` on unrecoverable backend failures.
        """


class LLMError(RuntimeError):
    """Raised when the LLM backend fails (server down, model missing, ...)."""
