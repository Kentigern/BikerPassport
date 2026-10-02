"""Site Admins, like superusers, skip the phone check on bearers (2 Oct
2026); Passport Loggers still have to search by phone first."""
import pytest
from django.contrib.auth.models import Group, Permission

from passports.models import Bearer

pytestmark = pytest.mark.django_db

BEARER_PERMS = ['view_bearer', 'change_bearer']


def staff_user(django_user_model, username, codenames):
    group = Group.objects.create(name=username)
    group.permissions.set(Permission.objects.filter(content_type__app_label='passports', codename__in=codenames))
    user = django_user_model.objects.create_user(username=username, password='x', is_staff=True)
    user.groups.add(group)
    return user


@pytest.fixture
def bearer():
    return Bearer.objects.create(name='Pat Jones', phone='+447700900123', email='pat@example.com')


def change(client, bearer, **data):
    form = {'name': bearer.name, 'email': bearer.email, 'mailing_address': '', 'phone': bearer.phone,
            'retention_consent_status': 'pending', 'marketing_consent_status': 'pending'}
    form.update(data)
    return client.post(f'/admin/passports/bearer/{bearer.pk}/change/', form)


def test_site_admin_can_edit_without_searching_by_phone(client, django_user_model, bearer):
    client.force_login(staff_user(django_user_model, 'siteadmin', [*BEARER_PERMS, 'is_site_admin']))
    page = client.get(f'/admin/passports/bearer/{bearer.pk}/change/')
    assert b'+447700900123' in page.content and b'name="_save"' in page.content
    assert change(client, bearer, name='Pat Smith').status_code == 302
    bearer.refresh_from_db()
    assert bearer.name == 'Pat Smith'


def test_site_admin_finds_bearers_by_name_on_the_intake_form(client, django_user_model, bearer):
    client.force_login(staff_user(django_user_model, 'siteadmin', [*BEARER_PERMS, 'is_site_admin']))
    [result] = client.get('/passports/bearers/search/', {'q': 'Pat'}).json()['results']
    assert result['needs_phone'] is False and result['phone'] == '+447700900123'


def test_logger_still_needs_the_phone(client, django_user_model, bearer):
    client.force_login(staff_user(django_user_model, 'logger', BEARER_PERMS))
    page = client.get(f'/admin/passports/bearer/{bearer.pk}/change/')
    assert b'+447700900123' not in page.content and b'name="_save"' not in page.content
    change(client, bearer, name='Pat Smith')
    bearer.refresh_from_db()
    assert bearer.name == 'Pat Jones'
    [result] = client.get('/passports/bearers/search/', {'q': 'Pat'}).json()['results']
    assert result == {'name': 'Pat Jones', 'needs_phone': True}
