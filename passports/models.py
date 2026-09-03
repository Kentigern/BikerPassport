import uuid

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class ConsentStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    GRANTED = 'granted', 'Granted'
    DECLINED = 'declined', 'Declined'


class SeasonManager(models.Manager):
    def current(self):
        return self.filter(is_current=True).first() or self.order_by('-name').first()


class Season(models.Model):
    """A year's Bike + Brew program (§4). Each season has its own submissions."""

    objects = SeasonManager()

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


class Venue(models.Model):
    """A numbered stamp location on the passport (§4). Not every venue is strictly
    a cafe — kept extensible for the possible future CRM use noted in §11.1."""

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


class Bearer(models.Model):
    """A passport holder's personal details (§4). A fresh record per submission
    unless staff explicitly match to an existing bearer."""

    name = models.CharField(max_length=200)
    email = models.EmailField(
        blank=True,
        help_text="Often not collected — bearers skew older and this is an "
        "old-school charity. Phone is the more reliable match key.",
    )
    mailing_address = models.TextField()
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

    # Consent/retention state (§5.6). Purpose-specific from the start per §11.2 —
    # "keep me updated for next year" and "contact me about other MYM things" are
    # asked, recorded, and can be withdrawn separately.
    consent_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Token for the no-login consent link emailed to the bearer.",
    )
    consent_requested_at = models.DateTimeField(null=True, blank=True)

    next_season_consent_status = models.CharField(
        max_length=10,
        choices=ConsentStatus.choices,
        default=ConsentStatus.PENDING,
        help_text="Consent to be contacted about next year's Bike + Brew.",
    )
    next_season_consent_responded_at = models.DateTimeField(null=True, blank=True)

    marketing_consent_status = models.CharField(
        max_length=10,
        choices=ConsentStatus.choices,
        default=ConsentStatus.PENDING,
        help_text="Consent to be contacted about other Make Your Mark events/merchandise.",
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
        help_text="Bearer's raffle ticket count at the moment they were drawn — the odds they actually had."
    )
    ticket_number = models.CharField(
        max_length=5,
        blank=True,
        default='',
        help_text="Randomly assigned 5-digit number (09999–99999) revealed for "
        "this draw's slot-machine animation — generated at draw time, not a "
        "pre-printed physical ticket ID.",
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
