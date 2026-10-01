"""The two consent questions in the intake form's bearer section: asked by
the volunteer, recorded separately, "not set" unless answered."""
import pytest

from passports.models import Bearer

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_superuser(username='admin', password='x'))
    return client


def save_bearer(client, **extra):
    data = {'name': 'Pat Jones', 'phone': '07900000001', 'email': 'pat@example.com', 'mailing_address': ''}
    data.update(extra)
    return client.post('/passports/bearers/save/', data=data)


def test_new_bearer_defaults_to_not_set(admin_client):
    assert save_bearer(admin_client).json()['ok']
    bearer = Bearer.objects.get()
    assert (bearer.retention_consent_status, bearer.marketing_consent_status) == ('pending', 'pending')
    assert bearer.retention_consent_responded_at is None


def test_answers_are_recorded_separately_with_a_date(admin_client):
    resp = save_bearer(admin_client, retention_consent_status='granted', marketing_consent_status='declined')
    assert resp.json()['bearer']['retention_consent_status'] == 'granted'
    bearer = Bearer.objects.get()
    assert (bearer.retention_consent_status, bearer.marketing_consent_status) == ('granted', 'declined')
    assert bearer.retention_consent_responded_at and bearer.marketing_consent_responded_at


def test_left_out_answer_keeps_its_value(admin_client):
    bearer_id = save_bearer(admin_client, marketing_consent_status='granted').json()['bearer']['id']
    save_bearer(admin_client, bearer_id=bearer_id, name='Pat Jones-Smith')
    assert Bearer.objects.get().marketing_consent_status == 'granted'


def test_setting_back_to_not_set_clears_the_date(admin_client):
    bearer_id = save_bearer(admin_client, retention_consent_status='granted').json()['bearer']['id']
    save_bearer(admin_client, bearer_id=bearer_id, retention_consent_status='pending')
    bearer = Bearer.objects.get()
    assert bearer.retention_consent_status == 'pending' and bearer.retention_consent_responded_at is None


def test_submission_save_also_records_answers(admin_client, season, venues):
    bearer_id = save_bearer(admin_client).json()['bearer']['id']
    resp = admin_client.post('/passports/submissions/save/', data={
        'bearer_id': bearer_id, 'venues_stamped': [venues[0].pk], 'date_received': '2026-06-01',
        'notes': '', 'exit': 'false', 'retention_consent_status': 'granted', 'marketing_consent_status': 'granted',
    })
    assert resp.json()['ok']
    bearer = Bearer.objects.get()
    assert (bearer.retention_consent_status, bearer.marketing_consent_status) == ('granted', 'granted')


def test_submission_save_rejects_unknown_answer(admin_client, season, venues):
    bearer_id = save_bearer(admin_client).json()['bearer']['id']
    resp = admin_client.post('/passports/submissions/save/', data={
        'bearer_id': bearer_id, 'venues_stamped': [venues[0].pk], 'exit': 'false',
        'marketing_consent_status': 'maybe',
    })
    assert resp.status_code == 400 and Bearer.objects.get().marketing_consent_status == 'pending'


def test_form_shows_the_questions_with_not_set_ticked(admin_client):
    page = admin_client.get('/passports/submissions/new/').content.decode()
    assert 'keep their contact details after this season?' in page
    assert 'use their contact details for marketing' in page
    for field in ('retention_consent_status', 'marketing_consent_status'):
        assert f'name="{field}" value="pending" id="id_{field}_0" checked>' in page
