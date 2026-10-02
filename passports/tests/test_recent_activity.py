from io import StringIO

import pytest
from django.core.management import call_command

from passports.models import Bearer

pytestmark = pytest.mark.django_db


def run():
    out = StringIO()
    call_command('recent_activity', stdout=out)
    return out.getvalue()


def test_nothing_yet():
    output = run()
    assert 'Saved something in the last 15 min: nobody' in output
    assert 'Last save: never' in output
    assert 'Logins not yet expired (0): none' in output


def test_reports_recent_savers_and_logins(client, django_user_model):
    client.force_login(django_user_model.objects.create_superuser(username='kim', password='x'))
    client.post('/passports/bearers/save/', {'name': 'Pat Jones', 'phone': '07900000001', 'email': '', 'mailing_address': ''})
    assert Bearer.objects.exists()
    output = run()
    assert 'Saved something in the last 15 min: kim' in output
    assert 'min ago) by kim' in output
    assert 'Logins not yet expired (1): kim' in output
