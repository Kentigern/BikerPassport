from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from passports.models import RaffleWinner


class Command(BaseCommand):
    help = (
        "Delete ALL RaffleWinner records. RaffleWinner has no delete path in the "
        "admin UI by design (records are meant to be tamper-proof), so this exists "
        "as an explicit, auditable escape hatch for wiping test data. Refuses to "
        "run unless DEBUG=True, as a guard against accidentally targeting a "
        "production database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help="Actually perform the deletion. Without this flag, only reports what would be deleted.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "Refusing to run: DEBUG is False, which indicates a production "
                "environment. This command only runs where DEBUG=True."
            )

        db = connection.settings_dict
        self.stdout.write(f"Target database: {db.get('NAME')} on {db.get('HOST') or 'local'}")

        count = RaffleWinner.objects.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No RaffleWinner records found — nothing to delete."))
            return

        if not options['yes']:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {count} RaffleWinner record(s) would be deleted. "
                    f"Re-run with --yes to actually delete them."
                )
            )
            return

        deleted, _ = RaffleWinner.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} RaffleWinner record(s)."))
