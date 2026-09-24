# CLAUDE.md — Bike + Brew Passport system

Context for Claude Code sessions on this repo. Read with [SPEC.md](SPEC.md) (the
full spec) and [README.md](README.md) (setup). **Never put secrets in this repo**
(API keys, passwords, `.env` contents) — it is public on GitHub.

## Keeping this file current

Steve works on this repo from two PCs, each with its own Claude memory that does
**not** sync — this file is the shared memory. So:

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
  unique identifying key and the access-control "secret" (§5.2 of SPEC).
- **Save & Exit locks** a submission (and its bearer) for Loggers; Site Admins/superusers can still edit.
- **Raffle tickets** (`RaffleTicket`): issued at Save & Exit for every locked submission,
  email or not; sequential per season, zero-padded 6 digits (`000001`); **never
  renumbered or removed** once issued (they've been emailed). The export and the
  live draw work only from issued numbers; the draw reveals the winner's own number.
- **Confirmation email** (§5.3): sent once at Save & Exit via Resend, transactional —
  **no consent request** in it (raffle data needs none). Failures set
  `email_send_failed`; staff retry via the admin action or `retry_confirmation_emails`.
- **Notes alert**: Save & Exit with anything in Notes emails `DJANGO_NOTES_ALERT_EMAILS`.
- **Public message page** `/message/`: off unless `DJANGO_PUBLIC_MESSAGES_ENABLED=True`.
- Physical anti-duplicate safeguard: every processed passport's **corner is snipped**
  before it's returned (nothing in the data model tracks this).
- Three intake channels, same data model: left at a venue (volunteer collects),
  posted to Steve, or handed over in person at the **3–4 October 2026 event**
  (the most time-pressured case — keep intake fast).
- Raffle draw: yellow/black roulette wheel only (slot machine removed at MARK's request).

## Hosting

- **Railway** — the test site, and the planned **fallback** for real intake if Krystal
  can't be used: [docs/railway_fallback.md](docs/railway_fallback.md) (plan only, deliberately
  not pre-built; recovery takes ~half a day, starting with building `reset_intake_data`). Only one site may take intake at a time.
  Project "Make Your Mark", service "BikerPassport", deploys automatically from `master`;
  served at www.steve-newman.com. Test data only.
  Start command runs `migrate` + `collectstatic`. Single gunicorn worker.
  **Variable changes need a Deploy/Redeploy** before the app sees them.
- **Krystal (production)** — shared cPanel hosting, Passenger + MySQL, same account as
  MARK's WordPress site; Python 3.12 there. SSH/cPanel Terminal venv:
  `source /home/cfdfcfde/virtualenv/bikerpassport/3.12/bin/activate && cd /home/cfdfcfde/bikerpassport`.
  Staging app at **staging.bikeandbrew.org** (folder `~/bikerpassport`,
  `.env` in the app folder). Production will be **bikeandbrew.org** after the cutover in
  [docs/krystal_migration.md](docs/krystal_migration.md). Krystal requires the footer
  credit "Hosting kindly provided by Krystal" (linked) — contractual, don't remove it.
- **Email**: Resend. The verified domain is the **subdomain `passports.makeyourmark.co.uk`**,
  so the sender must be `…@passports.makeyourmark.co.uk` (default
  `noreply@passports.makeyourmark.co.uk`). The bare `makeyourmark.co.uk` is NOT verified.

## Current status (24 Sep 2026, late evening — on Steve's personal PC)

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

**Found today:** `bikeandbrew.org` is a **parked domain (alias)** of the account's main
domain — not the primary domain as earlier notes said. Aliases have no document-root
setting (that's why cPanel showed no options), so it can't simply be "repointed". The
fix needs no Krystal ticket: on cutover day remove the alias and re-add it as a normal
domain with its own folder `bikerpassport` (full steps in
[docs/krystal_migration.md](docs/krystal_migration.md) Phase 3, step 6).
**Decision:** do both — run Day 1 intake on **staging.bikeandbrew.org** if needed (its
database is the production database), and switch the domain whenever convenient.

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
3. Cutover bikeandbrew.org (runbook Phase 3, revised for the parked-domain finding) — **on hold**:
   it takes bikeandbrew.org off WordPress, whose handover to Steve is paused. Ignore
   WordPress until he says otherwise. Day 1 intake runs on staging.bikeandbrew.org.

Waiting on Steve: recipient lists for `DJANGO_NOTES_ALERT_EMAILS` / `DJANGO_PUBLIC_MESSAGE_ALERT_EMAILS`;
the boss's wishes for the confirmation email design (it's a hand-coded HTML template —
logo, wording, conditional messages, an existing MARK/Mailchimp design are all possible;
admin-editable wording deferred until after Day 1).

**Parked** (don't pursue unless asked): bulk email campaigns (when resumed, the first
campaign is the data-use consent request — needs an audience rule for *not yet
consented* bearers);
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
- Krystal MySQL needs `?ssl_disabled=true` on `DATABASE_URL` (PyMySQL SSL handshake fails otherwise).
- WhiteNoise manifest storage: a missing `collectstatic` makes every page 500.
- `dumpdata` returns nothing inside the pytest harness — tests serialize directly instead.
- SQLite "database is locked" under concurrent load is a local-only artefact (MySQL/Postgres are fine).
- Resend free tier is ~100 emails/day — watch it when testing with real sends.
- Intake numbers have gaps where test submissions were deleted; they're never reused.
- `.sh` files must stay LF (`.gitattributes`) — bash on Windows fails on CRLF scripts; `.bat` files stay CRLF.
- The push hook matches the text `git push` anywhere in a command, so an unrelated command mentioning it can be refused — use the `# claude-md-reviewed` comment.
