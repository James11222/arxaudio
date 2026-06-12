"""Tests for arxaudio.llm.ollama_backend.OllamaBackend.

All HTTP calls are monkeypatched — no real ollama server is needed.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from arxaudio.llm.base import LLMError
from arxaudio.llm.ollama_backend import OllamaBackend

# ---------------------------------------------------------------------------
# Helpers to build fake urllib responses
# ---------------------------------------------------------------------------

def _make_response(body: dict | str, status: int = 200) -> MagicMock:
    """Return a mock that behaves like the context-manager result of urlopen."""
    if isinstance(body, dict):
        data = json.dumps(body).encode("utf-8")
    else:
        data = body.encode("utf-8") if isinstance(body, str) else body
    mock = MagicMock()
    mock.read.return_value = data
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def _make_http_error(code: int, body: str = "") -> urllib.error.HTTPError:
    fp = BytesIO(body.encode("utf-8"))
    return urllib.error.HTTPError(
        url="http://localhost:11434/api/chat",
        code=code,
        msg="Error",
        hdrs={},  # type: ignore[arg-type]
        fp=fp,
    )


# ---------------------------------------------------------------------------
# OllamaBackend.complete
# ---------------------------------------------------------------------------

def test_complete_extracts_message_text(monkeypatch):
    """complete() must return the content field from the /api/chat response."""
    response_body = {
        "model": "qwen2.5:0.5b",
        "message": {"role": "assistant", "content": "KEEP"},
        "done": True,
    }
    mock_resp = _make_response(response_body)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=None: mock_resp
    )
    backend = OllamaBackend("qwen2.5:0.5b", host="http://localhost:11434")
    result = backend.complete("system", "prompt")
    assert result == "KEEP"


def test_complete_strips_whitespace(monkeypatch):
    """complete() must strip leading/trailing whitespace from the response."""
    response_body = {
        "message": {"role": "assistant", "content": "  DISCARD  \n"},
    }
    mock_resp = _make_response(response_body)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: mock_resp)
    backend = OllamaBackend("qwen2.5:0.5b")
    result = backend.complete("s", "p")
    assert result == "DISCARD"


def test_complete_connection_error_raises_llm_error(monkeypatch):
    """A URLError (server down) must raise LLMError with a helpful message."""
    def _raise_url_error(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise_url_error)
    backend = OllamaBackend("qwen2.5:0.5b", host="http://localhost:11434")
    with pytest.raises(LLMError, match="ollama"):
        backend.complete("s", "p")


def test_complete_http_404_raises_llm_error_with_pull_hint(monkeypatch):
    """A 404 from ollama means the model isn't pulled; error must mention 'pull'."""
    def _raise_404(req, timeout=None):
        raise _make_http_error(404, '{"error":"model not found"}')

    monkeypatch.setattr("urllib.request.urlopen", _raise_404)
    backend = OllamaBackend("qwen2.5:0.5b")
    with pytest.raises(LLMError, match="pull"):
        backend.complete("s", "p")


def test_complete_http_500_raises_llm_error(monkeypatch):
    """A 500 from ollama must raise LLMError."""
    def _raise_500(req, timeout=None):
        raise _make_http_error(500, "Internal Server Error")

    monkeypatch.setattr("urllib.request.urlopen", _raise_500)
    backend = OllamaBackend("qwen2.5:0.5b")
    with pytest.raises(LLMError):
        backend.complete("s", "p")


def test_complete_malformed_json_raises_llm_error(monkeypatch):
    """Non-JSON response body must raise LLMError."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"not valid json {{{"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: mock_resp)
    backend = OllamaBackend("qwen2.5:0.5b")
    with pytest.raises(LLMError, match="non-JSON"):
        backend.complete("s", "p")


def test_complete_missing_message_key_raises_llm_error(monkeypatch):
    """Response missing 'message' key must raise LLMError."""
    response_body = {"done": True}  # no 'message' key
    mock_resp = _make_response(response_body)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: mock_resp)
    backend = OllamaBackend("qwen2.5:0.5b")
    with pytest.raises(LLMError):
        backend.complete("s", "p")


def test_complete_timeout_raises_llm_error(monkeypatch):
    """A TimeoutError must be wrapped into LLMError."""
    def _raise_timeout(req, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _raise_timeout)
    backend = OllamaBackend("qwen2.5:0.5b")
    with pytest.raises(LLMError, match="timed out"):
        backend.complete("s", "p")


# ---------------------------------------------------------------------------
# OllamaBackend.ensure_model
# ---------------------------------------------------------------------------

_TAGS_WITH_MODEL = {
    "models": [
        {"name": "qwen2.5:0.5b"},
        {"name": "llama3.2:1b"},
    ]
}

_TAGS_WITHOUT_MODEL = {
    "models": [
        {"name": "llama3.2:1b"},
    ]
}

_TAGS_EMPTY = {"models": []}


def test_ensure_model_present_does_not_raise(monkeypatch):
    """ensure_model() must succeed when the model is in the tags list."""
    mock_resp = _make_response(_TAGS_WITH_MODEL)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: mock_resp)
    backend = OllamaBackend("qwen2.5:0.5b")
    # Must not raise
    backend.ensure_model()


def test_ensure_model_missing_raises_llm_error(monkeypatch):
    """ensure_model() must raise LLMError when the model is absent."""
    mock_resp = _make_response(_TAGS_WITHOUT_MODEL)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: mock_resp)
    backend = OllamaBackend("qwen2.5:0.5b")
    with pytest.raises(LLMError, match="not available"):
        backend.ensure_model()


def test_ensure_model_server_down_raises_llm_error(monkeypatch):
    """ensure_model() must raise LLMError when the server is unreachable."""
    def _raise_url_error(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise_url_error)
    backend = OllamaBackend("qwen2.5:0.5b", host="http://localhost:11434")
    with pytest.raises(LLMError):
        backend.ensure_model()


def test_ensure_model_bare_name_match(monkeypatch):
    """ensure_model() should succeed when bare model name (without tag) matches."""
    # Tags list has "qwen2.5:latest"; we ask for "qwen2.5" (no tag)
    tags = {"models": [{"name": "qwen2.5:latest"}]}
    mock_resp = _make_response(tags)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: mock_resp)
    backend = OllamaBackend("qwen2.5")
    # Should not raise — bare name matches
    backend.ensure_model()


# ---------------------------------------------------------------------------
# OllamaBackend normalise_host
# ---------------------------------------------------------------------------

def test_normalize_host_no_scheme():
    b = OllamaBackend("m", host="localhost:11434")
    assert b.host.startswith("http://")


def test_normalize_host_with_scheme():
    b = OllamaBackend("m", host="http://localhost:11434")
    assert b.host == "http://localhost:11434"


def test_normalize_host_trailing_slash():
    b = OllamaBackend("m", host="http://localhost:11434/")
    assert not b.host.endswith("/")
