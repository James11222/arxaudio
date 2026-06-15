# NotebookLM Backend Implementation Plan

## Overview

Add a `TTS_BACKEND = "notebooklm"` option that replaces the per-paper Edge TTS pipeline with a single notebookLM Audio Overview covering all top-ranked papers. When active, regex/LLM math cleanup and Microsoft Edge TTS are bypassed entirely.

---

## Pipeline Changes (by source/backend combination)

| PAPER_SOURCE | TTS_BACKEND | Stages used |
|---|---|---|
| arxiv | edge | fetch → ollama rank → ollama clean → edge-tts → email |
| benty | edge | fetch(benty) → ollama clean → edge-tts → email |
| arxiv | notebooklm | fetch → ollama rank → **notebookLM audio** → email |
| benty | notebooklm | fetch(benty) → **notebookLM audio** → email |

The `benty + notebooklm` combination eliminates all local LLM usage.

---

## New Files

### `src/arxaudio/tts/notebooklm_backend.py`

A new `DirectAudioBackend` subclass (not `TTSBackend`) that:

1. Creates a new notebookLM notebook named `"arxaudio - YYYY-MM-DD"`
2. Adds each paper as a text source:
   ```
   Title: <title>
   First Author: <first_author>
   Abstract: <abstract>
   ```
3. Generates an Audio Overview with the user-configured format/length/instructions
4. Polls until generation is complete (with configurable timeout)
5. Downloads the audio to `out_path` as MP3
6. Optionally deletes the notebook afterwards
7. Raises `TTSError` on failure

Key implementation:
- Uses `notebooklm-py` (async API via `asyncio.run`)
- Auth via `NOTEBOOKLM_AUTH_JSON` env var → `NotebookLMClient.from_storage()`
- The instructions field includes the default expert-astrophysicist prompt
- One notebook per run (not one per paper)

### `src/arxaudio/tts/base.py` (addition)

Add `DirectAudioBackend` ABC:
```python
class DirectAudioBackend(ABC):
    @abstractmethod
    def generate_audio(self, papers: list[Paper], out_path: Path) -> None: ...
```

---

## Modified Files

### `pyproject.toml`

Add `notebooklm-py` as an optional dependency:
```toml
[project.optional-dependencies]
notebooklm = ["notebooklm-py>=0.8"]
```

It must be optional because it requires Playwright/Chromium browser automation for login, which we don't want to force on all users (only needed when `TTS_BACKEND="notebooklm"`).

### `config.py`

Add notebookLM-specific config block:
```python
# ---------------------------------------------------------------------------
# NotebookLM TTS backend settings (only used when TTS_BACKEND = "notebooklm")
# ---------------------------------------------------------------------------

NOTEBOOKLM_AUDIO_FORMAT: str = "brief"
# Options: "deep-dive", "brief", "critique", "debate"
# "brief" produces a concise overview — recommended for daily digests.

NOTEBOOKLM_AUDIO_LENGTH: str = "default"
# Options: "short", "default", "long"

NOTEBOOKLM_INSTRUCTIONS: str = """\
You are generating a daily arXiv digest for an expert audience of postdoctoral
researchers and senior PhD students in astrophysics and cosmology. For each
paper, announce the paper title and first author's name, then give the key
takeaways of the abstract in 2-4 sentences. Do not compare papers to each
other. Each paper gets its own self-contained segment. Be precise and technical;
the audience is familiar with standard methods and terminology in the field.
"""

NOTEBOOKLM_DELETE_NOTEBOOK: bool = True
# Whether to delete the notebook from notebookLM after the audio is generated.
# Set to False to keep the notebook for inspection.

NOTEBOOKLM_TIMEOUT: int = 1200
# Maximum seconds to wait for notebookLM to finish generating the audio.
```

### `settings.py`

Add fields:
```python
# NotebookLM (only used when tts_backend="notebooklm")
notebooklm_audio_format: str = "brief"
notebooklm_audio_length: str = "default"
notebooklm_instructions: str = "..."  # default expert astrophysics prompt
notebooklm_delete_notebook: bool = True
notebooklm_timeout: int = 1200
notebooklm_auth_json: str = ""  # from NOTEBOOKLM_AUTH_JSON env var
```

Also add `notebooklm_configured` property and validation.

### `pipeline.py`

Changes:
1. Import `DirectAudioBackend` and `NotebookLMTTSBackend`
2. Register `"notebooklm"` in `_TTS_REGISTRY`
3. Add `notebooklm_mode` flag: `settings.tts_backend == "notebooklm"`
4. When `notebooklm_mode` is True, skip the `process_papers` step
5. Adjust `needs_llm` to exclude clean step when `notebooklm_mode`
6. When building audio, check if `isinstance(tts, DirectAudioBackend)`:
   - True → call `tts.generate_audio(kept, output_path)` directly
   - False → call `audio.build_daily_audio(...)` as before
7. Fail fast if `TTS_BACKEND="notebooklm"` but `NOTEBOOKLM_AUTH_JSON` is missing

### `README.md`

Add a new section **"NotebookLM TTS backend"** explaining:
- What it does and when to use it
- Required secret: `NOTEBOOKLM_AUTH_JSON`
- Step-by-step setup: install notebooklm-py, run `notebooklm login`, export auth JSON
- How to configure `config.py`
- Supported combinations (arxiv+notebooklm, benty+notebooklm)
- Limitations / caveats (unofficial API, generation takes 2-5 min)

---

## New Tests

### `tests/test_notebooklm_backend.py`

Tests using `unittest.mock.AsyncMock` for the notebookLM client (never calls real API):
- `test_generate_audio_happy_path` — mock client, verify notebook created, sources added, audio generated and downloaded
- `test_generate_audio_cleans_up_on_success` — notebook deleted when `delete_notebook=True`
- `test_generate_audio_no_cleanup_when_disabled` — notebook NOT deleted when `delete_notebook=False`
- `test_generate_audio_cleans_up_on_failure` — notebook deleted even on error (no orphaned notebooks)
- `test_generate_audio_missing_auth_raises_tts_error` — no auth raises TTSError, not crashes
- `test_generate_audio_single_paper` — works with a single paper
- `test_generate_audio_many_papers` — sources match paper count
- `test_source_text_format` — each source contains title, first author, abstract
- `test_notebooklm_not_configured_error` — missing auth JSON raises at construction
- `test_dry_run_skip` — dry-run never calls notebookLM

### `tests/test_settings.py` additions

- `test_notebooklm_settings_defaults` — defaults load correctly
- `test_notebooklm_auth_json_from_env` — reads from env var
- `test_notebooklm_configured_property` — True when auth set

---

## Dependencies (pyproject.toml)

```toml
[project.optional-dependencies]
notebooklm = ["notebooklm-py>=0.8"]
dev = ["pytest>=8"]
```

**In GitHub Actions:** Add to the CI step: `pip install ".[notebooklm]"` when `TTS_BACKEND="notebooklm"`. The existing daily.yml does a plain `pip install -e ".[dev]"`. For notebookLM CI runs, users must also add `NOTEBOOKLM_AUTH_JSON` as a GitHub Secret.

---

## GitHub Secrets Required

| Secret | Description |
|---|---|
| `NOTEBOOKLM_AUTH_JSON` | Google session cookies for notebooklm-py authentication. Obtained via `notebooklm login` + `notebooklm auth export --json` (or stored by the CLI automatically at `~/.notebooklm/storage_state.json`). |

---

## Implementation Checklist

- [ ] Create `CODEBASE_REFERENCE.md`
- [ ] Create `NOTEBOOKLM_PLAN.md` (this file)
- [ ] Add `notebooklm-py` optional dependency to `pyproject.toml`
- [ ] Add `DirectAudioBackend` ABC to `tts/base.py`
- [ ] Create `tts/notebooklm_backend.py` with full implementation
- [ ] Update `config.py` with notebookLM config block
- [ ] Update `settings.py` with notebookLM fields + validation
- [ ] Update `pipeline.py` to handle notebookLM mode
- [ ] Add tests: `tests/test_notebooklm_backend.py`
- [ ] Add settings tests for notebookLM fields
- [ ] Update `README.md` with notebookLM setup section
- [ ] Run `pytest` — all tests pass
- [ ] Create pull request
