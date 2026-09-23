from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from passports.models import RaffleTicket, Season


class Command(BaseCommand):
    help = (
        "One-off backfill: issues raffle ticket numbers (RaffleTicket) for every "
        "already Save & Exited submission in the current season that's short of "
        "its earned tickets. Numbers used to be issued only when a confirmation "
        "email was sent, so submissions locked before that changed — and every "
        "bearer without an email — have none yet. Idempotent: never renumbers "
        "or removes a ticket already issued."
    )

    def handle(self, *args, **options):
        db = connection.settings_dict
        self.stdout.write(f"Target database: {db.get('NAME')} on {db.get('HOST') or 'local'}")

        season = Season.objects.current()
        if season is None:
            raise CommandError("No current season.")

        topped_up = RaffleTicket.objects.issue_missing_for_season(season, locked_only=True)
        self.stdout.write(self.style.SUCCESS(f"Issued missing ticket numbers for {topped_up} submission(s) in {season}."))
