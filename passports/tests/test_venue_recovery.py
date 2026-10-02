"""Venue reports linked to their venue and season, and the "Venues by
season" admin list built on them (kit recovery)."""
import importlib
import re

import pytest
from django.apps import apps
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.utils import timezone

from passports.models import PublicMessage, Season, Venue, VenueSeason

pytestmark = pytest.mark.django_db

LIST_URL = '/admin/passports/venueseason/'


@pytest.fixture
def admin_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_superuser(username='admin', password='x'))
    return client


def make_report(venue, season, **kwargs):
    data = {
        'name': 'Pat Jones', 'ambassador_number': 17, 'venue_name': venue.name, 'venue_number': venue.number,
        'venue': venue, 'season': season, 'report_date': timezone.localdate(), 'stamp': True,
    }
    data.update(kwargs)
    return PublicMessage.objects.create(**data)


def test_report_from_the_form_is_linked_to_venue_and_season(client, settings, monkeypatch, season, venues):
    settings.PUBLIC_MESSAGES_ENABLED = True
    monkeypatch.setattr('passports.public_views.MIN_FILL_SECONDS', 0)
    cache.clear()
    started = client.get('/message/').context['started']
    client.post('/message/', data={
        'name': 'Pat Jones', 'ambassador_number': '17', 'venue_name': 'Anywhere', 'venue_number': '5',
        'stamp': 'on', 'message': '', 'reply_to': '', 'website': '', 'started': started,
    })
    report = PublicMessage.objects.get()
    assert report.venue == Venue.objects.get(number=5) and report.season == season


def test_list_creates_a_row_per_active_venue_for_the_current_season(admin_client, season, venues):
    Venue.objects.filter(number=3).update(is_active=False)
    assert admin_client.get(LIST_URL).status_code == 200
    rows = VenueSeason.objects.filter(season=season)
    assert rows.count() == len(venues) - 1 and not rows.filter(venue__number=3).exists()
    assert set(rows.values_list('recovery_status', flat=True)) == {'outstanding'}
    admin_client.get(LIST_URL)  # opening it again adds nothing
    assert rows.count() == len(venues) - 1


def test_list_shows_report_count_and_latest_kit(admin_client, season, venues):
    venue = venues[4]
    make_report(venue, season, stamp=False)
    make_report(venue, season, second_stamp=True, unused_passports=True, passports_collected=12)
    make_report(venue, Season.objects.create(name='2025'))  # another season's: not counted
    page = admin_client.get(LIST_URL).content.decode()
    assert f'?venue__id__exact={venue.pk}&season__id__exact={season.pk}">2</a>' in page
    row = page[page.index(f'>Venue {venue.number}<'):]
    row = row[:row.index('</tr>')]
    assert f'{timezone.localdate():%d %b} (Pat Jones)' in row
    assert '>12</td>' in row  # passports collected
    # stamp, 2nd stamp, inkpad, folder, stationery, for validation
    assert re.findall(r'icon-(yes|no)', row) == ['yes', 'yes', 'no', 'no', 'no', 'no']


def test_validation_passports_column_shows_the_count(admin_client, season, venues):
    make_report(venues[0], season, validation_passports=True, validation_collected=5)
    page = admin_client.get(LIST_URL).content.decode()
    row = page[page.index('>Venue 1<'):]
    row = row[:row.index('</tr>')]
    assert '<td class="field-kit_validation">5</td>' in row


def test_kit_columns_are_blank_without_a_report(admin_client, season, venues):
    page = admin_client.get(LIST_URL).content.decode()
    row = page[page.index('>Venue 1<'):]
    row = row[:row.index('</tr>')]
    assert 'icon-yes' not in row and 'icon-no' not in row


def test_reported_filter(admin_client, season, venues):
    make_report(venues[0], season)
    admin_client.get(LIST_URL)
    yes = admin_client.get(LIST_URL, {'reported': 'yes', 'season__id__exact': season.pk})
    no = admin_client.get(LIST_URL, {'reported': 'no', 'season__id__exact': season.pk})
    assert [r.venue for r in yes.context['cl'].result_list] == [venues[0]]
    assert venues[0] not in [r.venue for r in no.context['cl'].result_list]
    assert len(no.context['cl'].result_list) == len(venues) - 1


def test_reports_link_opens_that_venues_reports(admin_client, season, venues):
    make_report(venues[0], season)
    make_report(venues[1], season, name='Someone Else')
    page = admin_client.get(
        '/admin/passports/publicmessage/', {'venue__id__exact': venues[0].pk, 'season__id__exact': season.pk}
    )
    assert page.status_code == 200
    assert [r.venue for r in page.context['cl'].result_list] == [venues[0]]


def test_status_can_be_set_and_is_audited(admin_client, season, venues):
    admin_client.get(LIST_URL)
    row = VenueSeason.objects.get(season=season, venue=venues[0])
    resp = admin_client.post(f'{LIST_URL}{row.pk}/change/', {'recovery_status': 'kept', 'recovery_notes': 'Back next year'})
    assert resp.status_code == 302
    row.refresh_from_db()
    assert row.recovery_status == 'kept' and row.history.count() == 1


def test_site_admin_group_is_granted_access():
    group = Group.objects.create(name='Site Admin')
    migration = importlib.import_module('passports.migrations.0027_link_reports_grant_venueseason')
    migration.grant_permissions(apps, None)
    assert set(group.permissions.values_list('codename', flat=True)) == {'view_venueseason', 'change_venueseason'}
