import uuid

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords


class ConsentStatus(models.TextChoices):
    PENDING = 'pending', 'Not set'
    GRANTED = 'granted', 'Granted'
    DECLINED = 'declined', 'Declined'


class SeasonManager(models.Manager):
    def current(self):
        return self.filter(is_current=True).first() or self.order_by('-name').first()

    def get_by_natural_key(self, name):
        return self.get(name=name)


class VenueManager(models.Manager):
    def get_by_natural_key(self, number):
        return self.get(number=number)


class Season(models.Model):
    """A year's Bike + Brew program (§4). Each season has its own submissions."""

    objects = SeasonManager()

    # Natural keys let `dumpdata --natural-primary` / `loaddata` move seasons
    # and venues between databases by name/number instead of by id — so
    # loading into a database that already has them updates the existing
    # rows rather than clashing (see scripts/transfer_reference_data.txt).
    def natural_key(self):
        return (self.name,)

    name = models.CharField(max_length=20, unique=True, help_text="e.g. '2026'.")
    is_current = models.BooleanField(
        default=False,
        help_text="The season new submissions default to (§5.2).",
    )
    raffle_concluded_at = models.DateField(
        null=True,
        blank=True,
        help_text="When this season's raffle draw/processing concluded — "
        "starts the retention grace period (§5.6).",
    )
    retention_grace_period_days = models.PositiveIntegerField(
        default=90,
        help_text="Days after raffle_concluded_at before a declined/non-responding "
        "bearer's data is purged (§9 — admin-configurable; spec sets no fixed default).",
    )

    class Meta:
        ordering = ['-name']
        constraints = [
            models.UniqueConstraint(
                fields=['is_current'],
                condition=models.Q(is_current=True),
                name='unique_current_season',
            ),
        ]
        permissions = [
            (
                'is_site_admin',
                'Can access the dashboard, audit log, and raffle export (site admin)',
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Only one season may be current. The conditional unique constraint
        # enforces that on Postgres/SQLite, but MariaDB (Krystal) can't
        # create it (models.W036) — so marking a season current here always
        # un-marks the others, on every database.
        with transaction.atomic():
            if self.is_current:
                Season.objects.filter(is_current=True).exclude(pk=self.pk).update(is_current=False)
            super().save(*args, **kwargs)


class Venue(models.Model):
    """A numbered stamp location on the passport (§4). Not every venue is strictly
    a cafe — kept extensible for the possible future CRM use noted in §11.1."""

    objects = VenueManager()

    def natural_key(self):
        return (self.number,)

    number = models.PositiveSmallIntegerField(unique=True, help_text="Passport number, 1-296.")
    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    page_group = models.CharField(
        max_length=50,
        blank=True,
        help_text="Which physical passport page-spread this venue appears on "
        "(e.g. 'img001.pdf') — groups venues into pages for the intake "
        "form's Book view (§5.2). Pages can have fewer than 12 venues "
        "where the original book had section-divider artwork instead of "
        "a full page of listings.",
    )

    # Room for a future simple CRM (§11.1) — most of these stay empty for now.
    category = models.CharField(max_length=100, blank=True)
    contact_name = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)

    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck instead of deleting if a venue drops out of a season's list.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['number']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(number__gte=1, number__lte=296),
                name='venue_number_in_range',
            ),
        ]

    def __str__(self):
        return f"{self.number}. {self.name}"


class VenueSeason(models.Model):
    """A venue's part in one season. For now it tracks recovering the
    season's kit (fed by ambassadors' venue reports); it's also where
    later per-season venue work belongs — recruitment stage, that year's
    passport number, the ambassador looking after it. Rows for the current
    season's active venues are created when the admin list is opened."""

    class RecoveryStatus(models.TextChoices):
        OUTSTANDING = 'outstanding', 'Outstanding'
        COLLECTED = 'collected', 'Collected'
        KEPT = 'kept', 'Kept at venue for next year'
        LOST = 'lost', 'Lost'

    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name='seasons')
    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name='venues')
    recovery_status = models.CharField(
        'kit recovery', max_length=12, choices=RecoveryStatus.choices, default=RecoveryStatus.OUTSTANDING
    )
    recovery_notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'venue by season'
        verbose_name_plural = 'venues by season'
        ordering = ['-season__name', 'venue__number']
        constraints = [
            models.UniqueConstraint(fields=['venue', 'season'], name='one_row_per_venue_per_season'),
        ]

    def __str__(self):
        return f"{self.venue} ({self.season})"

    @classmethod
    def ensure_rows(cls, season):
        """Add any missing rows for the season's active venues."""
        existing = cls.objects.filter(season=season).values_list('venue_id', flat=True)
        missing = Venue.objects.filter(is_active=True).exclude(pk__in=existing)
        cls.objects.bulk_create([cls(venue=venue, season=season) for venue in missing], ignore_conflicts=True)


class Bearer(models.Model):
    """A passport holder's personal details (§4). A fresh record per submission
    unless staff explicitly match to an existing bearer."""

    name = models.CharField(max_length=200)
    email = models.EmailField(
        blank=True,
        help_text="Often not collected — bearers skew older and this is an "
        "old-school charity. Phone is the more reliable match key.",
    )
    mailing_address = models.TextField(
        blank=True,
        help_text="Not always collected — some bearers only give a phone number.",
    )
    phone = models.CharField(
        max_length=30,
        unique=True,
        help_text="Stored normalized (E.164, e.g. +447990575555). The mandatory, "
        "unique key for matching an existing bearer — not email, which many "
        "bearers don't have.",
        error_messages={
            'unique': "A bearer with this phone number already exists — "
            "search for them instead of creating a new record.",
        },
    )

    # Consent (§5.6), asked by the volunteer when the passport is entered and
    # recorded separately for each of two purposes: keeping the contact
    # details after the season, and using them for marketing. MARK may not
    # email bearers to ask for consent, so "not set" means never asked.
    # consent_token is for the bearer's no-login withdraw link.
    consent_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Token for the bearer's no-login link to withdraw consent.",
    )
    consent_requested_at = models.DateTimeField(null=True, blank=True)

    retention_consent_status = models.CharField(
        'keep contact details',
        max_length=10,
        choices=ConsentStatus.choices,
        default=ConsentStatus.PENDING,
        help_text="Permission for Make Your Mark to keep their contact details after this season.",
    )
    retention_consent_responded_at = models.DateTimeField(null=True, blank=True)

    marketing_consent_status = models.CharField(
        'use for marketing',
        max_length=10,
        choices=ConsentStatus.choices,
        default=ConsentStatus.PENDING,
        help_text="Permission to use their contact details for marketing (e.g. events, merchandise).",
    )
    marketing_consent_responded_at = models.DateTimeField(null=True, blank=True)

    retention_expiry_date = models.DateField(
        null=True,
        blank=True,
        help_text="Purge-due date for a declined/non-responding bearer, set when "
        "an admin runs the retention purge review (§5.6).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    CONSENT_FIELDS = ['retention_consent_status', 'marketing_consent_status']

    def set_consent(self, field, status):
        """Set one consent status, stamping when it was answered (cleared
        if set back to not set). Returns the changed field names (empty if
        unchanged), for save(update_fields=...)."""
        if getattr(self, field) == status:
            return []
        responded_field = field.replace('_status', '_responded_at')
        setattr(self, field, status)
        setattr(self, responded_field, None if status == ConsentStatus.PENDING else timezone.now())
        return [field, responded_field]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class PassportSubmission(models.Model):
    """One returned physical passport (§4), linked to a Season and a Bearer."""

    MAX_RAFFLE_TICKETS = 28

    class Status(models.TextChoices):
        RECEIVED = 'received', 'Received'
        ENTERED = 'entered', 'Entered'
        EMAILED = 'emailed', 'Emailed'

    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name='submissions')
    bearer = models.ForeignKey(Bearer, on_delete=models.PROTECT, related_name='submissions')

    intake_number = models.PositiveIntegerField(
        help_text="Sequential number auto-assigned per season, the first time this "
        "submission's venues are saved. Combined with the one-submission-per-"
        "bearer-per-season rule below, this is effectively 'the Nth bearer "
        "processed this season' (§5.2).",
    )
    date_received = models.DateField()
    venues_stamped = models.ManyToManyField(Venue, blank=True, related_name='submissions')

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECEIVED)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='entered_submissions',
    )

    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_send_failed = models.BooleanField(
        default=False,
        help_text="Flagged for staff follow-up if the confirmation email bounced "
        "or failed to send (§5.3) — a failure must be visible, not silent.",
    )

    notes = models.TextField(
        blank=True,
        help_text="Anomalies, e.g. ambiguous stamp, duplicate cafe stamps.",
    )

    locked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set the first time a Passport Logger saves this submission and "
        "exits the intake form. A locked submission — and its bearer — can no "
        "longer be edited by a Logger, only by a Site Admin or superuser; see "
        "access.is_submission_editable/is_bearer_editable.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(m2m_fields=['venues_stamped'])

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['season', 'intake_number'], name='unique_intake_number_per_season'
            ),
            models.UniqueConstraint(
                fields=['bearer', 'season'], name='unique_bearer_per_season'
            ),
        ]
        ordering = ['season', 'intake_number']

    def __str__(self):
        return f"#{self.intake_number} ({self.season}) — {self.bearer}"

    @property
    def stamp_count(self):
        return self.venues_stamped.count()

    @property
    def raffle_tickets(self):
        return min(self.stamp_count // 10, self.MAX_RAFFLE_TICKETS)


class RaffleTicketManager(models.Manager):
    def ensure_for_submission(self, submission):
        """Tops up this submission's issued ticket numbers to match its
        current .raffle_tickets count — called whenever a locked submission
        is saved (Save & Exit, or a later Site Admin correction), whether
        or not the bearer has an email, and again right before the
        confirmation email (§5.3) is rendered, so the numbers it lists
        already exist. Never removes or renumbers a ticket already issued,
        even if a later correction lowers the count: once a number's been
        emailed to a bearer it has to stay theirs (and stays in the draw),
        same rationale as RaffleExport/RaffleWinner's immutability. Numbers
        are sequential per season, guarded the same way
        PassportSubmission.intake_number is — a
        SELECT ... FOR UPDATE on the season row — so concurrent saves
        can't race to the same number."""
        wanted = submission.raffle_tickets
        with transaction.atomic():
            season = Season.objects.select_for_update().get(pk=submission.season_id)
            existing = list(self.filter(submission=submission).order_by('number'))
            missing = wanted - len(existing)
            if missing <= 0:
                return existing

            last_number = self.filter(season=season).aggregate(models.Max('number'))['number__max']
            next_int = int(last_number) + 1 if last_number else 1
            new_tickets = [
                self.model(season=season, submission=submission, number=f'{next_int + i:06d}')
                for i in range(missing)
            ]
            self.bulk_create(new_tickets)
            existing.extend(new_tickets)
        return existing

    def issue_missing_for_season(self, season, *, locked_only=False):
        """Runs ensure_for_submission for every submission this season
        that's earned more tickets than it's been issued — so the raffle
        export/draw (which work purely from issued numbers) can't miss a
        submission that was saved but never Save & Exited. One query finds
        the short ones; only those pay the per-submission cost."""
        submissions = PassportSubmission.objects.filter(season=season)
        if locked_only:
            submissions = submissions.exclude(locked_at=None)
        candidates = submissions.annotate(
            stamp_total=models.Count('venues_stamped', distinct=True),
            issued=models.Count('ticket_numbers', distinct=True),
        ).filter(stamp_total__gte=10)
        topped_up = 0
        for submission in candidates:
            earned = min(submission.stamp_total // 10, PassportSubmission.MAX_RAFFLE_TICKETS)
            if submission.issued < earned:
                self.ensure_for_submission(submission)
                topped_up += 1
        return topped_up


class RaffleTicket(models.Model):
    """One physical raffle-ticket number issued for a submission's earned
    tickets (§5.3) — lets the confirmation email tell a bearer exactly
    which numbers are theirs. Assigned via RaffleTicketManager.ensure_for_submission,
    sequential per season, and never edited or deleted afterwards."""

    objects = RaffleTicketManager()

    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name='raffle_tickets')
    submission = models.ForeignKey(PassportSubmission, on_delete=models.PROTECT, related_name='ticket_numbers')
    number = models.CharField(max_length=6, help_text="Sequential per season, zero-padded, e.g. '000001'.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['season', 'number']
        constraints = [
            models.UniqueConstraint(fields=['season', 'number'], name='unique_raffle_ticket_number_per_season'),
        ]

    def __str__(self):
        return f"#{self.number} ({self.season}) — {self.submission.bearer}"


class RaffleExport(models.Model):
    """Audit record of a raffle-ticket draw list export. Real prizes are on
    the line, so every export is logged here — who, when, how many tickets
    — and this record is immutable (no add/change/delete via the raw admin,
    §passports.admin) so it can't be edited after the fact to paper over a
    dispute about the draw."""

    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name='raffle_exports')
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='raffle_exports',
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    entry_count = models.PositiveIntegerField(help_text="Total ticket rows in this export.")

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return f"{self.season} — {self.entry_count} entries by {self.generated_by} at {self.generated_at:%Y-%m-%d %H:%M}"


class RaffleWinner(models.Model):
    """Immutable record of a winner drawn live on the raffle wheel
    (views.raffle_draw_view) — same rationale as RaffleExport: real prizes
    are on the line, so who won what, when, and drawn by whom must be
    tamper-proof after the fact. Unique per (season, bearer) — once drawn,
    a bearer's remaining tickets are out of the running for the rest of
    the season, enforced here at the DB level too."""

    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name='raffle_winners')
    bearer = models.ForeignKey(Bearer, on_delete=models.PROTECT, related_name='raffle_wins')
    prize = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional label the host can type in before drawing, e.g. 'Weekend for two'.",
    )
    ticket_count = models.PositiveIntegerField(
        help_text="Bearer's issued raffle ticket count at the moment they were drawn — the odds they actually had."
    )
    ticket = models.OneToOneField(
        RaffleTicket,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='win',
        help_text="The issued ticket actually drawn. Null only for winners drawn "
        "before the draw switched to issued numbers.",
    )
    ticket_number = models.CharField(
        max_length=6,
        blank=True,
        default='',
        help_text="The drawn ticket's number (a copy of ticket.number, so the "
        "record reads on its own) — the same number the bearer was sent in "
        "their confirmation email.",
    )
    drawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='raffle_winners_drawn',
    )
    drawn_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-drawn_at']
        constraints = [
            models.UniqueConstraint(fields=['season', 'bearer'], name='unique_winner_per_season'),
        ]

    def __str__(self):
        return f"{self.bearer} — {self.season} — drawn {self.drawn_at:%Y-%m-%d %H:%M}"


class EmailCampaign(models.Model):
    """A bulk email a Site Admin drafts, previews, and sends to bearers.

    The audience is never admin-chosen — it's derived entirely from
    `purpose`, which maps to one of Bearer's two purpose-specific consent
    flags (§5.6). This makes it structurally impossible to bulk-email a
    bearer who hasn't granted that specific consent."""

    class Purpose(models.TextChoices):
        NEXT_SEASON = 'next_season', 'Next season update'
        MARKETING = 'marketing', 'Other MYM news/events'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SENDING = 'sending', 'Sending'
        SENT = 'sent', 'Sent'

    subject = models.CharField(max_length=200)
    body_html = models.TextField(blank=True, help_text="Rich-text body from the editor.")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='email_campaigns',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    # Denormalized so the status page can poll cheaply instead of
    # re-counting EmailCampaignRecipient rows on every request.
    recipient_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    history = HistoricalRecords()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.subject} ({self.get_purpose_display()}) — {self.get_status_display()}"


class EmailCampaignRecipient(models.Model):
    """One bearer's send-time slot in a campaign — snapshotted when Send is
    clicked, so the audience is locked in up front rather than
    re-evaluated mid-send, and so a stalled/interrupted send can safely
    resume by just processing whatever's still `pending`."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'

    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE, related_name='recipients')
    bearer = models.ForeignKey(Bearer, on_delete=models.CASCADE, related_name='campaign_sends')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['campaign', 'bearer'], name='unique_recipient_per_campaign'),
        ]

    def __str__(self):
        return f"{self.bearer} — {self.campaign} — {self.get_status_display()}"


class PublicMessage(models.Model):
    """An ambassador's venue report, sent without logging in from the
    public /message/ page (off unless settings.PUBLIC_MESSAGES_ENABLED):
    who, which venue, which kit they collected, and notes. Stored here as
    the record, and emailed to settings.PUBLIC_MESSAGE_ALERT_EMAILS.
    Deliberately minimal: no files, no HTML, no IP address kept.

    Rows from before 29 Sep 2026 are general "contact the organisers"
    messages: only name / reply_to / message are filled in."""

    name = models.CharField('ambassador name', max_length=100, blank=True)
    ambassador_number = models.PositiveIntegerField(null=True, blank=True)
    report_date = models.DateField(
        null=True, blank=True, help_text="The day the report was sent (set automatically)."
    )
    venue_name = models.CharField(max_length=200, blank=True)
    venue_number = models.PositiveIntegerField(null=True, blank=True)
    # Set from venue_number when the report arrives (the form checks it's a
    # real venue), with the season current then — empty on general messages.
    venue = models.ForeignKey(Venue, null=True, blank=True, on_delete=models.PROTECT, related_name='reports')
    season = models.ForeignKey(Season, null=True, blank=True, on_delete=models.PROTECT, related_name='venue_reports')
    unused_passports = models.BooleanField('unused passports', default=False)
    passports_collected = models.PositiveIntegerField('number collected', null=True, blank=True)
    stamp = models.BooleanField(default=False)
    second_stamp = models.BooleanField('2nd stamp', default=False)
    inkpad = models.BooleanField(default=False)
    folder = models.BooleanField(default=False)
    unused_stationery = models.BooleanField('unused stationery', default=False)
    # Bearers' completed passports left at the venue, to be logged.
    validation_passports = models.BooleanField('passports for validation', default=False)
    validation_collected = models.PositiveIntegerField('number collected', null=True, blank=True)
    reply_to = models.CharField(
        max_length=200, blank=True, help_text="Email or phone the sender gave for a reply (optional)."
    )
    message = models.TextField('notes', max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    alert_sent = models.BooleanField(default=False, help_text="Whether the staff alert email went out.")
    handled = models.BooleanField(default=False, help_text="Tick once someone has dealt with this message.")

    class Meta:
        ordering = ['-created_at']

    COLLECTED_ITEMS = [
        ('unused_passports', 'Unused passports'),
        ('inkpad', 'Inkpad'),
        ('folder', 'Folder'),
        ('unused_stationery', 'Unused stationery'),
        ('validation_passports', 'Passports for validation'),
    ]
    # Ticked item -> the field holding how many.
    COUNTED_ITEMS = {'unused_passports': 'passports_collected', 'validation_passports': 'validation_collected'}

    def __str__(self):
        return f"{self.name or 'Anonymous'} — {self.created_at:%Y-%m-%d %H:%M}"

    def collected_summary(self):
        """e.g. "Unused passports (12), 2 stamps, Folder, Passports for
        validation (5)" — or "Nothing"."""
        items = []
        for field, label in self.COLLECTED_ITEMS:
            if getattr(self, field):
                count = getattr(self, self.COUNTED_ITEMS[field]) if field in self.COUNTED_ITEMS else None
                if count is not None:
                    label = f'{label} ({count})'
                items.append(label)
            if field == 'unused_passports':
                # The two stamp boxes are reported as a count, so it's explicit.
                stamps = self.stamp + self.second_stamp
                if stamps:
                    items.append(f'{stamps} stamp{"s" if stamps > 1 else ""}')
        return ', '.join(items) or 'Nothing'
