# arxaudio — Codebase Reference

This document is a concise reference for agents (and contributors) to quickly orient themselves in the arxaudio codebase. It covers the repo layout, all key abstractions, how stages wire together, and the conventions to follow when adding new backends.

---

## Repository Layout

```
arxaudio/
├── config.py                  # USER-EDITED: all user-facing knobs (categories, models, voice, limits)
├── preferences.md             # USER-EDITED: research interests — fed to the LLM ranker
├── math_replacements.md       # LaTeX/symbol → spoken-text table used by process.py
├── pyproject.toml             # Package metadata + pip dependencies
├── README.md                  # User-facing setup guide
├── PLAN.md                    # Original implementation plan
├── CODEBASE_REFERENCE.md      # This file
├── src/arxaudio/
│   ├── __init__.py
│   ├── models.py              # Paper dataclass — FIXED CONTRACT, do not change field names
│   ├── settings.py            # Loads config.py + env vars into a Settings dataclass
│   ├── fetch.py               # arXiv RSS → list[Paper] (no auth, stdlib only)
│   ├── benty.py               # benty-fields.com → list[Paper] (already ranked)
│   ├── rank.py                # LLM-rank papers by relevance against preferences.md
│   ├── process.py             # Math cleanup: regex fast-path + LLM polish pass
│   ├── audio.py               # TTS segments → single MP3 (ffmpeg concat + size budget)
│   ├── emailer.py             # SMTP email with MP3 attachment
│   ├── pipeline.py            # Orchestrator: wires all stages; CLI entry point
│   ├── llm/
│   │   ├── base.py            # LLMBackend ABC — `complete(system, prompt) -> str`
│   │   └── ollama_backend.py  # Local ollama server implementation
│   └── tts/
│       ├── base.py            # TTSBackend ABC — `synthesize(text, voice, out_path)`
│       └── edge_backend.py    # Microsoft Edge TTS (free, no API key)
└── tests/
    ├── conftest.py            # Shared fixtures: FakeLLM, FakeTTS, sample Paper objects
    ├── test_audio.py          # audio.py tests (require ffmpeg)
    ├── test_benty.py          # benty.py tests (HTML fixture-based)
    ├── test_edge_backend.py   # edge_backend.py tests
    ├── test_emailer.py        # emailer.py tests
    ├── test_fetch.py          # fetch.py tests
    ├── test_models.py         # models.py tests
    ├── test_ollama_backend.py # ollama_backend.py tests
    ├── test_process.py        # process.py tests
    ├── test_rank.py           # rank.py tests
    └── test_settings.py       # settings.py tests
```

---

## Key Abstractions and Contracts

### `Paper` (models.py) — FIXED CONTRACT

The single data object that flows through every pipeline stage.

```python
@dataclass
class Paper:
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]          # first_author property = authors[0]
    categories: list[str]
    published: str              # ISO 8601

    keep: bool | None = None    # Set by rank stage: True = audio, False = email-only
    clean_title: str = ""       # Set by process stage (math-cleaned for TTS)
    clean_abstract: str = ""    # Set by process stage
```

Key properties: `first_author`, `url` (arxiv abs URL), `spoken_author`, `spoken_text(position)`.

**Do not rename or remove any field.** The `keep` flag is the rank→process→audio contract. The `clean_title`/`clean_abstract` are the process→audio contract.

### `LLMBackend` (llm/base.py) — FIXED CONTRACT

```python
class LLMBackend(ABC):
    @abstractmethod
    def complete(self, system: str, prompt: str) -> str: ...
```

Stateless, one-shot completions only — no conversation history between calls, by design (tiny models, fresh context per call). Raise `LLMError` on failures. To add a new backend: subclass `LLMBackend`, register in `_LLM_REGISTRY` in `pipeline.py`.

### `TTSBackend` (tts/base.py) — FIXED CONTRACT

```python
class TTSBackend(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice: str, out_path: Path) -> None: ...
```

Produces ONE MP3 per call. `audio.py` owns concatenation. Raise `TTSError` on failures. To add a new per-paper backend: subclass `TTSBackend`, register in `_TTS_REGISTRY` in `pipeline.py`.

**Exception for batch backends:** Some backends (e.g. notebookLM) generate ONE audio for ALL papers in a single call. These use a different ABC; see `DirectAudioBackend` below.

### `DirectAudioBackend` (tts/base.py) — for batch audio generation

For backends that produce a single audio file for all papers:

```python
class DirectAudioBackend(ABC):
    @abstractmethod
    def generate_audio(self, papers: list[Paper], out_path: Path) -> None: ...
```

The pipeline detects `isinstance(tts, DirectAudioBackend)` and calls `generate_audio()` directly, bypassing the per-paper `audio.py` stage entirely. When this backend is active, the process stage (math cleanup) is also skipped since the backend handles its own text formatting.

---

## Pipeline Flow (pipeline.py)

```
load settings
    → read preferences.md
    → fetch papers (arxiv RSS -OR- benty-fields)
    → [rank papers by LLM] ← skipped in benty mode OR when notebookLM backend
    → split into audio papers (top N) + email-only extras
    → [process: clean math for TTS] ← skipped when notebookLM backend
    → [dry-run exit?]
    → build audio (edge-tts per paper + ffmpeg concat -OR- notebookLM batch)
    → email digest
```

### When to skip LLM stages

| paper_source | tts_backend | needs_llm_rank | needs_llm_clean |
|--------------|-------------|----------------|-----------------|
| arxiv        | edge        | yes (unless `--no-rank`) | yes (unless `--no-llm-clean`) |
| benty        | edge        | no (benty pre-ranks) | yes (unless `--no-llm-clean`) |
| arxiv        | notebooklm  | yes (unless `--no-rank`) | **no** (notebookLM handles formatting) |
| benty        | notebooklm  | no | **no** — zero LLM usage |

---

## Settings (settings.py + config.py)

`load_settings(config_path)` loads `config.py`, merges defaults, reads secrets from env vars, validates, and returns a `Settings` dataclass.

| config.py variable | Settings field | Default | Notes |
|---|---|---|---|
| `PAPER_SOURCE` | `paper_source` | `"arxiv"` | `"arxiv"` or `"benty"` |
| `CATEGORIES` | `categories` | `["astro-ph.CO", "astro-ph.GA"]` | arXiv category list |
| `LLM_BACKEND` | `llm_backend` | `"ollama"` | Only `"ollama"` supported |
| `OLLAMA_MODEL` | `ollama_model` | `"qwen2.5:0.5b"` | |
| `TTS_BACKEND` | `tts_backend` | `"edge"` | `"edge"` or `"notebooklm"` |
| `TTS_VOICE` | `tts_voice` | `"en-US-AndrewNeural"` | Edge voice; ignored by notebookLM |
| `TTS_SPEED` | `tts_speed` | `1.0` | Ignored by notebookLM |
| `MAX_MB` | `max_mb` | `20` | Ignored by notebookLM |
| `PAUSE_SECONDS` | `pause_seconds` | `1.2` | Ignored by notebookLM |
| `MAX_PAPERS` | `max_papers` | `10` | Applies to all backends |
| `NOTEBOOKLM_AUDIO_FORMAT` | `notebooklm_audio_format` | `"brief"` | notebookLM only |
| `NOTEBOOKLM_AUDIO_LENGTH` | `notebooklm_audio_length` | `"default"` | notebookLM only |
| `NOTEBOOKLM_INSTRUCTIONS` | `notebooklm_instructions` | `"..."` | Custom prompt for notebookLM |
| `NOTEBOOKLM_DELETE_NOTEBOOK` | `notebooklm_delete_notebook` | `True` | Clean up notebook after use |
| `NOTEBOOKLM_TIMEOUT` | `notebooklm_timeout` | `1200` | Max seconds to wait for generation |

**Environment variables / GitHub Secrets:**

| Variable | When required |
|---|---|
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` | Always, for email |
| `BENTY_EMAIL`, `BENTY_PASSWORD` | When `PAPER_SOURCE="benty"` |
| `NOTEBOOKLM_AUTH_JSON` | When `TTS_BACKEND="notebooklm"` |

---

## Backend Registry Pattern

New backends are added via the `_LLM_REGISTRY` / `_TTS_REGISTRY` dicts in `pipeline.py`:

```python
_TTS_REGISTRY: dict[str, callable[[Settings], TTSBackend | DirectAudioBackend]] = {
    "edge": lambda s: EdgeTTSBackend(default_voice=s.tts_voice, speed=s.tts_speed),
    "notebooklm": lambda s: NotebookLMTTSBackend(settings=s),
}
```

Adding a new backend = one new subclass file + one line in the registry.

---

## Testing Conventions

- Run tests: `pytest` from repo root.
- All tests are offline — no network, no ollama, no edge-tts calls.
- `conftest.py` provides `FakeLLM`, `FakeTTS`, and sample `Paper` objects.
- Audio tests require ffmpeg at `/opt/homebrew/bin/ffmpeg` and are skipped otherwise.
- Use `monkeypatch.setenv` / `monkeypatch.delenv` for env var tests.
- Use `tmp_path` for file I/O in tests.
- New TTS backend tests belong in `tests/test_<name>_backend.py`.
- Mock the notebooklm client with `unittest.mock.AsyncMock` — never call the real API in tests.

---

## Error Handling Philosophy

- **Per-paper failures** are isolated (logged + skipped). One bad paper never kills the run.
- **Systemic failures** (network, auth, config) exit nonzero so GitHub Actions surfaces them.
- Every stage uses `try/except` internally but only swallows paper-level errors, not systemic ones.
- LLM backends raise `LLMError`; TTS backends raise `TTSError`; the pipeline catches both at the per-paper level.

---

## GitHub Actions CI

`.github/workflows/daily.yml` runs on a cron schedule. It:
1. Installs Python + pip dependencies
2. Installs + starts ollama (downloads model, cached per model name)
3. Installs ffmpeg
4. Runs `python -m arxaudio.pipeline`
5. Uploads the MP3 as an artifact (belt-and-braces backup)

When `TTS_BACKEND="notebooklm"`: ollama is still needed for arXiv mode ranking (but not for benty mode). The `NOTEBOOKLM_AUTH_JSON` secret must be present.
