from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Bearer, PassportSubmission, Season, Venue


class SuperuserOnlyMixin:
    """Hides a model entirely from everyone but superusers, regardless of any
    group permissions granted — used for Bearer, where phone/email/address
    must not be casually browsable. Staff reach bearer records only through
    the intake form's phone-gated search, never through this admin (§5.2)."""

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


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
class BearerAdmin(SuperuserOnlyMixin, SimpleHistoryAdmin):
    list_display = [
        'name',
        'email',
        'phone',
        'next_season_consent_status',
        'marketing_consent_status',
        'retention_expiry_date',
    ]
    search_fields = ['name', 'email', 'phone']
    list_filter = ['next_season_consent_status', 'marketing_consent_status']
    readonly_fields = ['consent_token']


@admin.register(PassportSubmission)
class PassportSubmissionAdmin(SimpleHistoryAdmin):
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
    autocomplete_fields = ['bearer']
    filter_horizontal = ['venues_stamped']
