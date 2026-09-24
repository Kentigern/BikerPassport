# Railway as a fallback for real intake

**Status:** plan only — nothing here has been done, deliberately (Steve, 24 Sep: effort
proportionate to the risk). Recovery is **not immediate**: allow roughly half a day —
build and test `reset_intake_data` (below), then the ~45-minute switch. Steve manages
expectations with MARK on that basis. Railway is the test site; this is
how to turn it into the live intake site if Krystal can't be used (e.g. Day 1 comes
before Krystal is ready, or Krystal has an outage), and how to hand back afterwards.

Railway already has the same code, the same staff accounts (same passwords — Krystal's
were copied from Railway on 24 Sep), the same groups, the 2026 season and all 296
venues. So the switch is: **clear out the test intake data, change settings, redeploy.**

---

## The one rule: only one site takes intake at a time

Intake numbers and raffle ticket numbers are handed out per site (next number = highest
so far + 1). If volunteers type passports into Railway *and* Krystal at the same time,
both sites issue ticket 000001, 000002… and bearers get emailed clashing numbers that
can never be renumbered. So when one site is live, **the other must be closed to
Loggers** (Step 4), and everyone must be given the one address to use.

---

## What "test data" means here

Removed: everything created by testing —
bearers, passport submissions, raffle tickets, raffle winners, raffle exports, email
campaigns (and their recipients), public messages, and the audit-log (history) entries
for all of these.

Kept: staff users, groups and their permissions, the 2026 season, the 296 venues.

After the reset, the next passport on Railway is intake #1 and its first ticket is 000001.

## Why superuser access in the admin isn't enough

By design, raffle tickets, winners, exports and email campaigns **can't be deleted in the
admin, even by a superuser** (they're an evidence trail). Bearers and submissions can't
be deleted while they have tickets or wins attached. And the admin never touches the
audit-log history. So the reset needs a small management command.

### To build before it's needed (Claude, ~30 min, tested locally)

`python manage.py reset_intake_data` — deletes exactly the "Removed" list above, in the
right order, in one transaction (all or nothing).

- Dry run by default: prints what it *would* delete, per table.
- Deletes only with `--yes --database-name <name>`, where `<name>` must match the
  database the site is connected to (the dry run prints it). That makes it very hard to
  run against Krystal's production database by mistake.
- Never touches users, groups, seasons or venues.

---

## Steps to switch intake to Railway

Allow about 45 minutes. Tell volunteers the address only after Step 6.

### 1. Check Railway is on the current code (2 min)
Railway deploys `master` automatically. In the Railway dashboard → BikerPassport →
Deployments, check the latest deployment is green and matches the latest commit on GitHub.

### 2. Clear the test data (10 min)
In **Command Prompt** (not PowerShell), in the repo folder:

```
railway ssh -- python manage.py reset_intake_data
```

Check the dry-run counts look like test data only, note the database name it prints, then:

```
railway ssh -- python manage.py reset_intake_data --yes --database-name <name>
```

Check: admin shows 0 passport submissions, 0 raffle tickets, 0 raffle winners; staff
users, groups, the season and 296 venues are still there.

### 3. Update Railway's variables (10 min)
Railway dashboard → BikerPassport → **Variables**. Set or check:

| Variable | Value |
|---|---|
| `DJANGO_DEBUG` | `False` (already False since 25 Sep) |
| `RESEND_API_KEY` | a Resend key (Sending access, domain passports.makeyourmark.co.uk) |
| `DJANGO_DEFAULT_FROM_EMAIL` | `Bike + Brew <noreply@passports.makeyourmark.co.uk>` |
| `DJANGO_PUBLIC_BASE_URL` | `https://www.steve-newman.com` (the address volunteers will use) |
| `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` | include that address |
| `DJANGO_NOTES_ALERT_EMAILS` | the real staff recipients (same as Krystal's) |
| `DJANGO_PUBLIC_MESSAGE_ALERT_EMAILS` | the real staff recipients |
| `DJANGO_PUBLIC_MESSAGES_ENABLED` | `False` unless MARK wants the page live |
| `WEB_CONCURRENCY` | `4` — gunicorn workers, for 30–40 volunteers at once (default is 1) |

Then **Deploy** — Railway only picks up variable changes on a redeploy.

### 4. Close the other site to Loggers (5 min)
On Krystal (cPanel Terminal, venv active), make every Passport Logger inactive so nobody
can log intake there by accident:

```
python manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(groups__name='Passport Logger', is_superuser=False).update(is_active=False))"
```

(Undo with the same command and `is_active=True`.) Site Admins and you stay active.

### 5. Freeze pushes to `master` (standing rule while Railway is live)
Every push to `master` redeploys Railway within minutes — a restart mid-intake. While
Railway is live, **push only deliberately, at a quiet moment**, and only fixes needed
for intake.

### 6. Smoke test (15 min)
Same as the Krystal smoke test (plan of 24 Sep, Step 5) but on Railway: one submission
with your own email → confirmation with ticket 000001; one with Notes → staff alert; a
Logger login lands on the Logger Dashboard. Then clean those test entries up with
`reset_intake_data` (Step 2) so real intake starts at #1, **before** telling volunteers
the address.

---

## Handing back to Krystal afterwards

Krystal's intake tables must be **empty** at this point (Step 4 kept Loggers out; clear
any smoke-test data with `loadtest_fixtures --cleanup`).

1. Close Railway to Loggers (Step 4's command, run on Railway via `railway ssh`).
2. Export the intake data from Railway (Command Prompt, not PowerShell):
   ```
   railway ssh -- python manage.py dumpdata passports.bearer passports.historicalbearer passports.passportsubmission passports.historicalpassportsubmission passports.historicalpassportsubmission_venues_stamped passports.raffleticket passports.rafflewinner passports.raffleexport passports.publicmessage --natural-foreign --indent 2 > intake_data.json
   ```
   (Claude to confirm the exact history table names and do a local trial run first.)
3. Upload to Krystal and `python manage.py loaddata intake_data.json`; delete the file on
   both machines (it holds bearers' personal data).
4. Check the counts match, and that bearers keep **the same ticket numbers** they were
   emailed. Re-activate Krystal's Loggers; tell volunteers the Krystal address.
5. Put Railway back to test: set `RESEND_API_KEY` blank (so tests can't email real
   people), alert lists to your own address, `WEB_CONCURRENCY` back to `1`; redeploy.
   Leave the real data on Railway until Krystal is confirmed good, then clear it with
   `reset_intake_data`.

## Decided

- Volunteers use **www.steve-newman.com** for Railway (at least initially). It's also the
  planned temporary WordPress address, but that work is on hold.
- Railway plan is **Hobby (paid)**: resources are ample for 4 gunicorn workers (roughly
  0.5 GB between them); usage-billed, so a busy intake period costs a little more. Confirm
  the service's limit under BikerPassport → Settings → Resources before switching.
