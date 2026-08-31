from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .access import is_bearer_verified, mark_bearer_verified
from .models import Bearer, PassportSubmission, Season, Venue
from .phone import normalize_uk_phone


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_current', 'raffle_concluded_at', 'retention_grace_period_days']
    list_editable = ['is_current']


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ['number', 'name', 'category', 'is_active']
    list_editable = ['is_active']
    search_fields = ['number', 'name', 'address']
    list_filter = ['is_active', 'category']


@admin.register(Bearer)
class BearerAdmin(SimpleHistoryAdmin):
    """Group permissions govern whether a role can touch Bearer data at
    all; the phone number is still required to reveal or act on any one
    specific bearer (§5.2). The changelist never browses freely — it only
    ever shows an exact phone match — and view/change on an individual
    bearer additionally requires this session to have proven it knows
    that bearer's phone (via a matching admin or intake-form search)."""

    list_display = [
        'name',
        'email',
        'phone',
        'next_season_consent_status',
        'marketing_consent_status',
        'retention_expiry_date',
    ]
    search_fields = ['phone']
    list_filter = ['next_season_consent_status', 'marketing_consent_status']
    readonly_fields = ['consent_token']

    def get_search_results(self, request, queryset, search_term):
        # Note: get_queryset() stays the normal, unrestricted queryset — it's
        # what get_object() uses to look up a single bearer for the change
        # page, and that lookup must succeed so has_view/change_permission's
        # object-level check (below) is what actually gates access, not a
        # missing-object 404/redirect. Only the changelist/search itself is
        # restricted here, to a phone-exact match — no search term (or a
        # name) yields nothing.
        normalized = normalize_uk_phone(search_term)
        if not normalized:
            return queryset.none(), False
        matches = queryset.filter(phone=normalized)
        for b in matches:
            mark_bearer_verified(request, b.pk)
        return matches, False

    def has_view_permission(self, request, obj=None):
        if not super().has_view_permission(request, obj):
            return False
        return is_bearer_verified(request, obj.pk) if obj else True

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        return is_bearer_verified(request, obj.pk) if obj else True


@admin.register(PassportSubmission)
class PassportSubmissionAdmin(SimpleHistoryAdmin):
    """intake_number/status/entered_by/email_sent_at/email_send_failed are
    system-managed by the intake form's own logic (atomic numbering, status
    transitions, audit attribution) — read-only here for everyone, including
    superusers, so that granting add/change_passportsubmission (needed for
    staff to use the intake form at all, since it checks the same
    permissions) can't be used to hand-edit them via the raw admin form.
    `bearer` is read-only too — reassigning a submission to a different
    bearer via a free autocomplete search would bypass the phone-gate
    entirely (§5.2), so that's not an action the raw admin offers at all."""

    readonly_fields = [
        'bearer',
        'intake_number',
        'status',
        'entered_by',
        'email_sent_at',
        'email_send_failed',
    ]
    list_display = [
        'intake_number',
        'season',
        'bearer',
        'status',
        'stamp_count',
        'raffle_tickets',
        'date_received',
        'entered_by',
        'email_send_failed',
    ]
    list_filter = ['season', 'status', 'email_send_failed']
    search_fields = ['bearer__name', 'bearer__email', 'intake_number']
    filter_horizontal = ['venues_stamped']
