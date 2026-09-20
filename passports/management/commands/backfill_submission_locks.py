from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import F

from passports.models import PassportSubmission


class Command(BaseCommand):
    help = (
        "One-off backfill for PassportSubmission.locked_at (see "
        "passports/access.py:is_submission_editable). That field was added to stop "
        "Passport Loggers re-editing a submission once it's been saved & exited, but "
        "the migration that added it left every pre-existing submission with "
        "locked_at=NULL, i.e. unlocked — the exact state the feature was meant to "
        "close off. Before this feature existed, a submission row only ever meant "
        "'processed', so this locks every already-null submission using its own "
        "updated_at as the lock time. Site Admins/superusers are unaffected either "
        "way (they're exempt from the lock)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help="Actually perform the backfill. Without this flag, only reports what would change.",
        )

    def handle(self, *args, **options):
        db = connection.settings_dict
        self.stdout.write(f"Target database: {db.get('NAME')} on {db.get('HOST') or 'local'}")

        queryset = PassportSubmission.objects.filter(locked_at__isnull=True)
        count = queryset.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No unlocked submissions found — nothing to backfill."))
            return

        if not options['yes']:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {count} submission(s) would be locked (locked_at set to their own "
                    f"updated_at). Re-run with --yes to actually apply it."
                )
            )
            return

        updated = queryset.update(locked_at=F('updated_at'))
        self.stdout.write(self.style.SUCCESS(f"Locked {updated} submission(s)."))
