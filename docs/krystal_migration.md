# Krystal migration runbook

Deploying the Django Passport app to Krystal alongside MARK's WordPress site, and
settling the account's domains. See [CLAUDE.md](../CLAUDE.md) for current status.

**Status (29 Sep 2026):** Phases 0–2 done. The app is **live on Krystal** at
staging.bikeandbrew.org (its database is the production database). Phase 3, the domain
layout below, is **on hold with the WordPress handover** and needs no data migration.

## Domain layout (decided 29 Sep 2026)

Krystal's Amethyst plan allows **one domain**. Today that slot holds Krystal's placeholder
(`3cfd762f3c16f59d5ea876245a8e5714-17604.sites.k-hosting.co.uk`), and bikeandbrew.org is an
**alias** of it. Target:

| Address | Role | Counts toward the one domain? |
|---|---|---|
| **makeyourmark.co.uk** | The account's main domain: the public WordPress site. The charity's public face stays here. | Yes: the one domain |
| **Passport app subdomain** of makeyourmark.co.uk (name to choose, e.g. `passport.` or `passports.`) | The Passport app, folder `~/bikerpassport` | No (subdomain) |
| **bikeandbrew.org** | Alias that **redirects** to the app subdomain, so trustees', ambassadors' and volunteers' links keep working | No (alias) |
| staging.bikeandbrew.org | Today's app address; redirect to the app subdomain afterwards | No (subdomain) |
| makeyourmark.co.uk/bike-and-brew (optional) | Public page for the fundraising programme, on WordPress | n/a |

Railway keeps www.steve-newman.com as the test site; it is no longer part of this plan.

Why: makeyourmark.co.uk is the domain the charity markets, so it should hold the slot; the
app is an internal tool used by trustees, ambassadors and volunteers, and sits under the
charity's name as a subdomain. Emails already send from `@passports.makeyourmark.co.uk`.

**Confirm with Krystal before Phase 3:** (1) that aliases and subdomains don't count toward
the Amethyst one-domain limit; (2) whether renaming the main domain is a cPanel, client-area
or support job.

**Hard constraint on WordPress:** Steve does not want WordPress's files moved, ever. Nothing
below moves them: WordPress stays in `public_html`, served by the main domain.

### Phase 0 — Discovery (no live impact)
1. ~~Confirm cPanel > Domains lets you edit the Primary Domain's document root~~ — **checked 2026-09-24:** bikeandbrew.org is a parked domain (alias), which has no document-root setting; see the finding at the top and the revised Phase 3.
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

### Phase 3 — Domain switchover (ON HOLD — do together with the WordPress handover)

Only makeyourmark.co.uk's DNS move affects the public; the app keeps working at
staging.bikeandbrew.org throughout, and no data moves.

1. **A day ahead:** at GoDaddy, lower the TTL on makeyourmark.co.uk's DNS records. Export or
   screenshot the whole zone (MX/email records especially), including the Resend records
   under `passports.makeyourmark.co.uk` (they must survive the move, or confirmation
   emails stop).
2. **Check WordPress's Site URL** (wp-admin → Settings → General). Note it; it must become
   `https://makeyourmark.co.uk` in step 4.
3. **Rename the main domain** from the k-hosting placeholder to `makeyourmark.co.uk`
   (cPanel/client area/Krystal support, per the check above). bikeandbrew.org stays an alias.
4. **Update WordPress's Site Address and Home URL** to `https://makeyourmark.co.uk`
   (Settings → General, or WP-CLI `search-replace` for hard-coded links).
5. **Point makeyourmark.co.uk at Krystal:** either move its nameservers to Krystal (then
   recreate the step 1 records in cPanel Zone Editor) or keep GoDaddy DNS and change the
   apex/www records to Krystal's IP. Wait for propagation; confirm WordPress loads at
   https://makeyourmark.co.uk.
6. **Create the app subdomain** in cPanel → Domains: `<app>.makeyourmark.co.uk`, **untick
   "Share document root"**, folder `bikerpassport` (it holds the Passenger `.htaccess`, so the
   app answers on any domain whose root is that folder; check it does). Add its DNS record if
   DNS stays at GoDaddy.
7. **App settings** in `~/bikerpassport/.env`: add the subdomain to `DJANGO_ALLOWED_HOSTS` and
   `https://<app>.makeyourmark.co.uk` to `DJANGO_CSRF_TRUSTED_ORIGINS`; set
   `DJANGO_PUBLIC_BASE_URL=https://<app>.makeyourmark.co.uk`. Keep the staging entries until
   step 9. Restart the app.
8. **cPanel → SSL/TLS Status → Run AutoSSL**, and confirm certificates for makeyourmark.co.uk
   and the app subdomain.
9. **Redirects:** cPanel → Domains → Redirects: `bikeandbrew.org` (and `www.`) and
   `staging.bikeandbrew.org` → `https://<app>.makeyourmark.co.uk/` (permanent, 301).
10. **Smoke test:** WordPress at makeyourmark.co.uk; app login and a test intake at the new
    subdomain (LOADTEST data, then `loadtest_fixtures --cleanup`); old addresses redirect;
    a confirmation email's links use the new address; the Krystal footer credit shows.
11. Tell trustees, ambassadors and volunteers the new address (the old ones keep redirecting).

**Rollback:** WordPress never moves, so undo = reverse the DNS change and the domain rename;
the app stays reachable at staging.bikeandbrew.org until step 9, so keep the redirects last.

### Phase 4 — Harden & decommission
- Django is staff-only by app login already, but the domain is still publicly reachable — consider `robots.txt` disallow-all and/or cPanel directory password protection / IP allowlist given real PII is involved.
- Set real (not staging) env vars for `DJANGO_ALLOWED_HOSTS` etc. on Krystal.
- Railway: decided — it stays the test site (www.steve-newman.com), with a plan-only fallback in [railway_fallback.md](railway_fallback.md).
- Update SPEC.md / other memory once done — several existing notes (Railway as the live host, bikeandbrew.org on WordPress) will be stale.

### Rollback
Phases 0–2 are done. Phase 3 has its own rollback note above.



## History

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
