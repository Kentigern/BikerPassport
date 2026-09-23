from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from passports.models import Bearer, PassportSubmission, RaffleTicket

# Everything scripts/loadtest/loadtest.py creates is identifiable by these, so
# --cleanup can remove exactly that and nothing else. The phone block is
# 07700 7xxxxx: valid to libphonenumber (so it survives BearerForm's
# validation, unlike Ofcom's 07700 900xxx fiction range — see
# seed_demo_data.py) and distinct from seed_demo_data's 07700 100xxx.
USERNAME_PREFIX = 'loadtest'
PHONE_PREFIX = '+4477007'
NAME_PREFIX = 'LOADTEST '


class Command(BaseCommand):
    help = (
        "Sets up / tears down data for scripts/loadtest/loadtest.py. --create N makes N "
        "Passport Logger accounts (loadtest01..N) with the given password; "
        "--cleanup deletes those accounts plus every bearer, submission and "
        "raffle ticket the load test created (identified by the LOADTEST name "
        "prefix and the 07700 7xxxxx phone block). Staging only: cleanup deletes "
        "raffle ticket numbers, which must never happen once real bearers have "
        "been emailed theirs."
    )

    def add_arguments(self, parser):
        parser.add_argument('--create', type=int, metavar='N', help="Create N load-test Logger accounts.")
        parser.add_argument('--password', help="Password for the created accounts (required with --create).")
        parser.add_argument('--group', default='Passport Logger', help="Group granting Logger permissions.")
        parser.add_argument('--cleanup', action='store_true', help="Delete all load-test accounts and data.")
        parser.add_argument('--yes', action='store_true', help="Actually do it (otherwise dry run).")

    def handle(self, *args, **options):
        db = connection.settings_dict
        self.stdout.write(f"Target database: {db.get('NAME')} on {db.get('HOST') or 'local'}")
        if bool(options['create']) == options['cleanup']:
            raise CommandError("Pass exactly one of --create N or --cleanup.")
        if options['create']:
            self._create(options)
        else:
            self._cleanup(options)

    def _create(self, options):
        if not options['password']:
            raise CommandError("--password is required with --create.")
        try:
            group = Group.objects.get(name=options['group'])
        except Group.DoesNotExist:
            raise CommandError(f"No group named {options['group']!r} — pass --group.") from None

        usernames = [f'{USERNAME_PREFIX}{i:02d}' for i in range(1, options['create'] + 1)]
        if not options['yes']:
            self.stdout.write(self.style.WARNING(f"Dry run: would create/reset {len(usernames)} accounts ({usernames[0]}..{usernames[-1]}) in {group.name!r}. Re-run with --yes."))
            return

        User = get_user_model()
        for username in usernames:
            user, _ = User.objects.get_or_create(username=username, defaults={'is_staff': True})
            user.is_staff = True
            user.set_password(options['password'])
            user.save()
            user.groups.add(group)
        self.stdout.write(self.style.SUCCESS(f"Ready: {len(usernames)} accounts ({usernames[0]}..{usernames[-1]})."))

    def _cleanup(self, options):
        submissions = PassportSubmission.objects.filter(bearer__phone__startswith=PHONE_PREFIX, bearer__name__startswith=NAME_PREFIX)
        bearers = Bearer.objects.filter(phone__startswith=PHONE_PREFIX, name__startswith=NAME_PREFIX)
        tickets = RaffleTicket.objects.filter(submission__in=submissions)
        users = get_user_model().objects.filter(username__regex=rf'^{USERNAME_PREFIX}\d+$')
        counts = f"{users.count()} accounts, {bearers.count()} bearers, {submissions.count()} submissions, {tickets.count()} raffle tickets"

        if not options['yes']:
            self.stdout.write(self.style.WARNING(f"Dry run: would delete {counts}. Re-run with --yes."))
            return

        with transaction.atomic():
            tickets.delete()
            submission_ids = list(submissions.values_list('pk', flat=True))
            bearer_ids = list(bearers.values_list('pk', flat=True))
            submissions.delete()
            bearers.delete()
            # Keep the audit log free of load-test noise too.
            PassportSubmission.history.filter(id__in=submission_ids).delete()
            Bearer.history.filter(id__in=bearer_ids).delete()
            users.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {counts}."))
