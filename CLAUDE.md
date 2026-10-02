# CLAUDE.md — Bike + Brew Passport system

Context for Claude Code sessions on this repo. Read with [SPEC.md](SPEC.md) (the
full spec) and [README.md](README.md) (setup). **Never put secrets in this repo**
(API keys, passwords, `.env` contents) — it is public on GitHub.

## Keeping this file current

Steve works on this repo from two PCs, each with its own Claude memory that does
**not** sync — this file is the shared memory. From 28 Sep 2026 his **personal PC** is the
main one (dev setup, Railway CLI and SSH key are there); the work PC is occasional. So:

- **Every push includes a CLAUDE.md update.** Before pushing, update "Current
  status", the Day 1 list, "Waiting on Steve", "Parked" and "Gotchas" to match
  what the commits being pushed change, and commit it with them. A project hook
  (`.claude/hooks/claude_md_before_push.sh`, wired in `.claude/settings.json`)
  refuses Claude's `git push` when CLAUDE.md isn't among the commits being
  pushed; if it genuinely needs no change, append `# claude-md-reviewed` to the
  push command. (The hook only sees pushes Claude runs, not VS Code's Sync button.)
- Anything worth remembering across sessions goes **here**, not only in local memory.
- At the start of a session, if the working tree is behind `origin/master`, suggest pulling first.

## What this is

Internal staff tool for Make Your Mark's (MARK) annual **Bike + Brew** charity
fundraiser. Bikers collect stamps at up to 296 numbered cafes/venues in a paper
passport; volunteers ("Passport Loggers") type each returned passport in; every
10 stamps earns a raffle ticket (cap 28). The system emails the bearer a
confirmation with their ticket numbers, and runs the raffle draw.

Owner: Steve (runs the project for the charity; non-developer stakeholders
include "the boss" at MARK). 30–40 volunteers will use it concurrently at peak.

## Stack

Django 5.2, Python 3.11, django-simple-history (audit log), WhiteNoise, Resend
(email API). SQLite locally; Postgres on Railway; MySQL (via PyMySQL) on Krystal.
Browser tests with pytest-playwright against `live_server`.

- `config/` — settings (all env-driven, see `.env.example`), urls
- `passports/` — the app: models, intake form (`views.py`, `static/passports/intake.js`),
  admin, `emailing.py` + `resend_client.py`, `public_views.py` (the only no-login page)
- `scripts/` — `loadtest/` (load-test kit), `transfer_reference_data.txt` (Railway→Krystal data copy)
- `docs/krystal_migration.md` — the production migration runbook

## Business rules that matter

- **One submission per bearer per season** (DB constraint). Bearer's phone is the
  unique identifying key and the access-control "secret" (§5.2 of SPEC): Loggers must search by
  phone before they can edit a bearer or see their phone. Superusers and (since 2 Oct 2026, as MARK
  has effectively one) Site Admins skip this check (`access.is_privileged`).
- **Save & Exit locks** a submission (and its bearer) for Loggers; Site Admins/superusers can still edit.
- **Raffle tickets** (`RaffleTicket`): issued at Save & Exit for every locked submission,
  email or not; sequential per season, zero-padded 6 digits (`000001`); **never
  renumbered or removed** once issued (they've been emailed). The export and the
  live draw work only from issued numbers; the draw reveals the winner's own number.
- **Confirmation email** (§5.3): sent once at Save & Exit via Resend, transactional —
  **no consent request** in it (raffle data needs none). Failures set
  `email_send_failed`; staff retry via the admin action or `retry_confirmation_emails`.
- **Notes alert**: Save & Exit with anything in Notes emails `DJANGO_NOTES_ALERT_EMAILS`.
- **Public page** `/message/` is the **ambassador venue report** (since 29 Sep 2026; was a general
  contact form): ambassador name/number, venue name/number (must be a real venue), today's
  date (server-set), collected kit (unused passports + count, stamp, inkpad, folder, stationery),
  notes, optional reply contact. Plain text only (letters, digits, ordinary punctuation). Off
  unless `DJANGO_PUBLIC_MESSAGES_ENABLED=True`; login-page link "Ambassador? Send a venue report".
- **Consent can't be sought by email.** MARK may not email bearers whose address it holds
  without permission, so there is **no consent-request email campaign** (Steve, 29 Sep 2026).
  Consent can only be recorded when the bearer gives it: in person at intake, or (future) a
  tick box printed on the paper passport. A bearer never asked stays `pending` and falls under
  the post-season retention purge.
- **Intake consent (1 Oct 2026, live on Krystal):** the capture form's bearer section asks two separate
  questions, each Not set (default) / Yes / No, with the answer date stamped: **keep contact
  details** after the season (`retention_consent_status`, was `next_season_…`, migration `0025`)
  and **use them for marketing** (`marketing_consent_status`). Saved by Save bearer *and* by
  Save / Save & Exit. Planned next (not built): before any use, an email to those who said Yes
  explaining what MARK will do with the data, with a no-login link to withdraw (`consent_token`).
  The parked bulk email now needs both consents granted; its unsubscribe withdraws marketing.
- Physical anti-duplicate safeguard: every processed passport's **corner is snipped**
  before it's returned (nothing in the data model tracks this).
- Three intake channels, same data model: left at a venue (volunteer collects),
  posted to Steve, or handed over in person at the **3–4 October 2026 event**
  (the most time-pressured case — keep intake fast).
- Raffle draw: yellow/black roulette wheel only (slot machine removed at MARK's request).

## Hosting

- **Railway** — **web app stopped 28 Sep 2026** (Krystal is live); Postgres left running with
  staff/venue data. Restart = redeploy the BikerPassport service. Was the test site, and is the planned **fallback** for real intake if Krystal
  can't be used: [docs/railway_fallback.md](docs/railway_fallback.md) (plan only, deliberately
  not pre-built; recovery takes ~half a day, starting with building `reset_intake_data`). Only one site may take intake at a time.
  Project "Make Your Mark", service "BikerPassport", deploys automatically from `master`;
  served at www.steve-newman.com (404 while stopped). Test data only. Disconnect the GitHub
  source in Railway settings, or any push to `master` restarts it.
  Start command runs `migrate` + `collectstatic`. Single gunicorn worker.
  **Variable changes need a Deploy/Redeploy** before the app sees them.
- **Krystal (production)** — shared cPanel hosting, Passenger + MySQL, same account as
  MARK's WordPress site; Python 3.12 there. SSH/cPanel Terminal venv:
  `source /home/cfdfcfde/virtualenv/bikerpassport/3.12/bin/activate && cd /home/cfdfcfde/bikerpassport`.
  The live app is at **staging.bikeandbrew.org** (folder `~/bikerpassport`, `.env` in the app
  folder). **Domain layout decided 29 Sep** ([docs/krystal_migration.md](docs/krystal_migration.md)):
  Amethyst plan = one domain; the main domain (today Krystal's k-hosting placeholder) becomes
  **makeyourmark.co.uk** (public WordPress), the app moves to a **subdomain of it**, and
  **bikeandbrew.org** stays an alias redirecting to the app. On hold with the WordPress handover. Krystal requires the footer
  credit "Hosting kindly provided by Krystal" (linked) — contractual, don't remove it.
- **Email**: Resend. The verified domain is the **subdomain `passports.makeyourmark.co.uk`**,
  so the sender must be `…@passports.makeyourmark.co.uk` (default
  `noreply@passports.makeyourmark.co.uk`). The bare `makeyourmark.co.uk` is NOT verified.

## Current status (1 Oct 2026 — on Steve's personal PC)

**Released to Krystal 1 Oct** (migrations up to `0025`): venue report "2nd stamp" box ("1 stamp"/
"2 stamps"); intake consent questions (see Business rules); MariaDB fixes (see Gotchas).

**Venue kit recovery (1 Oct, live on Krystal):** venue reports now link to their `Venue` and
`Season` (migrations `0026`/`0027`, which also backfill old reports and grant Site Admin access).
New model `VenueSeason` = a venue's part in one season; admin list **Venues by season** shows each
active venue's kit recovery status (Outstanding / Collected / Kept at venue for next year / Lost,
editable from the list), report count (links to its reports) last report (date, ambassador) and its kit as one column per item (passports count, stamp, 2nd stamp, inkpad, folder, stationery — blank if no report); filters
by season, status, "no report yet". Rows for the current season are created when the list is
opened. Deliberately the home for MARK's hoped-for venue management (recruitment stage, that
year's passport number, ambassador, contact details — `Venue` already has contact fields).
Steve's Gemini draft of a full venue management system (serialised assets, depot, routes) was
reviewed and judged too heavy; this lean version was agreed instead (draft not kept in the repo).

**Krystal releases** use [scripts/deploy_krystal.sh](scripts/deploy_krystal.sh) (pull, `check`, `migrate`,
`collectstatic`, restart, login-page check; stops at the first failure). In cPanel Terminal/SSH:
`bash ~/bikerpassport/scripts/deploy_krystal.sh` — the first time, `git pull` first so the script is there.
Before deploying, `bash ~/bikerpassport/scripts/recent_activity.sh` (the `recent_activity` command,
read-only) shows who saved anything in the last 15/60 min, the last save, and unexpired logins.

**Krystal is in real use** (2 Oct 2026): 100+ submissions logged by 17 volunteers. Release at quiet
moments, and never run load-test cleanup there.

**Ambassador venue report (29 Sep):** replaces the public message form (migration `0023`, 78 tests
pass, checked in a browser). On Railway via the 29 Sep push; **not yet on Krystal** — release there
with `git pull`, `migrate`, restart (no collectstatic) when Steve is ready for ambassadors to see it.

**Railway is a test site again (29 Sep):** web app running, GitHub reconnected (deploys on push to
`master`), every pre-existing account inactive except `Kentigern`, plus Steve's new test users;
alert lists go to Steve only; public page on. **Never re-run `transfer_reference_data`** (it would
copy the inactive flags to Krystal).

**Krystal is ready for real intake at staging.bikeandbrew.org.** Steps 1–6 of
[docs/plan_2026-09-24_krystal.md](docs/plan_2026-09-24_krystal.md) done; step 7 (DNS prep for
the cutover) on hold with the WordPress work. Intake will start at #1 / ticket 000001.
- Code current (incl. migration `0022`: Site Admin sees Public messages).
- `.env` on Krystal (Steve edits it with WinSCP): Resend key, sender, alert lists set;
  **`DJANGO_DEBUG=False`** (it was True until tonight — see Gotchas). Public message page
  is **on** there — decide with MARK whether it stays on.
- Reference data copied Railway → Krystal: 70 users, 3 groups, season 2026, 296 venues.
  Staff log in with their Railway passwords. (`railway ssh` needs Steve's
  passphrase-protected key, so he runs those commands himself.)
- HTTPS verified: http→https 301, HSTS (1 h), secure cookies, CSRF OK, plain 404s.
- Smoke test passed (confirmation + resend emails, notes alert, locking, CSV export, draw
  page, audit log, Krystal footer); test data then removed (`loadtest_fixtures --cleanup`,
  test raffle export and public message deleted).
- `DJANGO_DEBUG` now **defaults to False** (released 25 Sep); tests no longer depend on `.env`'s
  DEBUG (conftest forces plain-HTTP test servers). 58 pass with DEBUG on, off or unset.
- Load test on Krystal (24 Sep, 23:48): 40 volunteers × 10 min, 775 passports, p95 < 0.42 s,
  0 app errors (24 tool-caused duplicate-phone 400s). Report: Claude Docs "Bike + Brew Krystal
  Test Report". cPanel Resource Usage: 0 faults on every limit (CPU est. ~70% of one core during the test,
  memory 117 MB of 1 GB). Load-test data cleaned up 25 Sep — Krystal back to 0 submissions.
- **Railway fixed (25 Sep, 00:18 redeploy):** `DJANGO_DEBUG` was explicitly True — now False
  (verified: http→https 301, HSTS, secure cookies, plain 404, CSRF OK). Misnamed
  `DJANGO_PUBLIC_MESSAGES_ALERT_EMAILS` renamed to `DJANGO_PUBLIC_MESSAGE_ALERT_EMAILS` (same value).
- Personal PC has a dev setup: Python 3.11 `.venv`, `pip install -r requirements-dev.txt`,
  `playwright install chromium`; 58 tests pass.

**Domains:** `bikeandbrew.org` is an alias of the account's main domain. The 24 Sep plan to make it
a full domain is superseded by the 29 Sep layout (see Hosting above); intake runs on
staging.bikeandbrew.org meanwhile, and the switch needs no data migration.

Done and on Railway: ticket numbers, draw from issued numbers, email retry, notes
alerts, public message page (off), yellow/black wheel, 10s Resend timeout.
Repo is set up for two PCs (work + Steve's personal PC, both with Claude Code);
`scripts/fix_claude_path.bat` fixes a Claude Code install that isn't on PATH.

Tested live on Railway (2026-09-23), all passing: confirmation email end to end
(Resend, verified sender); failed send → admin resend; ticket backfill; Save & Exit
with no email (tickets issued, no email); notes alert to staff; raffle CSV export
(108 rows, ticket number/name/email/phone — mailing address removed because multi-line
addresses broke it in spreadsheets); live draw revealing the winner's own issued
ticket. Tested only locally: bulk retry, public message page (off on Railway), 10s
timeout, data-transfer matching. Nothing tested on Krystal yet. Railway holds one test
RaffleWinner (removed by `reset_intake_data` if Railway becomes the fallback).

Day 1 MVP — remaining (Day 1 may be brought forward at short notice):
1. Real-passport smoke test on Krystal (then decide whether to keep or clean it up).
2. Later, raise HSTS (`DJANGO_SECURE_HSTS_SECONDS`) once HTTPS has been solid for a while.
3. Domain switchover (runbook Phase 3: main domain → makeyourmark.co.uk, app → its subdomain,
   bikeandbrew.org redirects) — **on hold** with the WordPress handover. Ask Krystal first whether
   aliases/subdomains count toward the one-domain limit and how to rename the main domain.

Waiting on Steve: recipient lists for `DJANGO_NOTES_ALERT_EMAILS` / `DJANGO_PUBLIC_MESSAGE_ALERT_EMAILS`;
the boss's wishes for the confirmation email design (it's a hand-coded HTML template —
logo, wording, conditional messages, an existing MARK/Mailchimp design are all possible;
admin-editable wording deferred until after Day 1).

**Parked** (don't pursue unless asked): bulk email campaigns (only ever to bearers who have
*granted* that purpose's consent);
recording Resend bounces (needs a webhook). (Load testing: done 24 Sep — the kit's cleanup
must never run once real tickets are emailed.)

## How Steve likes to work

- **Lean v1s**: build the smallest genuinely useful version; name what's deferred.
- **Verify larger/riskier changes in a real browser** (pytest-playwright + screenshots,
  temp test files deleted after). **Skip verification for small edits** — just make them.
- Commit/push only when asked; he usually works directly on `master` and asks to push.
- Before anything that changes live sites (Railway variables, deploys, data), confirm first.
- Plain-English summaries; he's the owner, not a full-time developer.

## Gotchas learned the hard way

- Steve's local `.env` holds the **live** settings (live Resend key, alert addresses, a
  MySQL `DATABASE_URL`). Run tests/`manage.py` locally with `DATABASE_URL=` blanked to use
  SQLite; `passports/tests/conftest.py` blanks the Resend key and alert lists for every test.
- New-admin-model checklist: Site Admin only sees it after a data migration grants the
  permissions (pattern: `0009`, `0014`, `0022`) — superusers see everything, so it's easy to miss.
- `DJANGO_DEBUG` used to **default to True when unset** (now False; local dev sets
  `DJANGO_DEBUG=True` in `.env` if wanted). Krystal staging ran with `DEBUG=True` until
  24 Sep (no HTTPS redirect, debug error pages). Fixed in its `.env`; with DEBUG off, Krystal's
  LiteSpeed works with `SECURE_PROXY_SSL_HEADER` (http→https 301, HSTS, secure cookies, CSRF OK).
- Windows **PowerShell `>` writes UTF-16** — use cmd or Git Bash for `dumpdata > file`.
- `bikeandbrew.org` is a cPanel **alias (parked domain)**: no document-root setting; check domain types with `uapi DomainInfo list_domains` in cPanel Terminal. Removing an alias can drop its DNS zone — export records first.
- Krystal's database is **MariaDB**: it can't enforce conditional unique constraints, so "one
  current season" is enforced in `Season.save()` (W036 silenced); the app turns on strict mode
  for MySQL connections (was W002). Both live on Krystal since 1 Oct (strict mode came up
  cleanly on real MariaDB).
- Krystal MySQL needs `?ssl_disabled=true` on `DATABASE_URL` (PyMySQL SSL handshake fails otherwise).
- WhiteNoise manifest storage: a missing `collectstatic` makes every page 500.
- `dumpdata` returns nothing inside the pytest harness — tests serialize directly instead.
- SQLite "database is locked" under concurrent load is a local-only artefact (MySQL/Postgres are fine).
- Resend free tier is ~100 emails/day — watch it when testing with real sends.
- Intake numbers have gaps where test submissions were deleted; they're never reused.
- `.sh` files must stay LF (`.gitattributes`) — bash on Windows fails on CRLF scripts; `.bat` files stay CRLF.
- The push hook matches the text `git push` anywhere in a command, so an unrelated command mentioning it can be refused — use the `# claude-md-reviewed` comment.
