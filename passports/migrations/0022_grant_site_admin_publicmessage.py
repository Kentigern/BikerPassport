from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations

# Site Admins read public messages and tick them handled; nobody adds them
# by hand (the admin disallows it) and deleting would lose the record.
CODENAMES = ['view_publicmessage', 'change_publicmessage']


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
        ('passports', '0021_publicmessage'),
    ]

    operations = [
        migrations.RunPython(grant_permissions, revoke_permissions),
    ]
