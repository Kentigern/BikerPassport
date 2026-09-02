import pytest

pytestmark = pytest.mark.django_db


def test_venue_checkboxes_disabled_until_bearer_saved(venues, logged_in_page):
    page = logged_in_page

    checkbox = page.locator('.venue-row input[type=checkbox]').first
    select_all = page.locator('#book-select-all')
    save_btn = page.locator('.venue-save-btn').first

    assert checkbox.is_disabled()
    assert select_all.is_disabled()
    assert save_btn.is_disabled()

    page.fill('#id_name', 'Test Bearer')
    page.fill('#id_phone', '07700 100001')
    page.fill('#id_mailing_address', '1 Test Street, Testville, TE1 1ST')
    page.click('#bearer-save-btn')
    page.wait_for_selector('#bearer-save-status.status-ok')

    assert checkbox.is_enabled()
    assert select_all.is_enabled()
    assert save_btn.is_enabled()
