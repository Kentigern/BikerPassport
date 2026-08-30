import csv

from django.core.management.base import BaseCommand, CommandError

from passports.models import Venue


class Command(BaseCommand):
    help = (
        "Load/update the Venue list from a CSV with Number,Name,Address columns "
        "(§5.1 cafe list setup). Existing venues are matched by number and updated "
        "in place; new numbers are created."
    )

    def add_arguments(self, parser):
        parser.add_argument('csv_path', help="Path to a CSV with Number,Name,Address columns.")

    def handle(self, *args, **options):
        path = options['csv_path']
        try:
            f = open(path, newline='', encoding='utf-8')
        except OSError as exc:
            raise CommandError(f"Could not open {path}: {exc}")

        created, updated = 0, 0
        with f:
            reader = csv.DictReader(f)
            for row in reader:
                venue, was_created = Venue.objects.update_or_create(
                    number=int(row['Number']),
                    defaults={
                        'name': row['Name'],
                        'address': row.get('Address', ''),
                    },
                )
                created += was_created
                updated += not was_created

        self.stdout.write(self.style.SUCCESS(f"Created {created}, updated {updated} venues."))
