"""Tests for arxaudio.emailer.send_digest.

SMTP is monkeypatched with a recording fake — no real network connections.
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from arxaudio.emailer import send_digest, _build_subject, _build_body
from arxaudio.settings import Settings


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
# Test subject and body helpers
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


def test_build_body_contains_titles():
    body = _build_body(2, ["Title One", "Title Two"])
    assert "Title One" in body
    assert "Title Two" in body


def test_build_body_contains_count():
    body = _build_body(3, ["T1", "T2", "T3"])
    assert "3" in body


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
            # Copy state into the shared instance for inspection
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
        send_digest(_smtp_settings(587), mp3, 2, ["Paper A", "Paper B"])

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

    # Make sure smtplib.SMTP is NOT called for port 465
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
            send_digest(_smtp_settings(465), mp3, 1, ["Paper A"])

    # SMTP_SSL path: login and sendmail must be called
    assert ssl_instance["login_called"]
    assert ssl_instance["sendmail_called"]
    # STARTTLS must NOT be called on the SSL path
    assert not ssl_instance["starttls_called"]
    # Plain SMTP.__init__ must NOT be called on port 465
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
        send_digest(_smtp_settings(587), mp3, 3, ["T1", "T2", "T3"])

    assert captured_msg, "sendmail was not called"
    msg_text = captured_msg[0].decode("utf-8", errors="replace")
    # The attachment should be base64-encoded content
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

    with patch("arxaudio.emailer.smtplib.SMTP", CapturingSMTP):
        send_digest(_smtp_settings(587), mp3, 5, ["T1", "T2", "T3", "T4", "T5"])

    assert captured_msg
    msg_text = captured_msg[0].decode("utf-8", errors="replace")
    assert "Subject:" in msg_text
    assert "5" in msg_text


def test_message_body_lists_titles(tmp_path):
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

    titles = ["Cosmological Constraints Paper", "Galaxy Clustering Study"]
    with patch("arxaudio.emailer.smtplib.SMTP", CapturingSMTP):
        send_digest(_smtp_settings(587), mp3, 2, titles)

    assert captured_msg

    # The plain-text body is base64-encoded in the MIME message.
    # Decode all base64 chunks from the message and search for titles there.
    import base64
    import re as _re
    raw = captured_msg[0]
    msg_text = raw.decode("utf-8", errors="replace")

    # Extract base64 blocks from the message
    b64_blocks = _re.findall(r"(?:^|\n\n)((?:[A-Za-z0-9+/\n]{60,}\n*={0,2}))", msg_text)
    decoded_bodies = []
    for block in b64_blocks:
        try:
            decoded_bodies.append(base64.b64decode(block.replace("\n", "")).decode("utf-8", errors="replace"))
        except Exception:
            pass

    all_decoded = "\n".join(decoded_bodies)
    assert "Cosmological Constraints Paper" in all_decoded
    assert "Galaxy Clustering Study" in all_decoded


# ---------------------------------------------------------------------------
# Raises cleanly when not configured
# ---------------------------------------------------------------------------

def test_raises_when_not_configured(tmp_path):
    mp3 = tmp_path / "digest.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 100)
    with pytest.raises(RuntimeError, match="SMTP is not configured"):
        send_digest(_no_smtp_settings(), mp3, 1, ["T"])


def test_raises_when_mp3_missing():
    settings = _smtp_settings()
    with pytest.raises(FileNotFoundError):
        send_digest(settings, "/tmp/nonexistent_arxaudio_test.mp3", 1, ["T"])
