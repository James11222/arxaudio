"""NotebookLM TTS backend: generates a single podcast-style audio overview
for all top-ranked papers using Google's NotebookLM service.

Unlike the per-paper ``EdgeTTSBackend``, this backend submits *all* kept papers
as sources to a single NotebookLM notebook and requests one Audio Overview
podcast covering them all in one generation call.  The downloaded MP3 is used
directly as the daily digest audio — no ffmpeg concatenation is needed.

Because NotebookLM generates the audio from the raw title/author/abstract text
(it understands scientific notation), the upstream ``process.py`` math-cleanup
stage is bypassed entirely when this backend is active.

Authentication
--------------
The notebooklm-py library reads authentication from the ``NOTEBOOKLM_AUTH_JSON``
environment variable (a JSON string containing Google session cookies).  Obtain
the JSON by running ``notebooklm login`` locally, then copy the contents of
``~/.notebooklm/storage_state.json``.  Add it as a GitHub Actions Secret named
``NOTEBOOKLM_AUTH_JSON``.

Install
-------
``pip install "notebooklm-py>=0.8"``  (optional dep — ``pip install ".[notebooklm]"``)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from .base import DirectAudioBackend, TTSError

if TYPE_CHECKING:
    from arxaudio.models import Paper
    from arxaudio.settings import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FORMAT_MAP: dict[str, str] = {
    "brief": "BRIEF",
    "deep-dive": "DEEP_DIVE",
    "critique": "CRITIQUE",
    "debate": "DEBATE",
}

_LENGTH_MAP: dict[str, str] = {
    "short": "SHORT",
    "default": "DEFAULT",
    "long": "LONG",
}


def _format_source_text(paper: "Paper") -> str:
    """Return the source text for one paper to add to NotebookLM."""
    return (
        f"Title: {paper.title}\n"
        f"First Author: {paper.first_author}\n"
        f"Abstract: {paper.abstract}"
    )


def _format_source_title(paper: "Paper") -> str:
    """Return a short title string for one paper's NotebookLM source."""
    # Truncate to 200 chars to stay within reasonable title limits.
    title = paper.title[:195] + "…" if len(paper.title) > 200 else paper.title
    return title


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class NotebookLMTTSBackend(DirectAudioBackend):
    """Generate a single podcast-style audio overview via NotebookLM.

    All kept papers are added as text sources to a freshly-created NotebookLM
    notebook.  One Audio Overview is then generated with the configured format,
    length, and instructions prompt.  The resulting MP3 is downloaded to
    ``out_path``; the notebook is optionally deleted afterwards.

    Args:
        settings: A fully-loaded :class:`arxaudio.settings.Settings` instance.
            The following fields are used:
            ``notebooklm_audio_format``, ``notebooklm_audio_length``,
            ``notebooklm_instructions``, ``notebooklm_delete_notebook``,
            ``notebooklm_timeout``, ``notebooklm_auth_json``.
    """

    def __init__(self, settings: "Settings") -> None:
        self._audio_format = settings.notebooklm_audio_format.lower()
        self._audio_length = settings.notebooklm_audio_length.lower()
        self._instructions = settings.notebooklm_instructions
        self._delete_notebook = settings.notebooklm_delete_notebook
        self._timeout = settings.notebooklm_timeout
        self._auth_json = settings.notebooklm_auth_json

        if not self._auth_json:
            raise TTSError(
                "NotebookLMTTSBackend requires the NOTEBOOKLM_AUTH_JSON "
                "environment variable.  Set it to the contents of "
                "~/.notebooklm/storage_state.json (obtained by running "
                "'notebooklm login')."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_audio(self, papers: "list[Paper]", out_path: Path) -> None:
        """Generate a single podcast MP3 for all ``papers`` via NotebookLM.

        Args:
            papers: The kept papers to include.  Each paper's title, first
                author, and abstract are added as a separate text source.
            out_path: Destination path for the MP3 file.

        Raises:
            TTSError: On any unrecoverable failure (auth, generation, download).
        """
        kept = [p for p in papers if p.keep]
        if not kept:
            raise TTSError("NotebookLMTTSBackend.generate_audio: no kept papers.")

        logger.info(
            "NotebookLM: generating audio overview for %d papers (format=%s, length=%s).",
            len(kept),
            self._audio_format,
            self._audio_length,
        )

        try:
            asyncio.run(self._generate_async(kept, Path(out_path)))
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(
                f"NotebookLM audio generation failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Internal async implementation
    # ------------------------------------------------------------------

    async def _generate_async(
        self, papers: "list[Paper]", out_path: Path
    ) -> None:
        """Full async workflow: create notebook → add sources → generate → download."""
        try:
            from notebooklm import NotebookLMClient, AudioFormat, AudioLength
        except ImportError as exc:
            raise TTSError(
                "notebooklm-py is not installed.  "
                "Install it with:  pip install 'notebooklm-py>=0.8'  "
                "or:  pip install '.[notebooklm]'"
            ) from exc

        # Map config strings to enum values.
        fmt_name = _FORMAT_MAP.get(self._audio_format, "BRIEF")
        len_name = _LENGTH_MAP.get(self._audio_length, "DEFAULT")
        try:
            audio_format = AudioFormat[fmt_name]
            audio_length = AudioLength[len_name]
        except KeyError as exc:
            raise TTSError(
                f"Invalid NotebookLM audio format/length: {exc}.  "
                f"Valid formats: {sorted(_FORMAT_MAP)}.  "
                f"Valid lengths: {sorted(_LENGTH_MAP)}."
            ) from exc

        # Write auth JSON to a temp file (the client expects a storage_state
        # file path).  We write to a NamedTemporaryFile so it is cleaned up
        # even on error.
        notebook_id: str | None = None

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            tf.write(self._auth_json)
            auth_path = tf.name

        try:
            async with NotebookLMClient.from_storage(auth_path) as client:
                notebook_id = await self._run_workflow(
                    client, papers, out_path, audio_format, audio_length
                )
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(
                f"NotebookLM workflow failed: {exc}"
            ) from exc
        finally:
            # Always clean up the temp auth file.
            try:
                Path(auth_path).unlink(missing_ok=True)
            except OSError:
                pass

    async def _run_workflow(
        self,
        client: object,
        papers: "list[Paper]",
        out_path: Path,
        audio_format: object,
        audio_length: object,
    ) -> str | None:
        """Create notebook, add sources, generate and download audio."""
        today = date.today().isoformat()
        notebook_name = f"arxaudio - {today}"

        # 1. Create notebook.
        logger.debug("NotebookLM: creating notebook %r.", notebook_name)
        nb = await client.notebooks.create(notebook_name)
        notebook_id: str = nb.id
        logger.debug("NotebookLM: notebook id=%s.", notebook_id)

        try:
            # 2. Add each paper as a text source.
            for i, paper in enumerate(papers, start=1):
                source_text = _format_source_text(paper)
                source_title = _format_source_title(paper)
                logger.debug(
                    "NotebookLM: adding source %d/%d (%s).",
                    i,
                    len(papers),
                    paper.arxiv_id,
                )
                await client.sources.add_text(
                    notebook_id, source_title, source_text, wait=True
                )

            logger.info(
                "NotebookLM: added %d paper sources; requesting audio overview.",
                len(papers),
            )

            # 3. Generate the audio overview.
            status = await client.artifacts.generate_audio(
                notebook_id,
                instructions=self._instructions,
                audio_format=audio_format,
                audio_length=audio_length,
            )
            task_id: str = status.task_id
            logger.info(
                "NotebookLM: audio generation started (task_id=%s, timeout=%ds).",
                task_id,
                self._timeout,
            )

            # 4. Wait for completion.
            final = await client.artifacts.wait_for_completion(
                notebook_id,
                task_id,
                timeout=self._timeout,
            )

            if not final.is_complete:
                raise TTSError(
                    f"NotebookLM audio generation did not complete "
                    f"(final status: {final.status!r}).  "
                    "Try increasing NOTEBOOKLM_TIMEOUT in config.py."
                )

            logger.info("NotebookLM: audio generation complete; downloading.")

            # 5. Download the audio.
            out_path.parent.mkdir(parents=True, exist_ok=True)
            await client.artifacts.download_audio(notebook_id, str(out_path))

            if not out_path.exists() or out_path.stat().st_size == 0:
                raise TTSError(
                    f"NotebookLM audio download produced no file at {out_path}."
                )

            logger.info(
                "NotebookLM: audio downloaded to %s (%.1f MB).",
                out_path,
                out_path.stat().st_size / 1_000_000,
            )

        finally:
            # 6. Optionally delete the notebook to keep the workspace tidy.
            if self._delete_notebook and notebook_id:
                try:
                    logger.debug(
                        "NotebookLM: deleting notebook %s.", notebook_id
                    )
                    await client.notebooks.delete(notebook_id)
                    logger.info(
                        "NotebookLM: notebook %s deleted.", notebook_id
                    )
                except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
                    logger.warning(
                        "NotebookLM: failed to delete notebook %s: %s",
                        notebook_id,
                        exc,
                    )

        return notebook_id
