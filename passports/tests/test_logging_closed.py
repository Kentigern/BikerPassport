"""Season.logging_open: when unticked, Passport Loggers can no longer log or
change passports; Site Admins and superusers still can, for corrections."""
import pytest
from django.contrib.auth.models import Group, Permission

from passports.models import Bearer, PassportSubmission

pytestmark = pytest.mark.django_db


@pytest.fixture
def closed(season):
    season.logging_open = False
    season.save()
    return season


@pytest.fixture
def bearer_with_submission(season, venues):
    bearer = Bearer.objects.create(name='Pat Jones', phone='+447900000001')
    submission = PassportSubmission.objects.create(
        season=season, bearer=bearer, intake_number=1, date_received='2026-06-01'
    )
    submission.venues_stamped.set(venues[:3])
    return bearer, submission


def logger_client(client, logger_user, bearer=None):
    client.force_login(logger_user)
    if bearer is not None:
        session = client.session
        session['verified_bearer_ids'] = [bearer.pk]
        session.save()
    return client


def test_open_by_default_logger_sees_the_button(client, logger_user, season):
    page = logger_client(client, logger_user).get('/passports/')
    assert b'Log a Submission' in page.content and b'closed until next season' not in page.content


def test_closed_logger_sees_a_message_not_the_button(client, logger_user, closed):
    page = logger_client(client, logger_user).get('/passports/')
    assert b'closed until next season' in page.content and b'Log a Submission' not in page.content
    assert client.get('/passports/submissions/new/').url == '/passports/'


def test_closed_logger_cannot_save_bearers_or_submissions(client, logger_user, closed, bearer_with_submission, venues):
    bearer, submission = bearer_with_submission
    logger_client(client, logger_user, bearer)
    resp = client.post('/passports/bearers/save/', {'name': 'New Person', 'phone': '07900000002', 'email': '', 'mailing_address': ''})
    assert resp.status_code == 403 and resp.json()['errors']['permission'] == ['Passport logging is closed until next season.']
    assert not Bearer.objects.filter(name='New Person').exists()
    resp = client.post('/passports/submissions/save/', {
        'bearer_id': bearer.pk, 'submission_id': submission.pk, 'venues_stamped': [v.pk for v in venues],
        'date_received': '2026-06-01', 'notes': '', 'exit': 'false',
    })
    assert resp.status_code == 403
    assert submission.venues_stamped.count() == 3
    assert client.get(f'/passports/submissions/{submission.pk}/edit/').url == '/passports/'


def test_closed_logger_cannot_edit_in_the_admin_either(client, logger_user, closed, bearer_with_submission):
    bearer, submission = bearer_with_submission
    logger_client(client, logger_user, bearer)
    page = client.get(f'/admin/passports/bearer/{bearer.pk}/change/')
    assert b'name="_save"' not in page.content


def test_closed_site_admin_can_still_correct(client, django_user_model, closed, bearer_with_submission, venues):
    bearer, submission = bearer_with_submission
    group = Group.objects.create(name='Site Admin')
    group.permissions.set(Permission.objects.filter(
        content_type__app_label='passports',
        codename__in=['is_site_admin', 'add_bearer', 'change_bearer', 'view_bearer',
                      'add_passportsubmission', 'change_passportsubmission', 'view_passportsubmission'],
    ))
    admin = django_user_model.objects.create_user(username='siteadmin', password='x', is_staff=True)
    admin.groups.add(group)
    client.force_login(admin)
    assert client.get('/passports/submissions/new/').status_code == 200
    resp = client.post('/passports/submissions/save/', {
        'bearer_id': bearer.pk, 'submission_id': submission.pk, 'venues_stamped': [v.pk for v in venues],
        'date_received': '2026-06-01', 'notes': '', 'exit': 'false',
    })
    assert resp.json()['ok'] and submission.venues_stamped.count() == len(venues)


def test_reopening_restores_logging(client, logger_user, closed):
    closed.logging_open = True
    closed.save()
    page = logger_client(client, logger_user).get('/passports/')
    assert b'Log a Submission' in page.content
