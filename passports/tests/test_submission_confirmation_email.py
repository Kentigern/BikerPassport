import pytest
from django.core.management import call_command
from django.utils import timezone

from passports.emailing import outstanding_confirmations, send_confirmations, send_submission_confirmation
from passports.models import Bearer, PassportSubmission, RaffleTicket

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

    def test_renders_and_persists_ticket_numbers(self, season, venues, monkeypatch):
        bearer = make_bearer()
        submission = PassportSubmission.objects.create(
            season=season, bearer=bearer, intake_number=1, date_received='2026-06-01'
        )
        submission.venues_stamped.set(venues[:20])  # 20 stamps -> 2 tickets

        sent = {}
        monkeypatch.setattr(
            'passports.emailing.resend_client.send_email',
            lambda **kwargs: sent.update(kwargs),
        )

        send_submission_confirmation(submission)

        tickets = list(RaffleTicket.objects.filter(submission=submission).order_by('number'))
        assert len(tickets) == 2
        assert tickets[0].number in sent['html_body']
        assert tickets[1].number in sent['html_body']

    def test_ticket_numbers_stable_across_resend(self, season, venues, monkeypatch):
        bearer = make_bearer()
        submission = PassportSubmission.objects.create(
            season=season, bearer=bearer, intake_number=1, date_received='2026-06-01'
        )
        submission.venues_stamped.set(venues[:20])
        monkeypatch.setattr('passports.emailing.resend_client.send_email', lambda **kwargs: None)

        send_submission_confirmation(submission)
        first_numbers = list(
            RaffleTicket.objects.filter(submission=submission).order_by('number').values_list('number', flat=True)
        )

        send_submission_confirmation(submission)
        second_numbers = list(
            RaffleTicket.objects.filter(submission=submission).order_by('number').values_list('number', flat=True)
        )

        assert first_numbers == second_numbers


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

    def test_exit_without_email_still_issues_ticket_numbers(
        self, client, django_user_model, season, venues, monkeypatch
    ):
        admin = django_user_model.objects.create_superuser(
            username='admin', email='a@example.com', password='x'
        )
        client.force_login(admin)

        resp = client.post(
            '/passports/bearers/save/',
            data={'name': 'No Email', 'phone': '07900111222', 'email': '', 'mailing_address': '1 Test Street'},
        )
        bearer_id = resp.json()['bearer']['id']
        client.post(
            '/passports/submissions/save/',
            data={
                'bearer_id': bearer_id,
                'venues_stamped': [v.pk for v in venues[:10]],
                'date_received': '2026-06-01',
                'notes': '',
                'exit': 'true',
            },
        )

        submission = PassportSubmission.objects.get(bearer_id=bearer_id)
        assert RaffleTicket.objects.filter(submission=submission).count() == 1

    def test_save_without_exit_issues_no_ticket_numbers(
        self, client, django_user_model, season, venues, monkeypatch
    ):
        admin = django_user_model.objects.create_superuser(
            username='admin', email='a@example.com', password='x'
        )
        client.force_login(admin)
        venue_pks = [v.pk for v in venues[:10]]

        resp = client.post(
            '/passports/bearers/save/',
            data={'name': 'Mid Intake', 'phone': '07900111333', 'email': 'b@example.com', 'mailing_address': '1 Test Street'},
        )
        bearer_id = resp.json()['bearer']['id']
        client.post(
            '/passports/submissions/save/',
            data={'bearer_id': bearer_id, 'venues_stamped': venue_pks, 'date_received': '2026-06-01', 'notes': '', 'exit': 'false'},
        )

        assert not RaffleTicket.objects.filter(submission__bearer_id=bearer_id).exists()


def _locked_submission(season, venues, *, email='bearer@example.com', intake_number=1, **fields):
    submission = PassportSubmission.objects.create(
        season=season,
        bearer=make_bearer(email=email),
        intake_number=intake_number,
        date_received='2026-06-01',
        locked_at=timezone.now(),
        **fields,
    )
    submission.venues_stamped.set(venues[:10])
    return submission


class TestRetry:
    @pytest.fixture(autouse=True)
    def _no_throttle(self, monkeypatch):
        monkeypatch.setattr('passports.emailing.BULK_SEND_INTERVAL_SECONDS', 0)

    def test_outstanding_is_locked_with_email_and_not_emailed(self, season, venues):
        failed = _locked_submission(season, venues, intake_number=1, email_send_failed=True)
        _locked_submission(season, venues, intake_number=2, status=PassportSubmission.Status.EMAILED)
        _locked_submission(season, venues, intake_number=3, email='')
        PassportSubmission.objects.create(
            season=season, bearer=make_bearer(), intake_number=4, date_received='2026-06-01'
        )  # never Save & Exited

        assert list(outstanding_confirmations()) == [failed]

    def test_send_confirmations_records_success_and_failure_and_skips(self, season, venues, monkeypatch):
        good = _locked_submission(season, venues, intake_number=1, email_send_failed=True)
        bad = _locked_submission(season, venues, intake_number=2, email='bad@example.com')
        no_email = _locked_submission(season, venues, intake_number=3, email='')

        def fake_send(*, to, **kwargs):
            if to == 'bad@example.com':
                raise RuntimeError('Resend said no')

        monkeypatch.setattr('passports.emailing.resend_client.send_email', fake_send)

        assert send_confirmations([good, bad, no_email]) == (1, 1, 1)

        good.refresh_from_db()
        bad.refresh_from_db()
        assert good.status == PassportSubmission.Status.EMAILED
        assert good.email_send_failed is False
        assert good.email_sent_at is not None
        assert bad.email_send_failed is True
        assert bad.status != PassportSubmission.Status.EMAILED

    def test_admin_action_resends_selected(self, client, django_user_model, season, venues, monkeypatch):
        admin = django_user_model.objects.create_superuser(username='admin', email='a@example.com', password='x')
        client.force_login(admin)
        submission = _locked_submission(season, venues, email_send_failed=True)
        calls = []
        monkeypatch.setattr('passports.emailing.resend_client.send_email', lambda **kwargs: calls.append(kwargs))

        resp = client.post(
            '/admin/passports/passportsubmission/',
            data={'action': 'send_confirmation_emails', '_selected_action': [submission.pk]},
            follow=True,
        )

        assert resp.status_code == 200
        assert len(calls) == 1
        submission.refresh_from_db()
        assert submission.status == PassportSubmission.Status.EMAILED
        assert submission.email_send_failed is False

    def test_admin_action_hidden_from_loggers(self, client, logger_user, season, venues):
        client.force_login(logger_user)
        resp = client.get('/admin/passports/passportsubmission/')
        assert b'send_confirmation_emails' not in resp.content

    def test_command_sends_all_outstanding(self, season, venues, monkeypatch):
        first = _locked_submission(season, venues, intake_number=1, email_send_failed=True)
        second = _locked_submission(season, venues, intake_number=2, email_send_failed=True)
        calls = []
        monkeypatch.setattr('passports.emailing.resend_client.send_email', lambda **kwargs: calls.append(kwargs))

        call_command('retry_confirmation_emails')  # dry run
        assert calls == []

        call_command('retry_confirmation_emails', '--yes')
        assert len(calls) == 2
        for submission in (first, second):
            submission.refresh_from_db()
            assert submission.status == PassportSubmission.Status.EMAILED
