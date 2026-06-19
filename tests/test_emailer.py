"""Tests for arxaudio.emailer.send_digest.

SMTP is monkeypatched with a recording fake — no real network connections.
"""
from __future__ import annotations

import base64
import re as _re
import smtplib
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from arxaudio.emailer import (
    send_digest,
    _build_subject,
    _build_body,
    _build_html_body,
)
from arxaudio.models import Paper
from arxaudio.settings import Settings

REPO_URL = "https://github.com/James11222/arxaudio"
ARXIV_URL = "https://arxiv.org"
BENTY_URL = "https://www.benty-fields.com"


# ---------------------------------------------------------------------------
# Settings builder helpers
# ---------------------------------------------------------------------------

def _smtp_settings(port: int = 587) -> Settings:
    return Settings(
        categories=["astro-ph.CO"],
        smtp_host="smtp.example.com",
        smtp_port=port,
        smtp_user="user@example.com",
        smtp_password="secret",
        email_to="recipient@example.com",
        email_from="user@example.com",
        email_subject_prefix="ArXaudio Digest",
    )


def _no_smtp_settings() -> Settings:
    return Settings(categories=["astro-ph.CO"])


# ---------------------------------------------------------------------------
# Sample Paper builders
# ---------------------------------------------------------------------------

def _paper(arxiv_id: str, title: str, authors: list[str]) -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        abstract="An abstract.",
        authors=authors,
        categories=["astro-ph.CO"],
        published="2026-06-10T00:00:00+00:00",
        keep=True,
    )


PAPER_MULTI = _paper("2606.00001", "Multi-Author Paper Title", ["Smith, Alice", "Jones, Bob"])
PAPER_SINGLE = _paper("2606.00002", "Single Author Paper Title", ["Patel, David"])
PAPER_EXTRA1 = _paper("2606.00003", "Extra Paper One", ["Lee, Eve", "Park, Frank"])
PAPER_EXTRA2 = _paper("2606.00004", "Extra Paper Two", ["Kim, Carol"])


# ---------------------------------------------------------------------------
# Fake SMTP connection recorder
# ---------------------------------------------------------------------------

class _RecordedSMTP:
    """Mock SMTP/SMTP_SSL connection that records all calls."""

    def __init__(self, *args, **kwargs):
        self.host = args[0] if args else kwargs.get("host", "")
        self.port = args[1] if len(args) > 1 else kwargs.get("port", 0)
        self.calls: list[str] = []
        self.login_args: tuple | None = None
        self.sendmail_args: tuple | None = None
        self.starttls_called = False
        self.ehlo_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        self.calls.append("ehlo")
        self.ehlo_count += 1

    def starttls(self):
        self.calls.append("starttls")
        self.starttls_called = True

    def login(self, user: str, password: str):
        self.calls.append("login")
        self.login_args = (user, password)

    def sendmail(self, sender: str, recipients: list[str], msg: bytes):
        self.calls.append("sendmail")
        self.sendmail_args = (sender, recipients, msg)


# ---------------------------------------------------------------------------
# Helper: decode all base64 blocks from a raw MIME message
# ---------------------------------------------------------------------------

def _decode_body(raw_bytes: bytes) -> str:
    """Extract and decode base64-encoded MIME parts from the raw message bytes."""
    msg_text = raw_bytes.decode("utf-8", errors="replace")
    b64_blocks = _re.findall(r"(?:^|\n\n)((?:[A-Za-z0-9+/\n]{60,}\n*={0,2}))", msg_text)
    parts = []
    for block in b64_blocks:
        try:
            parts.append(base64.b64decode(block.replace("\n", "")).decode("utf-8", errors="replace"))
        except Exception:
            pass
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Test _build_subject
# ---------------------------------------------------------------------------

def test_build_subject_contains_count():
    subj = _build_subject("ArXaudio Digest", 7)
    assert "7" in subj
    assert "papers" in subj


def test_build_subject_singular():
    subj = _build_subject("ArXaudio Digest", 1)
    assert "1 paper" in subj
    assert "papers" not in subj


def test_build_subject_prefix():
    subj = _build_subject("My Custom Prefix", 3)
    assert subj.startswith("My Custom Prefix")


# Subject count uses len(audio_papers), not total papers
def test_subject_count_uses_audio_papers_only():
    subj = _build_subject("ArXaudio Digest", 3)
    assert "3" in subj
    assert "papers" in subj


# ---------------------------------------------------------------------------
# Test _build_body — two sections present
# ---------------------------------------------------------------------------

def test_build_body_audio_section_present():
    body = _build_body([PAPER_MULTI, PAPER_SINGLE], [PAPER_EXTRA1], REPO_URL)
    assert "In today's audio:" in body
    assert PAPER_MULTI.title in body
    assert PAPER_SINGLE.title in body


def test_build_body_extra_section_present_with_divider():
    body = _build_body([PAPER_MULTI], [PAPER_EXTRA1, PAPER_EXTRA2], REPO_URL)
    assert "More new papers (not in the audio):" in body
    assert PAPER_EXTRA1.title in body
    assert PAPER_EXTRA2.title in body
    # Section headers are underlined with a row of '=' characters
    assert "===" in body


def test_build_body_numbering_continues_across_divider():
    """Extra papers numbered starting after the last audio paper."""
    audio = [PAPER_MULTI, PAPER_SINGLE]   # 1, 2
    extra = [PAPER_EXTRA1, PAPER_EXTRA2]  # should be 3, 4
    body = _build_body(audio, extra, REPO_URL)
    lines = body.splitlines()

    # Find lines containing each title and check the leading number
    def _number_for_title(title: str) -> int:
        for line in lines:
            if title in line:
                m = _re.search(r"(\d+)\.", line)
                if m:
                    return int(m.group(1))
        return -1

    assert _number_for_title(PAPER_MULTI.title) == 1
    assert _number_for_title(PAPER_SINGLE.title) == 2
    assert _number_for_title(PAPER_EXTRA1.title) == 3
    assert _number_for_title(PAPER_EXTRA2.title) == 4


def test_build_body_first_author_and_url_present():
    body = _build_body([PAPER_MULTI], [], REPO_URL)
    assert PAPER_MULTI.first_author in body
    assert PAPER_MULTI.url in body


def test_build_body_et_al_only_for_multi_author():
    body = _build_body([PAPER_MULTI, PAPER_SINGLE], [], REPO_URL)
    # PAPER_MULTI has 2 authors → "et al." expected
    # PAPER_SINGLE has 1 author  → "et al." must NOT appear near that entry
    lines = body.splitlines()

    multi_idx = next(i for i, l in enumerate(lines) if PAPER_MULTI.title in l)
    single_idx = next(i for i, l in enumerate(lines) if PAPER_SINGLE.title in l)

    # Byline is the line right after the title line
    multi_byline = lines[multi_idx + 1]
    single_byline = lines[single_idx + 1]

    assert "et al." in multi_byline
    assert "et al." not in single_byline


def test_build_body_url_format():
    body = _build_body([PAPER_MULTI], [], REPO_URL)
    assert f"https://arxiv.org/abs/{PAPER_MULTI.arxiv_id}" in body


def test_build_body_no_extra_omits_divider_and_second_section():
    body = _build_body([PAPER_MULTI, PAPER_SINGLE], [], REPO_URL)
    assert "More new papers" not in body
    # Should not have a second divider beyond the audio section header line
    assert body.count("---------------------------------------------") == 0


def test_build_body_contains_count():
    body = _build_body([PAPER_MULTI, PAPER_SINGLE], [], REPO_URL)
    assert "2" in body


def test_build_body_footer_present():
    body = _build_body([PAPER_MULTI], [], REPO_URL)
    assert "Happy" in body
    assert "arxaudio" in body


def test_build_body_footer_uses_repo_url():
    body = _build_body([PAPER_MULTI], [], REPO_URL)
    assert REPO_URL in body
    # The old hard-coded owner must be gone.
    assert "jsunseri" not in body


def test_build_body_footer_includes_default_source_link():
    body = _build_body([PAPER_MULTI], [], REPO_URL)
    assert "Papers sourced from arXiv" in body
    assert ARXIV_URL in body


# ---------------------------------------------------------------------------
# Test _build_html_body
# ---------------------------------------------------------------------------

def test_build_html_body_is_html():
    html = _build_html_body([PAPER_MULTI, PAPER_SINGLE], [PAPER_EXTRA1], REPO_URL)
    assert "<html>" in html.lower()
    assert PAPER_MULTI.title in html
    assert PAPER_SINGLE.title in html
    assert PAPER_EXTRA1.title in html


def test_build_html_body_uses_repo_url():
    html = _build_html_body([PAPER_MULTI], [], REPO_URL)
    assert REPO_URL in html
    assert "jsunseri" not in html


def test_build_html_body_includes_default_source_link():
    html = _build_html_body([PAPER_MULTI], [], REPO_URL)
    assert "Papers sourced from" in html
    assert "arXiv" in html
    assert ARXIV_URL in html


def test_build_html_body_links_and_authors():
    html = _build_html_body([PAPER_MULTI], [], REPO_URL)
    assert PAPER_MULTI.url in html
    assert PAPER_MULTI.first_author in html
    assert "et al." in html


def test_build_html_body_escapes_titles():
    nasty = _paper("2606.09999", "Tension in <H0> & the CMB", ["Doe, Jane"])
    html = _build_html_body([nasty], [], REPO_URL)
    assert "<H0>" not in html
    assert "&lt;H0&gt;" in html
    assert "&amp;" in html


# ---------------------------------------------------------------------------
# STARTTLS used on port 587
# ---------------------------------------------------------------------------

def test_starttls_on_port_587(tmp_path):
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 100)

    smtp_instance = _RecordedSMTP()

    class FakeSMTP(_RecordedSMTP):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            smtp_instance.calls = self.calls
            smtp_instance.login_args = None
            smtp_instance.sendmail_args = None
            smtp_instance.starttls_called = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            self.calls.append("ehlo")
            smtp_instance.calls = self.calls

        def starttls(self):
            self.calls.append("starttls")
            smtp_instance.starttls_called = True
            smtp_instance.calls = self.calls

        def login(self, u, p):
            self.calls.append("login")
            smtp_instance.login_args = (u, p)
            smtp_instance.calls = self.calls

        def sendmail(self, s, r, m):
            self.calls.append("sendmail")
            smtp_instance.sendmail_args = (s, r, m)
            smtp_instance.calls = self.calls

    with patch("arxaudio.emailer.smtplib.SMTP", FakeSMTP):
        send_digest(_smtp_settings(587), mp3, [PAPER_MULTI, PAPER_SINGLE], [])

    assert smtp_instance.starttls_called
    assert "login" in smtp_instance.calls
    assert "sendmail" in smtp_instance.calls


# ---------------------------------------------------------------------------
# SMTP_SSL used on port 465
# ---------------------------------------------------------------------------

def test_smtp_ssl_on_port_465(tmp_path):
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 100)

    ssl_instance = {"starttls_called": False, "login_called": False, "sendmail_called": False}

    class FakeSMTP_SSL:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            ssl_instance["login_called"] = True

        def sendmail(self, s, r, m):
            ssl_instance["sendmail_called"] = True

    smtp_called = [False]

    class GuardSMTP:
        def __init__(self, *a, **kw):
            smtp_called[0] = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            ssl_instance["starttls_called"] = True

        def login(self, u, p):
            pass

        def sendmail(self, s, r, m):
            pass

    with patch("arxaudio.emailer.smtplib.SMTP_SSL", FakeSMTP_SSL):
        with patch("arxaudio.emailer.smtplib.SMTP", GuardSMTP):
            send_digest(_smtp_settings(465), mp3, [PAPER_MULTI], [])

    assert ssl_instance["login_called"]
    assert ssl_instance["sendmail_called"]
    assert not ssl_instance["starttls_called"]
    assert not smtp_called[0]


# ---------------------------------------------------------------------------
# Message structure: MP3 attachment, MIME type, subject with paper count
# ---------------------------------------------------------------------------

def test_message_has_mp3_attachment(tmp_path):
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 200)

    captured_msg: list[bytes] = []

    class CapturingSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def sendmail(self, s, r, msg_bytes):
            captured_msg.append(msg_bytes)

    with patch("arxaudio.emailer.smtplib.SMTP", CapturingSMTP):
        send_digest(_smtp_settings(587), mp3, [PAPER_MULTI, PAPER_SINGLE, PAPER_EXTRA1], [])

    assert captured_msg, "sendmail was not called"
    msg_text = captured_msg[0].decode("utf-8", errors="replace")
    assert "Content-Disposition" in msg_text
    assert "attachment" in msg_text
    assert "digest.mp3" in msg_text


def test_message_subject_contains_paper_count(tmp_path):
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 200)

    captured_msg: list[bytes] = []

    class CapturingSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def sendmail(self, s, r, msg_bytes):
            captured_msg.append(msg_bytes)

    audio = [PAPER_MULTI, PAPER_SINGLE, PAPER_EXTRA1, PAPER_EXTRA2, PAPER_MULTI]
    with patch("arxaudio.emailer.smtplib.SMTP", CapturingSMTP):
        send_digest(_smtp_settings(587), mp3, audio, [])

    assert captured_msg
    msg_text = captured_msg[0].decode("utf-8", errors="replace")
    assert "Subject:" in msg_text
    assert "5" in msg_text


def test_subject_count_uses_audio_papers_not_extras(tmp_path):
    """Subject line count must equal len(audio_papers), not total papers."""
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 200)

    captured_msg: list[bytes] = []

    class CapturingSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def sendmail(self, s, r, msg_bytes):
            captured_msg.append(msg_bytes)

    # 2 audio, 2 extra → subject should say "2 papers"
    with patch("arxaudio.emailer.smtplib.SMTP", CapturingSMTP):
        send_digest(_smtp_settings(587), mp3, [PAPER_MULTI, PAPER_SINGLE], [PAPER_EXTRA1, PAPER_EXTRA2])

    assert captured_msg
    msg_text = captured_msg[0].decode("utf-8", errors="replace")
    # Decode the (possibly RFC2047-encoded) subject value for inspection
    from email import message_from_bytes
    from email.header import decode_header
    parsed = message_from_bytes(captured_msg[0])
    subject_parts = decode_header(parsed["Subject"])
    subject_decoded = "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part
        for part, enc in subject_parts
    )
    # Subject should say "2 papers" (the audio count), not "4 papers"
    assert "2 papers" in subject_decoded
    assert "4 papers" not in subject_decoded


def test_message_body_lists_titles_and_authors(tmp_path):
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 200)

    captured_msg: list[bytes] = []

    class CapturingSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def sendmail(self, s, r, msg_bytes):
            captured_msg.append(msg_bytes)

    with patch("arxaudio.emailer.smtplib.SMTP", CapturingSMTP):
        send_digest(_smtp_settings(587), mp3, [PAPER_MULTI, PAPER_SINGLE], [PAPER_EXTRA1])

    assert captured_msg
    all_decoded = _decode_body(captured_msg[0])

    assert PAPER_MULTI.title in all_decoded
    assert PAPER_SINGLE.title in all_decoded
    assert PAPER_EXTRA1.title in all_decoded
    assert PAPER_MULTI.first_author in all_decoded
    assert "et al." in all_decoded   # PAPER_MULTI is multi-author
    assert PAPER_SINGLE.first_author in all_decoded
    assert PAPER_MULTI.url in all_decoded
    assert PAPER_EXTRA1.url in all_decoded


def test_extra_section_absent_when_empty(tmp_path):
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 200)

    captured_msg: list[bytes] = []

    class CapturingSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def sendmail(self, s, r, msg_bytes):
            captured_msg.append(msg_bytes)

    with patch("arxaudio.emailer.smtplib.SMTP", CapturingSMTP):
        send_digest(_smtp_settings(587), mp3, [PAPER_MULTI], [])

    assert captured_msg
    all_decoded = _decode_body(captured_msg[0])
    assert "More new papers" not in all_decoded


def test_send_digest_uses_benty_source_link_when_configured(tmp_path):
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 200)

    captured_msg: list[bytes] = []

    class CapturingSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def sendmail(self, s, r, msg_bytes):
            captured_msg.append(msg_bytes)

    settings = _smtp_settings(587)
    settings.paper_source = "benty"
    settings.benty_base_url = BENTY_URL
    with patch("arxaudio.emailer.smtplib.SMTP", CapturingSMTP):
        send_digest(settings, mp3, [PAPER_MULTI], [])

    assert captured_msg
    all_decoded = _decode_body(captured_msg[0])
    assert "Papers sourced from benty-fields" in all_decoded
    assert BENTY_URL in all_decoded


# ---------------------------------------------------------------------------
# Raises cleanly when not configured
# ---------------------------------------------------------------------------

def test_raises_when_not_configured(tmp_path):
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 100)
    with pytest.raises(RuntimeError, match="SMTP is not configured"):
        send_digest(_no_smtp_settings(), mp3, [PAPER_MULTI], [])


def test_raises_when_mp3_missing():
    settings = _smtp_settings()
    with pytest.raises(FileNotFoundError):
        send_digest(settings, "/tmp/nonexistent_arxaudio_test.mp3", [PAPER_MULTI], [])
