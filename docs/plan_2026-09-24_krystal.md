# Plan — 24 September 2026: Krystal deploy, config data, email, smoke test

**Objective:** by the end of the day, the Krystal app (staging.bikeandbrew.org) runs
the current code with the real staff accounts, groups, season and venues, sends
email through Resend, and has passed a smoke test, so it's ready for the domain
cutover.

**Not today:** the bikeandbrew.org domain cutover (runbook Phase 3). One prep step
for it is included (lowering DNS TTLs), so the cutover can happen as early as tomorrow.

**Risk:** low. Nothing today touches a live public domain, WordPress, or Railway.
Railway stays the working fallback throughout.

**Time:** about 3 hours, including slack. Stop points are marked ⏸ — safe places to
pause and pick up later, even from the other PC.

---

## Before you start (5 min)

Have these ready:

- [ ] SSH or cPanel Terminal access to Krystal, and the virtualenv activate command
      (shown at the top of cPanel → Setup Python App → the app's page)
- [ ] The **Resend API key** for Krystal. Recommended: create a separate key in Resend
      called `krystal`, so each host's key can be revoked on its own.
- [ ] The email address(es) for **notes alerts** and **public messages**
- [ ] An email inbox you can check, for the test emails
- [ ] This PC: repo up to date (`git pull`), Railway CLI logged in (`railway status`)

Resend's free plan allows about 100 emails a day. Today's tests use about 5–10.

---

## Step 1 — Update the code on Krystal (20 min)

In the SSH session:

```
cd ~/bikerpassport
source <virtualenv activate command>
git status                  # should be clean (.env is ignored, not shown)
git pull
pip install -r requirements.txt
python manage.py migrate    # expect 0019, 0020, 0021 to apply
python manage.py collectstatic --noinput
python manage.py check
```

Then restart the app: cPanel → **Setup Python App** → **Restart**
(or `touch tmp/restart.txt` in the app folder).

✅ **Done when:** https://staging.bikeandbrew.org/ shows the login page, with no error.

If `collectstatic` was skipped, every page shows a 500 error. Re-run it and restart.

---

## Step 2 — Email and alert settings in Krystal's `.env` (15 min)

Edit `~/bikerpassport/.env` (cPanel File Manager or `nano .env`). Add or check:

```
RESEND_API_KEY=<the krystal key>
DJANGO_DEFAULT_FROM_EMAIL=Bike + Brew <noreply@passports.makeyourmark.co.uk>
DJANGO_PUBLIC_BASE_URL=https://staging.bikeandbrew.org
DJANGO_NOTES_ALERT_EMAILS=<address(es), comma-separated>
DJANGO_PUBLIC_MESSAGE_ALERT_EMAILS=<address(es)>
DJANGO_PUBLIC_MESSAGES_ENABLED=False
```

These should already be there from Phase 1. Just check them:

- `DJANGO_DEBUG=False`
- `DJANGO_ALLOWED_HOSTS` includes `staging.bikeandbrew.org`
- `DJANGO_CSRF_TRUSTED_ORIGINS` includes `https://staging.bikeandbrew.org`
- `DATABASE_URL=mysql://…?ssl_disabled=true`

The sender **must** be on `passports.makeyourmark.co.uk`, the verified Resend subdomain.
The bare `makeyourmark.co.uk` fails with "domain is not verified".

**Restart the app** again. `.env` is only read at start-up.

✅ **Done when:** the site still loads after the restart.

⏸ *Safe stop point.*

---

## Step 3 — Copy the config data from Railway (30 min)

Follow [scripts/transfer_reference_data.txt](../scripts/transfer_reference_data.txt),
steps 1–5. In short:

1. **Pre-check Krystal** (step 1 of the guide). Look for a *different* current season,
   or a username clash with the temporary setup superuser.
2. **Export from Railway** on this PC, in **Command Prompt or Git Bash, not PowerShell**:
   `railway ssh -- python manage.py dumpdata auth.group auth.user passports.season passports.venue --natural-foreign --natural-primary --indent 2 > reference_data.json`
   Then check the counts with the one-line Python command in the guide: expect 296 venues.
3. **Upload** `reference_data.json` to `~/bikerpassport/` (File Manager → Upload).
4. **Load:** `python manage.py loaddata reference_data.json`, then `rm reference_data.json`.
   Delete the copy on this PC too, because it contains staff password hashes.

✅ **Done when:** you can log in to Krystal with your **Railway** username and password,
and the admin shows 296 venues, the 2026 season as current, and the Passport Logger
and Site Admin groups with their permissions.

⏸ *Safe stop point.*

---

## Step 4 — Logins over HTTPS (10 min)

Phase 1 already logged in successfully on staging, so this is a quick confirmation,
now with the real accounts:

- [ ] Log in as a **Site Admin** → you land on the Dashboard
- [ ] Log in as a **Passport Logger** (in a private window) → you land on the Logger Dashboard
- [ ] Save any small change in the admin (e.g. edit and re-save a venue without changing it) → no CSRF error
- [ ] No redirect loop, and the padlock shows in the browser

If any of these fail with a CSRF error or a redirect loop, stop and bring the exact error
to Claude. It's a known possible difference between Railway's proxy and Krystal's Apache
(see `SECURE_PROXY_SSL_HEADER` in `config/settings.py`).

---

## Step 5 — Smoke test (45 min)

**Test-data rule — read first:** so the clean-up in Step 6 can remove it all automatically,
every test bearer's **name must start with `LOADTEST `** (e.g. `LOADTEST Smoke 1`) and
their **phone must be in the 07700 7xxxxx block** (e.g. `07700 700001`, `07700 700002`, …).
Anything else stays in what becomes the production database.

**Do not run the raffle draw on Krystal.** A draw records a permanent winner that the
clean-up can't remove. The draw was fully tested on Railway. Just open the draw page to
check it loads.

As a **Passport Logger**:

| # | Do | Expect |
|---|----|--------|
| 1 | New submission: `LOADTEST Smoke 1`, phone `07700 700001`, **your** email, tick 20 venues, **Save & Exit** | Saves; the confirmation email arrives from noreply@passports… with **2 ticket numbers** (000001 and 000002 if staging has no earlier tickets) |
| 2 | Search for phone `07700 700001` again | Finds the bearer; the submission opens **read-only** (locked) |
| 3 | New: `LOADTEST Smoke 2`, `07700 700002`, **no email**, 10 venues, Save & Exit | Saves; no email |
| 4 | New: `LOADTEST Smoke 3`, `07700 700003`, your email, 10 venues, Notes "Smoke test note", Save & Exit | Confirmation email **and** a staff "Passport note — intake #…" alert with an admin link |

As a **Site Admin**:

| # | Do | Expect |
|---|----|--------|
| 5 | Admin → Passport submissions | All 3 listed; each shows its raffle ticket numbers; #2 has tickets despite having no email |
| 6 | Tick Smoke 1 → **Send / resend confirmation email** → Go | "1 sent"; a second copy of the email arrives |
| 7 | Dashboard → **Produce Raffle Tickets** | CSV opens cleanly: Ticket Number / Name / Email / Phone, one row per ticket (4 from the smoke test) |
| 8 | Dashboard → **Run Raffle Draw** | Yellow/black wheel shows "3 entrants". **Don't click Draw.** |
| 9 | Dashboard → **View Audit Log** | The test submissions and edits appear |
| 10 | Any page footer | "Hosting kindly provided by Krystal" link present |
| 11 | *(Optional)* Set `DJANGO_PUBLIC_MESSAGES_ENABLED=True`, restart, send a message from `/message/` in a private window (wait 3+ seconds before sending) | Email arrives; the message appears under Admin → Public messages. Then set it back to `False` and restart, unless MARK wants it live. |

✅ **Done when:** all rows behave as expected. Note anything odd for Claude, with the exact message.

---

## Step 6 — Clean up and record (15 min)

On Krystal:

```
python manage.py loadtest_fixtures --cleanup          # dry run: expect 0 accounts, 3 bearers, 3 submissions, 4 raffle tickets
python manage.py loadtest_fixtures --cleanup --yes
```

(If you sent a public message, delete it in Admin → Public messages.)

✅ **Done when:** the admin shows **0 passport submissions**, so real intake starts at
intake #1 and ticket 000001.

Then ask Claude to update `CLAUDE.md` (Krystal deployed, config data migrated, email
working, smoke test passed) and commit and push.

---

## Step 7 — Prep tomorrow's cutover (5 min)

At GoDaddy, **lower the TTL** on the `steve-newman.com` / `www` DNS records to the minimum
(runbook Phase 3, step 1). It takes up to a day to take effect, which is why it's done
now. It changes nothing visible.

---

## If Day 1 is suddenly brought forward

If today goes well, run intake on Krystal at staging.bikeandbrew.org straight away. The
domain name is cosmetic, and the cutover can follow. If Krystal isn't ready, use the
Railway fallback in CLAUDE.md.
