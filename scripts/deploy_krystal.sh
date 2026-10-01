#!/bin/bash
# Release the latest master to Krystal (staging.bikeandbrew.org).
#
# Run in cPanel Terminal or over SSH:
#     bash ~/bikerpassport/scripts/deploy_krystal.sh
#
# Stops at the first failure. Safe to re-run: every step does nothing if
# there's nothing new. Wrapped in main() so bash reads the whole script
# before `git pull` can change this file underneath it.

set -euo pipefail

APP_DIR=/home/cfdfcfde/bikerpassport
VENV=/home/cfdfcfde/virtualenv/bikerpassport/3.12/bin/activate
SITE_URL=https://staging.bikeandbrew.org

step() { echo; echo "=== $* ==="; }

main() {
    # shellcheck disable=SC1090
    source "$VENV"
    cd "$APP_DIR"

    step "Checking for local changes"
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        git status --short --untracked-files=no
        echo "Files have been edited on the server. Sort these out first - nothing has been changed."
        exit 1
    fi

    step "Fetching from GitHub"
    git fetch origin master
    local before
    before=$(git rev-parse HEAD)
    if [ "$before" = "$(git rev-parse origin/master)" ]; then
        echo "Already up to date - continuing anyway (migrate/collectstatic/restart are harmless)."
    else
        echo "New commits:"
        git log --oneline HEAD..origin/master
    fi
    git merge --ff-only origin/master

    if ! git diff --quiet "$before" HEAD -- requirements.txt; then
        step "requirements.txt changed - installing packages"
        pip install -r requirements.txt
    fi

    step "Checking the app"
    python manage.py check

    step "Migrations to apply"
    python manage.py showmigrations --plan | grep '^\[ \]' || echo "(none)"

    step "Migrating the database"
    python manage.py migrate --noinput

    step "Collecting static files"
    python manage.py collectstatic --noinput

    step "Restarting the app"
    mkdir -p tmp
    touch tmp/restart.txt

    step "Checking the site responds"
    sleep 5
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' "$SITE_URL/admin/login/" || true)
    if [ "$code" = "200" ]; then
        echo "Login page OK (200). Now at: $(git log --oneline -1)"
    else
        echo "Login page returned '$code' - check the site, and cPanel > Setup Python App > Restart."
        exit 1
    fi
}

main "$@"
