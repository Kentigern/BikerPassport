import pytest

from passports.emailing import send_submission_confirmation
from passports.models import Bearer, PassportSubmission

pytestmark = pytest.mark.django_db


def make_bearer(**kwargs):
    defaults = {
        'name': 'Test Bearer',
        'phone': f"+4479005{Bearer.objects.count():06d}",
        'mailing_address': '1 Test Street',
        'email': 'bearer@example.com',
    }
    defaults.update(kwargs)
    return Bearer.objects.create(**defaults)


class TestSendSubmissionConfirmation:
    def test_renders_stamps_venues_and_tickets(self, season, venues, monkeypatch):
        bearer = make_bearer()
        submission = PassportSubmission.objects.create(
            season=season, bearer=bearer, intake_number=1, date_received='2026-06-01'
        )
        submission.venues_stamped.set(venues[:2])

        sent = {}

        def fake_send_email(*, to, subject, html_body, text_body):
            sent.update(to=to, subject=subject, html_body=html_body, text_body=text_body)

        monkeypatch.setattr('passports.emailing.resend_client.send_email', fake_send_email)

        send_submission_confirmation(submission)

        assert sent['to'] == bearer.email
        assert venues[0].name in sent['html_body']
        assert venues[1].name in sent['html_body']
        assert '2' in sent['html_body']  # stamp count


class TestSubmissionSaveExitTriggersEmail:
    def _save_bearer_and_submission(self, client, season, venue, *, exit='true', email='bearer@example.com'):
        resp = client.post(
            '/passports/bearers/save/',
            data={
                'name': 'Returning Bearer',
                'phone': f"07900{Bearer.objects.count():06d}",
                'email': email,
                'mailing_address': '1 Test Street',
            },
        )
        bearer_id = resp.json()['bearer']['id']

        return client.post(
            '/passports/submissions/save/',
            data={
                'bearer_id': bearer_id,
                'venues_stamped': [venue.pk],
                'date_received': '2026-06-01',
                'notes': '',
                'exit': exit,
            },
        ), bearer_id

    def test_exit_with_email_on_file_sends_and_marks_emailed(
        self, client, django_user_model, season, venues, monkeypatch
    ):
        admin = django_user_model.objects.create_superuser(
            username='admin', email='a@example.com', password='x'
        )
        client.force_login(admin)

        calls = []
        monkeypatch.setattr(
            'passports.emailing.resend_client.send_email',
            lambda **kwargs: calls.append(kwargs),
        )

        resp, bearer_id = self._save_bearer_and_submission(client, season, venues[0])
        assert resp.status_code == 200
        assert len(calls) == 1
        assert calls[0]['to'] == 'bearer@example.com'

        submission = PassportSubmission.objects.get(bearer_id=bearer_id)
        assert submission.status == PassportSubmission.Status.EMAILED
        assert submission.email_sent_at is not None
        assert submission.email_send_failed is False

    def test_exit_without_email_on_file_skips_sending(
        self, client, django_user_model, season, venues, monkeypatch
    ):
        admin = django_user_model.objects.create_superuser(
            username='admin', email='a@example.com', password='x'
        )
        client.force_login(admin)

        calls = []
        monkeypatch.setattr(
            'passports.emailing.resend_client.send_email',
            lambda **kwargs: calls.append(kwargs),
        )

        resp, bearer_id = self._save_bearer_and_submission(client, season, venues[0], email='')
        assert resp.status_code == 200
        assert calls == []

        submission = PassportSubmission.objects.get(bearer_id=bearer_id)
        assert submission.status == PassportSubmission.Status.ENTERED
        assert submission.email_sent_at is None

    def test_send_failure_is_recorded_and_does_not_fail_the_save(
        self, client, django_user_model, season, venues, monkeypatch
    ):
        admin = django_user_model.objects.create_superuser(
            username='admin', email='a@example.com', password='x'
        )
        client.force_login(admin)

        def boom(**kwargs):
            raise RuntimeError('Resend said no')

        monkeypatch.setattr('passports.emailing.resend_client.send_email', boom)

        resp, bearer_id = self._save_bearer_and_submission(client, season, venues[0])
        assert resp.status_code == 200
        assert resp.json()['ok'] is True

        submission = PassportSubmission.objects.get(bearer_id=bearer_id)
        assert submission.status == PassportSubmission.Status.ENTERED
        assert submission.email_send_failed is True
        assert submission.email_sent_at is None
