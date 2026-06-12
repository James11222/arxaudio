"""Ollama LLM backend talking to a local ollama server over its REST API.

Uses only the Python standard library (``urllib``) — no ``ollama`` pip package —
so the pipeline keeps its "stdlib-only for our files" promise and stays trivial
to run in GitHub Actions.

Every :meth:`OllamaBackend.complete` call is fully stateless: it opens a fresh
``/api/chat`` request with ``stream=false`` and no conversation history, which is
exactly what the tiny-model design in idea.md requires (context cleared per
abstract).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from arxaudio.llm.base import LLMBackend, LLMError

logger = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT = 120.0  # seconds; tiny models on CI can still be slow to load

# ollama defaults num_ctx to only 2048 tokens. Our filter/process prompts embed
# the whole of preferences.md (~1.1k tokens) plus a full abstract (~0.4-0.7k),
# which can brush against or exceed 2048 — at which point llama.cpp silently
# truncates the OLDEST tokens, mangling the system instructions and making a tiny
# model emit garbage (e.g. discarding every paper). 4096 holds preferences + one
# abstract with headroom; it costs a little KV-cache memory but does NOT change
# how many prompt tokens are actually evaluated, so inference speed is unaffected.
DEFAULT_NUM_CTX = 4096


class OllamaBackend(LLMBackend):
    """Stateless one-shot completions against a local ollama server.

    Args:
        model: ollama model tag, e.g. ``"qwen2.5:0.5b"``.
        host: base URL of the ollama server. Defaults to the ``OLLAMA_HOST``
            environment variable, then ``http://localhost:11434``.
        options: extra ollama generation options merged over the defaults.
            ``temperature`` defaults to ``0`` for deterministic output.
        timeout: per-request timeout in seconds.
    """

    def __init__(
        self,
        model: str,
        host: str | None = None,
        options: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model
        raw_host = host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
        self.host = self._normalize_host(raw_host)
        self.timeout = timeout
        # Deterministic by default, with an explicit context window large enough
        # to fit preferences.md + one abstract (see DEFAULT_NUM_CTX). Caller may
        # override either (incl. temperature / num_ctx).
        self.options: dict[str, Any] = {
            "temperature": 0,
            "num_ctx": DEFAULT_NUM_CTX,
        }
        if options:
            self.options.update(options)

    @staticmethod
    def _normalize_host(host: str) -> str:
        """Accept ``host:port`` or full URLs; always return an ``http(s)://`` base."""
        host = host.strip().rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        return host

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to ``path`` and return the decoded JSON response."""
        url = f"{self.host}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:  # pragma: no cover - best-effort detail only
                pass
            if exc.code == 404:
                raise LLMError(
                    f"ollama at {self.host} returned 404 for {path}. "
                    f"The model {self.model!r} is probably not pulled. "
                    f"Run 'ollama pull {self.model}'. Server said: {detail}"
                ) from exc
            raise LLMError(
                f"ollama HTTP {exc.code} from {url}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError(
                f"Could not reach ollama at {self.host} ({exc.reason}). "
                f"Is the server running? Start it with 'ollama serve' or set "
                f"OLLAMA_HOST."
            ) from exc
        except TimeoutError as exc:
            raise LLMError(
                f"ollama request to {url} timed out after {self.timeout:.0f}s."
            ) from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"ollama returned non-JSON from {url}: {body[:200]!r}"
            ) from exc

    def complete(self, system: str, prompt: str) -> str:
        """Run one stateless chat completion and return the response text.

        Raises:
            LLMError: if the server is unreachable, the model is missing, the
                request times out, or the response is malformed.
        """
        payload = {
            "model": self.model,
            "stream": False,
            "options": self.options,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        result = self._post("/api/chat", payload)
        try:
            content = result["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMError(
                f"Unexpected ollama /api/chat response shape: {result!r}"
            ) from exc
        if not isinstance(content, str):
            raise LLMError(f"ollama returned non-string content: {content!r}")
        return content.strip()

    def ensure_model(self) -> None:
        """Health check the pipeline can call at startup.

        Confirms the server is reachable and the configured model is available.
        Raises :class:`LLMError` with an actionable message otherwise so the
        pipeline can fail fast (and CI surfaces a real problem) rather than
        dying mid-run on the first abstract.
        """
        # 1) Is the server up? /api/tags lists locally available models.
        url = f"{self.host}/api/tags"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                tags = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LLMError(
                f"Could not reach ollama at {self.host} ({exc.reason}). "
                f"Start it with 'ollama serve' or set OLLAMA_HOST."
            ) from exc
        except (json.JSONDecodeError, TimeoutError) as exc:
            raise LLMError(f"ollama health check failed at {url}: {exc}") from exc

        # 2) Is our model present? Match by exact tag or bare name (':latest').
        available = {m.get("name", "") for m in tags.get("models", [])}
        bare = {name.split(":", 1)[0] for name in available}
        wanted_bare = self.model.split(":", 1)[0]
        if self.model in available or wanted_bare in bare:
            logger.info("ollama model %r is available at %s", self.model, self.host)
            return

        raise LLMError(
            f"ollama model {self.model!r} is not available at {self.host}. "
            f"Available: {sorted(available) or 'none'}. "
            f"Pull it with 'ollama pull {self.model}'."
        )
