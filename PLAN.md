# arxaudio — Implementation Plan

Pipeline: fetch new arXiv papers daily → LLM-filter against user preferences →
LLM-clean math notation for speech → TTS → concatenate to one MP3 (<20 MB) →
email to user. Runs entirely in GitHub Actions with no paid APIs.

## Repository layout

```
arxaudio/
├── README.md                  # setup guide, troubleshooting
├── pyproject.toml             # package metadata + deps
├── config.py                  # USER-EDITED: categories, ollama model, voice, limits
├── preferences.md             # USER-EDITED: research interests for filtering
├── math_replacements.md       # reference table of LaTeX/symbol → spoken text
├── src/arxaudio/
│   ├── __init__.py
│   ├── models.py              # Paper dataclass (FIXED CONTRACT — do not change)
│   ├── settings.py            # loads config.py into a Settings object
│   ├── fetch.py               # arXiv API: papers submitted "today" per category
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py            # LLMBackend ABC (FIXED CONTRACT)
│   │   └── ollama_backend.py  # talks to local ollama server
│   ├── filter.py              # keep/discard per abstract via LLMBackend
│   ├── process.py             # math-notation → spoken-text cleanup via LLMBackend
│   ├── tts/
│   │   ├── __init__.py
│   │   ├── base.py            # TTSBackend ABC (FIXED CONTRACT)
│   │   └── edge_backend.py    # edge-tts implementation
│   ├── audio.py               # per-paper segments → single MP3, pauses, <20MB budget
│   ├── emailer.py             # SMTP send with attachment
│   └── pipeline.py            # CLI orchestrator: python -m arxaudio.pipeline
├── tests/                     # pytest; unit tests with mocked LLM/TTS/network
└── .github/workflows/daily.yml  # cron daily; caches ollama model + pip
```

## Fixed contracts

- `models.Paper`: one record flows through the whole pipeline; stages fill in
  fields (`keep`, `clean_title`, `clean_abstract`). See `src/arxaudio/models.py`.
- `llm.base.LLMBackend.complete(system, prompt) -> str`: stateless, one-shot —
  fresh context per call by design (idea.md requires clearing context per
  abstract). Swapping in a future fine-tuned model = new subclass + one line in
  config.
- `tts.base.TTSBackend.synthesize(text, voice, out_path)`: produces one MP3 per
  paper; `audio.py` owns concatenation and size budgeting.

## Stage notes

1. **Fetch** (`fetch.py`): arXiv API via `urllib`/`feedparser` (no key). Query
   each category in `config.CATEGORIES`, sorted by `submittedDate` descending,
   keep papers whose announcement falls in the last 24h window; de-dupe across
   categories by arXiv id. Be polite: single request per category, paging only
   if needed, 3s delay between requests per arXiv API ToS.
2. **Filter** (`filter.py`): for each paper, one LLM call with `preferences.md`
   in the system prompt; require a strict `KEEP`/`DISCARD` token answer; default
   to KEEP on unparseable output (never silently lose papers).
3. **Process** (`process.py`): regex/table fast-path from `math_replacements.md`
   first, then one LLM call per paper (primed with few-shot examples) to catch
   the long tail; must NOT paraphrase. Validate output length is close to input
   length; on suspicious output fall back to the regex-only version.
4. **TTS** (`audio.py` + `tts/`): per paper read "title. by <first author> et
   al. <abstract>"; synthesize each paper separately; join with ~1.2s silence;
   re-encode/bitrate-step-down with ffmpeg if total exceeds `MAX_MB` (20).
5. **Email** (`emailer.py`): stdlib `smtplib`/`email`; creds from env vars
   (`SMTP_HOST/PORT/USER/PASSWORD/TO`), i.e. GitHub Secrets. Skip-and-log
   cleanly if no papers survived filtering.
6. **CI** (`daily.yml`): ubuntu-latest, cron daily; install+start ollama, cache
   `~/.ollama/models` keyed on model name; cache pip; install ffmpeg; run
   `python -m arxaudio.pipeline`; upload MP3 as artifact too (belt and braces).

## Error handling & logging

- Python `logging` everywhere, INFO default, `--verbose` flag for DEBUG.
- Per-paper try/except in filter/process/TTS: one bad paper never kills the run.
- Pipeline exits nonzero only on systemic failures (arXiv unreachable, ollama
  missing, SMTP auth failure) so Actions surfaces real problems.

## Testing

- Unit tests with fake `LLMBackend`/`TTSBackend` (no network, no ollama).
- Golden tests for the regex math-replacement table.
- An integration smoke test gated behind env flags for local runs.
