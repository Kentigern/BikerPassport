import json
import os
import subprocess
import sys

import pytest

from passports.models import Season

pytestmark = pytest.mark.django_db


class TestOneCurrentSeason:
    # The database constraint doesn't exist on MariaDB (Krystal), so the rule
    # has to hold through Season.save() alone.

    def test_marking_a_season_current_unmarks_the_old_one(self):
        old = Season.objects.create(name='2026', is_current=True)
        new = Season.objects.create(name='2027', is_current=True)

        old.refresh_from_db()
        assert (old.is_current, new.is_current) == (False, True)
        assert Season.objects.current() == new

    def test_re_marking_the_old_season_swaps_back(self):
        old = Season.objects.create(name='2026', is_current=True)
        new = Season.objects.create(name='2027', is_current=True)
        old.is_current = True
        old.save()

        new.refresh_from_db()
        assert list(Season.objects.filter(is_current=True)) == [old]
        assert new.is_current is False

    def test_saving_a_non_current_season_leaves_the_current_one_alone(self):
        current = Season.objects.create(name='2026', is_current=True)
        Season.objects.create(name='2025', is_current=False)

        current.refresh_from_db()
        assert current.is_current is True


def test_mysql_connections_use_strict_mode():
    # Settings are read once per process, so check a MySQL DATABASE_URL in a
    # fresh one (no database connection is made).
    env = {**os.environ, 'DATABASE_URL': 'mysql://user:pw@localhost/db?ssl_disabled=true', 'DJANGO_SETTINGS_MODULE': 'config.settings'}
    code = 'from django.conf import settings; import json; print(json.dumps(settings.DATABASES["default"]["OPTIONS"]))'
    out = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, check=True).stdout
    options = json.loads(out.strip().splitlines()[-1])
    assert options['init_command'] == "SET sql_mode='STRICT_TRANS_TABLES'"
    assert options['ssl_disabled'] is True  # the Krystal fix from DATABASE_URL survives
