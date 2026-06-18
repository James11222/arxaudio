# arxaudio

Turn today's arXiv abstracts into a podcast-style MP3, delivered to your inbox every morning — no API keys, no paid services, no local GPU required. Fork the repo, tell it what you're interested in, add a few email secrets, and GitHub Actions does the rest every weekday.

**New here? Jump straight to the [Quick start](#quick-start-5-minutes).** Everything below that explains how it works and how to customize it — you don't need any of it to get a daily digest running.

---

## Quick start (5 minutes)

You'll fork the repo, pick where your papers come from, add email secrets, and turn on the scheduled job. No code required.

### 1. Fork this repository

Click **Fork** on GitHub. Every step below happens on _your_ fork.

### 2. Choose your paper source

arxaudio can get your daily papers in one of two ways. Pick **one** and edit `PAPER_SOURCE` in `config.py` accordingly.

<table>
<tr><th>Option A — arXiv (default)</th><th>Option B — benty-fields</th></tr>
<tr><td valign="top">

Pulls the day's new papers from arXiv's RSS feeds and ranks them with a tiny local AI model against interests you describe in plain English.

**In `config.py`:**

```python
PAPER_SOURCE = "arxiv"
```

**Then edit two files:**

- **`config.py` → `CATEGORIES`** — the arXiv categories to follow:

  ```python
  CATEGORIES = [
      "astro-ph.CO",   # Cosmology
      "cs.LG",         # Machine Learning
  ]
  ```

  Full list: <https://arxiv.org/category_taxonomy>

- **`preferences.md`** — describe, in plain English, the topics, methods, and surveys you care about (and a "Not interested in" section). This is fed to the ranking model.

**No extra secrets needed.**

</td><td valign="top">

If you have a [benty-fields.com](https://www.benty-fields.com) account, let _its_ machine-learning model — trained on your own reading and voting history — pick and rank the day's papers for you.

**In `config.py`:**

```python
PAPER_SOURCE = "benty"
```

In this mode `CATEGORIES` and `preferences.md` are **ignored** — benty uses your account's settings — and the AI ranking step is skipped.

**Add two more secrets** (alongside the email secrets in step 3):

| Secret           | Value                                                                               |
| ---------------- | ----------------------------------------------------------------------------------- |
| `BENTY_EMAIL`    | Your benty-fields login email                                                       |
| `BENTY_PASSWORD` | Your benty-fields password — **use a unique one**, since it's stored as a CI secret |

More detail in the [benty-fields section](#paper-source-details-arxiv-vs-benty-fields).

</td></tr>
</table>

### 3. Add email secrets

On your fork: **Settings → Secrets and variables → Actions → New repository secret**. Add these five:

| Secret name     | Description                                        |
| --------------- | -------------------------------------------------- |
| `SMTP_HOST`     | Your SMTP server, e.g. `smtp.gmail.com`            |
| `SMTP_PORT`     | `587` (STARTTLS) or `465` (SSL)                    |
| `SMTP_USER`     | Your full email address                            |
| `SMTP_PASSWORD` | Your SMTP password or app password                 |
| `EMAIL_TO`      | Recipient address (can be the same as `SMTP_USER`) |

**Using Gmail?** You must create an _App Password_, not use your normal password:

1. Google Account → Security → enable **2-Step Verification**.
2. Search **App passwords** in your Google Account settings, create one (name it "arxaudio").
3. Use `smtp.gmail.com` / `587` / your Gmail address / the generated 16-character password.

**Other providers:** Outlook/Hotmail → `smtp.office365.com:587`; iCloud → `smtp.mail.me.com:587`. Make sure SMTP AUTH is enabled in your account. Port `465` switches to SSL automatically.

### 4. (Optional) Point the email footer at your fork

In `config.py`, set `REPO_URL` to your fork so the digest's "Sent by arxaudio" link is correct:

```python
REPO_URL = "https://github.com/your-username/arxaudio"
```

### 5. Enable Actions and run it

1. Go to the **Actions** tab on your fork and click **"I understand my workflows, go ahead and enable them."**
2. Select **"arxaudio daily digest"** → **Run workflow** to trigger the first run manually.

The first run downloads the local AI model (~400 MB) and takes 10–15 minutes; later runs restore it from cache and are much faster. The finished MP3 is emailed to you _and_ saved as a workflow artifact (under **Actions → your run → arxaudio-digest**, kept 14 days) so you can grab it even before email is working.

That's it — by default it now runs automatically every weekday at 10:37 UTC.

### 6. (Optional) Change the schedule

Edit the cron line in `.github/workflows/daily.yml`:

```yaml
- cron: "37 10 * * 1-5" # 10:37 UTC, Mon–Fri
```

arXiv announces new papers Mon–Fri around 00:00 UTC, so any morning-UTC run catches the fresh batch. Build your own time with [crontab.guru](https://crontab.guru/) (all GitHub Actions cron times are UTC).

---

## How it works

```
arXiv RSS / benty-fields
    │
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

4. **TTS + assembly** — `audio.py` and `tts/edge_backend.py` synthesize each paper as a separate MP3 using Microsoft's `edge-tts` (free, no key). Each paper is announced with its position, title, and author ("Paper 1: <title>, written by <author> et al. The abstract reads: …") so you can follow along. Segments are joined with a configurable silence gap. If the result exceeds `MAX_MB` (default 20 MB), `audio.py` re-encodes progressively at lower bitrates (48k → 32k → 24k) until it fits.

5. **Email** — `emailer.py` uses stdlib `smtplib` to attach the MP3 and send it as a formatted HTML email (with a plain-text fallback). Credentials come entirely from environment variables (GitHub Secrets in CI). The email lists all audio papers plus, in a second section, the email-only runner-up papers so you can skim before you listen.

### Pluggable backends

Every LLM call goes through `LLMBackend` (the abstract base class in `src/arxaudio/llm/base.py`), and every TTS call goes through `TTSBackend` (`src/arxaudio/tts/base.py`). Swapping in a different model — including a fine-tuned one — means writing a subclass and adding one line to the registry in `src/arxaudio/pipeline.py`:

```python
_LLM_REGISTRY["mymodel"] = lambda s: MyBackend(...)
```

Then set `LLM_BACKEND = "mymodel"` in `config.py`. Nothing else in the pipeline changes. The same pattern applies to TTS engines.

---

## Paper source details: arXiv vs benty-fields

The [Quick start](#2-choose-your-paper-source) covers the basic switch. This section explains the trade-offs.

**arXiv (default)** fetches papers from arXiv's RSS feeds and ranks them with the local LLM using your `preferences.md`. It needs no extra accounts and is the most robust option.

**benty-fields** replaces the **Fetch and Rank stages** with a single authenticated scrape of your benty-fields daily page (papers there are already sorted best-first by benty's ML personalization). Everything downstream — Process, TTS, Email — is identical:

```
benty-fields.com  ─(login + scrape, already ranked)─▶  Process ──▶ TTS ──▶ Email
```

What changes in benty mode:

- **`CATEGORIES` in `config.py` is ignored** — benty uses your account's own subscription settings instead.
- **The LLM ranking step is skipped entirely** — benty's ranking is used as-is. (ollama is still used for the Process/LaTeX-cleanup step, unless you also pass `--no-llm-clean`.)
- **Two new secrets are required** — `BENTY_EMAIL` and `BENTY_PASSWORD` (see the [Quick start](#2-choose-your-paper-source)). Optionally `BENTY_BASE_URL` overrides the site root (defaults to `https://www.benty-fields.com`).

> **A note on scraping:** this logs in to _your own_ account and fetches one page per day — benty-fields' `robots.txt` permits it and the load is negligible. Because it scrapes rendered HTML (benty exposes no public API), it is inherently more fragile than the arXiv RSS path: if benty changes their page layout, this source may need updating. The arXiv source remains the robust default.

To run benty mode locally, set the two environment variables before running:

```bash
export BENTY_EMAIL=you@example.com
export BENTY_PASSWORD=your-benty-password
python -m arxaudio.pipeline          # with PAPER_SOURCE="benty" in config.py
```

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

### Pull the language model and start the server

```bash
ollama pull qwen2.5:0.5b
ollama serve
```

> **Installing ollama:** Download from [ollama.com](https://ollama.com/) or install via Homebrew with `brew install ollama`. To stop the server when you're done: `pkill ollama`.

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

| Flag                 | Type    | Description                                                               |
| -------------------- | ------- | ------------------------------------------------------------------------- |
| `--config PATH`      | string  | Path to a `config.py` (default: repo-root `config.py`)                    |
| `--preferences PATH` | string  | Path to a `preferences.md` (default: repo-root `preferences.md`)          |
| `--output PATH`      | string  | Output MP3 path (default: `./output/arxaudio_YYYY-MM-DD.mp3`)             |
| `--verbose`          | flag    | Enable DEBUG logging                                                      |
| `--max-papers N`     | integer | Override `MAX_PAPERS` (0 = unlimited)                                     |
| `--no-rank`          | flag    | Skip the LLM ranking; use arrival order for all fetched papers            |
| `--no-llm-clean`     | flag    | Skip the LLM math-cleanup pass; use regex-only replacements               |
| `--no-email`         | flag    | Build the audio but do not send the email                                 |
| `--dry-run`          | flag    | Fetch + filter + process only; print what would be synthesized, then exit |
| `--output-text PATH` | string  | Save the processed text transcript to a file (default: `./output/arxaudio_YYYY-MM-DD.txt` when no path given) |

---

## Configuration reference

All user-facing settings live in `config.py` at the repository root. Do not put secrets there — SMTP and benty credentials come from environment variables only.

### config.py variables

| Variable               | Default                                    | Description                                                                                                                                                                                                                                                                    |
| ---------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `PAPER_SOURCE`         | `"arxiv"`                                  | Where papers come from: `"arxiv"` (RSS feeds + LLM ranking) or `"benty"` (benty-fields ML ranking; see the [details section](#paper-source-details-arxiv-vs-benty-fields)). In `"benty"` mode `CATEGORIES` is ignored and `BENTY_EMAIL`/`BENTY_PASSWORD` env vars are required |
| `BENTY_BASE_URL`       | `"https://www.benty-fields.com"`           | (benty mode only) Override the benty-fields site root. Rarely needed                                                                                                                                                                                                           |
| `CATEGORIES`           | `["astro-ph.CO", "astro-ph.GA"]`           | arXiv categories to poll (ignored when `PAPER_SOURCE="benty"`). See https://arxiv.org/category_taxonomy                                                                                                                                                                        |
| `LLM_BACKEND`          | `"ollama"`                                 | Which LLM backend to use. Currently `"ollama"`; extensible via the registry in `pipeline.py`                                                                                                                                                                                   |
| `OLLAMA_MODEL`         | `"qwen2.5:0.5b"`                           | ollama model tag. The workflow reads this at runtime — change it here and CI follows automatically                                                                                                                                                                             |
| `TTS_BACKEND`          | `"edge"`                                   | Which TTS backend to use. Currently `"edge"` (edge-tts); extensible via the registry                                                                                                                                                                                           |
| `TTS_VOICE`            | `"en-US-AndrewNeural"`                     | Edge TTS voice identifier. Run `edge-tts --list-voices` to browse options                                                                                                                                                                                                      |
| `TTS_SPEED`            | `1.0`                                      | Narration speed multiplier (`1.0` normal, `0.8` slower, `1.5`/`2.0` faster). Useful range ~0.5–2.0                                                                                                                                                                             |
| `MAX_MB`               | `20`                                       | Maximum MP3 size in megabytes. Audio is bitrate-stepped-down automatically if exceeded                                                                                                                                                                                         |
| `PAUSE_SECONDS`        | `1.2`                                      | Silence gap in seconds between papers                                                                                                                                                                                                                                          |
| `MAX_PAPERS`           | `10`                                       | Top N ranked papers get full audio; next N are listed in the email only. `0` means unlimited (all papers get audio, no email-only section)                                                                                                                                     |
| `EMAIL_SUBJECT_PREFIX` | `"ArXaudio Digest"`                        | Prepended to every email subject. The pipeline appends the date and paper count                                                                                                                                                                                                |
| `REPO_URL`             | `"https://github.com/James11222/arxaudio"` | Link shown in the email footer. Set this to your own fork                                                                                                                                                                                                                      |

### preferences.md

A plain Markdown file read verbatim by the ranking LLM as its system context. Write in plain English. Describe topics, methods, surveys, and datasets you want to follow. Include a "Not interested in" section to sharpen the ranking. Changes take effect on the next run with no code changes required. (Ignored when `PAPER_SOURCE="benty"`.)

### math_replacements.md

The single source of truth for turning LaTeX and math notation into speakable English. It contains two sections:

- **Literal replacements** — plain substring swaps (e.g. `\alpha` → `alpha`)
- **Regex patterns** — Python regular expressions for structured notation (exponents, subscripts, fractions, units with word boundaries, etc.)

Both are markdown tables parsed by `process.py`. **Extend the pipeline by editing this file only — no code changes needed.** The header section of the file documents the exact column format. This is the right place to add domain-specific notation your field uses (e.g. survey abbreviations, telescope names, unusual unit strings).

---

## Customization and forkability

**Different arXiv categories:** Update `CATEGORIES` in `config.py`. That is the only change needed.

**Different voice:** Run `edge-tts --list-voices` to see all available neural voices, then set `TTS_VOICE` in `config.py`. Good English options include `en-US-JennyNeural`, `en-GB-RyanNeural`, and `en-AU-NatashaNeural`.

**Narration speed:** Set `TTS_SPEED` in `config.py` to a multiplier — `1.0` is normal, `0.8` slows it down, and `1.2`/`1.5`/`2.0` speed it up. It applies to every paper in the audio.

**Larger or different ollama model:** Change `OLLAMA_MODEL` in `config.py`. The workflow reads that variable at runtime to set the cache key and run `ollama pull` — no changes to `daily.yml` are needed. Larger options like `qwen2.5:1.5b` or `llama3.2:1b` improve ranking quality at the cost of a larger cache and slower CI.

**Swapping the TTS engine:** Subclass `TTSBackend` (in `src/arxaudio/tts/base.py`), implement `synthesize(text, voice, out_path)`, and register it in `_TTS_REGISTRY` in `pipeline.py`. Set `TTS_BACKEND` in `config.py`.

**Swapping or fine-tuning the LLM:** Subclass `LLMBackend` (in `src/arxaudio/llm/base.py`), implement `complete(system, prompt) -> str`, and register it in `_LLM_REGISTRY` in `pipeline.py`. Set `LLM_BACKEND` in `config.py`. Because every LLM call is stateless and one-shot, a fine-tuned replacement model slots in with no other pipeline changes.

**Changing distribution:** The `emailer.py` module is self-contained and talks only to `Settings` and an MP3 path. Replace or wrap it to push to Slack, upload to S3, post to a feed, or any other delivery mechanism.

---

## NotebookLM TTS backend (AI-generated podcast)

> ⚠️ This uses the **unofficial** [notebooklm-py](https://github.com/teng-lin/notebooklm-py) library. Google can change their internal API without notice. Best for personal use and research.

Instead of the default Microsoft Edge TTS (which reads each abstract aloud one at a time), the **notebookLM backend** sends all selected papers to Google NotebookLM and requests a single AI-generated Audio Overview — a podcast-style conversation that covers each paper's key takeaways for an expert audience.

### What changes with this backend

|                    | Edge TTS (default)                            | NotebookLM                       |
| ------------------ | --------------------------------------------- | -------------------------------- |
| Audio style        | Synthetic narration, one abstract per segment | Natural podcast conversation     |
| Processing         | Per-paper Edge TTS + ffmpeg concat            | Single NotebookLM Audio Overview |
| LLM cleanup        | ollama math-cleanup pass                      | **None** (notebookLM handles it) |
| Internet required  | Edge TTS endpoint                             | Google NotebookLM                |
| Benty + notebookLM | ollama still used for math cleanup            | **Zero local LLM usage**         |
| Generation time    | ~30 s for 10 papers                           | ~2–5 minutes                     |

When `PAPER_SOURCE="benty"` + `TTS_BACKEND="notebooklm"`, **no local AI model (ollama) is needed at all**.

### Setup (one-time, on your local machine)

#### 1. Install notebooklm-py

```bash
pip install "notebooklm-py[browser]>=0.8"
```

This installs Playwright and downloads Chromium (~170 MB) on first use.

#### 2. Log in to NotebookLM

```bash
notebooklm login
```

A browser window opens — sign in with your Google account. Cookies are saved to `~/.notebooklm/storage_state.json`.

Verify the login worked:

```bash
notebooklm auth check --test
```

You should see `"status": "ok"`.

#### 3. Copy the auth JSON

```bash
cat ~/.notebooklm/storage_state.json
```

Copy the entire JSON output.

#### 4. Add `NOTEBOOKLM_AUTH_JSON` as a GitHub Secret

On your fork: **Settings → Secrets and variables → Actions → New repository secret**.

| Secret name            | Value                              |
| ---------------------- | ---------------------------------- |
| `NOTEBOOKLM_AUTH_JSON` | The full JSON you copied in step 3 |

> **Security note:** This JSON contains your Google session cookies. Treat it like a password. Use a dedicated Google account if you prefer.

### Configure config.py

```python
# Switch to NotebookLM audio generation
TTS_BACKEND: str = "notebooklm"

# Optional: customise the audio style
NOTEBOOKLM_AUDIO_FORMAT: str = "brief"    # "brief", "deep-dive", "critique", "debate"
NOTEBOOKLM_AUDIO_LENGTH: str = "default"  # "short", "default", "long"

# Optional: edit the instructions prompt (default is optimised for astrophysics)
NOTEBOOKLM_INSTRUCTIONS: str = (
    "You are generating a daily arXiv digest for an expert audience of "
    "postdoctoral researchers and senior PhD students in astrophysics and "
    "cosmology. For each paper in the sources, announce the paper title and "
    "first author's name, then give the key takeaways of the abstract in 2-4 "
    "concise sentences. Each paper must get its own self-contained segment. "
    "Do NOT compare papers to each other, and do NOT group papers by theme. "
    "Be precise and technical; the audience is already familiar with standard "
    "methods and terminology in the field."
)

# Delete the NotebookLM notebook after audio is downloaded (keeps workspace tidy)
NOTEBOOKLM_DELETE_NOTEBOOK: bool = True

# Maximum seconds to wait for NotebookLM to finish (generation takes 2-5 min)
NOTEBOOKLM_TIMEOUT: int = 600
```

`TTS_VOICE` and `TTS_SPEED` are **ignored** when `TTS_BACKEND="notebooklm"`.

### Install the optional dependency in CI

Your fork's workflow needs the extra dependency. If you don't want to edit the workflow file, you can also add it as a pip install step:

In `.github/workflows/daily.yml`, change the pip install step from:

```yaml
- run: pip install -e ".[dev]"
```

to:

```yaml
- run: pip install -e ".[dev,notebooklm]"
```

### Keeping your auth fresh

NotebookLM session cookies typically last several weeks. When a run fails with an auth error, re-run `notebooklm login` on your local machine and update the `NOTEBOOKLM_AUTH_JSON` secret with the new cookie JSON.

### Limitations

- **Unofficial API** — Google can change internal endpoints without notice.
- **Generation time** — NotebookLM takes 2–5 minutes to generate audio (vs ~30 s for Edge TTS). Set `NOTEBOOKLM_TIMEOUT` higher if runs time out.
- **One audio file** — You get a single podcast per run, not a separate segment per paper. The `MAX_MB` size budget and ffmpeg re-encoding are **not applied** (notebookLM controls the output format).
- **Language** — Defaults to English. If you need another language, use the Edge TTS backend.

---

## Troubleshooting

| Symptom                               | Likely cause and fix                                                                                                                                                                                                                                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| No email received                     | Check your spam folder. Verify the five secrets are set correctly in GitHub. If SMTP is only partially configured (e.g. `SMTP_HOST` set but `SMTP_PASSWORD` missing), the pipeline exits with an error — check the Actions log.                                          |
| Gmail authentication error            | You must use an App Password, not your regular account password. See the Gmail walkthrough in the [Quick start](#3-add-email-secrets).                                                                                                                                   |
| Zero papers in the output             | arXiv announces new papers Monday through Friday only. Weekend and holiday runs see the most recent weekday mailing (or nothing new). Run locally with `--dry-run --verbose` to see what today's feed contains.                                                          |
| No papers in the audio                | The ranking LLM uses arrival order as a fallback, so this is unlikely unless `MAX_PAPERS` is set very low or no papers were fetched. Try running locally with `--dry-run --verbose` to see the ranking output. Sharpen your `preferences.md` to improve ranking quality. |
| `ollama: connection refused` (local)  | The ollama server is not running. Start it with `ollama serve` in a separate terminal.                                                                                                                                                                                   |
| `model not found` / `404` error       | The model has not been pulled. Run `ollama pull qwen2.5:0.5b` (or whatever `OLLAMA_MODEL` is set to).                                                                                                                                                                    |
| MP3 too large to email                | The bitrate step-down is automatic (64k → 48k → 32k → 24k). If it is still over the limit, lower `MAX_PAPERS` in `config.py` to cap the number of papers per run.                                                                                                        |
| First Actions run takes 10–15 minutes | The ollama model is being downloaded and the cache is being populated. Subsequent runs restore from cache and are much faster.                                                                                                                                           |
| `edge-tts` synthesis failures         | edge-tts requires an outbound network connection to Microsoft's servers. Transient failures are retried; persistent failures skip that paper and continue. Check the Actions log for details.                                                                            |
| `benty-fields login failed`           | (benty mode) Wrong `BENTY_EMAIL`/`BENTY_PASSWORD`, or your account is locked. Verify the credentials by logging in through a browser.                                                                                                                                    |
| Benty mode fetches no/odd papers      | benty scrapes rendered HTML; a site layout change can break parsing. Run locally with `--dry-run --verbose` to inspect. The arXiv source (`PAPER_SOURCE="arxiv"`) is the robust fallback.                                                                                |
| Pipeline exits 1 with no clear error  | Run locally with `--verbose` for DEBUG-level logging.                                                                                                                                                                                                                    |

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
