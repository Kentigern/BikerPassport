import pytest
from django.core import mail

from passports.emailing import qualifying_bearers, send_campaign, snapshot_recipients
from passports.models import Bearer, EmailCampaign, EmailCampaignRecipient


def make_bearer(**kwargs):
    defaults = {
        'name': 'Test Bearer',
        'phone': f"+4479005{Bearer.objects.count():06d}",
        'mailing_address': '1 Test Street',
        'email': 'bearer@example.com',
    }
    defaults.update(kwargs)
    return Bearer.objects.create(**defaults)


@pytest.mark.django_db
class TestQualifyingBearers:
    def test_only_granted_consent_is_included(self):
        granted = make_bearer(next_season_consent_status='granted')
        make_bearer(next_season_consent_status='pending')
        make_bearer(next_season_consent_status='declined')

        result = list(qualifying_bearers(EmailCampaign.Purpose.NEXT_SEASON))

        assert result == [granted]

    def test_purposes_are_independent(self):
        next_season_only = make_bearer(
            next_season_consent_status='granted', marketing_consent_status='pending'
        )
        marketing_only = make_bearer(
            next_season_consent_status='declined', marketing_consent_status='granted'
        )

        assert list(qualifying_bearers(EmailCampaign.Purpose.NEXT_SEASON)) == [next_season_only]
        assert list(qualifying_bearers(EmailCampaign.Purpose.MARKETING)) == [marketing_only]

    def test_blank_email_excluded_even_if_granted(self):
        make_bearer(next_season_consent_status='granted', email='')

        assert list(qualifying_bearers(EmailCampaign.Purpose.NEXT_SEASON)) == []


@pytest.mark.django_db
class TestSendCampaign:
    def test_sends_to_every_qualifying_bearer_and_updates_counters(self):
        b1 = make_bearer(next_season_consent_status='granted', email='one@example.com')
        b2 = make_bearer(next_season_consent_status='granted', email='two@example.com')
        make_bearer(next_season_consent_status='pending')  # excluded

        campaign = EmailCampaign.objects.create(
            subject='Hello', body_html='<p>Hi there</p>', purpose=EmailCampaign.Purpose.NEXT_SEASON
        )
        snapshot_recipients(campaign)
        assert campaign.recipient_count == 2

        send_campaign(campaign.pk)
        campaign.refresh_from_db()

        assert len(mail.outbox) == 2
        assert {m.to[0] for m in mail.outbox} == {b1.email, b2.email}
        assert campaign.sent_count == 2
        assert campaign.failed_count == 0
        assert campaign.status == EmailCampaign.Status.SENT
        assert campaign.sent_at is not None
        assert set(
            campaign.recipients.values_list('status', flat=True)
        ) == {EmailCampaignRecipient.Status.SENT}

    def test_resuming_skips_already_sent_recipients(self):
        make_bearer(next_season_consent_status='granted', email='one@example.com')
        b2 = make_bearer(next_season_consent_status='granted', email='two@example.com')

        campaign = EmailCampaign.objects.create(
            subject='Hello', body_html='<p>Hi</p>', purpose=EmailCampaign.Purpose.NEXT_SEASON
        )
        snapshot_recipients(campaign)
        campaign.recipients.filter(bearer__email='one@example.com').update(
            status=EmailCampaignRecipient.Status.SENT
        )

        send_campaign(campaign.pk)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [b2.email]

    def test_a_send_failure_is_recorded_and_does_not_block_others(self, monkeypatch):
        make_bearer(next_season_consent_status='granted', email='one@example.com')
        make_bearer(next_season_consent_status='granted', email='two@example.com')

        campaign = EmailCampaign.objects.create(
            subject='Hello', body_html='<p>Hi</p>', purpose=EmailCampaign.Purpose.NEXT_SEASON
        )
        snapshot_recipients(campaign)

        calls = {'n': 0}
        original_send = mail.EmailMultiAlternatives.send

        def flaky_send(self, *args, **kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('SMTP said no')
            return original_send(self, *args, **kwargs)

        monkeypatch.setattr(mail.EmailMultiAlternatives, 'send', flaky_send)

        send_campaign(campaign.pk)
        campaign.refresh_from_db()

        assert campaign.sent_count == 1
        assert campaign.failed_count == 1
        assert campaign.status == EmailCampaign.Status.SENT
        failed = campaign.recipients.get(status=EmailCampaignRecipient.Status.FAILED)
        assert 'SMTP said no' in failed.error_message


@pytest.mark.django_db
class TestUnsubscribeView:
    def test_unsubscribe_flips_matching_consent_only(self, client):
        bearer = make_bearer(next_season_consent_status='granted', marketing_consent_status='granted')

        url = f'/passports/email/unsubscribe/{bearer.consent_token}/next_season/'
        response = client.get(url)

        bearer.refresh_from_db()
        assert response.status_code == 200
        assert bearer.next_season_consent_status == 'declined'
        assert bearer.next_season_consent_responded_at is not None
        assert bearer.marketing_consent_status == 'granted'  # untouched

    def test_unknown_token_is_404_not_500(self, client):
        response = client.get('/passports/email/unsubscribe/00000000-0000-0000-0000-000000000000/marketing/')
        assert response.status_code == 404

    def test_unknown_purpose_is_404_not_500(self, client):
        bearer = make_bearer()
        response = client.get(f'/passports/email/unsubscribe/{bearer.consent_token}/not-a-real-purpose/')
        assert response.status_code == 404
