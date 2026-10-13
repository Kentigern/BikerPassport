import csv
import io

import pytest
from django.urls import reverse
from django.utils import timezone

from passports.access import is_submission_editable
from passports.emailing import outstanding_confirmations
from passports.models import RaffleTicket, RaffleWinner, Venue
from passports.tests.test_raffle_ticket import make_bearer, make_submission

pytestmark = pytest.mark.django_db

CHANGELIST = 'admin:passports_passportsubmission_changelist'


@pytest.fixture
def duplicate(season):
    """A bearer's rule-breaking second passport, under another phone, with one issued ticket."""
    make_submission(season, make_bearer(name='First'), intake_number=1, stamp_count=10)
    submission = make_submission(season, make_bearer(name='Second'), intake_number=2, stamp_count=12)
    submission.locked_at = timezone.now()
    submission.save()
    RaffleTicket.objects.issue_missing_for_season(season)
    return submission


def void_via_admin(client, submission, reason):
    return client.post(
        reverse(CHANGELIST),
        {'action': 'void_submissions', '_selected_action': [submission.pk], 'confirm': 'yes', 'void_reason': reason},
    )


def test_void_keeps_records_and_marks_tickets(duplicate, staff_user):
    duplicate.void(staff_user, 'Second passport, different phone')

    duplicate.refresh_from_db()
    assert duplicate.voided_by == staff_user
    assert duplicate.void_reason == 'Second passport, different phone'
    ticket = RaffleTicket.objects.get(submission=duplicate)
    assert ticket.voided_at == duplicate.voided_at
    assert not is_submission_editable(staff_user, duplicate)  # not even a superuser


def test_voided_tickets_leave_export_and_draw_but_keep_numbers(client, duplicate, staff_user, season):
    voided_number = RaffleTicket.objects.get(submission=duplicate).number
    duplicate.void(staff_user, 'Duplicate')
    client.force_login(staff_user)

    rows = list(csv.reader(io.StringIO(client.post(reverse('raffle_export')).content.decode())))
    assert [row[0] for row in rows[1:]] == ['000001']

    winner = client.post(reverse('raffle_draw_spin')).json()['winner']
    assert winner['ticket_number'] == '000001'
    assert client.post(reverse('raffle_draw_spin')).status_code == 400  # nobody else left

    # Never reissued, and the next number issued skips it.
    later = make_submission(season, make_bearer(), intake_number=3, stamp_count=10)
    assert RaffleTicket.objects.ensure_for_submission(later)[0].number == '000003'
    assert voided_number == '000002'


def test_voided_submission_gets_no_new_tickets_or_emails(duplicate, staff_user):
    duplicate.void(staff_user, 'Duplicate')
    duplicate.venues_stamped.add(*[Venue.objects.create(number=200 + n, name=f'V{n}') for n in range(10)])  # 22 stamps now

    assert len(RaffleTicket.objects.ensure_for_submission(duplicate)) == 1
    assert duplicate not in outstanding_confirmations()


def test_admin_action_asks_for_reason_then_voids_and_logs_it(client, duplicate, staff_user):
    client.force_login(staff_user)

    confirm_page = client.post(reverse(CHANGELIST), {'action': 'void_submissions', '_selected_action': [duplicate.pk]})
    assert b'Yes, void them' in confirm_page.content
    assert void_via_admin(client, duplicate, '').status_code == 200  # no reason, nothing voided
    duplicate.refresh_from_db()
    assert duplicate.voided_at is None

    void_via_admin(client, duplicate, 'Second passport, different phone')
    duplicate.refresh_from_db()
    assert duplicate.voided_at is not None

    log = client.get(reverse('audit_log')).content.decode()
    assert 'Voided — #2' in log
    assert 'tickets voided: 000002' in log
    assert 'reason: Second passport, different phone' in log


def test_only_superusers_can_void(client, duplicate, django_user_model):
    from django.contrib.auth.models import Permission

    site_admin = django_user_model.objects.create_user(username='siteadmin', password='x', is_staff=True)
    site_admin.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label='passports', codename__in=['is_site_admin', 'view_passportsubmission', 'change_passportsubmission']
        )
    )
    client.force_login(site_admin)

    void_via_admin(client, duplicate, 'Duplicate')

    duplicate.refresh_from_db()
    assert duplicate.voided_at is None


def test_cannot_void_a_winning_submission(duplicate, staff_user, season):
    ticket = RaffleTicket.objects.get(submission=duplicate)
    RaffleWinner.objects.create(
        season=season, bearer=duplicate.bearer, ticket_count=1, ticket=ticket, ticket_number=ticket.number, drawn_by=staff_user
    )

    with pytest.raises(ValueError, match='winning ticket'):
        duplicate.void(staff_user, 'Duplicate')
