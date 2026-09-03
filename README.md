# Bike + Brew Passport Processing System

Internal staff tool for Make Your Mark's annual Bike + Brew fundraiser — see
[SPEC.md](SPEC.md) for the full specification.

Repository: https://github.com/Kentigern/BikerPassport

## Requirements

- Python 3.11+
- PostgreSQL (production) — SQLite works fine for local dev, no extra setup needed

## Setup

1. Create and activate a virtualenv:

   ```sh
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   source .venv/bin/activate   # macOS/Linux
   ```

2. Install dependencies:

   ```sh
   pip install -r requirements.txt
   ```

3. Copy the environment template and adjust as needed (defaults are fine for local dev — SQLite database, console email backend):

   ```sh
   copy .env.example .env      # Windows
   cp .env.example .env        # macOS/Linux
   ```

4. Apply migrations:

   ```sh
   python manage.py migrate
   ```

5. Create a staff/admin login:

   ```sh
   python manage.py createsuperuser
   ```

6. (Optional) Load the venue list from a CSV with `Number,Name,Address` columns (plus optional `image_file`, imported as `page_group` — which page-spread each venue appears on in the physical book, used by the intake form's Book view) — `page_scans/all_venues.csv` has the current season's 296 venues, OCR'd from the passport scans:

   ```sh
   python manage.py load_venues page_scans/all_venues.csv
   ```

7. Create a `Season` and mark it current — the intake form needs one to default to. Easiest via the admin (`/admin/passports/season/add/`), or:

   ```sh
   python manage.py shell -c "from passports.models import Season; Season.objects.create(name='2026', is_current=True)"
   ```

8. Run the dev server:

   ```sh
   python manage.py runserver
   ```

   Then visit `http://127.0.0.1:8000/admin/` and log in.

## Using the app

- **Landing page** (`/passports/`) — a single "Log a Submission" button, the entry point for Passport Logger-type staff whose only job is intake. Good URL to bookmark/hand out to volunteers instead of `/admin/`.
- **Admin** (`/admin/`) — manage seasons, venues, and look up/correct existing bearers and submissions.
- **New submission** (`/passports/submissions/new/`, also linked from the submissions admin page and the landing page) — the fast passport-intake form: search for an existing bearer by name/phone or enter a new one, check off stamped venues, and save. The same form (`/passports/submissions/<id>/edit/`) is used to correct an existing submission. Two venue-checklist styles, toggleable per staff member (remembered via the browser's local storage): **List view** (searchable, scrolling, default) and **Book view** (a paginated 4-column grid echoing the physical passport's own page layout, including its real section breaks).
- **Audit history** — open a Bearer or Passport submission in the admin and click **History** (top right of its page) to see every change, who made it, and when — including edits made through the intake form, not just the admin.

## Running tests

Browser-driven end-to-end tests (Playwright, via `pytest-playwright`) live under `passports/tests/`. They spin up a real local server (`pytest-django`'s `live_server`) and drive an actual browser against it — no separate `manage.py runserver` needed.

```sh
pip install -r requirements-dev.txt
python -m playwright install chromium   # one-time browser download
python -m pytest
```

Add `--headed` to watch the browser as tests run (and `--slowmo=200`, say, to slow it down enough to follow), or leave both off for a fast headless run.

## Project layout

- `config/` — Django project settings/urls
- `passports/` — domain app: `Season`, `Venue`, `Bearer`, `PassportSubmission` models, the intake form (`forms.py`/`views.py`/`templates/passports/submission_form.html`), and Django admin registration
- `page_scans/` — scanned passport pages and the OCR'd venue list

## Switching to PostgreSQL

Set `DATABASE_URL` (a single connection string, as Railway's Postgres plugin provides), or the split `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_HOST`/`POSTGRES_PORT` vars, in `.env` — leaving both unset falls back to SQLite.

## Deploying to Railway

The app is set up to deploy as-is via Railway's `Procfile`-based build (gunicorn + WhiteNoise for static files, no separate static-hosting service needed):

1. Create a new Railway project from this repo, and add a **Postgres** plugin to it — Railway wires its `DATABASE_URL` into the app service automatically.
2. Set these environment variables on the app service:
   - `DJANGO_SECRET_KEY` — a real, random secret (**do not** leave this unset — the fallback in `config/settings.py` is for local dev only and is committed to the repo, so it must never be used publicly).
   - `DJANGO_DEBUG=False`
   - `DJANGO_ALLOWED_HOSTS` — the Railway-assigned domain, e.g. `your-app.up.railway.app` (a leading dot, `.up.railway.app`, matches any subdomain if useful).
   - `DJANGO_CSRF_TRUSTED_ORIGINS` — the same host with scheme, e.g. `https://your-app.up.railway.app` (required — without it, login and every form submission fail with a CSRF error, since Railway's proxy sits in front of the app).
   - `DJANGO_SECURE_HSTS_SECONDS` (optional) — defaults to `3600` once `DJANGO_DEBUG=False`. Raise it (eventually to `31536000`, one year) only after confirming HTTPS works reliably on every domain in use — browsers cache this and getting it wrong locks visitors out until it expires.
3. Deploy. The `Procfile`'s `release` phase runs `collectstatic` and `migrate` automatically on every deploy; `web` starts gunicorn.
4. One-time, via Railway's shell (`railway run` or the dashboard's shell tab) against the deployed app:

   ```sh
   python manage.py createsuperuser
   python manage.py load_venues page_scans/all_venues.csv
   python manage.py shell -c "from passports.models import Season; Season.objects.create(name='2026', is_current=True)"
   ```

Email defaults to the console backend (i.e. emails aren't actually sent) unless `DJANGO_EMAIL_*` vars are set — fine for a demo.
