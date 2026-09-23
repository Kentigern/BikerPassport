# Krystal migration runbook

Deploying the Django app to Krystal (production) alongside MARK's existing
WordPress site, moving **bikeandbrew.org** to Django and giving WordPress
**steve-newman.com** as a temporary domain. Agreed 2026-09-20; progress notes at
the end. See [CLAUDE.md](../CLAUDE.md) for the current Day 1 status.

**Status (2026-09-23):** Phase 0 and Phase 1 done (staging live at
staging.bikeandbrew.org). Phase 2 next, narrowed to reference data only — see
[scripts/transfer_reference_data.txt](../scripts/transfer_reference_data.txt).
Phases 3–4 not started.


Detailed runbook, agreed with the user on 2026-09-20, for the three-part migration: deploy Django to Krystal, give Django the bikeandbrew.org domain, and give WordPress steve-newman.com as a temporary replacement domain. 

**Hard constraint driving the sequencing:** makeyourmark.co.uk (WordPress's eventual real domain) is still on GoDaddy, not pointed at Krystal — bikeandbrew.org is WordPress's *only* live public domain right now. So bikeandbrew.org can't be handed to Django until steve-newman.com is already live serving WordPress, or the public WordPress site goes dark in between. The three user-stated steps have to become one coordinated cutover for the domain-swap parts, not three independent sequential actions.

**Hard constraint on WordPress:** the user explicitly does not want WordPress's files moved/relocated, ever. The resolved approach is a config-only split: Django gets a brand-new folder; bikeandbrew.org's *document-root mapping* is repointed to that new folder (cPanel lets you edit which folder a domain — including the Primary Domain — points to, independent of what's already there); steve-newman.com is added as a second Addon Domain whose document root is set to WordPress's *existing, untouched* `public_html`. Multiple domains sharing one document root is a standard cPanel pattern (classic "Parked Domain" behavior). WordPress's own canonical URL (Settings > General / wp_options) still needs updating to steve-newman.com — a settings edit, not a file move — and again later to makeyourmark.co.uk when that's ready, with no further file moves either time.

### Phase 0 — Discovery (no live impact)
1. Confirm cPanel > Domains lets you edit the Primary Domain's document root independently (this is the crux of the whole no-move approach).
2. Confirm Python version options in Setup Python App include 3.10+ (app runs 3.11 locally, needs Django 5.2).
3. Confirm shell/SSH access works (resolved: Krystal support enables SSH on request) or find the GUI pip-install/execute-script alternative if Krystal's build has one.
4. Confirm cPanel > Git Version Control is available for deploying from `Kentigern/BikerPassport` on GitHub.
5. Pick a temporary staging hostname to fully test the Django deploy before touching any real domain.

### Phase 1 — Deploy Django to Krystal as a new sibling app (not yet live to the public)
Code changes (done — `passenger_wsgi.py`, PyMySQL shim in `config/__init__.py`):
- Add `passenger_wsgi.py` at repo root — Krystal's Setup Python App/Passenger needs this specific entrypoint, not `config/wsgi.py` directly.
- Add `PyMySQL` to `requirements.txt` + `pymysql.install_as_MySQLdb()` in `config/__init__.py` — lets the existing `django.db.backends.mysql` engine work without needing the compiled `mysqlclient` driver. No `settings.py` changes needed — `dj_database_url.parse()` already handles `mysql://` URLs, and the app has no Postgres-only field types.
- WhiteNoise needs no changes — plain WSGI middleware, host-agnostic.

Manual steps: create the MySQL DB/user in cPanel, set up the Python App pointed at a git-cloned copy of the repo, populate a `.env` in the app dir (same `python-dotenv` pattern as local dev) with `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DATABASE_URL=mysql://...`, `RESEND_API_KEY`, `DJANGO_DEFAULT_FROM_EMAIL`, `DJANGO_PUBLIC_BASE_URL`, then `pip install -r requirements.txt` and `python manage.py migrate`.

**Known gotcha to test explicitly once staging is up:** `settings.py`'s `SECURE_PROXY_SSL_HEADER` assumes a reverse-proxy TLS setup copied from Railway's model. Krystal's Apache+Passenger terminates TLS directly — if it doesn't forward `X-Forwarded-Proto`, every request looks insecure to Django (breaks CSRF, secure cookies, can cause an HTTPS redirect loop). Test an HTTPS POST on staging specifically before relying on it.

### Phase 2 — Data migration (Railway Postgres → Krystal MySQL)
Cross-engine, so goes through Django's ORM, not a raw SQL dump:
1. On Railway (`railway ssh -s BikerPassport`): `python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission -e admin.logentry -e sessions > data.json`
2. Copy `data.json` to Krystal via SFTP (works today, independent of the shell-access blocker).
3. On Krystal, after `migrate`: `python manage.py loaddata data.json`.
4. Spot-check counts (bearers, submissions, users, groups+permissions incl. Passport Logger) match Railway's.
5. Re-run `backfill_submission_locks` (dry run) on Krystal — should report zero unlocked, confirming the data (already backfilled on Railway) came across intact.
This is a rehearsal now; repeat with a fresh dump right before the real cutover so the final dataset isn't stale.

### Phase 3 — The coordinated cutover
1. A day ahead: lower DNS TTLs for steve-newman.com/www at GoDaddy.
2. In cPanel, create Django's new app folder (WordPress's `public_html` untouched).
3. Add steve-newman.com as an Addon Domain, document root = existing `public_html`.
4. Update WordPress's Site Address/Home URL to steve-newman.com (wp-admin > Settings > General, or WP-CLI `search-replace` for hardcoded links).
5. At GoDaddy, repoint `www.steve-newman.com`/apex forwarding from Railway to Krystal's addon-domain target; wait for propagation; confirm WordPress loads at steve-newman.com.
6. Repoint bikeandbrew.org's document root from `public_html` to Django's new folder.
7. Re-run the data migration (fresh dump) right before step 6.
8. cPanel SSL/TLS Status > Run AutoSSL for both domains.
9. Smoke test both live domains fully.

### Phase 4 — Harden & decommission
- Django is staff-only by app login already, but the domain is still publicly reachable — consider `robots.txt` disallow-all and/or cPanel directory password protection / IP allowlist given real PII is involved.
- Set real (not staging) env vars for `DJANGO_ALLOWED_HOSTS` etc. on Krystal.
- Decide Railway's fate once bikeandbrew.org has run cleanly on Krystal for a while — decommission, or keep briefly as a fallback (same pattern as the existing `bikenbrew-demo` fallback project).
- Update SPEC.md / other memory once done — several existing notes (Railway as the live host, bikeandbrew.org on WordPress) will be stale.

### Rollback
Phases 0–2 touch nothing live, fully abandonable. Phase 3 is the only risky window — keep Railway's Django deployment running untouched until Phase 3 step 9 passes, and know WordPress's original state (it never physically moves, so revert = undo the domain remaps + GoDaddy DNS) as a rehearsed procedure, not something improvised under pressure.



### Progress as of 2026-09-20 (end of session)

Phase 1 is done and verified working — a live staging deploy exists at **staging.bikeandbrew.org** (a subdomain created specifically for this, pointing at a sibling folder `~/bikerpassport`, per the account's account-root, NOT under `public_html` — WordPress's dev/staging copy in `public_html` was never touched, confirming the no-move approach holds). Concretely, in order:
- Krystal support granted SSH/terminal access on request (the self-service Client Area toggle wasn't sufficient on its own — needed an explicit support-side grant).
- Krystal's cPanel build **does** have the GUI "Run Pip Install" and "Execute Python Script" buttons on the Setup Python App page (resolves the earlier uncertainty) — used for `pip install -r requirements.txt`, `manage.py migrate`, `manage.py collectstatic --noinput`, and `manage.py createsuperuser --noinput`. Only `git` operations needed the actual SSH terminal.
- The app's folder (`bikerpassport`) already had cPanel's standard new-subdomain boilerplate (`cgi-bin`, `.htaccess`, `.well-known`) before the code went in — the repo doesn't track any of those paths, so bringing the code in was `rm passenger_wsgi.py` (cPanel's placeholder) then `git init && git remote add origin ... && git fetch origin master && git checkout -f master` **in place**, not a plain `git clone` (which refuses a non-empty target directory).
- Repo is public on GitHub — confirmed via an anonymous `git ls-remote`, so no deploy key/PAT was needed for the clone.
- **Real bug hit and fixed: `collectstatic` had never been run.** WhiteNoise's `CompressedManifestStaticFilesStorage` needs its manifest file to exist before any `{% static %}` tag can resolve — without it, the Django admin login page itself (which every page redirects to) throws a hard 500. Fix: run `manage.py collectstatic --noinput` via the Execute Python Script button.
- **Real bug hit and fixed: MySQL connection failed with `OperationalError (2006, "MySQL server has gone away (SSLEOFError...")`.** PyMySQL was attempting an SSL/TLS handshake by default against Krystal's local MySQL, which broke mid-handshake. Fix (verified locally, not guessed): append `?ssl_disabled=true` to the `DATABASE_URL` value in `.env` — confirmed via local inspection that `dj_database_url.parse()` turns URL query params straight into `OPTIONS`, and Django's mysql backend passes `OPTIONS` straight through as kwargs to `pymysql.connect()`, which accepts `ssl_disabled`. **Remember this exact fix for the real bikeandbrew.org `.env` later too**, not just staging's.
- A temporary superuser was created via `.env`'s `DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD` + `manage.py createsuperuser --noinput` (the Execute Python Script field can't handle interactive prompts) — those three lines get removed from `.env` again after use.
- End-to-end confirmed working: Passenger → MySQL via PyMySQL → WhiteNoise static files → Django admin login, all on the staging subdomain.

**Next session starts at Phase 2**: migrate real data from Railway's Postgres into this Krystal MySQL DB via `dumpdata`/`loaddata` (not a raw SQL dump — cross-engine). The exact commands are already written out earlier in this file under "Phase 2".

**User's chosen scope for that first migration (set 2026-09-20, for the next session):** deliberately narrow, not the full dataset in one go —
1. `auth.Group` + `auth.User` + users' group memberships (i.e. the real staff accounts and the Passport Logger/Site Admin groups) — but NOT Bearer/PassportSubmission data yet.
2. `passports.Season`
3. `passports.Venue`

**Correction (2026-09-20): Bearer/PassportSubmission data currently in the system (Railway included) is all test data, not real bearer PII**. The reason to skip migrating Bearers/PassportSubmissions now isn't about protecting real PII in transit — it's simply that test data isn't worth carrying over. Real bearer data will presumably start accumulating once actual intake begins (venue drop-off, post, the Oct 3-4 event), at which point it'll live on whichever host is actually production by then.

**Also queued for next session: get the Resend confirmation email working on Krystal** (the submission-confirmation email feature from `passports/emailing.py`/`resend_client.py`) — will need `RESEND_API_KEY` actually set in Krystal's `.env` at that point (deliberately left blank during Phase 1 to avoid any risk of sending real email before this was intentional).

**Update 2026-09-23:** Phase 2's narrow reference-data move (users, groups, memberships, seasons, venues) now has a tested runbook in the repo: `scripts/transfer_reference_data.txt`. Season and Venue got natural keys (name / number) so `dumpdata --natural-primary --natural-foreign` + `loaddata` match existing Krystal rows instead of clashing on ids. Export must be run from cmd/Git Bash, not PowerShell (UTF-16 `>`). Krystal `.env` will also need the new alert vars: `DJANGO_NOTES_ALERT_EMAILS`, `DJANGO_PUBLIC_MESSAGE_ALERT_EMAILS`, `DJANGO_PUBLIC_MESSAGES_ENABLED` (off by default).
