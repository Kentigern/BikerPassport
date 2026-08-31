import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from passports.models import Bearer, PassportSubmission, Season, Venue

# Phone numbers use the 07700 100xxx block, a distinctly patterned range
# unlikely to be real. (Ofcom's actual "reserved for fiction" range,
# 07700 900000-900999, seems safer but backfires: it's excluded from
# libphonenumber's valid-number metadata *because* it's not allocated to
# any operator, so it fails our own phone validation and can never be
# found by search - the fictional block doesn't survive contact with a
# validator that's supposed to reject exactly that kind of number.)
# (name, phone suffix, mailing_address, stamp_count, notes, status)
DEMO_BEARERS = [
    ("Megan Pritchard", "001", "12 Bryn Road, Bangor, LL57 2AB", 8, "", "entered"),
    ("Owen Hughes", "002", "45 Castle Street, Caernarfon, LL55 1SE", 15, "", "entered"),
    ("Ffion Roberts", "003", "3 Marine Terrace, Pwllheli, LL53 5AA", 22, "", "entered"),
    ("Rhys Williams", "004", "27 Terrace Road, Aberystwyth, SY23 2AJ", 30, "", "entered"),
    (
        "Carys Davies",
        "005",
        "9 Maengwyn Street, Machynlleth, SY20 8EB",
        45,
        "Ambiguous stamp on Whistlestop Café — counted as stamped.",
        "entered",
    ),
    ("Dafydd Jones", "006", "18 Broad Street, Newtown, SY16 2BQ", 60, "", "entered"),
    ("Bethan Evans", "007", "6 The Watton, Brecon, LD3 7EG", 75, "", "entered"),
    ("Gareth Morgan", "008", "51 Lammas Street, Carmarthen, SA31 3AL", 90, "", "emailed"),
    ("Siân Lewis", "009", "14 Wind Street, Swansea, SA1 1DP", 110, "", "entered"),
    ("Huw Thomas", "010", "22 Cathedral Road, Cardiff, CF11 9LJ", 130, "", "entered"),
    (
        "Eleri Griffiths",
        "011",
        "7 Beaufort Square, Chepstow, NP16 5EP",
        150,
        "Duplicate stamp for Conwy Falls Cafe — counted once.",
        "entered",
    ),
    ("Aled Price", "012", "33 Watergate Street, Chester, CH1 2LA", 170, "", "emailed"),
    ("Non Edwards", "013", "5 Wyle Cop, Shrewsbury, SY1 1XB", 190, "", "entered"),
    ("Iestyn Vaughan", "014", "19 Widemarsh Street, Hereford, HR4 9EW", 210, "", "entered"),
    ("Catrin Rhys", "015", "40 Westgate Street, Gloucester, GL1 2NW", 230, "", "entered"),
    ("Tomos Bevan", "016", "16 Park Street, Bristol, BS1 5HX", 250, "", "entered"),
    ("Angharad Powell", "017", "8 Fisherton Street, Salisbury, SP2 7RB", 270, "", "entered"),
    ("Geraint Hopkins", "018", "29 Micklegate, York, YO1 6JH", 296, "", "entered"),
]

# The one flagged as a bounced/failed send, to demo that operational signal.
EMAIL_FAILED_PHONE_SUFFIX = "008"


class Command(BaseCommand):
    help = (
        "Seed (or refresh) realistic demo data: ~18 fictional bearers with "
        "varying stamp counts, for the current season. Idempotent - safe to "
        "re-run, matches existing demo bearers by their distinctly-patterned "
        "phone number rather than creating duplicates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help="Remove previously-seeded demo bearers/submissions instead of creating them.",
        )

    def handle(self, *args, **options):
        phones = [f"+447700100{suffix}" for _, suffix, *_ in DEMO_BEARERS]

        if options['clear']:
            bearers = Bearer.objects.filter(phone__in=phones)
            count = bearers.count()
            PassportSubmission.objects.filter(bearer__in=bearers).delete()
            bearers.delete()
            self.stdout.write(self.style.SUCCESS(f"Removed {count} demo bearers (and their submissions)."))
            return

        season = Season.objects.current()
        if season is None:
            self.stdout.write(self.style.ERROR("No season exists yet — create one first."))
            return

        User = get_user_model()
        entered_by = User.objects.filter(is_superuser=True).order_by('id').first()

        active_venue_ids = list(Venue.objects.filter(is_active=True).values_list('id', flat=True))
        today = timezone.localdate()

        created, updated = 0, 0
        for i, (name, suffix, address, stamp_count, notes, status) in enumerate(DEMO_BEARERS):
            phone = f"+447700100{suffix}"
            rng = random.Random(phone)

            bearer, bearer_created = Bearer.objects.update_or_create(
                phone=phone,
                defaults={'name': name, 'mailing_address': address},
            )

            venues = rng.sample(active_venue_ids, min(stamp_count, len(active_venue_ids)))
            date_received = today - timedelta(days=rng.randint(0, 35))

            with transaction.atomic():
                submission = PassportSubmission.objects.filter(bearer=bearer, season=season).first()
                if submission is None:
                    locked_season = Season.objects.select_for_update().get(pk=season.pk)
                    next_number = (
                        PassportSubmission.objects.filter(season=locked_season)
                        .aggregate(Max('intake_number'))['intake_number__max']
                        or 0
                    ) + 1
                    submission = PassportSubmission.objects.create(
                        season=locked_season,
                        bearer=bearer,
                        intake_number=next_number,
                        date_received=date_received,
                        status=status,
                        entered_by=entered_by,
                    )
                    created += 1
                else:
                    submission.date_received = date_received
                    submission.status = status
                    updated += 1

                submission.notes = notes
                submission.email_send_failed = suffix == EMAIL_FAILED_PHONE_SUFFIX
                submission.email_sent_at = timezone.now() if status == 'emailed' else None
                submission.save()
                submission.venues_stamped.set(venues)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(DEMO_BEARERS)} demo bearers for season {season}: "
                f"{created} new submissions, {updated} refreshed."
            )
        )
