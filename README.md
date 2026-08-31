# Bike + Brew Passport Processing System

Internal staff tool for Make Your Mark's annual Bike + Brew fundraiser — see
[SPEC.md](SPEC.md) for the full specification.

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

6. (Optional) Load the venue list from a CSV with `Number,Name,Address` columns — `page_scans/all_venues.csv` has the current season's 296 venues, OCR'd from the passport scans:

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
- **New submission** (`/passports/submissions/new/`, also linked from the submissions admin page and the landing page) — the fast passport-intake form: search for an existing bearer by name/phone or enter a new one, check off stamped venues, and save. The same form (`/passports/submissions/<id>/edit/`) is used to correct an existing submission. Two venue-checklist styles, toggleable per staff member (remembered via the browser's local storage): **List view** (searchable, scrolling, default) and **Book view** (a paginated 4-column grid echoing the physical passport's own page layout, 12 venues per page).
- **Audit history** — open a Bearer or Passport submission in the admin and click **History** (top right of its page) to see every change, who made it, and when — including edits made through the intake form, not just the admin.

## Project layout

- `config/` — Django project settings/urls
- `passports/` — domain app: `Season`, `Venue`, `Bearer`, `PassportSubmission` models, the intake form (`forms.py`/`views.py`/`templates/passports/submission_form.html`), and Django admin registration
- `page_scans/` — scanned passport pages and the OCR'd venue list

## Switching to PostgreSQL

Set `POSTGRES_DB` (and `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_HOST`/`POSTGRES_PORT` as needed) in `.env` — leaving `POSTGRES_DB` unset falls back to SQLite.
