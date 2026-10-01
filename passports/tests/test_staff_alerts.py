import pytest
from django.core.cache import cache
from django.utils import timezone

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
    """The public /message/ page: an ambassador's venue report."""

    NOTES = "Owner's away till Friday.\nKit left at the bar - see Sam!"

    @pytest.fixture(autouse=True)
    def _enabled(self, settings, monkeypatch, venues):
        settings.PUBLIC_MESSAGES_ENABLED = True
        settings.PUBLIC_MESSAGE_ALERT_EMAILS = ['ops@example.com']
        monkeypatch.setattr('passports.public_views.MIN_FILL_SECONDS', 0)
        cache.clear()

    def _post(self, client, **overrides):
        page = client.get('/message/')
        started = page.context['started']
        data = {
            'name': 'Pat Jones', 'ambassador_number': '17', 'venue_name': 'The Old Mill', 'venue_number': '5',
            'unused_passports': 'on', 'passports_collected': '12', 'stamp': 'on',
            'message': self.NOTES, 'reply_to': 'pat@example.com', 'website': '', 'started': started,
        }
        data.update(overrides)
        # None = leave the field out entirely (an unticked checkbox).
        return client.post('/message/', data={k: v for k, v in data.items() if v is not None})

    def test_disabled_by_default_is_404(self, client, settings):
        settings.PUBLIC_MESSAGES_ENABLED = False
        assert client.get('/message/').status_code == 404

    def test_report_is_stored_and_emailed(self, client, sent):
        resp = self._post(client)

        assert resp.status_code == 302 and resp['Location'].endswith('?sent=1')
        report = PublicMessage.objects.get()
        assert (report.name, report.ambassador_number, report.venue_name, report.venue_number) == (
            'Pat Jones', 17, 'The Old Mill', 5,
        )
        assert (report.unused_passports, report.passports_collected, report.stamp, report.inkpad) == (True, 12, True, False)
        assert report.message == self.NOTES
        assert report.report_date == timezone.localdate()
        assert report.alert_sent is True
        assert sent[0]['to'] == ['ops@example.com']
        assert sent[0]['subject'] == 'Ambassador report: venue 5 The Old Mill'
        body = sent[0]['text_body']
        for expected in ('Pat Jones (no. 17)', 'The Old Mill (no. 5)', 'Unused passports (12), 1 stamp', 'see Sam!'):
            assert expected in body, expected
        assert client.get(resp['Location']).status_code == 200

    def test_page_shows_todays_date_and_it_cannot_be_set(self, client, sent):
        page = client.get('/message/')
        assert timezone.localdate().strftime('%B %Y').encode() in page.content
        self._post(client, report_date='2020-01-01')
        assert PublicMessage.objects.get().report_date == timezone.localdate()

    @pytest.mark.parametrize('field', ['name', 'ambassador_number', 'venue_name', 'venue_number'])
    def test_names_and_numbers_are_required(self, client, sent, field):
        resp = self._post(client, **{field: ''})
        assert resp.status_code == 200 and field in resp.context['form'].errors
        assert not PublicMessage.objects.exists() and sent == []

    def test_checkboxes_notes_and_contact_are_optional(self, client, sent):
        resp = self._post(client, unused_passports=None, passports_collected='', stamp=None, message='', reply_to='')
        assert resp.status_code == 302
        report = PublicMessage.objects.get()
        assert report.collected_summary() == 'Nothing' and report.message == ''
        assert '(none)' in sent[0]['text_body']

    @pytest.mark.parametrize('stamp, second_stamp, expected', [
        ('on', 'on', 'Unused passports (12), 2 stamps'),
        (None, 'on', 'Unused passports (12), 1 stamp'),
        (None, None, 'Unused passports (12)'),
    ])
    def test_collected_says_how_many_stamps(self, client, sent, stamp, second_stamp, expected):
        self._post(client, stamp=stamp, second_stamp=second_stamp)
        assert PublicMessage.objects.get().collected_summary() == expected
        assert expected in sent[0]['text_body']

    @pytest.mark.parametrize('field,value', [
        ('ambassador_number', '17a'),
        ('ambassador_number', '0'),
        ('venue_number', 'five'),
        ('passports_collected', '1.5'),
    ])
    def test_numbers_are_whole_numbers(self, client, sent, field, value):
        resp = self._post(client, **{field: value})
        assert resp.status_code == 200 and field in resp.context['form'].errors
        assert not PublicMessage.objects.exists()

    def test_venue_number_must_be_a_real_venue(self, client, sent):
        resp = self._post(client, venue_number='999')
        assert 'no venue number 999' in resp.context['form'].errors['venue_number'][0]
        assert not PublicMessage.objects.exists()

    def test_unused_passports_needs_a_count(self, client, sent):
        resp = self._post(client, passports_collected='')
        assert 'passports_collected' in resp.context['form'].errors
        assert not PublicMessage.objects.exists()

    def test_a_count_ticks_unused_passports(self, client, sent):
        self._post(client, unused_passports=None, passports_collected='3')
        report = PublicMessage.objects.get()
        assert report.unused_passports is True and report.passports_collected == 3

    @pytest.mark.parametrize('field,value', [
        ('name', 'Pat <b>Jones</b>'),
        ('venue_name', 'Mill {cafe}'),
        ('message', '<script>alert(1)</script>'),
        ('message', 'Great day \U0001F600'),
        ('reply_to', 'pat=example'),
    ])
    def test_plain_text_only(self, client, sent, field, value):
        resp = self._post(client, **{field: value})
        assert resp.status_code == 200 and field in resp.context['form'].errors
        assert not PublicMessage.objects.exists() and sent == []

    def test_accents_and_punctuation_are_fine(self, client, sent):
        resp = self._post(client, name="Siân O'Brien-Hughes", venue_name='Café & Co. (Mill St.)')
        assert resp.status_code == 302
        assert PublicMessage.objects.get().name == "Siân O'Brien-Hughes"

    def test_ampersand_is_escaped_in_the_html_email(self, client, sent):
        self._post(client, message='Tea & cake')
        assert 'Tea &amp; cake' in sent[0]['html_body']

    def test_names_cannot_inject_subject_lines(self, client, sent):
        self._post(client, venue_name='Mill\r\nBcc: evil@example.com', name='Pat\r\nJones')
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
        assert b'Send a venue report' in client.get('/admin/login/').content
        settings.PUBLIC_MESSAGES_ENABLED = False
        assert b'Send a venue report' not in client.get('/admin/login/').content

    def test_admin_lists_reports(self, client, django_user_model, sent):
        self._post(client)
        admin = django_user_model.objects.create_superuser(username='admin', email='a@example.com', password='x')
        client.force_login(admin)
        page = client.get('/admin/passports/publicmessage/')
        assert page.status_code == 200
        assert b'The Old Mill' in page.content and b'Unused passports (12), 1 stamp' in page.content
