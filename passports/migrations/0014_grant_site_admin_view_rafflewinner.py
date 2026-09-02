from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations


def _ensure_permissions_created():
    # See 0009_grant_site_admin_raffleexport_view for why this is needed —
    # the new view_rafflewinner permission otherwise doesn't exist yet for
    # this data migration to look up when it runs in the same batch as the
    # schema migration that added the model.
    for app_config in global_apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=global_apps, verbosity=0)
        app_config.models_module = None


def grant_permission(apps, schema_editor):
    _ensure_permissions_created()
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    try:
        group = Group.objects.get(name='Site Admin')
        permission = Permission.objects.get(
            content_type__app_label='passports', codename='view_rafflewinner'
        )
    except (Group.DoesNotExist, Permission.DoesNotExist):
        return
    group.permissions.add(permission)


def revoke_permission(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    try:
        group = Group.objects.get(name='Site Admin')
        permission = Permission.objects.get(
            content_type__app_label='passports', codename='view_rafflewinner'
        )
    except (Group.DoesNotExist, Permission.DoesNotExist):
        return
    group.permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ('passports', '0013_rafflewinner'),
    ]

    operations = [
        migrations.RunPython(grant_permission, revoke_permission),
    ]
