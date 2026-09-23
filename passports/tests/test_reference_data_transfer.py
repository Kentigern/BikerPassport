"""The Railway -> Krystal reference-data move (scripts/transfer_reference_data.txt):
dumpdata with natural keys on one database, loaddata on another that may
already hold some of the same users/groups/seasons/venues under different
ids. Matching must be by username / group name / season name / venue
number, updating in place — never duplicating or clashing."""

import json

import pytest
from django.apps import apps
from django.contrib.auth.models import Group, Permission, User
from django.core import serializers
from django.core.management import call_command

from passports.models import Season, Venue

pytestmark = pytest.mark.django_db

MODELS = ['auth.group', 'auth.user', 'passports.season', 'passports.venue']


def _dump():
    # What `dumpdata <MODELS> --natural-foreign --natural-primary` produces
    # (it serializes each model's default manager this same way) — called
    # directly because dumpdata itself sees no rows inside this test harness.
    objects = [obj for label in MODELS for obj in apps.get_model(label)._default_manager.order_by('pk')]
    return serializers.serialize('json', objects, use_natural_foreign_keys=True, use_natural_primary_keys=True)


def test_transfer_matches_existing_rows_by_natural_key(tmp_path):
    # --- source (Railway)
    logger_group = Group.objects.create(name='Passport Logger')
    logger_group.permissions.add(Permission.objects.get(codename='add_passportsubmission'))
    Group.objects.create(name='Site Admin')
    alice = User.objects.create_user('alice', password='source-pass-1', is_staff=True, first_name='Alice')
    alice.groups.add(logger_group)
    Season.objects.create(name='2026', is_current=True)
    for n in (1, 2, 3):
        Venue.objects.create(number=n, name=f'Railway Venue {n}')
    dump = _dump()
    assert all('pk' not in obj for obj in json.loads(dump) if obj['model'] in ('passports.venue', 'passports.season', 'auth.user', 'auth.group'))

    # --- target (Krystal): wipe, then pre-existing overlapping rows at other ids
    User.objects.all().delete()
    Group.objects.all().delete()
    Venue.objects.all().delete()
    Season.objects.all().delete()
    for _ in range(5):  # push ids forward so nothing lines up by pk
        Venue.objects.create(number=250 + _, name='filler').delete()
    Venue.objects.create(number=2, name='Old Krystal name')
    Season.objects.create(name='2026', is_current=True)
    User.objects.create_superuser('krystal-admin', 'k@example.com', 'x')
    User.objects.create_user('alice', password='target-pass', is_staff=False)

    path = tmp_path / 'reference_data.json'
    path.write_text(dump, encoding='utf-8')
    call_command('loaddata', str(path), verbosity=0)

    assert sorted(Venue.objects.values_list('number', 'name')) == [(1, 'Railway Venue 1'), (2, 'Railway Venue 2'), (3, 'Railway Venue 3')]
    assert list(Season.objects.values_list('name', 'is_current')) == [('2026', True)]
    assert User.objects.filter(username='alice').count() == 1
    alice = User.objects.get(username='alice')
    assert alice.check_password('source-pass-1')  # password hash carried over as-is
    assert alice.is_staff and alice.first_name == 'Alice'
    assert list(alice.groups.values_list('name', flat=True)) == ['Passport Logger']
    assert Group.objects.get(name='Passport Logger').permissions.filter(codename='add_passportsubmission').exists()
    assert User.objects.filter(username='krystal-admin').exists()  # untouched
