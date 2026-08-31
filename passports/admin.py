from django.contrib import admin
from django.shortcuts import redirect
from simple_history.admin import SimpleHistoryAdmin

from .access import is_bearer_verified, mark_bearer_verified
from .models import Bearer, PassportSubmission, Season, Venue
from .phone import normalize_uk_phone

admin.site.site_header = "MARK Passport Administration"
admin.site.site_title = "MARK Passport Administration"
admin.site.index_title = "MARK Passport Administration"

_default_admin_index = admin.site.index


def _role_aware_admin_index(request, extra_context=None):
    """`config.urls.root_redirect` already sends non-superusers to the
    intake landing page instead of the raw admin — but that only fires for
    the bare `/`. A non-superuser who lands on `/admin/` itself (bookmark,
    typed URL, or the admin login's own default `next`) skipped that
    routing entirely. Applying the same rule here keeps it consistent
    without touching deep links (e.g. a bearer's change page), which stay
    reachable for whatever a role's group permissions actually allow.

    Site Admins are exempt from the bounce (same as superusers) — the
    dashboard's own "Site Administration" button links straight to this
    same index, and bouncing them back to the landing page would turn that
    button into a redirect loop."""
    if (
        request.user.is_authenticated
        and not request.user.is_superuser
        and not request.user.groups.filter(name='Site Admin').exists()
    ):
        return redirect('landing')
    return _default_admin_index(request, extra_context)


admin.site.index = _role_aware_admin_index


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
    """The phone-gate (§5.2) restricts *changing* a bearer, not viewing
    one — group permissions (view_bearer) already control whether a role
    can browse the list/detail pages at all. Phone itself never appears
    in the list, and is hidden on an unverified bearer's detail page too,
    since showing it would let anyone read the "secret" straight off the
    screen and defeat the point of requiring it. Verifying (an exact
    phone search here or via the intake form) reveals the field and
    unlocks editing for that one bearer. Superusers bypass all of this —
    full list, full search, phone always visible — as the most trusted
    tier and the one actually administering the app."""

    list_display = [
        'name',
        'email',
        'phone',
        'next_season_consent_status',
        'marketing_consent_status',
        'retention_expiry_date',
    ]
    search_fields = ['phone', 'name', 'email']
    search_help_text = (
        "Search by name or phone. Only an exact phone match reveals that "
        "bearer's phone number and unlocks editing them (privacy control, "
        "§5.2) — everything else here is freely browsable."
    )
    list_filter = ['next_season_consent_status', 'marketing_consent_status']
    readonly_fields = ['consent_token']

    def get_list_display(self, request):
        if request.user.is_superuser:
            return self.list_display
        return [f for f in self.list_display if f != 'phone']

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if not request.user.is_superuser and obj is not None and not is_bearer_verified(request, obj.pk):
            fields = [f for f in fields if f != 'phone']
        return fields

    def get_search_results(self, request, queryset, search_term):
        if not request.user.is_superuser:
            normalized = normalize_uk_phone(search_term)
            if normalized:
                matches = queryset.filter(phone=normalized)
                for b in matches:
                    mark_bearer_verified(request, b.pk)
                return matches, False
        # Everything else — an empty term (browse), a name, or any
        # superuser search — falls through to Django's normal behaviour.
        return super().get_search_results(request, queryset, search_term)

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
    entirely (§5.2), so that's not an action the raw admin offers at all.
    Creating a submission here is blocked outright (has_add_permission) —
    `bearer` being required and readonly makes the raw "Add" form
    fundamentally broken (no way to set a bearer at all); the intake
    form's own "New submission" is the only correct way in."""

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

    def has_add_permission(self, request):
        return False
