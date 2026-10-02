from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from passports.models import Bearer, PassportSubmission


class Command(BaseCommand):
    help = (
        "Who is using the app right now: who saved a bearer or passport in the "
        "last 15 and 60 minutes, when the last save was, and who has a login "
        "that hasn't expired (logins last two weeks, so that list is only a "
        "rough guide). Read-only — safe at any time. Run it before a deploy: "
        "nobody saving in the last 15 minutes means it's a quiet moment."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        history = [PassportSubmission.history, Bearer.history]

        for minutes in (15, 60):
            since = now - timedelta(minutes=minutes)
            who = set()
            for records in history:
                who |= set(records.filter(history_date__gte=since).values_list('history_user__username', flat=True))
            names = ', '.join(sorted(filter(None, who))) or 'nobody'
            self.stdout.write(f'Saved something in the last {minutes} min: {names}')

        latest = [r for r in (records.order_by('-history_date').first() for records in history) if r]
        if latest:
            last = max(latest, key=lambda r: r.history_date)
            ago = int((now - last.history_date).total_seconds() // 60)
            when = timezone.localtime(last.history_date).strftime('%d %b %H:%M')
            self.stdout.write(f'Last save: {when} ({ago} min ago) by {last.history_user or "unknown"}')
        else:
            self.stdout.write('Last save: never')

        user_ids = set()
        for session in Session.objects.filter(expire_date__gt=now):
            user_id = session.get_decoded().get('_auth_user_id')
            if user_id:
                user_ids.add(user_id)
        usernames = sorted(get_user_model().objects.filter(pk__in=user_ids).values_list('username', flat=True))
        self.stdout.write(f'Logins not yet expired ({len(usernames)}): {", ".join(usernames) or "none"}')
