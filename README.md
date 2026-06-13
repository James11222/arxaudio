# arxaudio

Turn today's arXiv abstracts into a podcast-style MP3, delivered to your inbox every morning — no API keys, no paid services, no local GPU required. Fork the repo, drop in your interests, add five email secrets, and GitHub Actions handles everything else: fetching the papers arXiv announced that day, ranking them against your research preferences with a tiny local language model, cleaning up LaTeX notation for speech, synthesizing audio with a free neural TTS voice, and emailing you one MP3 a day.

---

## How it works

```
arXiv API
    │  feedparser (no key)
    ▼
┌─────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌────────────┐   ┌─────────┐
│  Fetch  │──▶│   Rank   │──▶│  top-N only  │──▶│ Process  │──▶│    TTS     │──▶│  Email  │
└─────────┘   └──────────┘   └──────────────┘   └──────────┘   └────────────┘   └─────────┘
               ollama LLM      next-N: email        ollama LLM    edge-tts          smtplib
               title ranking   listing only         LaTeX→spoken  per-paper MP3     SMTP/TLS
                                                                  ffmpeg concat
```

1. **Fetch** — `fetch.py` pulls the daily announcement RSS feed (`rss.arxiv.org/rss/<category>`, no key) for each category in `config.py` and de-duplicates papers across categories. Each feed is exactly that day's mailing — the same papers that appear on `arxiv.org/list/<category>/new` that morning. New submissions and cross-lists are kept; replacements (revised versions of older papers) are skipped. One request per category with a polite 3-second delay between requests, as required by arXiv's terms of service.

2. **Rank** — `rank.py` sends all fetched paper titles to a tiny ollama LLM (default: `qwen2.5:0.5b`, ~400 MB) in a single call alongside your `preferences.md`. The model ranks papers by relevance (1 = most relevant). The top `MAX_PAPERS` ranked papers proceed to full audio treatment; the next `MAX_PAPERS` (ranks N+1..2N) are listed in the email only (title, first author, arXiv link). Any LLM error falls back silently to arrival order — papers are never lost.

3. **Process** — `process.py` converts LaTeX and math notation into speakable English. A deterministic regex/literal pass driven by `math_replacements.md` runs first (fast, reliable), then one stateless LLM call per paper catches the long tail. The LLM output passes a length-drift and chatter check; if it fails, the regex-only version is used. The model is instructed to only replace notation — never paraphrase.

4. **TTS + assembly** — `audio.py` and `tts/edge_backend.py` synthesize each paper as a separate MP3 using Microsoft's `edge-tts` (free, no key). Each paper is read as "title, by first author et al., abstract." Segments are joined with a configurable silence gap. If the result exceeds `MAX_MB` (default 20 MB), `audio.py` re-encodes progressively at lower bitrates (48k → 32k → 24k) until it fits.

5. **Email** — `emailer.py` uses stdlib `smtplib` to attach the MP3 and send it. Credentials come entirely from environment variables (GitHub Secrets in CI). The email body lists all audio papers plus, below a divider, the email-only runner-up papers so you can skim before you listen.

### Pluggable backends

Every LLM call goes through `LLMBackend` (the abstract base class in `src/arxaudio/llm/base.py`), and every TTS call goes through `TTSBackend` (`src/arxaudio/tts/base.py`). Swapping in a different model — including a fine-tuned one — means writing a subclass and adding one line to the registry in `src/arxaudio/pipeline.py`:

```python
_LLM_REGISTRY["mymodel"] = lambda s: MyBackend(...)
```

Then set `LLM_BACKEND = "mymodel"` in `config.py`. Nothing else in the pipeline changes. The same pattern applies to TTS engines.

---

## Alternative paper source: benty-fields.com

By default arxaudio fetches papers from arXiv's RSS feeds and ranks them with the local LLM. If you have an account on [benty-fields.com](https://www.benty-fields.com), you can instead let **benty-fields' own machine-learning model** — trained on your personal reading and voting history — pick and rank the day's papers for you. Set one variable in `config.py`:

```python
PAPER_SOURCE: str = "benty"
```

When `PAPER_SOURCE = "benty"`, the **Fetch and Rank stages are both replaced** by a single authenticated scrape of your benty-fields daily page (the papers there are already sorted best-first by benty's ML personalization). Everything downstream — Process, TTS, Email — is identical:

```
benty-fields.com  ─(login + scrape, already ranked)─▶  Process ──▶ TTS ──▶ Email
```

What changes in this mode:

- **`CATEGORIES` in `config.py` is ignored** — benty uses your account's own subscription settings instead.
- **The LLM ranking step is skipped entirely** — benty's ranking is used as-is. (ollama is still used for the Process/LaTeX-cleanup step, unless you also pass `--no-llm-clean`.)
- **Two new secrets are required:** your benty-fields login.

| Secret name      | Description                                                        |
|------------------|-------------------------------------------------------------------|
| `BENTY_EMAIL`    | The email address you log in to benty-fields with                 |
| `BENTY_PASSWORD` | Your benty-fields password — **use a unique password**, not one reused on other accounts, since it is stored as a CI secret |

Add them under **Settings → Secrets and variables → Actions** just like the SMTP secrets. Optionally, `BENTY_BASE_URL` overrides the site root (defaults to `https://www.benty-fields.com`).

> **A note on scraping:** this logs in to *your own* account and fetches one page per day — benty-fields' `robots.txt` permits it and the load is negligible. Because it scrapes rendered HTML (benty exposes no public API), it is inherently more fragile than the arXiv RSS path: if benty changes their page layout, this source may need updating. The arXiv source remains the robust default.

Locally, set the same two environment variables before running:

```bash
export BENTY_EMAIL=you@example.com
export BENTY_PASSWORD=your-benty-password
python -m arxaudio.pipeline          # with PAPER_SOURCE="benty" in config.py
```

---

## Quick start: fork and run in GitHub Actions

### 1. Fork this repository

Click **Fork** on GitHub. All subsequent steps are on your fork.

### 2. Edit `config.py` — choose your arXiv categories

Open `config.py` in your fork and update `CATEGORIES`:

```python
CATEGORIES: list[str] = [
    "astro-ph.CO",   # Cosmology and Nongalactic Astrophysics
    "cs.LG",         # Machine Learning
]
```

The full list of valid category strings is at: https://arxiv.org/category_taxonomy

### 3. Edit `preferences.md` — describe your research interests

This plain-text (Markdown) file is passed verbatim to the ranking LLM. Write in natural language. Be specific about methods, surveys, and topics you care about. Include a "Not interested in" section to help the model focus. See the existing file for an example.

### 4. Add repository secrets for email delivery

Go to your fork on GitHub: **Settings → Secrets and variables → Actions → New repository secret**.

Add these five secrets:

| Secret name     | Description                                      |
|-----------------|--------------------------------------------------|
| `SMTP_HOST`     | Your SMTP server, e.g. `smtp.gmail.com`          |
| `SMTP_PORT`     | Port number, e.g. `587` (STARTTLS) or `465` (SSL) |
| `SMTP_USER`     | Your full email address                          |
| `SMTP_PASSWORD` | Your SMTP password or app password               |
| `EMAIL_TO`      | Recipient address (can be the same as `SMTP_USER`) |

(If you use `PAPER_SOURCE = "benty"`, also add `BENTY_EMAIL` and `BENTY_PASSWORD` — see the [benty-fields section](#alternative-paper-source-benty-fieldscom).)

**Gmail walkthrough (recommended):** Gmail requires an App Password rather than your regular account password.
1. Go to your Google Account → Security → 2-Step Verification (enable it if not already on).
2. Search for "App passwords" in your Google Account settings.
3. Create a new app password (name it "arxaudio" or similar).
4. Use `smtp.gmail.com` as `SMTP_HOST`, `587` as `SMTP_PORT`, your Gmail address as `SMTP_USER`, and the generated 16-character app password as `SMTP_PASSWORD`.

**Other providers:** Outlook/Hotmail uses `smtp.office365.com:587`; iCloud uses `smtp.mail.me.com:587`. Check that SMTP AUTH is enabled in your provider's account settings. For port 465, the pipeline uses `SMTP_SSL` automatically.

### 5. Enable Actions on your fork

Go to the **Actions** tab on your fork and click **"I understand my workflows, go ahead and enable them."**

### 6. (Optional) Adjust the cron schedule

The default schedule in `.github/workflows/daily.yml` is:

```yaml
- cron: "30 10 * * 1-5"
```

This runs at 10:30 UTC, Monday through Friday. arXiv announces new papers Monday–Friday at approximately 00:00 UTC (20:00 ET the previous evening), so any morning-UTC run picks up the fresh batch. Adjust to your preferred time using [crontab.guru](https://crontab.guru/). Note that all GitHub Actions cron times are UTC.

### 7. Trigger a first run manually

On the **Actions** tab, select **"arxaudio daily digest"**, then click **"Run workflow"**. Two optional inputs are available:

| Input            | Description                                                   |
|------------------|---------------------------------------------------------------|
| `skip_email`     | Build the audio but do not send the email                     |

The first run downloads the ollama model (~400 MB for `qwen2.5:0.5b`); subsequent runs restore it from the Actions cache and start much faster.

The finished MP3 is also uploaded as a workflow artifact (retained for 14 days) under **Actions → your run → arxaudio-digest**, so you can download it even if email is not configured yet.

---

## Running locally

### Prerequisites

- Python 3.11 or newer
- [ffmpeg](https://ffmpeg.org/download.html) (must be on `PATH`)
- [ollama](https://ollama.com/) installed and running

### Install

```bash
git clone https://github.com/your-username/arxaudio.git
cd arxaudio
pip install -e .
```

### Pull the language model

```bash
ollama pull qwen2.5:0.5b
```

### Start the ollama server

```bash
ollama serve
```

### Set SMTP environment variables (for email delivery)

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=you@gmail.com
export SMTP_PASSWORD=your-app-password
export EMAIL_TO=you@gmail.com
```

### Run the pipeline

```bash
python -m arxaudio.pipeline
```

### Try it without ollama or email

```bash
python -m arxaudio.pipeline --dry-run --no-rank --no-llm-clean
```

This fetches papers, skips all LLM calls, and prints what would be synthesized — no ollama, no email, no output file.

### CLI flags

| Flag                    | Type    | Description                                                                 |
|-------------------------|---------|-----------------------------------------------------------------------------|
| `--config PATH`         | string  | Path to a `config.py` (default: repo-root `config.py`)                     |
| `--preferences PATH`    | string  | Path to a `preferences.md` (default: repo-root `preferences.md`)           |
| `--output PATH`         | string  | Output MP3 path (default: `./output/arxaudio_YYYY-MM-DD.mp3`)               |
| `--verbose`             | flag    | Enable DEBUG logging                                                        |
| `--max-papers N`        | integer | Override `MAX_PAPERS` (0 = unlimited)                                       |
| `--no-rank`             | flag    | Skip the LLM ranking; use arrival order for all fetched papers              |
| `--no-llm-clean`        | flag    | Skip the LLM math-cleanup pass; use regex-only replacements                 |
| `--no-email`            | flag    | Build the audio but do not send the email                                   |
| `--dry-run`             | flag    | Fetch + filter + process only; print what would be synthesized, then exit   |

---

## Configuration reference

All user-facing settings live in `config.py` at the repository root. Do not put secrets there — SMTP credentials come from environment variables only.

### config.py variables

| Variable               | Default                             | Description                                                                                  |
|------------------------|-------------------------------------|----------------------------------------------------------------------------------------------|
| `PAPER_SOURCE`         | `"arxiv"`                           | Where papers come from: `"arxiv"` (RSS feeds + LLM ranking) or `"benty"` (benty-fields ML ranking; see the [benty-fields section](#alternative-paper-source-benty-fieldscom)). In `"benty"` mode `CATEGORIES` is ignored and `BENTY_EMAIL`/`BENTY_PASSWORD` env vars are required |
| `BENTY_BASE_URL`       | `"https://www.benty-fields.com"`    | (benty mode only) Override the benty-fields site root. Rarely needed                          |
| `CATEGORIES`           | `["astro-ph.CO", "astro-ph.GA"]`    | arXiv categories to poll (ignored when `PAPER_SOURCE="benty"`). See https://arxiv.org/category_taxonomy |
| `LLM_BACKEND`          | `"ollama"`                          | Which LLM backend to use. Currently `"ollama"`; extensible via the registry in `pipeline.py` |
| `OLLAMA_MODEL`         | `"qwen2.5:0.5b"`                    | ollama model tag. The workflow reads this at runtime — change it here and CI follows automatically |
| `TTS_BACKEND`          | `"edge"`                            | Which TTS backend to use. Currently `"edge"` (edge-tts); extensible via the registry        |
| `TTS_VOICE`            | `"en-US-AndrewNeural"`              | Edge TTS voice identifier. Run `edge-tts --list-voices` to browse options                   |
| `MAX_MB`               | `20`                                | Maximum MP3 size in megabytes. Audio is bitrate-stepped-down automatically if exceeded      |
| `PAUSE_SECONDS`        | `1.2`                               | Silence gap in seconds between papers                                                        |
| `MAX_PAPERS`           | `10`                                | Top N ranked papers get full audio; next N are listed in the email only. `0` means unlimited (all papers get audio, no email-only section) |
| `EMAIL_SUBJECT_PREFIX` | `"ArXaudio Digest"`                 | Prepended to every email subject. The pipeline appends the date and paper count             |

### preferences.md

A plain Markdown file read verbatim by the ranking LLM as its system context. Write in plain English. Describe topics, methods, surveys, and datasets you want to follow. Include a "Not interested in" section to sharpen the ranking. Changes take effect on the next run with no code changes required.

### math_replacements.md

The single source of truth for turning LaTeX and math notation into speakable English. It contains two sections:

- **Literal replacements** — plain substring swaps (e.g. `\alpha` → `alpha`)
- **Regex patterns** — Python regular expressions for structured notation (exponents, subscripts, fractions, units with word boundaries, etc.)

Both are markdown tables parsed by `process.py`. **Extend the pipeline by editing this file only — no code changes needed.** The header section of the file documents the exact column format. This is the right place to add domain-specific notation your field uses (e.g. survey abbreviations, telescope names, unusual unit strings).

---

## Customization and forkability

**Different arXiv categories:** Update `CATEGORIES` in `config.py`. That is the only change needed.

**Different voice:** Run `edge-tts --list-voices` to see all available neural voices, then set `TTS_VOICE` in `config.py`. Good English options include `en-US-JennyNeural`, `en-GB-RyanNeural`, and `en-AU-NatashaNeural`.

**Larger or different ollama model:** Change `OLLAMA_MODEL` in `config.py`. The workflow reads that variable at runtime to set the cache key and run `ollama pull` — no changes to `daily.yml` are needed. Larger options like `qwen2.5:1.5b` or `llama3.2:1b` improve ranking quality at the cost of a larger cache and slower CI.

**Swapping the TTS engine:** Subclass `TTSBackend` (in `src/arxaudio/tts/base.py`), implement `synthesize(text, voice, out_path)`, and register it in `_TTS_REGISTRY` in `pipeline.py`. Set `TTS_BACKEND` in `config.py`.

**Swapping or fine-tuning the LLM:** Subclass `LLMBackend` (in `src/arxaudio/llm/base.py`), implement `complete(system, prompt) -> str`, and register it in `_LLM_REGISTRY` in `pipeline.py`. Set `LLM_BACKEND` in `config.py`. Because every LLM call is stateless and one-shot, a fine-tuned replacement model slots in with no other pipeline changes.

**Changing distribution:** The `emailer.py` module is self-contained and talks only to `Settings` and an MP3 path. Replace or wrap it to push to Slack, upload to S3, post to a feed, or any other delivery mechanism.

---

## Troubleshooting

| Symptom | Likely cause and fix |
|---------|----------------------|
| No email received | Check your spam folder. Verify the five secrets are set correctly in GitHub. If SMTP is only partially configured (e.g. `SMTP_HOST` set but `SMTP_PASSWORD` missing), the pipeline exits with an error — check the Actions log. |
| Gmail authentication error | You must use an App Password, not your regular account password. See the Gmail walkthrough above. |
| Zero papers in the output | arXiv announces new papers Monday through Friday only. Weekend and holiday runs see the most recent weekday mailing (or nothing new). Run locally with `--dry-run --verbose` to see what today's feed contains. |
| No papers in the audio | The ranking LLM uses arrival order as a fallback, so this is unlikely unless `MAX_PAPERS` is set very low or no papers were fetched. Try running locally with `--dry-run --verbose` to see the ranking output. Sharpen your `preferences.md` to improve ranking quality. |
| `ollama: connection refused` (local) | The ollama server is not running. Start it with `ollama serve` in a separate terminal. |
| `model not found` / `404` error | The model has not been pulled. Run `ollama pull qwen2.5:0.5b` (or whatever `OLLAMA_MODEL` is set to). |
| MP3 too large to email | The bitrate step-down is automatic (64k → 48k → 32k → 24k). If it is still over the limit, lower `MAX_PAPERS` in `config.py` to cap the number of papers per run. |
| First Actions run takes 10–15 minutes | The ollama model is being downloaded and the cache is being populated. Subsequent runs restore from cache and are much faster. |
| `edge-tts` synthesis failures | edge-tts requires an outbound network connection to Microsoft's servers. Transient failures are retried; persistent failures skip that paper and continue. Check the Actions log for details. |
| `benty-fields login failed` | (benty mode) Wrong `BENTY_EMAIL`/`BENTY_PASSWORD`, or your account is locked. Verify the credentials by logging in through a browser. |
| Benty mode fetches no/odd papers | benty scrapes rendered HTML; a site layout change can break parsing. Run locally with `--dry-run --verbose` to inspect. The arXiv source (`PAPER_SOURCE="arxiv"`) is the robust fallback. |
| Pipeline exits 1 with no clear error | Run locally with `--verbose` for DEBUG-level logging. |

---

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

The test suite uses fake `LLMBackend` and `TTSBackend` implementations — no network, no ollama, no edge-tts calls required.

---

## Project layout

```
arxaudio/
├── config.py                  # USER-EDITED: categories, model, voice, limits
├── preferences.md             # USER-EDITED: research interests for filtering
├── math_replacements.md       # LaTeX/symbol → spoken-text tables (user-extensible)
├── pyproject.toml             # package metadata and dependencies
├── src/arxaudio/
│   ├── models.py              # Paper dataclass — the contract between stages
│   ├── settings.py            # Loads config.py + SMTP env vars into Settings
│   ├── fetch.py               # arXiv RSS: papers announced today
│   ├── benty.py               # ALT SOURCE: scrape benty-fields.com (already ranked)
│   ├── rank.py                # LLM title ranking (one call for all papers)
│   ├── process.py             # Math-notation → spoken text (regex + LLM)
│   ├── audio.py               # Per-paper TTS segments → single MP3, size budget
│   ├── emailer.py             # SMTP send with MP3 attachment
│   ├── pipeline.py            # CLI orchestrator (python -m arxaudio.pipeline)
│   ├── llm/
│   │   ├── base.py            # LLMBackend ABC + LLMError
│   │   └── ollama_backend.py  # Stateless one-shot calls to a local ollama server
│   └── tts/
│       ├── base.py            # TTSBackend ABC + TTSError
│       └── edge_backend.py    # edge-tts implementation
└── .github/workflows/daily.yml  # Cron job: daily digest on weekdays
```

---

## A note on costs and API keys

arxaudio uses zero paid services and requires no API keys:

- **arXiv API** — free and open, no authentication required. The pipeline includes the mandatory 3-second delay between requests.
- **ollama + qwen2.5:0.5b** — runs locally (on your machine or the GitHub Actions runner). Completely free. The model is ~400 MB and cached between CI runs.
- **edge-tts** — Microsoft's Edge neural TTS, accessible for free without an API key via the `edge-tts` Python package.
- **ffmpeg** — open-source, installed via `apt` in CI.
- **GitHub Actions** — the free tier (2,000 minutes/month for public repos, 500 minutes/month for private) is sufficient for a daily run.
- **SMTP** — uses your own email account. App passwords are free.
- **benty-fields.com** (optional source) — free; uses your own account login. One page request per day.

If you find the project useful, please be a good citizen of the arXiv ecosystem: do not increase the request rate, and do not scrape bulk data beyond what the pipeline is designed for.

---

To contribute or adapt this project, add a license of your choice to the repository root.
