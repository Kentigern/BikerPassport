import os

import pytest

# pytest-playwright's sync API runs a background event loop in the same
# thread pytest-django's session-scoped DB setup runs in, which trips
# Django's async-context detection (SynchronousOnlyOperation) even though
# no async DB access is actually happening — a known interaction between
# the two plugins. This is Django's documented escape hatch for exactly
# that kind of false positive.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

STAFF_PASSWORD = 'e2e-test-pass-12345'  # noqa: S105 — test-only fixture, not a real credential


@pytest.fixture(autouse=True)
def _allow_test_hosts(settings):
    # live_server binds to a real local port under a dynamic host/IP —
    # ALLOWED_HOSTS defaults to empty outside DEBUG, so widen it for the
    # duration of the test rather than relying on version-specific
    # live_server/ALLOWED_HOSTS handling.
    settings.ALLOWED_HOSTS = ['*']


@pytest.fixture(autouse=True)
def _use_plain_static_storage(settings):
    # live_server serves static files via Django's *finders* (straight from
    # each app's static/ source dir, unhashed) — not via STATIC_ROOT/
    # WhiteNoise like production does. Production's manifest storage makes
    # {% static %} render hashed filenames (e.g. intake.1befde72.js) that
    # only exist post-collectstatic in STATIC_ROOT, which finders can't see
    # — every static asset 404s regardless of whether collectstatic has
    # run. Plain storage renders the unhashed name finders can resolve.
    settings.STORAGES = {
        **settings.STORAGES,
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }


@pytest.fixture
def season(db):
    from passports.models import Season

    return Season.objects.create(name='2026', is_current=True)


@pytest.fixture
def venues(db):
    # Two 12-venue book pages (mirrors the real book's page size) — enough
    # to exercise page-scoped select-all behaviour and Prev/Next.
    from passports.models import Venue

    created = []
    for page in range(2):
        for i in range(12):
            number = page * 12 + i + 1
            created.append(
                Venue.objects.create(
                    number=number,
                    name=f'Venue {number}',
                    page_group=f'page{page}',
                    is_active=True,
                )
            )
    return created


@pytest.fixture
def staff_user(db, django_user_model):
    return django_user_model.objects.create_superuser(
        username='e2e_tester', email='e2e@example.com', password=STAFF_PASSWORD
    )


@pytest.fixture
def logged_in_page(page, live_server, staff_user):
    """A Playwright page logged in as a staff superuser, parked on the
    new-submission intake form — the common starting point for the
    intake-form e2e tests."""
    page.goto(f'{live_server.url}/admin/login/?next=/passports/submissions/new/')
    page.fill('#id_username', staff_user.username)
    page.fill('#id_password', STAFF_PASSWORD)
    page.click('input[type=submit]')
    page.wait_for_url(f'{live_server.url}/passports/submissions/new/')
    return page


@pytest.fixture
def page_with_bearer(logged_in_page):
    """logged_in_page, taken one step further: a bearer has been entered
    and saved — the venues checklist (checkboxes, "select all", Save
    buttons) stays disabled until this happens, same as a real user."""
    page = logged_in_page
    page.fill('#id_name', 'Test Bearer')
    page.fill('#id_phone', '07700 100000')  # valid but obviously-fictional — see seed_demo_data.py
    page.fill('#id_mailing_address', '1 Test Street, Testville, TE1 1ST')
    page.click('#bearer-save-btn')
    page.wait_for_selector('#bearer-save-status.status-ok')
    return page
