"""Bulk-email audience resolution and sending — kept separate from
views.py, and deliberately free of any threading, so it's a plain
function tests (and, later, a real task queue if the production host
supports one) can call directly. See the plan's Context note: the
*trigger* (currently threading.Thread in views.py) is expected to
change; this module shouldn't need to."""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from .models import Bearer, EmailCampaign, EmailCampaignRecipient

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
