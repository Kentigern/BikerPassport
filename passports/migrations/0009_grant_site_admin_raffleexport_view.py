from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations


def _ensure_permissions_created():
    # Auto-created permissions (like view_raffleexport, added by the
    # previous migration) normally only appear once Django's post_migrate
    # signal fires at the very end of a `migrate` run — which is too late
    # for a data migration in the same run to look one up. Forcing
    # creation here makes this migration work whether it runs in the same
    # batch as 0008 (fresh install) or on its own (existing deployment).
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
            content_type__app_label='passports', codename='view_raffleexport'
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
            content_type__app_label='passports', codename='view_raffleexport'
        )
    except (Group.DoesNotExist, Permission.DoesNotExist):
        return
    group.permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ('passports', '0008_raffleexport'),
    ]

    operations = [
        migrations.RunPython(grant_permission, revoke_permission),
    ]
