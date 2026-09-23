from django.core.management.base import BaseCommand
from django.db import connection

from passports.emailing import outstanding_confirmations, send_confirmations


class Command(BaseCommand):
    help = (
        "Sends the confirmation email (§5.3) to every submission still owed one: "
        "Save & Exited, bearer has an email, but not successfully emailed yet — "
        "i.e. every failed send, plus any bearer whose email was added after the "
        "fact. The same thing as the admin's 'Send / resend confirmation email' "
        "action, without its per-run cap. Safe to re-run: a submission drops out "
        "of the list as soon as it sends."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help="Actually send. Without this flag, only reports how many would be sent.",
        )

    def handle(self, *args, **options):
        db = connection.settings_dict
        self.stdout.write(f"Target database: {db.get('NAME')} on {db.get('HOST') or 'local'}")

        submissions = outstanding_confirmations()
        count = submissions.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No submissions are owed a confirmation email — nothing to send."))
            return

        if not options['yes']:
            self.stdout.write(
                self.style.WARNING(f"Dry run: {count} confirmation email(s) would be sent. Re-run with --yes to send them.")
            )
            return

        sent, failed, _ = send_confirmations(submissions.iterator())
        style = self.style.WARNING if failed else self.style.SUCCESS
        self.stdout.write(style(f"Sent {sent}, failed {failed}."))
