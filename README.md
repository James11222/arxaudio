# arxaudio

Turn today's arXiv abstracts into a podcast-style MP3, delivered to your inbox every morning — no API keys, no paid services, no local GPU required.

---

## Quick start (5 minutes)

Fork the repo, configure it, add email secrets, and enable the scheduled workflow. No code required.

### 1. Fork this repository

Click **Fork** on GitHub. Every step below happens on your fork.

### 2. Choose your paper source

Edit `PAPER_SOURCE` in `config.py`:

**`"arxiv"` (default)** — fetches new papers from arXiv RSS feeds and ranks them with a local LLM against your stated interests. No extra accounts needed. Also edit:
- `CATEGORIES` — the arXiv categories to follow (see [arxiv.org/category_taxonomy](https://arxiv.org/category_taxonomy))
- `preferences.txt` — plain-English description of the topics, methods, and surveys you care about, plus a "Not interested in" section

**`"benty"`** — uses your [benty-fields.com](https://www.benty-fields.com) account's ML ranking directly. `CATEGORIES` and `preferences.txt` are ignored. Add two extra secrets: `BENTY_EMAIL` and `BENTY_PASSWORD`.

### 3. Add email secrets

**Settings → Secrets and variables → Actions → New repository secret:**

| Secret          | Description                                        |
| --------------- | -------------------------------------------------- |
| `SMTP_HOST`     | Your SMTP server, e.g. `smtp.gmail.com`            |
| `SMTP_PORT`     | `587` (STARTTLS) or `465` (SSL)                    |
| `SMTP_USER`     | Your full email address                            |
| `SMTP_PASSWORD` | Your SMTP password or app password                 |
| `EMAIL_TO`      | Recipient address (can be the same as `SMTP_USER`) |

**Gmail users:** you must use an [App Password](https://myaccount.google.com/apppasswords), not your regular password (Google Account → Security → enable 2-Step Verification → search "App passwords").

### 4. Enable Actions and run

1. Go to the **Actions** tab on your fork and enable workflows.
2. Select **"arxaudio daily digest"** → **Run workflow** to trigger the first run.

The first run downloads the LLM (~400 MB) and takes ~15 minutes. Later runs restore from cache and are much faster. The finished MP3 is emailed to you and saved as a workflow artifact (**Actions → your run → arxaudio-digest**, kept 14 days).

By default the workflow runs every weekday at 08:37 UTC. To change the schedule, edit the `cron` line in `.github/workflows/daily.yml` (all times are UTC; use [crontab.guru](https://crontab.guru/)).

---

## How it works

```
arXiv RSS / benty-fields
        │
        ▼
┌───────┐   ┌──────┐   ┌─────────┐   ┌─────┐   ┌───────┐
│ Fetch │──▶│ Rank │──▶│ Process │──▶│ TTS │──▶│ Email │
└───────┘   └──────┘   └─────────┘   └─────┘   └───────┘
             ollama      ollama        edge-tts   smtplib
             scoring     LaTeX→text    MP3 concat
```

1. **Fetch** — pulls today's arXiv RSS feed for each category. New submissions and cross-lists are kept; revisions are skipped.
2. **Rank** — sends all titles to `OLLAMA_RANK_MODEL` (default: `qwen2.5:1.5b`) in one call with your `preferences.txt`. Each paper is scored 0–10; the top `MAX_PAPERS` get audio, the next `MAX_PAPERS` are listed in the email only.
3. **Process** — converts LaTeX/math notation to speakable English via a regex pass (`math_replacements.md`) followed by an optional LLM polish call (`OLLAMA_MODEL`).
4. **TTS** — synthesizes each paper with Microsoft Edge TTS (`edge-tts`, free, no key). Segments are joined with ffmpeg.
5. **Email** — sends the MP3 as an HTML email listing all audio papers and email-only runners-up.

---

## Configuration reference

All settings live in `config.py`. Never put secrets there — credentials come from environment variables only.

| Variable               | Default                  | Description |
| ---------------------- | ------------------------ | ----------- |
| `PAPER_SOURCE`         | `"benty"`                | `"arxiv"` or `"benty"` |
| `CATEGORIES`           | `["astro-ph.CO", "astro-ph.GA"]` | arXiv categories to poll (arxiv mode only) |
| `OLLAMA_MODEL`         | `"qwen2.5:0.5b"`         | Model for math-cleanup (process stage) |
| `OLLAMA_RANK_MODEL`    | `"qwen2.5:1.5b"`         | Model for relevance ranking. Leave empty to reuse `OLLAMA_MODEL` |
| `TTS_VOICE`            | `"en-US-AndrewNeural"`   | Edge TTS voice. Run `edge-tts --list-voices` to browse |
| `TTS_SPEED`            | `1.0`                    | Narration speed (`0.8` slower, `1.5` faster) |
| `MAX_PAPERS`           | `10`                     | Top N papers get audio; next N are email-only. `0` = unlimited |
| `MAX_MB`               | `20`                     | MP3 size budget. Auto-reencodes at lower bitrate if exceeded |
| `EMAIL_SUBJECT_PREFIX` | `"arXaudio Digest"`      | Prepended to every email subject |
| `REPO_URL`             | `"https://github.com/James11222/arxaudio"` | Link in the email footer — set this to your fork |

### preferences.txt

Plain-English description of your research interests, fed verbatim to the ranking LLM. Describe topics, methods, and surveys you follow, and add a "Not interested in" section to sharpen results. Changes take effect on the next run. Ignored when `PAPER_SOURCE="benty"`.

### math_replacements.md

Markdown tables mapping LaTeX/math notation to speakable English. Two sections: **Literal replacements** (plain substring swaps) and **Regex patterns** (structured notation). Edit this file to add domain-specific notation — no code changes needed.

---

## Running locally

**Prerequisites:** Python 3.11+, [ffmpeg](https://ffmpeg.org/download.html), [ollama](https://ollama.com/)

```bash
git clone https://github.com/your-username/arxaudio.git
cd arxaudio
pip install -e .
ollama pull qwen2.5:0.5b   # or whichever OLLAMA_MODEL you set
ollama serve
```

Set SMTP environment variables, then:

```bash
python -m arxaudio.pipeline              # full run
python -m arxaudio.pipeline --dry-run    # fetch + rank + process, no TTS or email
python -m arxaudio.pipeline --no-rank --no-llm-clean --dry-run  # no LLM at all
```

**Useful CLI flags:**

| Flag                 | Description |
| -------------------- | ----------- |
| `--dry-run`          | Fetch, rank, and process only — no TTS or email |
| `--no-rank`          | Skip LLM ranking; use arrival order |
| `--no-llm-clean`     | Skip LLM math-cleanup; regex only |
| `--no-email`         | Build the MP3 but don't send it |
| `--output-text`      | Save cleaned text transcript to `output/arxaudio_YYYY-MM-DD.txt` |
| `--send-email MP3`   | Send an existing MP3 to test SMTP config (skips full pipeline) |
| `--date YYYY-MM-DD`  | Fetch papers for a specific past date (arXiv API, for debugging) |
| `--max-papers N`     | Override `MAX_PAPERS` for this run |
| `--verbose`          | Enable DEBUG logging |

---

## NotebookLM TTS backend (optional)

> ⚠️ Uses the unofficial [notebooklm-py](https://github.com/teng-lin/notebooklm-py) library. Google can change their API without notice.

Set `TTS_BACKEND = "notebooklm"` in `config.py` to replace per-paper Edge TTS with a single AI-generated podcast covering all selected papers.

**One-time setup:**

```bash
pip install "notebooklm-py[browser]>=0.8"
notebooklm login              # opens a browser — sign in with Google
cat ~/.notebooklm/storage_state.json  # copy the output
```

Add the copied JSON as a GitHub Secret named `NOTEBOOKLM_AUTH_JSON`. Update the pip install step in `daily.yml` to `pip install -e ".[notebooklm]"`.

Session cookies typically last several weeks. When a run fails with an auth error, re-run `notebooklm login` and update the secret.

When `PAPER_SOURCE="benty"` + `TTS_BACKEND="notebooklm"`, no local LLM is needed at all.

---

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| No email received | Check spam. Verify all five secrets are set. Check the Actions log for SMTP errors |
| Gmail auth error | Use an App Password, not your account password (see Quick start) |
| Zero papers | arXiv only publishes Mon–Fri. Run with `--dry-run --verbose` to inspect the feed |
| `ollama: connection refused` | Start the server: `ollama serve` |
| `model not found` | Run `ollama pull <model>` for the model in your `config.py` |
| MP3 too large | Bitrate step-down is automatic. Lower `MAX_PAPERS` if still over limit |
| First CI run slow | Model is being downloaded (~15 min). Later runs use cache and are much faster |
| Benty fetches no papers | Site layout may have changed. Switch to `PAPER_SOURCE="arxiv"` as fallback |
| Any unclear error | Re-run with `--verbose` for DEBUG-level logging |

---

## Project layout

```
arxaudio/
├── config.py                  # USER-EDITED: categories, models, voice, limits
├── preferences.txt            # USER-EDITED: research interests for ranking
├── math_replacements.md       # LaTeX/symbol → spoken-text tables (user-extensible)
├── src/arxaudio/
│   ├── pipeline.py            # CLI orchestrator
│   ├── fetch.py               # arXiv RSS / date-based API fetch
│   ├── benty.py               # benty-fields scraper
│   ├── rank.py                # LLM relevance scoring
│   ├── process.py             # Math-notation → spoken text
│   ├── audio.py               # TTS segments → single MP3
│   ├── emailer.py             # SMTP delivery
│   ├── models.py              # Paper dataclass
│   ├── settings.py            # Loads config + env vars
│   ├── llm/                   # LLMBackend ABC + ollama implementation
│   └── tts/                   # TTSBackend ABC + edge-tts / notebookLM implementations
└── .github/workflows/daily.yml
```

arxaudio uses no paid services and requires no API keys. The arXiv API, ollama, edge-tts, and ffmpeg are all free. GitHub Actions' free tier (2,000 min/month for public repos) is sufficient for daily runs.
