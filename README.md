# Bike + Brew Passport Processing System

Internal staff tool for Make Your Mark's annual Bike + Brew fundraiser — see
[SPEC.md](SPEC.md) for the full specification.

## Requirements

- Python 3.11+
- PostgreSQL (production) — SQLite works fine for local dev, no extra setup needed

## Setup

1. Create and activate a virtualenv:

   ```
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   source .venv/bin/activate   # macOS/Linux
   ```

2. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

3. Copy the environment template and adjust as needed (defaults are fine for local dev — SQLite database, console email backend):

   ```
   copy .env.example .env      # Windows
   cp .env.example .env        # macOS/Linux
   ```

4. Apply migrations:

   ```
   python manage.py migrate
   ```

5. Create a staff/admin login:

   ```
   python manage.py createsuperuser
   ```

6. (Optional) Load the venue list from a CSV with `Number,Name,Address` columns — `page_scans/all_venues.csv` has the current season's 296 venues, OCR'd from the passport scans:

   ```
   python manage.py load_venues page_scans/all_venues.csv
   ```

7. Run the dev server:

   ```
   python manage.py runserver
   ```

   Then visit `http://127.0.0.1:8000/admin/` and log in.

## Project layout

- `config/` — Django project settings/urls
- `passports/` — domain app: `Season`, `Venue`, `Bearer`, `PassportSubmission` models, registered in the Django admin
- `page_scans/` — scanned passport pages and the OCR'd venue list

## Switching to PostgreSQL

Set `POSTGRES_DB` (and `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_HOST`/`POSTGRES_PORT` as needed) in `.env` — leaving `POSTGRES_DB` unset falls back to SQLite.
