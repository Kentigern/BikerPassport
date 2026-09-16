import pytest
from django.utils import timezone

from passports.models import Bearer, PassportSubmission

pytestmark = pytest.mark.django_db


def test_logger_can_keep_saving_before_exit_but_locked_after(season, venues, live_server, logged_in_page_as_logger):
    page = logged_in_page_as_logger

    page.fill('#id_name', 'Returning Bearer')
    page.fill('#id_phone', '07700 100010')
    page.fill('#id_mailing_address', '1 Test Street, Testville, TE1 1ST')
    page.click('#bearer-save-btn')
    page.wait_for_selector('#bearer-save-status.status-ok')

    checkbox = page.locator('.venue-row input[type=checkbox]').first
    checkbox.check()

    save_btn = page.locator('.venue-save-btn[data-exit="false"]').first
    save_btn.click()
    page.wait_for_selector('.venue-save-status.status-ok')

    # A second non-exit save against the same in-progress submission must
    # still succeed — this is the "continue entering information" case.
    save_btn.click()
    page.wait_for_selector('.venue-save-status.status-ok')

    submission_id = page.locator('#submission_id').input_value()

    exit_btn = page.locator('.venue-save-btn[data-exit="true"]').first
    exit_btn.click()
    page.wait_for_url(f'{live_server.url}/passports/submissions/new/')

    edit_url = f'{live_server.url}/passports/submissions/{submission_id}/edit/'
    response = page.request.get(edit_url)
    assert response.status == 403


def test_superuser_can_still_edit_after_exit(season, venues, live_server, logged_in_page):
    page = logged_in_page

    page.fill('#id_name', 'Admin Edited Bearer')
    page.fill('#id_phone', '07700 100011')
    page.fill('#id_mailing_address', '1 Test Street, Testville, TE1 1ST')
    page.click('#bearer-save-btn')
    page.wait_for_selector('#bearer-save-status.status-ok')

    page.locator('.venue-row input[type=checkbox]').first.check()
    page.locator('.venue-save-btn[data-exit="false"]').first.click()
    page.wait_for_selector('.venue-save-status.status-ok')
    submission_id = page.locator('#submission_id').input_value()

    page.locator('.venue-save-btn[data-exit="true"]').first.click()
    page.wait_for_url(f'{live_server.url}/passports/submissions/new/')

    edit_url = f'{live_server.url}/passports/submissions/{submission_id}/edit/'
    response = page.request.get(edit_url)
    assert response.status == 200


def test_raw_admin_blocks_edits_to_locked_records_for_logger(client, season, logger_user):
    bearer = Bearer.objects.create(
        name='Locked Bearer', phone='+447700100012', mailing_address='1 Test Street'
    )
    submission = PassportSubmission.objects.create(
        season=season,
        bearer=bearer,
        intake_number=1,
        date_received=timezone.localdate(),
        status=PassportSubmission.Status.ENTERED,
        locked_at=timezone.now(),
    )

    client.force_login(logger_user)
    session = client.session
    session['verified_bearer_ids'] = [bearer.pk]
    session.save()

    resp = client.post(f'/admin/passports/bearer/{bearer.pk}/change/', data={'name': 'Changed'})
    assert resp.status_code == 403

    resp = client.post(
        f'/admin/passports/passportsubmission/{submission.pk}/change/', data={'notes': 'changed'}
    )
    assert resp.status_code == 403
