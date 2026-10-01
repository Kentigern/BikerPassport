from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations

# Site Admins work the "Venues by season" list: set each venue's kit
# recovery status. Rows are created automatically, never deleted.
CODENAMES = ['view_venueseason', 'change_venueseason']


def _ensure_permissions_created():
    # See 0009_grant_site_admin_raffleexport_view for why this is needed.
    for app_config in global_apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=global_apps, verbosity=0)
        app_config.models_module = None


def _permissions(apps):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    try:
        group = Group.objects.get(name='Site Admin')
    except Group.DoesNotExist:
        return None, []
    permissions = Permission.objects.filter(
        content_type__app_label='passports', codename__in=CODENAMES
    )
    return group, permissions


def link_existing_reports(apps, schema_editor):
    """Reports so far all belong to the current season (2026)."""
    PublicMessage = apps.get_model('passports', 'PublicMessage')
    Season = apps.get_model('passports', 'Season')
    Venue = apps.get_model('passports', 'Venue')
    season = Season.objects.filter(is_current=True).first() or Season.objects.order_by('-name').first()
    venues = {v.number: v for v in Venue.objects.all()}
    for report in PublicMessage.objects.filter(venue_number__isnull=False, venue__isnull=True):
        report.venue = venues.get(report.venue_number)
        report.season = season
        report.save(update_fields=['venue', 'season'])


def grant_permissions(apps, schema_editor):
    _ensure_permissions_created()
    group, permissions = _permissions(apps)
    if group is not None:
        group.permissions.add(*permissions)


def revoke_permissions(apps, schema_editor):
    group, permissions = _permissions(apps)
    if group is not None:
        group.permissions.remove(*permissions)


class Migration(migrations.Migration):

    dependencies = [
        ('passports', '0026_venueseason_and_report_links'),
    ]

    operations = [
        migrations.RunPython(link_existing_reports, migrations.RunPython.noop),
        migrations.RunPython(grant_permissions, revoke_permissions),
    ]
