import csv
import io

import pytest
from django.urls import reverse
from django.utils import timezone

from passports.models import Bearer, PassportSubmission, RaffleTicket, RaffleWinner, Venue

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


def make_submission(season, bearer, *, intake_number, stamp_count):
    start = Venue.objects.count() + 1
    venues = [
        Venue.objects.create(number=start + n, name=f'Venue {start + n}')
        for n in range(stamp_count)
    ]
    submission = PassportSubmission.objects.create(
        season=season, bearer=bearer, intake_number=intake_number, date_received='2026-06-01'
    )
    submission.venues_stamped.set(venues)
    return submission


class TestEnsureForSubmission:
    def test_assigns_one_ticket_per_ten_stamps(self, season):
        submission = make_submission(season, make_bearer(), intake_number=1, stamp_count=25)

        tickets = RaffleTicket.objects.ensure_for_submission(submission)

        assert len(tickets) == 2  # 25 // 10
        assert RaffleTicket.objects.filter(submission=submission).count() == 2

    def test_numbers_are_sequential_per_season_not_per_submission(self, season):
        first = make_submission(season, make_bearer(), intake_number=1, stamp_count=10)
        second = make_submission(season, make_bearer(), intake_number=2, stamp_count=10)

        first_tickets = RaffleTicket.objects.ensure_for_submission(first)
        second_tickets = RaffleTicket.objects.ensure_for_submission(second)

        assert first_tickets[0].number == '000001'
        assert second_tickets[0].number == '000002'

    def test_calling_again_is_a_no_op_when_count_unchanged(self, season):
        submission = make_submission(season, make_bearer(), intake_number=1, stamp_count=10)

        first_call = [t.number for t in RaffleTicket.objects.ensure_for_submission(submission)]
        second_call = [t.number for t in RaffleTicket.objects.ensure_for_submission(submission)]

        assert first_call == second_call
        assert RaffleTicket.objects.filter(submission=submission).count() == 1

    def test_tops_up_without_renumbering_existing_tickets_when_count_grows(self, season):
        submission = make_submission(season, make_bearer(), intake_number=1, stamp_count=10)
        first_numbers = [t.number for t in RaffleTicket.objects.ensure_for_submission(submission)]

        extra_start = Venue.objects.count() + 1
        extra_venues = [
            Venue.objects.create(number=extra_start + n, name=f'Extra Venue {extra_start + n}')
            for n in range(10)
        ]
        submission.venues_stamped.add(*extra_venues)

        grown_numbers = [t.number for t in RaffleTicket.objects.ensure_for_submission(submission)]

        assert grown_numbers[: len(first_numbers)] == first_numbers
        assert len(grown_numbers) == 2

    def test_never_removes_tickets_when_count_shrinks(self, season):
        submission = make_submission(season, make_bearer(), intake_number=1, stamp_count=20)
        original = [t.number for t in RaffleTicket.objects.ensure_for_submission(submission)]

        submission.venues_stamped.set(list(submission.venues_stamped.all()[:5]))

        after_shrink = [t.number for t in RaffleTicket.objects.ensure_for_submission(submission)]

        assert after_shrink == original


class TestIssueMissingForSeason:
    def test_tops_up_only_short_submissions(self, season):
        short = make_submission(season, make_bearer(), intake_number=1, stamp_count=20)
        done = make_submission(season, make_bearer(), intake_number=2, stamp_count=10)
        RaffleTicket.objects.ensure_for_submission(done)
        make_submission(season, make_bearer(), intake_number=3, stamp_count=5)  # earns none

        assert RaffleTicket.objects.issue_missing_for_season(season) == 1
        assert RaffleTicket.objects.filter(submission=short).count() == 2
        assert RaffleTicket.objects.filter(submission=done).count() == 1

    def test_locked_only_skips_unlocked(self, season):
        unlocked = make_submission(season, make_bearer(), intake_number=1, stamp_count=10)
        locked = make_submission(season, make_bearer(), intake_number=2, stamp_count=10)
        locked.locked_at = timezone.now()
        locked.save()

        RaffleTicket.objects.issue_missing_for_season(season, locked_only=True)

        assert RaffleTicket.objects.filter(submission=locked).count() == 1
        assert not RaffleTicket.objects.filter(submission=unlocked).exists()


class TestRaffleUsesIssuedNumbers:
    def test_export_lists_issued_numbers(self, client, django_user_model, season):
        admin = django_user_model.objects.create_superuser(username='admin', email='a@example.com', password='x')
        client.force_login(admin)
        submission = make_submission(season, make_bearer(name='Exported Bearer'), intake_number=1, stamp_count=20)
        issued = [t.number for t in RaffleTicket.objects.ensure_for_submission(submission)]

        resp = client.post(reverse('raffle_export'))

        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        assert rows[0] == ['Ticket Number', 'Name', 'Email', 'Phone']  # no mailing address
        assert [row[0] for row in rows[1:]] == issued
        assert all(row[1] == 'Exported Bearer' for row in rows[1:])

    def test_spin_draws_an_issued_ticket_and_excludes_winner(self, client, django_user_model, season):
        admin = django_user_model.objects.create_superuser(username='admin', email='a@example.com', password='x')
        client.force_login(admin)
        first = make_submission(season, make_bearer(), intake_number=1, stamp_count=20)
        second = make_submission(season, make_bearer(), intake_number=2, stamp_count=10)
        spin_url = reverse('raffle_draw_spin')

        winners = [client.post(spin_url).json()['winner'] for _ in range(2)]
        assert client.post(spin_url).status_code == 400  # pool exhausted

        assert {w['id'] for w in winners} == {first.bearer_id, second.bearer_id}
        for record in RaffleWinner.objects.filter(season=season):
            assert record.ticket.submission.bearer_id == record.bearer_id
            assert record.ticket_number == record.ticket.number
            assert record.ticket_count == record.ticket.submission.ticket_numbers.count()
