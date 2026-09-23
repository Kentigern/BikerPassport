"""Bulk-email audience resolution and sending — kept separate from
views.py, and deliberately free of any threading, so it's a plain
function tests (and, later, a real task queue if the production host
supports one) can call directly. See the plan's Context note: the
*trigger* (currently threading.Thread in views.py) is expected to
change; this module shouldn't need to."""

import logging
import time

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from . import resend_client
from .models import Bearer, EmailCampaign, EmailCampaignRecipient, PassportSubmission, RaffleTicket

logger = logging.getLogger(__name__)

# Pause between sends in a bulk retry (send_confirmations) — Resend's
# default API rate limit is a couple of requests per second per team,
# and 429s would just turn straight back into email_send_failed.
BULK_SEND_INTERVAL_SECONDS = 0.6

PURPOSE_CONSENT_FIELD = {
    EmailCampaign.Purpose.NEXT_SEASON: 'next_season_consent_status',
    EmailCampaign.Purpose.MARKETING: 'marketing_consent_status',
}


def qualifying_bearers(purpose):
    """Every bearer eligible for a campaign with this purpose: consent
    granted for that specific purpose, and an email address on file.
    Single source of truth — used for both the compose page's live
    count and the actual send snapshot, so they can never disagree."""
    field = PURPOSE_CONSENT_FIELD[purpose]
    return Bearer.objects.filter(**{field: 'granted'}).exclude(email='')


def snapshot_recipients(campaign):
    """Locks in campaign's audience as of right now. Safe to call only
    once per campaign (the caller is responsible for that) — recipients
    already exist once status has moved past draft."""
    bearers = qualifying_bearers(campaign.purpose)
    EmailCampaignRecipient.objects.bulk_create(
        [EmailCampaignRecipient(campaign=campaign, bearer=bearer) for bearer in bearers],
        ignore_conflicts=True,
    )
    campaign.recipient_count = bearers.count()
    campaign.save(update_fields=['recipient_count'])


def build_unsubscribe_url(bearer, purpose):
    """Absolute, no-login unsubscribe link for one bearer/purpose — built
    from PUBLIC_BASE_URL rather than a request, so send_campaign (which
    has no request) and the preview view render the identical link."""
    path = reverse('email_unsubscribe', kwargs={'token': bearer.consent_token, 'purpose': purpose})
    return f"{settings.PUBLIC_BASE_URL}{path}"


def send_submission_confirmation(submission):
    """The confirmation email (§5.3) — sent via Resend the first time a
    submission is saved & exited (see submission_save_view), and again on
    a staff retry (send_confirmations). Just the stamps/venues/tickets
    receipt — transactional, covering only data needed to run the raffle,
    so no consent request: that goes out later as the first bulk email
    (§5.3/§5.6). Only sends: use send_and_record_confirmation to also
    record the outcome."""
    bearer = submission.bearer
    tickets = RaffleTicket.objects.ensure_for_submission(submission)
    html_body = render_to_string(
        'passports/submission_confirmation_email.html',
        {
            'submission': submission,
            'venues': submission.venues_stamped.order_by('number'),
            'stamp_count': submission.stamp_count,
            'raffle_tickets': submission.raffle_tickets,
            'ticket_numbers': [ticket.number for ticket in tickets],
        },
    )
    resend_client.send_email(
        to=bearer.email,
        subject='Your Bike + Brew passport has been processed',
        html_body=html_body,
        text_body=strip_tags(html_body),
    )


def send_and_record_confirmation(submission):
    """Sends the confirmation email and records the outcome on the
    submission — emailed + email_sent_at on success, email_send_failed on
    any error (a bad address/API error must never propagate: it would
    block a Save & Exit, or kill a bulk retry halfway). Caller checks the
    bearer has an email first. Returns None on success, else the error
    message (e.g. Resend's reason) so staff-facing callers can show why."""
    try:
        send_submission_confirmation(submission)
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.exception('Confirmation email failed for submission %s', submission.pk)
        submission.email_send_failed = True
        submission.save(update_fields=['email_send_failed'])
        return str(exc) or type(exc).__name__
    submission.status = PassportSubmission.Status.EMAILED
    submission.email_sent_at = timezone.now()
    submission.email_send_failed = False
    submission.save(update_fields=['status', 'email_sent_at', 'email_send_failed'])
    return None


def outstanding_confirmations():
    """Submissions still owed a confirmation email: locked (so the email
    would have fired), bearer has an email, but not successfully emailed —
    covers both failed sends and an email address added after the fact."""
    return (
        PassportSubmission.objects.exclude(locked_at=None)
        .exclude(bearer__email='')
        .exclude(status=PassportSubmission.Status.EMAILED)
        .select_related('bearer')
    )


def send_confirmations(submissions):
    """Staff retry path (admin action / retry_confirmation_emails command)
    — sends to each submission in turn, throttled to stay under Resend's
    rate limit. Skips any not yet locked (still mid-intake) or without an
    email. Returns (sent, failures, skipped): failures is a list of
    (submission, error message) pairs."""
    sent = skipped = 0
    failures = []
    for submission in submissions:
        if submission.locked_at is None or not submission.bearer.email:
            skipped += 1
            continue
        if sent + len(failures) and BULK_SEND_INTERVAL_SECONDS:
            time.sleep(BULK_SEND_INTERVAL_SECONDS)
        error = send_and_record_confirmation(submission)
        if error is None:
            sent += 1
        else:
            failures.append((submission, error))
    return sent, failures, skipped


def send_campaign(campaign_id):
    """Processes every still-`pending` recipient for this campaign.
    Plain, synchronous, no threading — call it directly in tests, from a
    management command, or wrap it in threading.Thread/a task queue.
    Safe to re-run: already-`sent` rows are never revisited."""
    campaign = EmailCampaign.objects.get(pk=campaign_id)
    pending = campaign.recipients.filter(status=EmailCampaignRecipient.Status.PENDING).select_related('bearer')

    for recipient in pending.iterator():
        bearer = recipient.bearer
        try:
            html_body = render_to_string(
                'passports/email_frame.html',
                {
                    'body_html': campaign.body_html,
                    'unsubscribe_url': build_unsubscribe_url(bearer, campaign.purpose),
                },
            )
            message = EmailMultiAlternatives(
                subject=campaign.subject,
                body=strip_tags(html_body),
                to=[bearer.email],
            )
            message.attach_alternative(html_body, 'text/html')
            message.send()
        except Exception as exc:  # noqa: BLE001 — one bad address must not kill the batch
            recipient.status = EmailCampaignRecipient.Status.FAILED
            recipient.error_message = str(exc)
            campaign.failed_count += 1
        else:
            recipient.status = EmailCampaignRecipient.Status.SENT
            recipient.sent_at = timezone.now()
            campaign.sent_count += 1

        recipient.save(update_fields=['status', 'error_message', 'sent_at'])
        campaign.save(update_fields=['sent_count', 'failed_count'])

    if not campaign.recipients.filter(status=EmailCampaignRecipient.Status.PENDING).exists():
        campaign.status = EmailCampaign.Status.SENT
        campaign.sent_at = timezone.now()
        campaign.save(update_fields=['status', 'sent_at'])
