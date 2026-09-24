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

- **Railway** — test/backup only. Project "Make Your Mark", service "BikerPassport",
  deploys automatically from `master`; served at www.steve-newman.com. Test data only.
  Start command runs `migrate` + `collectstatic`. Single gunicorn worker.
  **Variable changes need a Deploy/Redeploy** before the app sees them.
- **Krystal (production)** — shared cPanel hosting, Passenger + MySQL, same account as
  MARK's WordPress site. Staging app at **staging.bikeandbrew.org** (folder `~/bikerpassport`,
  `.env` in the app folder). Production will be **bikeandbrew.org** after the cutover in
  [docs/krystal_migration.md](docs/krystal_migration.md). Krystal requires the footer
  credit "Hosting kindly provided by Krystal" (linked) — contractual, don't remove it.
- **Email**: Resend. The verified domain is the **subdomain `passports.makeyourmark.co.uk`**,
  so the sender must be `…@passports.makeyourmark.co.uk` (default
  `noreply@passports.makeyourmark.co.uk`). The bare `makeyourmark.co.uk` is NOT verified.

## Current status (24 Sep 2026, mid-session — switching PCs)

**Resume** [docs/plan_2026-09-24_krystal.md](docs/plan_2026-09-24_krystal.md) at **Step 1**
(not started yet). Prep done so far: Steve has cPanel **Terminal** access. Still to have
ready: the virtualenv `source …` command (cPanel → Setup Python App → edit the app),
a Resend API key named `krystal` (Sending access, domain passports.makeyourmark.co.uk —
never paste it into chat), and the alert email address(es).

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
RaffleWinner — clear it (DEBUG-only command won't run there) if Railway becomes the
Day 1 fallback.

Day 1 MVP — remaining, in order (Day 1 may be brought forward at short notice).
Steps 1–4 + smoke test are planned in detail for 24 Sep: [docs/plan_2026-09-24_krystal.md](docs/plan_2026-09-24_krystal.md).
1. Bring Krystal staging up to date (`git pull`, `migrate`, `collectstatic`, restart app).
2. Copy users/groups/seasons/venues Railway → Krystal: `scripts/transfer_reference_data.txt`.
3. Krystal `.env`: `RESEND_API_KEY`, `DJANGO_DEFAULT_FROM_EMAIL`, alert email lists; send a test.
4. Test HTTPS logins/forms on Krystal (`SECURE_PROXY_SSL_HEADER` assumes a proxy; Apache may differ).
5. Cutover bikeandbrew.org (runbook Phase 3 — revised for the parked-domain finding). Optional for Day 1: intake can run on staging.bikeandbrew.org. Railway stays as fallback until done.
6. Real-passport smoke test.
Fallback if Day 1 comes first: run intake on Railway (clear test data, 3–4 gunicorn
workers, bulk-create Logger accounts), move data to Krystal later.

Waiting on Steve: recipient lists for `DJANGO_NOTES_ALERT_EMAILS` / `DJANGO_PUBLIC_MESSAGE_ALERT_EMAILS`;
the boss's wishes for the confirmation email design (it's a hand-coded HTML template —
logo, wording, conditional messages, an existing MARK/Mailchimp design are all possible;
admin-editable wording deferred until after Day 1).

**Parked** (don't pursue unless asked): bulk email campaigns (when resumed, the first
campaign is the data-use consent request — needs an audience rule for *not yet
consented* bearers); load testing on Krystal staging (kit ready in `scripts/loadtest/`);
recording Resend bounces (needs a webhook).

## How Steve likes to work

- **Lean v1s**: build the smallest genuinely useful version; name what's deferred.
- **Verify larger/riskier changes in a real browser** (pytest-playwright + screenshots,
  temp test files deleted after). **Skip verification for small edits** — just make them.
- Commit/push only when asked; he usually works directly on `master` and asks to push.
- Before anything that changes live sites (Railway variables, deploys, data), confirm first.
- Plain-English summaries; he's the owner, not a full-time developer.

## Gotchas learned the hard way

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
