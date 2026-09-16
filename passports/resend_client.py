"""Thin wrapper around Resend's HTTP email API (resend.com) — the first
real email-sending provider this app calls; see emailing.py for what's
built on top of it. Falls back to logging instead of calling the API when
RESEND_API_KEY isn't set (dev/test), mirroring EMAIL_BACKEND's console
fallback for the older SMTP-based bulk-email path (still used by
send_campaign, unaffected by this module)."""

import logging

import resend
from django.conf import settings

logger = logging.getLogger(__name__)


def send_email(*, to, subject, html_body, text_body):
    """Sends one email via Resend. Raises on failure — callers are
    responsible for catching that and recording it (see
    PassportSubmission.email_send_failed)."""
    if not settings.RESEND_API_KEY:
        logger.info('RESEND_API_KEY not set — logging email instead of sending.\nTo: %s\nSubject: %s\n\n%s', to, subject, text_body)
        return

    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send(
        {
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [to],
            'subject': subject,
            'html': html_body,
            'text': text_body,
        }
    )
