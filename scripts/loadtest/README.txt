BIKE + BREW LOAD TEST
=====================

Simulates 30-40 volunteers logging passports at the same time on the STAGING
site (staging.bikeandbrew.org), to check Krystal copes before the real intake.
Each simulated volunteer logs in as its own test Logger and repeatedly: opens a
new submission, searches for a bearer by phone, saves the bearer, ticks venues
and saves, then does Save & Exit. Every request is timed.

Never run this against the production site: the clean-up step deletes raffle
ticket numbers, which must never happen once real bearers have been emailed.
Run it at a quiet time - staging shares its Krystal account (and resource
limits) with the WordPress site.


WHAT'S IN THIS FOLDER
---------------------
  loadtest.py        the test itself (needs Python 3.8+ and "requests")
  run_loadtest.bat   double-click to run it; asks for the settings
  README.txt         this file
  results_latest.txt appears after a run - the summary to send back


ON THE TEST PC (one-off)
------------------------
1. Install Python 3 from https://www.python.org/downloads/ - tick
   "Add python.exe to PATH" on the first installer screen.
2. Copy this folder (scripts/loadtest in the repo) onto that PC -
   or clone the repo there and use it in place.
   (run_loadtest.bat installs "requests" itself the first time if needed.)


STEP 1 - BEFORE THE TEST, on Krystal (SSH / cPanel Terminal)
------------------------------------------------------------
Get the latest code onto staging and create 40 test Logger accounts. Pick a
throwaway password - you'll type it into the test PC in step 2.

    cd ~/bikerpassport
    source <your virtualenv activate path>      (as shown in cPanel "Setup Python App")
    git pull
    python manage.py migrate
    python manage.py loadtest_fixtures --create 40 --password CHOOSE-ONE --yes

Then restart the app in cPanel "Setup Python App" so it picks up the new code.


STEP 2 - RUN THE TEST, on the test PC
-------------------------------------
Double-click run_loadtest.bat. Press Enter to accept each default, then type
the password from step 1. It starts the volunteers over the first minute, then
prints progress every 30 seconds. A 10-minute run takes about 11 minutes.

The summary appears at the end and is saved to results_latest.txt.

Or from a command prompt, e.g. a quick 2-minute check with 5 volunteers:
    python loadtest.py https://staging.bikeandbrew.org --users 5 --minutes 2 --password CHOOSE-ONE

Options:  --users N  --minutes N  --ramp SECONDS  --think-scale X (0 = flat out)
          --email delivered@resend.dev   also exercise the confirmation email
                   (Resend's test address - no real delivery, but it counts
                   toward the Resend quota; free plans allow ~100/day)
          --output FILE


STEP 3 - WHILE / AFTER IT RUNS, in cPanel
-----------------------------------------
Open cPanel > "Resource Usage" and note whether any limit was hit (CPU,
memory, entry processes, number of processes) during the test window.


STEP 4 - CLEAN UP, on Krystal
-----------------------------
Deletes the test accounts and everything the test created (bearers,
submissions, raffle tickets, their audit history) - nothing else. Run it
without --yes first to see what it will delete.

    python manage.py loadtest_fixtures --cleanup
    python manage.py loadtest_fixtures --cleanup --yes


READING THE RESULTS
-------------------
For each step: how many requests, how many failed, and response times in
milliseconds - p50 is the typical time, p95 is what 1 in 20 requests is slower
than, max is the worst.

Rough guide for 40 volunteers:
  good      p95 under ~1,000 ms on every step, no errors
  watch     p95 of 1-3 s, or a handful of errors
  problem   p95 over ~3 s, or errors in "save & exit" / "submission save"

Send results_latest.txt and the cPanel Resource Usage notes back for review.
"Login ... not logged in" errors mean step 1's accounts or password don't match.
