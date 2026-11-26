import pytest
from django.utils import timezone

from passports.models import Bearer, PassportSubmission, RaffleWinner

pytestmark = pytest.mark.django_db

STAFF_PASSWORD = 'e2e-test-pass-12345'  # noqa: S105 — matches conftest.staff_user's password


def _bearer_with_submission(season, venues, suffix):
    bearer = Bearer.objects.create(
        name=f'Raffle Bearer {suffix}',
        phone=f'+447700200{suffix:03d}',
        mailing_address='1 Test Street, Testville, TE1 1ST',
    )
    submission = PassportSubmission.objects.create(
        season=season, bearer=bearer, intake_number=suffix, date_received=timezone.localdate(),
    )
    submission.venues_stamped.set(venues)  # all of them -> 2 tickets each (len(venues) == 24)
    return bearer


def _login_to_draw_page(page, live_server, staff_user):
    page.goto(f'{live_server.url}/admin/login/?next=/passports/raffle/draw/')
    page.fill('#id_username', staff_user.username)
    page.fill('#id_password', STAFF_PASSWORD)
    page.click('input[type=submit]')
    page.wait_for_url(f'{live_server.url}/passports/raffle/draw/')


def test_draw_records_winner_and_excludes_them_from_future_draws(season, venues, staff_user, page, live_server):
    bearers = [_bearer_with_submission(season, venues, i) for i in range(3)]
    _login_to_draw_page(page, live_server, staff_user)

    # The wheel itself is a fixed, decorative 24-pocket roulette wheel
    # regardless of entrant count; the count isn't shown (MARK's request).
    page.wait_for_selector('#wheel-g path')
    assert page.locator('#wheel-g path').count() == 24
    assert page.locator('#pool-count').input_value() == '3'

    page.click('#spin-btn')
    page.wait_for_selector("#reveal-overlay[style*='flex']", timeout=20000)

    assert RaffleWinner.objects.filter(season=season).count() == 1
    winner = RaffleWinner.objects.get(season=season)
    assert winner.bearer in bearers
    assert winner.ticket_count == 2
    # Neither the entrant count nor the winner's ticket count is shown.
    assert 'entrant' not in page.content() and '2 tickets' not in page.locator('#reveal-card').inner_text()

    # A fresh load recomputes the count from RaffleWinner — the winner must
    # not be drawable again.
    page.reload()
    page.wait_for_selector('#wheel-g path')
    assert page.locator('#pool-count').input_value() == '2'


def test_wheel_reveals_matching_ticket_number(season, venues, staff_user, page, live_server):
    _bearer_with_submission(season, venues, 0)
    _login_to_draw_page(page, live_server, staff_user)

    # The slot-machine view was removed at the charity's request — the
    # yellow/black wheel is the only draw view.
    assert page.locator('#view-slot-btn, #slot-wrap').count() == 0
    fills = page.locator('#wheel-g path').evaluate_all("els => [...new Set(els.map(e => e.getAttribute('fill')))]")
    assert sorted(fills) == ['#111111', '#FFD100']

    page.click('#spin-btn')
    page.wait_for_selector("#reveal-overlay[style*='flex']", timeout=20000)

    winner = RaffleWinner.objects.get(season=season)
    # The revealed number is the winner's own issued ticket — the one their
    # confirmation email listed — not a number made up at draw time.
    assert winner.ticket is not None
    assert winner.ticket_number == winner.ticket.number
    assert winner.ticket.submission.bearer_id == winner.bearer_id
    assert page.locator('#reveal-ticket-number').inner_text() == f'Ticket #{winner.ticket_number}'


def test_empty_pool_shows_end_state(season, venues, staff_user, page, live_server):
    bearer = _bearer_with_submission(season, venues, 0)
    RaffleWinner.objects.create(season=season, bearer=bearer, ticket_count=2, drawn_by=staff_user)

    _login_to_draw_page(page, live_server, staff_user)
    page.wait_for_timeout(300)

    assert page.locator('#empty-state').evaluate("el => getComputedStyle(el).display") == 'block'
    assert page.locator('#stage').evaluate("el => getComputedStyle(el).display") == 'none'
