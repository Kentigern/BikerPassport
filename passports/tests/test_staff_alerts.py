import pytest
from django.core.cache import cache

from passports.models import PassportSubmission, PublicMessage

pytestmark = pytest.mark.django_db


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr('passports.emailing.resend_client.send_email', lambda **kwargs: calls.append(kwargs))
    return calls


class TestNotesAlert:
    @pytest.fixture(autouse=True)
    def _alert_list(self, settings):
        settings.NOTES_ALERT_EMAILS = ['ops@example.com', 'lead@example.com']

    def _save(self, client, django_user_model, venues, *, notes, exit='true', email=''):
        admin = django_user_model.objects.create_superuser(username='admin', email='a@example.com', password='x')
        client.force_login(admin)
        bearer_id = client.post(
            '/passports/bearers/save/',
            data={'name': 'Noted Bearer', 'phone': '07900123456', 'email': email, 'mailing_address': '1 Test Street'},
        ).json()['bearer']['id']
        resp = client.post(
            '/passports/submissions/save/',
            data={'bearer_id': bearer_id, 'venues_stamped': [v.pk for v in venues[:10]], 'date_received': '2026-06-01', 'notes': notes, 'exit': exit},
        )
        assert resp.status_code == 200
        return PassportSubmission.objects.get(bearer_id=bearer_id)

    def test_exit_with_notes_alerts_staff_with_context(self, client, django_user_model, season, venues, sent):
        submission = self._save(client, django_user_model, venues, notes='Stamp 14 is smudged — maybe 41?')

        assert len(sent) == 1
        alert = sent[0]
        assert alert['to'] == ['ops@example.com', 'lead@example.com']
        assert f'intake #{submission.intake_number}' in alert['subject']
        for expected in ('Stamp 14 is smudged', 'Noted Bearer', '10 stamps, 1 raffle tickets', 'admin', f'/admin/passports/passportsubmission/{submission.pk}/change/'):
            assert expected in alert['html_body'], expected
        assert 'Stamp 14 is smudged' in alert['text_body']

    def test_no_alert_without_notes_or_before_exit(self, client, django_user_model, season, venues, sent):
        self._save(client, django_user_model, venues, notes='   ')
        assert sent == []

    def test_no_alert_on_save_without_exit(self, client, django_user_model, season, venues, sent):
        self._save(client, django_user_model, venues, notes='Half done', exit='false')
        assert sent == []

    def test_no_alert_when_list_empty(self, client, django_user_model, season, venues, sent, settings):
        settings.NOTES_ALERT_EMAILS = []
        self._save(client, django_user_model, venues, notes='Anything')
        assert sent == []

    def test_alert_failure_does_not_break_save_or_confirmation(self, client, django_user_model, season, venues, monkeypatch):
        calls = []

        def fake_send(**kwargs):
            if isinstance(kwargs['to'], list):
                raise RuntimeError('alert provider down')
            calls.append(kwargs)

        monkeypatch.setattr('passports.emailing.resend_client.send_email', fake_send)
        submission = self._save(client, django_user_model, venues, notes='Note', email='bearer@example.com')

        assert len(calls) == 1  # the bearer's confirmation still went out
        assert submission.status == PassportSubmission.Status.EMAILED
        assert submission.locked_at is not None


class TestPublicMessage:
    @pytest.fixture(autouse=True)
    def _enabled(self, settings, monkeypatch):
        settings.PUBLIC_MESSAGES_ENABLED = True
        settings.PUBLIC_MESSAGE_ALERT_EMAILS = ['ops@example.com']
        monkeypatch.setattr('passports.public_views.MIN_FILL_SECONDS', 0)
        cache.clear()

    def _post(self, client, **overrides):
        page = client.get('/message/')
        started = page.context['started']
        data = {'name': 'Pat', 'reply_to': 'pat@example.com', 'message': 'When is the raffle?', 'website': '', 'started': started}
        data.update(overrides)
        return client.post('/message/', data=data)

    def test_disabled_by_default_is_404(self, client, settings):
        settings.PUBLIC_MESSAGES_ENABLED = False
        assert client.get('/message/').status_code == 404

    def test_anonymous_message_is_stored_and_emailed(self, client, sent):
        resp = self._post(client)

        assert resp.status_code == 302 and resp['Location'].endswith('?sent=1')
        message = PublicMessage.objects.get()
        assert (message.name, message.reply_to, message.message) == ('Pat', 'pat@example.com', 'When is the raffle?')
        assert message.alert_sent is True
        assert sent[0]['to'] == ['ops@example.com']
        assert 'When is the raffle?' in sent[0]['text_body']
        assert client.get(resp['Location']).status_code == 200

    def test_message_is_text_only(self, client, sent):
        self._post(client, message='<script>alert(1)</script> hi')
        assert '<script>' not in sent[0]['html_body']
        assert '&lt;script&gt;' in sent[0]['html_body']

    def test_name_cannot_inject_subject_lines(self, client, sent):
        self._post(client, name='Pat\r\nBcc: evil@example.com')
        assert '\n' not in sent[0]['subject'] and '\r' not in sent[0]['subject']

    def test_honeypot_is_silently_dropped(self, client, sent):
        resp = self._post(client, website='http://spam.example')
        assert resp.status_code == 302
        assert not PublicMessage.objects.exists() and sent == []

    def test_too_fast_or_forged_timestamp_is_dropped(self, client, sent, monkeypatch):
        monkeypatch.setattr('passports.public_views.MIN_FILL_SECONDS', 60)
        self._post(client)
        self._post(client, started='forged')
        assert not PublicMessage.objects.exists() and sent == []

    def test_rate_limited_per_sender(self, client, sent):
        for _ in range(5):
            self._post(client)
        resp = self._post(client)
        assert resp.status_code == 200
        assert b'try again in an hour' in resp.content
        assert PublicMessage.objects.count() == 5

    def test_login_page_links_to_it_only_when_enabled(self, client, settings):
        assert b'Contact the organisers' in client.get('/admin/login/').content
        settings.PUBLIC_MESSAGES_ENABLED = False
        assert b'Contact the organisers' not in client.get('/admin/login/').content
