#!/bin/bash
# Who is using the Krystal app right now — run before a deploy.
#
# Run in cPanel Terminal or over SSH:
#     bash ~/bikerpassport/scripts/recent_activity.sh
#
# Read-only. See passports/management/commands/recent_activity.py.

set -euo pipefail

# shellcheck disable=SC1091
source /home/cfdfcfde/virtualenv/bikerpassport/3.12/bin/activate
cd /home/cfdfcfde/bikerpassport
python manage.py recent_activity
