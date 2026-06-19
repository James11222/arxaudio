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

import html
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
    source_name, source_url = _paper_source_details(settings)
    subject = _build_subject(settings.email_subject_prefix, n_audio)
    text_body = _build_body(
        audio_papers, extra_papers, settings.repo_url, source_name, source_url
    )
    html_body = _build_html_body(
        audio_papers, extra_papers, settings.repo_url, source_name, source_url
    )
    msg = _build_message(sender, recipient, subject, text_body, html_body, mp3_path)

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


def _author_line(paper: Paper) -> str:
    """Return 'First Author et al.' or 'First Author' for display."""
    author = paper.first_author
    if len(paper.authors) > 1:
        author += " et al."
    return author


def _paper_source_details(settings: Settings) -> tuple[str, str]:
    """Return a display label + URL for the configured paper source."""
    if settings.paper_source == "benty":
        return "benty-fields", settings.benty_base_url
    return "arXiv", "https://arxiv.org"


def _build_body(
    audio_papers: list[Paper],
    extra_papers: list[Paper],
    repo_url: str,
    source_name: str = "arXiv",
    source_url: str = "https://arxiv.org",
) -> str:
    """Return the plain-text email body (fallback for non-HTML clients)."""
    today = date.today().strftime("%A, %B %-d %Y")
    n_audio = len(audio_papers)
    lines: list[str] = [
        f"Your ArXaudio digest for {today}",
        f"{n_audio} paper{'s' if n_audio != 1 else ''} included in today's audio.",
        "",
        "In today's audio:",
        "==================",
        "",
    ]
    for i, paper in enumerate(audio_papers, start=1):
        lines += [
            f"{i:2d}. {paper.title}",
            f"    {_author_line(paper)}",
            f"    {paper.url}",
            "",
        ]

    if extra_papers:
        lines += [
            "",
            "More new papers (not in the audio):",
            "===================================",
            "",
        ]
        for i, paper in enumerate(extra_papers, start=n_audio + 1):
            lines += [
                f"{i:2d}. {paper.title}",
                f"    {_author_line(paper)}",
                f"    {paper.url}",
                "",
            ]

    lines += [
        "",
        "The MP3 file is attached.  Happy* listening!",
        "",
        "--",
        f"Papers sourced from {source_name}: <{source_url}>",
        f"Sent by arxaudio  <{repo_url}>",
        "*: Not happy listening? Open an issue on GitHub!",
    ]
    return "\n".join(lines)


def _html_paper_item(index: int, paper: Paper) -> str:
    """Return one styled HTML list entry for a paper."""
    title = html.escape(paper.title)
    author = html.escape(_author_line(paper))
    url = html.escape(paper.url, quote=True)
    return (
        '<tr><td style="padding:0 0 22px 0;">'
        f'<div style="font-size:12px;color:#9aa0a6;font-weight:600;'
        f'letter-spacing:.04em;">{index}</div>'
        f'<a href="{url}" style="font-size:16px;line-height:1.4;'
        f'font-weight:600;color:#1a73e8;text-decoration:none;">{title}</a>'
        f'<div style="font-size:13px;color:#5f6368;margin-top:4px;">{author}</div>'
        f'<a href="{url}" style="font-size:12px;color:#9aa0a6;'
        f'text-decoration:none;">{url}</a>'
        "</td></tr>"
    )


def _build_html_body(
    audio_papers: list[Paper],
    extra_papers: list[Paper],
    repo_url: str,
    source_name: str = "arXiv",
    source_url: str = "https://arxiv.org",
) -> str:
    """Return the HTML email body."""
    today = date.today().strftime("%A, %B %-d, %Y")
    n_audio = len(audio_papers)
    repo = html.escape(repo_url, quote=True)
    source = html.escape(source_url, quote=True)
    source_name_escaped = html.escape(source_name)

    def section(heading: str, papers: list[Paper], start: int) -> str:
        rows = "".join(
            _html_paper_item(i, p) for i, p in enumerate(papers, start=start)
        )
        return (
            f'<h2 style="font-size:13px;text-transform:uppercase;'
            f'letter-spacing:.08em;color:#5f6368;font-weight:700;'
            f'margin:32px 0 18px 0;padding-bottom:8px;'
            f'border-bottom:1px solid #ececec;">{html.escape(heading)}</h2>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'width="100%" style="border-collapse:collapse;">{rows}</table>'
        )

    body_sections = section("In today's audio", audio_papers, 1)
    if extra_papers:
        body_sections += section(
            "More new papers (not in the audio)", extra_papers, n_audio + 1
        )

    plural = "paper" if n_audio == 1 else "papers"
    return f"""\
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f4f5f7;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#f4f5f7;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#ffffff;
                    border-radius:12px;overflow:hidden;
                    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
                    Roboto,Helvetica,Arial,sans-serif;
                    box-shadow:0 1px 3px rgba(0,0,0,0.08);">
        <tr><td style="background:#1a1a2e;padding:28px 32px;">
          <div style="font-size:22px;font-weight:700;color:#ffffff;">
            🎧 ArXaudio Digest</div>
          <div style="font-size:14px;color:#b8b8d0;margin-top:6px;">{today}</div>
        </td></tr>
        <tr><td style="padding:24px 32px 8px 32px;">
          <p style="font-size:15px;color:#3c4043;margin:0;">
            <strong>{n_audio}</strong> {plural} included in today's audio.
            The MP3 is attached — happy listening!
          </p>
          {body_sections}
        </td></tr>
        <tr><td style="padding:20px 32px 28px 32px;border-top:1px solid #ececec;">
          <p style="font-size:12px;color:#9aa0a6;margin:0;line-height:1.6;">
            Papers sourced from
            <a href="{source}" style="color:#1a73e8;
            text-decoration:none;">{source_name_escaped}</a>.<br>
            Sent by <a href="{repo}" style="color:#1a73e8;
            text-decoration:none;">arxaudio</a>.<br>
            Not happy listening?
            <a href="{repo}/issues" style="color:#1a73e8;
            text-decoration:none;">Open an issue on GitHub</a>.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_message(
    sender: str,
    recipient: str,
    subject: str,
    text_body: str,
    html_body: str,
    mp3_path: Path,
) -> MIMEMultipart:
    """Assemble a MIME message: plain-text + HTML alternatives and an MP3 attachment."""
    msg = MIMEMultipart("mixed")
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject

    # Body: plain-text fallback first, then HTML (clients pick the richest they
    # can render). Wrapped in multipart/alternative alongside the attachment.
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(text_body, "plain", "utf-8"))
    alternative.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alternative)

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
