# Bike + Brew Passport Processing System — Specification

**Charity:** Make Your Mark
**Status:** v0.2 — architecture decisions below are Claude's calls per user request ("Claude decide, keep under review"). Flagged items should be revisited as the project develops. Updated from v0.1 to document functionality actually built since the initial draft (§5.7–5.10, and the hosting decision in §7/§9) — v0.1's architecture reasoning is left intact where still accurate rather than rewritten.

## 1. Purpose

Make Your Mark runs an annual fundraiser, the **Bike + Brew Passport**. Each passport lists 296 named, numbered cafes. Bearers collect a stamp at a cafe each time they visit during the riding season. The passport then reaches data entry via one of three channels (not just mailing it in at season's end): left at a venue for a volunteer to collect later, posted directly to a staff contact, or handed to a volunteer in person at an organised event (e.g. the 2026-10-03/04 weekend), where it's often processed on the spot while the bearer waits. In every case, once a passport is processed its corner is physically snipped before it's returned to the bearer — the real-world safeguard against the same passport being entered twice for double raffle tickets.

This project is a web application that helps Make Your Mark staff:

1. Enter the data from each returned passport (bearer details + which of the 296 cafes were stamped).
2. Compute results: total stamps, cafes visited, raffle tickets earned (1 ticket per 10 stamps).
3. Email the bearer a summary of their results.
4. Keep a record of all processed passports for reporting and the eventual raffle draw.

This is an internal, staff-facing data-entry and reporting tool — not a public-facing bearer portal.

## 2. Hard Constraints

- **No paid/proprietary software at runtime.** Every component the running application depends on must be public domain or free/open-source (permissive or copyleft license — no per-seat, per-instance, or subscription licensing).
- **No dependency on Empowered Systems–licensed software.** The app must run entirely independent of any software Make Your Mark would need to separately license from, or through, Empowered Systems.
- Development tooling (this CLI, etc.) is not a runtime dependency and is exempt from the above — it doesn't ship with or get required by the deployed app.

## 3. Actors

- **Staff/volunteer** — logs in, processes returned passports, can look up and correct past entries, runs reports. Expect up to **30 volunteers** working concurrently during the intake window. Staff are assigned to Django groups matching their role (e.g. "Passport Logger", "Venue Admins"); ordinary Django group permissions govern create/read/update/delete access consistently across every model, **including** the intake form's own endpoints, not just the raw admin — see §5.2 for the Bearer-specific extra layer.
- **Bearer** — never logs in to the main app. Interacts via the physical passport, the summary email they receive, and (new — see §5.6) a single no-login consent link in that email. As of §5.10, also receives an occasional purpose-specific bulk email, each carrying its own no-login unsubscribe link.
- **Admin** — a staff role with additional permissions to manage the cafe list, seasons, staff accounts, data retention/purge, the live raffle draw, and bulk email, via a group with the relevant permissions. Built as a real Django permission (`passports.is_site_admin`, granted to a "Site Admin" group by default) rather than a hardcoded group-name check, so the group itself can be renamed/reorganized without breaking authorization — see §5.7.
- **Passport Logger** — the day-to-day data-entry role from §3's original "Staff/volunteer" description, named to match the group this build actually uses. Lands on a minimal intake-only landing page ("Logger Dashboard" — just a "Log a Submission" button) rather than the Site Admin's stats dashboard; see §5.7.

### Scale (confirmed)

- Up to **5,000 passports** returned, starting **end of September**.
- A **6-week window** for data capture.
- Up to **30 volunteers** doing data entry concurrently during that window.
- Roughly 120 submissions/day on average, but expect uneven daily load (bursts right after the return deadline).
- **Best-case ceiling:** all 17,000 sold passports come back, worked by ~100 volunteers. See §10 for the cost/capacity impact of this scenario.

## 4. Core Data Model

- **Season** — e.g. "2026". Each season has its own set of processed passports. (The program is annual and will recur; modeling this now avoids a rework next year.)
- **Cafe** — number (1–296), name. Reused season to season; editable by admins in case the list changes. *Naming note:* not every location on the list is strictly a cafe — "Venue" may be the more accurate long-term name for this entity; see §11.1 for why this matters beyond naming.
- **Bearer** — personal details captured off the passport: name, mailing address, phone, email (optional — bearers skew older and this charity doesn't reliably collect email). **Phone is mandatory and unique** (stored normalized, E.164 — see §5.2's access-control note) — it's the real identifying key, not name, since two different people can share a name. A bearer is a fresh record per submission unless staff explicitly match to an existing bearer — no assumption that identity is pre-registered. Also carries **consent/retention state**: consent status (`pending` / `granted` / `declined`), consent token (for the no-login email link), date requested, date responded, and a computed retention-expiry date for non-consenting bearers — see §5.6.
- **Passport Submission** — linked to a Season and a Bearer: date received, which Cafes were stamped (a checklist against the 296), processing status (received / entered / emailed), staff member who entered it, timestamp, notes field for anomalies (e.g. ambiguous stamp, duplicate cafe stamps). **One per bearer per season** (DB-enforced), not one per physical hand-in — since a bearer's passport accumulates stamps over the season and can be processed more than once (see §1's three intake channels), a later save for the same bearer updates their existing submission rather than creating a second one.
- **Derived per submission:** total stamp count, list of cafes visited, raffle tickets = `min(floor(stamp_count / 10), 28)` — **28 is a fixed cap**, confirmed by the charity, independent of how many of the 296 cafes exist in a given year.
- **Raffle Ticket** — one row per raffle ticket actually issued to a bearer (not just the count above): a sequential-per-season number, assigned when a submission is Save & Exited — for every submission, whether or not the bearer has an email — so the confirmation email can tell the bearer their specific ticket number(s) (§5.3), and the raffle export/draw (§5.5, §5.9) work from those same numbers. Any submission still short of its numbers (e.g. saved but never exited) is topped up automatically before an export or draw. Immutable once issued, same rationale as the Raffle Export/Raffle Winner records below — if a submission is later corrected and its ticket count grows, new numbers top it up; a shrinking count never removes/renumbers ones already sent.

## 5. Core Workflows

### 5.1 Cafe list setup (admin, one-time per season)

Load/confirm the 296 cafes for the season (import from CSV or carry forward from prior season with edits). The CSV can include an `image_file` column, imported as each `Venue`'s `page_group` — the source page-spread scan, reused to reconstruct the book's real page breaks in the intake form's Book view (§5.2).

### 5.2 Passport intake (staff, the main workflow)

1. Staff opens "New submission." Season is always the current one — never picked manually.
2. Enters bearer's personal details from the passport, or searches by name/phone to match an existing bearer, and saves — this can happen before any venues are ticked.
3. Marks which cafes were stamped — a checklist of all 296, sortable by number, in either of two styles staff can pick between: a searchable scrolling **list**, or a paginated **book view** echoing the physical passport's own 4-column, left/right-page-spread layout, including its real section breaks (a few page-spreads have fewer than 12 cafes, where the original book had regional-divider artwork instead of a full page of listings — each `Venue`'s `page_group` field, imported alongside the cafe list, records which spread it belongs to; see §5.1) — and saves; can be done in one pass or across several saves as the volunteer works through the passport.
4. System computes stamp count and raffle tickets live as boxes are checked.
5. Submission is saved with status "entered."
6. Staff (or a batch action) triggers the confirmation email; status moves to "emailed" (see §5.3–5.6).

**Phone as the access key — gates changing a bearer, not viewing one.** Group permissions decide whether a role can touch Bearer data at all (same as every other model — add/change/view/delete_bearer, ordinary Django permissions, checked on the intake form's endpoints as well as the admin). A permitted role — e.g. Passport Logger — can freely browse and search the `Bearer` list and open any bearer's detail page; **phone is simply never shown** in that list, and is omitted from an unverified bearer's detail page too (it isn't masked, it's absent — showing it would let anyone read the "secret" straight off the screen). Editing a bearer, and revealing their phone number, both require proving you know it first: search by exact phone (any common format, normalized before matching) to verify, which unlocks that one bearer for the rest of the session (`request.session`, cleared on logout/expiry) — searching by name finds and displays the record but does *not* verify it. The underlying save endpoints reject an unverified `bearer_id` even if POSTed directly, so knowing/guessing a database id is never sufficient on its own. A `PassportSubmission`'s `bearer` link is read-only in the admin for the same reason — reassigning a submission to a different bearer via a free autocomplete search would sidestep the phone-gate entirely, so that action isn't offered there at all. This stops a volunteer casually acquiring or changing another bearer's contact details by name alone — genuine write access requires actually having the phone number, which in practice means having the physical passport or the bearer present. **Superusers bypass the phone-gate entirely** (full list with phone visible, edit anyone, no verification needed anywhere) — a deliberate exception: superuser is already this app's most trusted tier and the one actually administering it, so a second gate on top adds friction without adding real protection for that role.

At this volume (up to 5,000 passports, 30 volunteers, 6 weeks) two things become real requirements rather than nice-to-haves:
- **No duplicate/missed processing.** Two backstops, both automatic: (1) a bearer can only have one submission per season — a DB constraint, not just a UI convention — so if staff search-and-match a bearer who's already been processed this season, saving takes them to *that* existing submission (with everything previously recorded already checked) instead of risking a second, competing record. (2) The intake number is assigned atomically by the system the first time a submission's venues are saved (sequential per season), replacing the manual paper-log approach originally envisioned here. Together these make the database itself the authoritative log, rather than a running list staff have to maintain. The bearer-facing half of the safeguard is unchanged: every processed passport's corner is snipped before it's returned (see §1), so the *same physical passport* can't be resubmitted later for a second set of raffle tickets.
- **Progress visibility.** Admin should be able to see at a glance how many of the logged passports have been entered/emailed, so the charity can track the 6-week window and reassign volunteer effort if it's falling behind.

### 5.3 Confirmation email
Sent to the bearer's email address on the submission. Contents:
- Total stamps collected.
- Full list of cafes visited (name + number).
- Number of raffle tickets earned, and each ticket's own number (see §4's Raffle Ticket record — assigned at Save & Exit, stable thereafter).
- **No consent request.** This is a transactional receipt: the data it covers is required to run the raffle, so it needs no consent. Consent to use bearers' details for other purposes (§5.6) will be sought later, as the first bulk email (§5.10) — not in this email.

Sent via Resend from `noreply@passports.makeyourmark.co.uk` (the verified Resend domain is the `passports.makeyourmark.co.uk` subdomain, so the sender must be `…@passports.makeyourmark.co.uk`; set by `DJANGO_DEFAULT_FROM_EMAIL`). Should be a plain, charity-branded template. Failures (bad address, bounce) must be visible to staff, not silent — a submission that failed to email should be flagged for follow-up, not lost. Site Admins retry from the admin's submission list ("Send / resend confirmation email" action — one submission, or every failed one via the "Email send failed" filter + select all), or all outstanding at once via the `retry_confirmation_emails` management command. Bounces reported by Resend after acceptance are not yet recorded (planned, low priority).

### 5.4 Lookup & correction
Staff can search past submissions (by bearer name, email, or season) to fix data-entry mistakes and re-send the email if corrected.

### 5.5 Reporting
- Season summary: total submissions, total stamps, total raffle tickets issued.
- Full raffle ticket list/export (CSV) — one row per issued ticket, by ticket number, so it can feed an actual raffle draw.
- Cafe popularity (optional/nice-to-have): stamps per cafe, for thanking participating cafes.
- Consent/retention report (see §5.6): counts of granted / declined / no-response, and which bearer records are due for purge.

### 5.6 Data retention & consent

The charity wants to **retain bearers' personal data** (for future seasons, newsletters, etc.) beyond what's strictly needed to run the current season's raffle — that requires the bearer's explicit permission.

Processing model:
- Every submission's personal data is retained **at minimum** through the end of the current season's raffle (that's an unavoidable, legitimate use — you can't run the raffle or contact a winner without it).
- The confirmation email (§5.3) asks the bearer for permission to keep their details **longer term** (e.g. "so we can contact you about next year's Bike + Brew"). The email includes a link to a single, no-login, token-based consent page — the one deliberate exception to "no bearer-facing UI" (§3, §8) — where the bearer clicks Yes or No.
- Each Bearer record carries a **consent status**: `pending` (email sent, no response yet), `granted`, or `declined`. Response date is recorded for audit.
- **Declined or non-responding** bearers: their personal data (name, address, phone, email) is scheduled for deletion/anonymization once the legitimate-use window closes (end-of-season raffle processing complete + some grace period — exact period TBD, see §9). Aggregate, non-identifying data (stamp counts, cafe popularity) can be retained indefinitely for reporting.
- **Granted** bearers: personal data retained per the charity's ongoing retention policy (no automatic purge).
- Admin needs a way to run/review the purge (§5.5 consent report) rather than it happening invisibly — a charity handling personal data should be able to show what it did and when.

This is consent/retention *for data the charity already lawfully holds to run this season's raffle* — it does not block processing a submission or paying out a raffle ticket regardless of how (or whether) the bearer responds.

### 5.7 Site Admin dashboard & role-based navigation

Every logged-in user lands on a dashboard for their role immediately after login, rather than a single fixed page:

- **Site Admin** (or superuser) → the **Dashboard**: current-season stat cards (total logged, logged today) and top-5 panels (venues by visits, loggers by passports logged, bearers by venues visited), plus a persistent sidebar linking to every other Site Admin workflow (Log a Submission, Site Administration/raw admin, Produce Raffle Tickets, Run Raffle Draw, Bulk Email, View Audit Log).
- **Passport Logger** (or any other non-admin staff) → the **Logger Dashboard**: just the one "Log a Submission" button — deliberately minimal, since intake is their whole job.

Every other staff-facing page (the intake form, audit log, raffle draw, bulk email, and the raw Django admin) carries a prominent "Back to Dashboard" button that returns the user to *their own* dashboard, not a fixed one — a shared role check (mirrored between the initial-login redirect and a small helper available to every template) decides which.

### 5.8 Audit log

A single, searchable, filterable timeline for Site Admins, merging what would otherwise be several separate audit trails: Bearer and Passport Submission history (covering edits made via *either* the intake form or the raw admin), the raw admin's own change log for everything else (Users, Groups, Venue, Season), raffle ticket exports, raffle winners drawn, and bulk email sends (§5.10). Filterable by category or free-text search (actor or subject), paginated, newest first — satisfies §6's "who entered/edited each submission and when" requirement with one page rather than requiring a Site Admin to check several models' raw admin history separately.

### 5.9 Live raffle draw

Beyond the CSV ticket export (§5.5, still available and unchanged — a full ticket list for a manual/backup paper draw if wanted), the system can now run the raffle draw itself, live, on-screen, at the event:

- A weighted-random pick happens **server-side** the instant a Site Admin clicks "Draw Next Winner" — uniformly over every issued ticket (§4's Raffle Ticket) whose bearer is still eligible this season (i.e. not already drawn) — which weights each bearer by their ticket count. The number revealed is that ticket's own issued number, the same one its bearer was emailed. The on-screen animation (a yellow-and-black roulette-style wheel — a slot-machine alternative was removed at the charity's request) is purely theatrical, landing on whatever the server already picked — the draw itself can't be influenced by anything happening in the browser.
- Each winner drawn is recorded permanently (bearer, prize label if entered, ticket count at the moment of drawing, and the issued ticket drawn, who drew them, when) and is immediately excluded from all further draws this season — refreshing or reopening the page mid-ceremony is always safe and just resumes where the draw left off, since eligibility is recomputed fresh from the winners recorded so far rather than tracked client-side.
- This **narrows §8's original "automatic raffle drawing is out of scope"** — the draw now happens inside the system rather than assumed to happen outside it. What's still out of scope is anything about physically awarding/shipping prizes.

### 5.10 Bulk email to bearers

Realizes the purpose-specific marketing consent idea from §11.2: Site Admins can draft, edit, preview, and send a rich-text bulk email to bearers, with **its audience computed automatically and non-editably** from whichever of the two consent purposes (§5.6, §11.2) the email is for — "next season update" or "other Make Your Mark news/events." There is no way, from the UI, to bulk-email a bearer who hasn't granted that specific consent.

- **Preview** shows the exact branded HTML the email will send (same template the real send uses), before anything goes out.
- **Sending** happens in the background rather than blocking the page, and is resumable — the recipient list is locked in the moment Send is clicked (so it can't shift mid-send), and each recipient's own send status is tracked, so re-triggering a stalled send only processes whoever's left.
- Every sent email carries a one-click, no-login **unsubscribe** link specific to that consent purpose (reusing the same consent-token mechanism as §5.6, rather than a separate token), and every send is logged in the audit log (§5.8).
- Deliberately minimal for this first version: one shared version of the email for every recipient (no per-bearer merge fields yet), no scheduling, and no open/click tracking.

## 6. Non-Functional Requirements

- **Scale:** seasonal and bursty but not small — up to 5,000 submissions over a 6-week window (§3), entered by up to 30 volunteers working concurrently. The app needs to comfortably handle ~30 simultaneous logged-in data-entry sessions; this is still a modest load for any conventional web framework/database, but it rules out a single-writer datastore (see §7 database row).
- **Auth:** staff/admin accounts with basic username+password login (or an open-source SSO if the charity already has one — not assumed here), one account per volunteer so entries and corrections are attributable. No self-service signup; accounts provisioned by an admin.
- **Data sensitivity:** bearer PII (name, address, email, phone) must be handled carefully — access restricted to logged-in staff, no public endpoints exposing bearer data (aside from the single tokenized consent link, §5.6), backups encrypted at rest if hosted anywhere shared.
- **Auditability:** who entered/edited each submission and when; who ran a consent purge and when.
- **Backups/export:** all data exportable (CSV/DB dump) — this is a small charity; the system must never be the single point of failure for donor/participant data.

## 7. Proposed Architecture (open to revision)

| Layer | Choice | Why |
|---|---|---|
| Language/framework | **Python + Django** | Free/open-source (BSD license). Django's built-in admin framework is a strong fit for an internal staff data-entry/reporting tool like this — much of §5 can be built on top of it rather than from scratch, saving significant effort. |
| Database | **PostgreSQL** | Free/open-source, mature, well-supported by Django. With up to 30 volunteers writing concurrently (§6), SQLite's single-writer locking model would cause real contention during intake — Postgres removes that risk. (SQLite remains fine for local dev.) |
| Email | Django's SMTP email backend, pointed at whatever mail account/relay the charity already controls (e.g. its own domain's SMTP, or a free-tier transactional mail provider) | No proprietary software dependency — SMTP is a protocol, not licensed software. The specific mail provider is a hosting/ops decision, not an architecture one. |
| Hosting | **Railway** for dev/test (`Procfile`: gunicorn + WhiteNoise for static files, managed Postgres plugin). **Production: Krystal.io** — decided since v0.1, on cost (a substantial charity discount on their commercial plans) and the charity's preference for an ethically-run provider. Krystal has no Railway-equivalent git-push PaaS for Python apps (their own docs steer production Python workloads to a plain VPS, not their shared-hosting "Python apps" feature) — production deploys will need their own small pipeline built on top of a Krystal Cloud VM (e.g. GitHub Actions over SSH, or their DeployHQ product), which Railway's managed PaaS gave for free. See §9. | Doesn't affect software licensing either way since these are hosting services, not software dependencies. |
| Frontend | Django server-rendered templates (+ minimal JS for the 296-checkbox UI: search/filter, live-updating stamp count) | Keeps the stack simple — no separate frontend framework/build pipeline needed for a form-and-reports tool like this. |

## 8. Explicitly Out of Scope (for now)

- Bearer self-service accounts, online stamp collection, or a bearer-facing portal — with the one narrow exception of the single-purpose, no-login links: the consent link (§5.6) and each bulk email's unsubscribe link (§5.10).
- Payment processing.
- ~~Automatic raffle drawing~~ — **now in scope**, see §5.9. Physically awarding/shipping prizes remains out of scope.
- Multi-charity/multi-tenant support.
- Per-bearer merge-field personalization, scheduled sends, or open/click tracking on bulk email (§5.10) — noted there as a deliberate v1 simplification, not ruled out long-term.

## 9. Open Questions

- Exact list of the 296 cafes and their numbering — needed before cafe-list import can be built.
- Does a bearer's identity ever need to match across seasons (e.g. "returning bearer" recognition), or is every submission independent? Affects whether Bearer should dedupe/link across Season.
- ~~Preferred hosting environment~~ — **resolved**: Krystal.io for production (§7). Still open: **mail-sending account** — no host (Railway dev/test or Krystal production) has real SMTP credentials configured yet, so email sending (both §5.3's confirmation email and §5.10's bulk email) currently only reaches Django's console log everywhere, not real inboxes. 30 concurrent users and a mail-sending volume of up to 5,000 emails in a burst may affect the choice of provider/relay once an account is chosen.
- **Krystal production deploy pipeline** (new, §7): since Krystal has no Railway-equivalent, decide how deploys actually happen there — their own DeployHQ product, or a plain GitHub Actions → SSH workflow — and whether that pipeline (and the VM itself) is something this project sets up, or something the charity's existing web team already has a pattern for.
- Any existing branding/template requirements for the confirmation email (§5.3) — also relevant to the bulk email template introduced in §5.10, which currently uses placeholder branding (colors only, no logo/imagery).
- **§5.3's confirmation email itself is still unbuilt** — the data model and consent-request wording exist, but no code sends it yet. §5.10's bulk email (a different, admin-triggered feature) was built first because it was asked for first; this is noted so it isn't assumed to already exist.
- **Consent default posture (§5.6):** should this be strict opt-in (retain only on explicit "yes," which is the safer/GDPR-style default assumed here), or opt-out? Is there a specific legal/regulatory framework the charity needs to comply with (jurisdiction, data protection law) that should govern this?
- **Retention grace period (§5.6):** how long after a season's raffle concludes should a declined/non-responding bearer's personal data be purged? (Spec currently leaves this as an admin-configurable period, no default chosen.)
- How should volunteers physically log/batch incoming passports in the 6-week window (§5.2) — is there an existing mailroom process this should slot into, or should the system define one?

## 10. Hosting & Cost Estimate (Rough)

Back-of-envelope only — for budgeting discussion, not a quote. Actual pricing varies by provider/region and by how much managed-service convenience the charity wants to pay for.

### 10.1 Base case — 5,000 passports, 30 volunteers (§3)

- **Data volume:** trivial. ~5,000 bearer + submission records, plus a stamp/cafe join table — even at a generous average of 50 stamps/passport that's ~250,000 rows (worst case, everyone maxes all 296 cafes: ~1.5M rows). Either way, well under 1GB including indexes and years of history.
- **Request load:** 30 concurrent volunteers, each generating maybe 10–20 server requests/hour (the 296-checkbox UI is handled client-side, no round-trip per click) → ~450 req/hr ≈ 0.13 req/sec sustained. Negligible for any conventional stack; a 10x burst is still trivial.
- **Email:** ~5,000 emails over 6 weeks (~120/day average, a few hundred on a heavy day) — comfortably within a normal Google Workspace/Microsoft 365 account's daily sending limits, so **effectively $0 extra** if sent via the charity's existing email. A pay-as-you-go alternative (Amazon SES) would cost ~$0.10/1,000 emails ≈ **$0.50 for the season**.

| Approach | Covers | Est. cost |
|---|---|---|
| Single small VM (Hetzner/DigitalOcean/Linode), app + Postgres combined | 1–2 vCPU, 2GB RAM, ~25GB SSD | **$6–15/month** |
| Managed PaaS (Render/Railway/Fly) — web service + managed Postgres | Less ops burden, automatic backups/TLS | **$15–25/month** |
| Domain (if needed) | — | ~$10–15/**year** |
| Email | Org's existing email, or SES | ~$0–5/**year** |

**All-in estimate: roughly $10–25/month ($120–300/year).**

### 10.2 Best case (sold-out) — 17,000 passports, ~100 volunteers

If every sold passport is returned, worked by a proportionally larger volunteer pool:

- **Data volume:** ~3.4x the base case — worst case ~5 million stamp-join rows. Still comfortably under a few hundred MB. Not a meaningful cost driver at any scale considered here.
- **Request load:** 100 concurrent volunteers → ~1,500 req/hr ≈ 0.4 req/sec sustained. Still trivial on its own, but 100 concurrent logged-in sessions can bump into Postgres's default 100-connection limit — worth adding connection pooling (**PgBouncer**, free/open-source, BSD-licensed) rather than a bigger server. This is a configuration change, not a cost driver.
- **Email:** ~17,000 emails over a similar window implies ~400/day average, with burst days plausibly in the 1,000–2,000/day range. That's tight against personal/free email caps and even risks reputation flags on a regular Workspace/365 mailbox at that volume. **Recommendation: switch to a proper transactional provider (e.g. Amazon SES)** regardless of cost — still only ~$0.10/1,000 emails ≈ **$1.70 for the season**, but it avoids deliverability problems at this volume.

| Approach | Base case (5k/30) | Best case (17k/100) |
|---|---|---|
| Single small VM, app+DB combined | $6–15/month | $15–30/month (one tier up, headroom + pooling) |
| Managed PaaS (web + managed Postgres) | $15–25/month | $25–45/month (next tier up on both) |
| Email | ~$0–5/year (org email fine) | ~$2–5/**season** (needs SES/transactional, not a regular mailbox) |
| Domain | ~$10–15/year | ~$10–15/year (unchanged) |

**All-in estimate: roughly $200–500/year** — noticeably higher in absolute terms, but the jump is small relative to the 3.4x increase in volume/headcount, because the base case was already far under any real capacity ceiling. The only *qualitative* (not just quantitative) changes at 17k/100 are: add DB connection pooling, and move email off a regular mailbox onto a transactional sending service.

## 11. Future Development Possibilities

Not being built now — noted so today's data model doesn't quietly foreclose them later. Nothing here changes §8's scope for the current build; it's context for how Venue and Bearer records are shaped so they can be extended rather than redone.

### 11.1 Venue data → simple CRM

- Not every numbered location on the passport is strictly a cafe (§4) — "Venue" is likely the more accurate long-term name for this entity, and better reflects a possible future use beyond stamp-tracking.
- The charity may want to retain and organize this venue data (contact person, address, category, participation history across seasons) for eventual use in a simple CRM — e.g. managing the partner relationship, renewals, thank-yous, and popularity tracking (already noted as a nice-to-have in §5.5) independent of any single season's passport.
- Implication for the current build: model Venue as its own entity with room for these fields (even if most stay empty for now), rather than a flat name+number list — the cost of doing this now is small, and it avoids a data migration later if the CRM idea goes ahead.

### 11.2 Bearer data for marketing (future events, online merchandising)

- Bearer data retained under consent (§5.6) is currently framed around one purpose: keeping contact details for *next season's* Bike + Brew. The charity may in future want to use the same retained data to market other things — future events, online merchandise.
- That's a **distinct consent purpose** from "keep my details for next year's passport," and best practice (and likely relevant data-protection law, per the open question in §9) is to ask for it separately rather than assume a bearer who agreed to one has agreed to the other.
- Implication for the current build: design the consent capture in §5.6 to be purpose-specific from the start (e.g. separate opt-ins — "contact me about next year's Bike + Brew" vs. "contact me about other Make Your Mark events and merchandise") rather than a single generic yes/no. This costs little now and avoids having to re-contact bearers to ask again if the charity wants to broaden how it uses the data later.
- **Implemented as of §5.10**: the purpose-specific opt-ins described above now exist and gate an actual bulk-email feature — this section's "future possibility" is built, not just modeled.
