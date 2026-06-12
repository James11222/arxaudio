"""Send the daily arXaudio digest via SMTP.

Uses only stdlib: ``smtplib``, ``email``.  No third-party libraries required.

Credentials are read from the ``Settings`` object, which in turn reads them
from environment variables (``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``,
``SMTP_PASSWORD``).  See ``settings.py`` and the README for setup instructions.

Usage::

    from arxaudio.emailer import send_digest
    from arxaudio.models import Paper
    from arxaudio.settings import load_settings

    settings = load_settings()
    send_digest(
        settings,
        "/tmp/digest.mp3",
        audio_papers=[...],   # papers included in the MP3
        extra_papers=[...],   # next-tier papers listed in email only
    )
"""

from __future__ import annotations

import logging
import mimetypes
import smtplib
from datetime import date
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from arxaudio.models import Paper
from arxaudio.settings import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_digest(
    settings: Settings,
    mp3_path: str | Path,
    audio_papers: list[Paper],
    extra_papers: list[Paper],
) -> None:
    """Send the daily digest email with an MP3 attachment.

    Parameters
    ----------
    settings:
        Fully-loaded ``Settings`` object.  ``settings.smtp_configured`` must
        be True or this function raises immediately.
    mp3_path:
        Path to the MP3 file to attach.
    audio_papers:
        Ranked papers included in the attached MP3 (drives the paper count in
        the subject line and the first section of the body).
    extra_papers:
        Next-tier papers listed in the email body only (no audio).  When empty
        the second section and divider are omitted from the body.

    Raises
    ------
    RuntimeError
        If SMTP credentials are not configured.
    FileNotFoundError
        If ``mp3_path`` does not exist.
    smtplib.SMTPAuthenticationError
        On authentication failure (e.g. wrong password / app password needed).
    smtplib.SMTPException
        On other SMTP errors.
    """
    if not settings.smtp_configured:
        raise RuntimeError(
            "SMTP is not configured.  Set the following environment variables "
            "before running the pipeline:\n"
            "  SMTP_HOST     — e.g. smtp.gmail.com\n"
            "  SMTP_USER     — your email address\n"
            "  SMTP_PASSWORD — your SMTP / app password\n"
            "  SMTP_PORT     — (optional) defaults to 587\n"
            "For Gmail, you must use an App Password (not your account password):\n"
            "  https://support.google.com/accounts/answer/185833"
        )

    mp3_path = Path(mp3_path)
    if not mp3_path.exists():
        raise FileNotFoundError(f"MP3 file not found: {mp3_path}")

    recipient = settings.effective_email_to
    sender = settings.effective_email_from

    n_audio = len(audio_papers)
    subject = _build_subject(settings.email_subject_prefix, n_audio)
    body = _build_body(audio_papers, extra_papers)
    msg = _build_message(sender, recipient, subject, body, mp3_path)

    _send(settings, msg, sender, recipient)
    logger.info(
        "Digest sent to %s (subject: %r, attachment: %s, audio papers: %d, extra papers: %d).",
        recipient,
        subject,
        mp3_path.name,
        n_audio,
        len(extra_papers),
    )


# ---------------------------------------------------------------------------
# Message construction helpers
# ---------------------------------------------------------------------------

def _build_subject(prefix: str, n_papers: int) -> str:
    """Return the email subject line."""
    today = date.today().isoformat()
    plural = "paper" if n_papers == 1 else "papers"
    return f"{prefix} — {today} ({n_papers} {plural})"


def _paper_byline(paper: Paper) -> str:
    """Return 'First Author et al. — <url>' or 'First Author — <url>'."""
    author = paper.first_author
    if len(paper.authors) > 1:
        author += " et al."
    return f"  {author} — {paper.url}"


def _build_body(audio_papers: list[Paper], extra_papers: list[Paper]) -> str:
    """Return the plain-text email body."""
    today = date.today().strftime("%A, %B %-d %Y")
    n_audio = len(audio_papers)
    lines: list[str] = [
        f"Your ArXaudio digest for {today}",
        f"{n_audio} paper{'s' if n_audio != 1 else ''} included in today's audio.",
        "",
        "In today's audio:",
        "------------------",
    ]
    for i, paper in enumerate(audio_papers, start=1):
        lines.append(f"  {i:2d}. {paper.title}")
        lines.append(_paper_byline(paper))

    if extra_papers:
        lines += [
            "",
            "---------------------------------------------",
            "More new papers (not in the audio):",
            "---------------------------------------------",
        ]
        for i, paper in enumerate(extra_papers, start=n_audio + 1):
            lines.append(f"  {i:2d}. {paper.title}")
            lines.append(_paper_byline(paper))

    lines += [
        "",
        "The MP3 file is attached.  Happy* listening!",
        "",
        "--",
        "Sent by arxaudio  <https://github.com/jsunseri/arxaudio>",
        "*: Not happy listening? Open an issue on Github!",
    ]
    return "\n".join(lines)


def _build_message(
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    mp3_path: Path,
) -> MIMEMultipart:
    """Assemble a MIME multipart message with a plain-text body and MP3 attachment."""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject

    # Plain-text body
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # MP3 attachment
    mime_type, _ = mimetypes.guess_type(str(mp3_path))
    if mime_type is None:
        mime_type = "audio/mpeg"
    main_type, sub_type = mime_type.split("/", 1)

    with mp3_path.open("rb") as fh:
        attachment = MIMEBase(main_type, sub_type)
        attachment.set_payload(fh.read())

    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=mp3_path.name,
    )
    msg.attach(attachment)

    return msg


# ---------------------------------------------------------------------------
# SMTP transport
# ---------------------------------------------------------------------------

def _send(
    settings: Settings,
    msg: MIMEMultipart,
    sender: str,
    recipient: str,
) -> None:
    """Connect to the SMTP server and deliver the message.

    Uses SMTP_SSL when ``settings.smtp_port == 465``; otherwise uses STARTTLS.
    """
    host = settings.smtp_host
    port = settings.smtp_port
    user = settings.smtp_user
    password = settings.smtp_password

    try:
        if port == 465:
            logger.debug("Connecting via SMTP_SSL to %s:%d", host, port)
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.sendmail(sender, [recipient], msg.as_bytes())
        else:
            logger.debug("Connecting via STARTTLS to %s:%d", host, port)
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(user, password)
                smtp.sendmail(sender, [recipient], msg.as_bytes())

    except smtplib.SMTPAuthenticationError as exc:
        raise smtplib.SMTPAuthenticationError(
            exc.smtp_code,
            (
                f"SMTP authentication failed for user {user!r} on {host}:{port}.\n"
                "Common fixes:\n"
                "  • Gmail: use an App Password, not your account password.\n"
                "    https://support.google.com/accounts/answer/185833\n"
                "  • Outlook/Hotmail: enable SMTP AUTH in account settings.\n"
                "  • Other providers: check that SMTP access is enabled.\n"
                f"Original error: {exc.smtp_error!r}"
            ),
        ) from exc
    except smtplib.SMTPConnectError as exc:
        raise smtplib.SMTPConnectError(
            exc.smtp_code,
            (
                f"Could not connect to SMTP server {host}:{port}.\n"
                "Check that SMTP_HOST and SMTP_PORT are correct, and that the\n"
                "server is reachable from this machine / GitHub Actions runner.\n"
                f"Original error: {exc.smtp_error!r}"
            ),
        ) from exc
    except smtplib.SMTPException as exc:
        raise smtplib.SMTPException(
            f"SMTP error while sending to {recipient!r} via {host}:{port}: {exc}"
        ) from exc
    except OSError as exc:
        raise OSError(
            f"Network error connecting to {host}:{port}: {exc}"
        ) from exc
