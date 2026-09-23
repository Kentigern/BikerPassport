import csv
import random
import threading

from django.contrib.admin.models import LogEntry
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from .access import (
    is_bearer_editable,
    is_bearer_verified,
    is_site_admin,
    is_submission_editable,
    mark_bearer_verified,
)
from .emailing import (
    qualifying_bearers,
    send_and_record_confirmation,
    send_campaign,
    send_notes_alert,
    snapshot_recipients,
)
from .forms import BearerForm
from .models import (
    Bearer,
    ConsentStatus,
    EmailCampaign,
    EmailCampaignRecipient,
    PassportSubmission,
    RaffleExport,
    RaffleTicket,
    RaffleWinner,
    Season,
    Venue,
)
from .phone import normalize_uk_phone

# Guards against double-starting a background send for the same campaign
# within one running process (e.g. a double form-submit) — see
# passports/emailing.py's module docstring for why this isn't a real
# task queue yet. A process restart clears this naturally; resuming a
# stalled send afterwards is just calling send_campaign again.
_SENDING_CAMPAIGN_IDS = set()


def _permission_denied_json(message):
    return JsonResponse({'ok': False, 'errors': {'permission': [message]}}, status=403)


def _require_perm(request, perm, message):
    """Shared JSON-403 pattern for this app's fetch/POST API endpoints
    (bearer_search_view, bearer_save_view, submission_save_view) — every
    permission failure on one of those must come back as this same JSON
    shape, never Django's HTML 403 page, so intake.js can handle every
    endpoint's failure the same way without special-casing. Full-page views
    (dashboard_view, raffle_export_view, audit_log_view) intentionally keep
    raising PermissionDenied instead — a plain browser navigation should get
    Django's normal HTML 403 page, not JSON. Returns the response to return
    if the permission is missing, or None if the caller may proceed."""
    if not request.user.has_perm(perm):
        return _permission_denied_json(message)
    return None


@staff_member_required
def landing_view(request):
    return render(request, 'passports/landing.html')


def _ranked(queryset, count_attr):
    """Attach each item's share of the list's own max as `pct`, so the
    template can size a CSS bar without doing division itself."""
    items = list(queryset)
    max_count = getattr(items[0], count_attr) if items else 0
    return [
        {
            'obj': item,
            'count': getattr(item, count_attr),
            'pct': round(getattr(item, count_attr) / max_count * 100) if max_count else 0,
        }
        for item in items
    ]


def _is_site_admin(user):
    return user.is_superuser or is_site_admin(user)


@staff_member_required
def dashboard_view(request):
    if not _is_site_admin(request.user):
        raise PermissionDenied

    season = Season.objects.current()
    context = {'season': season}

    if season is None:
        return render(request, 'passports/dashboard.html', context)

    submissions = PassportSubmission.objects.filter(season=season)

    top_venues = _ranked(
        Venue.objects.annotate(
            visit_count=Count('submissions', filter=Q(submissions__season=season))
        )
        .filter(visit_count__gt=0)
        .order_by('-visit_count', 'name'),
        'visit_count',
    )[:5]

    top_loggers = _ranked(
        get_user_model()
        .objects.annotate(
            logged_count=Count('entered_submissions', filter=Q(entered_submissions__season=season))
        )
        .filter(logged_count__gt=0)
        .order_by('-logged_count', 'username'),
        'logged_count',
    )[:5]

    top_bearers = _ranked(
        Bearer.objects.annotate(
            venues_visited=Count(
                'submissions__venues_stamped',
                filter=Q(submissions__season=season),
                distinct=True,
            )
        )
        .filter(venues_visited__gt=0)
        .order_by('-venues_visited', 'name'),
        'venues_visited',
    )[:5]

    all_venues = _ranked(
        Venue.objects.annotate(
            visit_count=Count('submissions', filter=Q(submissions__season=season))
        ).order_by('-visit_count', 'name'),
        'visit_count',
    )

    all_loggers = _ranked(
        get_user_model()
        .objects.annotate(
            logged_count=Count('entered_submissions', filter=Q(entered_submissions__season=season))
        )
        .order_by('-logged_count', 'username'),
        'logged_count',
    )

    all_bearers = _ranked(
        Bearer.objects.annotate(
            venues_visited=Count(
                'submissions__venues_stamped',
                filter=Q(submissions__season=season),
                distinct=True,
            )
        ).order_by('-venues_visited', 'name'),
        'venues_visited',
    )

    context.update(
        {
            'total_logged': submissions.count(),
            'logged_today': submissions.filter(date_received=timezone.localdate()).count(),
            'top_venues': top_venues,
            'top_loggers': top_loggers,
            'top_bearers': top_bearers,
            'all_venues': all_venues,
            'all_loggers': all_loggers,
            'all_bearers': all_bearers,
        }
    )
    return render(request, 'passports/dashboard.html', context)


@staff_member_required
@require_POST
def raffle_export_view(request):
    """CSV raffle draw list — one row per issued ticket (RaffleTicket), in
    ticket-number order, so each row's number is the same one its bearer
    was sent in their confirmation email. No mailing address: multi-line
    addresses broke the CSV in spreadsheets, and the live draw (not this
    export) is how the raffle is actually run.

    Real prizes are on the line, so this is POST-only (it can issue any
    still-missing ticket numbers first — see issue_missing_for_season)
    and every export is logged to RaffleExport — an immutable record of
    who generated it, when, and how many tickets it contained."""
    if not _is_site_admin(request.user):
        raise PermissionDenied

    season = Season.objects.current()
    filename = f"raffle_entries_{season or 'no_season'}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Ticket Number', 'Name', 'Email', 'Phone'])

    if season is not None:
        RaffleTicket.objects.issue_missing_for_season(season)
        tickets = RaffleTicket.objects.filter(season=season).select_related('submission__bearer').order_by('number')
        entry_count = 0
        for ticket in tickets:
            bearer = ticket.submission.bearer
            writer.writerow([ticket.number, bearer.name, bearer.email, bearer.phone])
            entry_count += 1

        RaffleExport.objects.create(
            season=season, generated_by=request.user, entry_count=entry_count
        )

    return response


def _raffle_draw_pool(season):
    """Every issued ticket (RaffleTicket) still in the running this season
    — i.e. whose bearer hasn't already won. Drawing uniformly over tickets
    is what weights each bearer by their ticket count. Tops up any
    submission still short of its earned tickets first, so one that was
    saved but never Save & Exited isn't silently left out of the draw.
    Returns (ticket_id, bearer_id) pairs — cheap enough for thousands."""
    RaffleTicket.objects.issue_missing_for_season(season)
    already_won = RaffleWinner.objects.filter(season=season).values_list('bearer_id', flat=True)
    return list(
        RaffleTicket.objects.filter(season=season)
        .exclude(submission__bearer_id__in=already_won)
        .values_list('pk', 'submission__bearer_id')
    )


@staff_member_required
def raffle_draw_view(request):
    """The live, on-screen raffle wheel — a roulette-style draw meant to be
    projected at the event itself. The wheel itself is a fixed, decorative
    set of pockets (like a real roulette wheel, which has 37/38 regardless
    of how many people are playing) — with a big event's worth of entrants
    potentially in the thousands, one slice per bearer would be illegible
    anyway, so only the eligible *count* is shown, not each bearer. Drawing
    a winner (raffle_draw_spin_view) removes them from all future draws
    this season; the count is recomputed fresh from RaffleWinner on every
    load, so refreshing mid-ceremony is always safe and just resumes where
    the draw left off."""
    if not _is_site_admin(request.user):
        raise PermissionDenied

    season = Season.objects.current()
    pool_count = 0
    winners = []
    if season is not None:
        pool_count = len({bearer_id for _, bearer_id in _raffle_draw_pool(season)})
        winners = RaffleWinner.objects.filter(season=season).select_related('bearer')

    return render(
        request,
        'passports/raffle_draw.html',
        {'season': season, 'pool_count': pool_count, 'winners': winners},
    )


@staff_member_required
@require_POST
def raffle_draw_spin_view(request):
    """Picks the winning ticket server-side (uniformly over every still-
    eligible issued ticket) the instant this is called — the browser only
    animates a spin that lands on whichever ticket this already chose, so
    the pick itself can't be influenced client-side. The number revealed
    is the drawn ticket's own issued number — the one its bearer was
    emailed — so winners can be announced by number. JSON-403 on failure,
    matching this app's other fetch-driven endpoints
    (bearer_search_view/bearer_save_view/submission_save_view) rather than
    the HTML PermissionDenied the full-page raffle views use."""
    if not _is_site_admin(request.user):
        return _permission_denied_json('You do not have permission to run the raffle draw.')

    season = Season.objects.current()
    if season is None:
        return JsonResponse({'ok': False, 'errors': {'season': ['No season exists yet.']}}, status=400)

    pool = _raffle_draw_pool(season)
    if not pool:
        return JsonResponse({'ok': False, 'errors': {'pool': ['No eligible entrants left.']}}, status=400)

    ticket_id, _ = random.SystemRandom().choice(pool)
    ticket = RaffleTicket.objects.select_related('submission__bearer').get(pk=ticket_id)
    winner_bearer = ticket.submission.bearer
    winner_tickets = RaffleTicket.objects.filter(submission_id=ticket.submission_id).count()
    ticket_number = ticket.number
    prize = request.POST.get('prize', '').strip()

    try:
        RaffleWinner.objects.create(
            season=season,
            bearer=winner_bearer,
            prize=prize,
            ticket_count=winner_tickets,
            ticket=ticket,
            ticket_number=ticket_number,
            drawn_by=request.user,
        )
    except IntegrityError:
        return JsonResponse(
            {'ok': False, 'errors': {'bearer': ['Already won this season.']}}, status=400
        )

    return JsonResponse(
        {
            'ok': True,
            'winner': {
                'id': winner_bearer.pk,
                'name': winner_bearer.name,
                'tickets': winner_tickets,
                'ticket_number': ticket_number,
                'prize': prize,
            },
        }
    )


HISTORY_LABELS = {'+': 'Created', '~': 'Updated', '-': 'Deleted'}

# Order controls the "All" dropdown's display order in the template too.
EVENT_TYPES = {
    'bearer': 'Bearer',
    'submission': 'Submission',
    'admin': 'User/Site Admin',
    'raffle': 'Raffle export',
    'raffle_winner': 'Raffle winner',
    'bulk_email': 'Bulk email',
}

# Bounded per-source, applied after any search filter — cheap and correct
# for this app's actual scale (a small yearly charity program). A single
# cross-table SQL UNION would avoid the bound but isn't worth the added
# complexity here.
_EVENTS_PER_SOURCE = 300


def _submission_summary(history_type, record):
    # PassportSubmission.__str__ traverses .season/.bearer live — safe for
    # a current row, but a historical row can point at an id that's since
    # been deleted (e.g. the bearer itself was later removed), which
    # raises DoesNotExist rather than just returning None like a
    # SET_NULL/blank FK would. Build the summary from raw ids instead of
    # calling str(record) so a stale reference degrades to a label rather
    # than a 500.
    try:
        bearer_desc = str(record.bearer) if record.bearer_id else 'no bearer'
    except Bearer.DoesNotExist:
        bearer_desc = f"bearer #{record.bearer_id} (deleted)"
    try:
        season_desc = str(record.season) if record.season_id else 'no season'
    except Season.DoesNotExist:
        season_desc = f"season #{record.season_id} (deleted)"
    return f"{HISTORY_LABELS[history_type]} — #{record.intake_number} ({season_desc}) — {bearer_desc}"


def _event(category, timestamp, actor, summary):
    return {
        'category': category,
        'category_label': EVENT_TYPES[category],
        'timestamp': timestamp,
        'actor': actor.username if actor else '—',
        'summary': summary,
    }


@staff_member_required
def audit_log_view(request):
    """Merges three otherwise-separate audit trails into one timeline:
    simple_history on Bearer/PassportSubmission (covers changes made via
    *either* the raw admin or the custom intake-form views, since
    HistoryRequestMiddleware attributes history_user regardless of entry
    point), Django's built-in admin LogEntry (covers everything else
    administered via the raw admin — Users, Groups, Venue, Season), and
    RaffleExport. LogEntry is excluded for Bearer/PassportSubmission
    specifically, since simple_history already covers those more
    completely and duplicating them here would just be noise."""
    if not _is_site_admin(request.user):
        raise PermissionDenied

    q = request.GET.get('q', '').strip()
    event_type = request.GET.get('type', '')
    if event_type not in EVENT_TYPES:
        # An unrecognized ?type= (typo'd or stale link) would otherwise
        # silently match none of the branches below and render an empty
        # page that reads as "no events" rather than "invalid filter" — so
        # treat it the same as no filter at all.
        event_type = ''
    events = []
    # Per-source labels where the _EVENTS_PER_SOURCE cap actually cut off
    # real rows, so the template can say so instead of the page silently
    # implying this is the complete history.
    truncated = []

    if event_type in ('', 'bearer'):
        qs = Bearer.history.select_related('history_user')
        if q:
            qs = qs.filter(Q(history_user__username__icontains=q) | Q(name__icontains=q))
        qs = qs.order_by('-history_date')
        if qs.count() > _EVENTS_PER_SOURCE:
            truncated.append(EVENT_TYPES['bearer'])
        for r in qs[:_EVENTS_PER_SOURCE]:
            events.append(
                _event('bearer', r.history_date, r.history_user, f"{HISTORY_LABELS[r.history_type]} — {r}")
            )

    if event_type in ('', 'submission'):
        qs = PassportSubmission.history.select_related('history_user', 'bearer', 'season')
        if q:
            qs = qs.filter(Q(history_user__username__icontains=q) | Q(bearer__name__icontains=q))
        qs = qs.order_by('-history_date')
        if qs.count() > _EVENTS_PER_SOURCE:
            truncated.append(EVENT_TYPES['submission'])
        for r in qs[:_EVENTS_PER_SOURCE]:
            events.append(
                _event('submission', r.history_date, r.history_user, _submission_summary(r.history_type, r))
            )

    if event_type in ('', 'admin'):
        qs = LogEntry.objects.exclude(
            content_type__app_label='passports',
            content_type__model__in=['bearer', 'passportsubmission'],
        ).select_related('user', 'content_type')
        if q:
            qs = qs.filter(Q(user__username__icontains=q) | Q(object_repr__icontains=q))
        qs = qs.order_by('-action_time')
        if qs.count() > _EVENTS_PER_SOURCE:
            truncated.append(EVENT_TYPES['admin'])
        for e in qs[:_EVENTS_PER_SOURCE]:
            events.append(_event('admin', e.action_time, e.user, f"{e.object_repr} — {e.get_change_message()}"))

    if event_type in ('', 'raffle'):
        qs = RaffleExport.objects.select_related('season', 'generated_by')
        if q:
            qs = qs.filter(Q(generated_by__username__icontains=q) | Q(season__name__icontains=q))
        qs = qs.order_by('-generated_at')
        if qs.count() > _EVENTS_PER_SOURCE:
            truncated.append(EVENT_TYPES['raffle'])
        for r in qs[:_EVENTS_PER_SOURCE]:
            events.append(_event('raffle', r.generated_at, r.generated_by, f"{r.season} — {r.entry_count} tickets"))

    if event_type in ('', 'raffle_winner'):
        qs = RaffleWinner.objects.select_related('season', 'bearer', 'drawn_by')
        if q:
            qs = qs.filter(
                Q(drawn_by__username__icontains=q) | Q(bearer__name__icontains=q) | Q(season__name__icontains=q)
            )
        qs = qs.order_by('-drawn_at')
        if qs.count() > _EVENTS_PER_SOURCE:
            truncated.append(EVENT_TYPES['raffle_winner'])
        for r in qs[:_EVENTS_PER_SOURCE]:
            prize_part = f' — {r.prize}' if r.prize else ''
            events.append(
                _event(
                    'raffle_winner',
                    r.drawn_at,
                    r.drawn_by,
                    f'{r.season} — {r.bearer}{prize_part} ({r.ticket_count} tickets)',
                )
            )

    if event_type in ('', 'bulk_email'):
        qs = EmailCampaign.objects.filter(status=EmailCampaign.Status.SENT).select_related('created_by')
        if q:
            qs = qs.filter(Q(created_by__username__icontains=q) | Q(subject__icontains=q))
        qs = qs.order_by('-sent_at')
        if qs.count() > _EVENTS_PER_SOURCE:
            truncated.append(EVENT_TYPES['bulk_email'])
        for c in qs[:_EVENTS_PER_SOURCE]:
            events.append(
                _event(
                    'bulk_email',
                    c.sent_at,
                    c.created_by,
                    f'{c.subject} ({c.get_purpose_display()}) — {c.sent_count} sent, {c.failed_count} failed',
                )
            )

    events.sort(key=lambda e: e['timestamp'], reverse=True)

    page = Paginator(events, 50).get_page(request.GET.get('page'))

    return render(
        request,
        'passports/audit_log.html',
        {
            'page': page,
            'q': q,
            'event_type': event_type,
            'event_types': EVENT_TYPES,
            'truncated': truncated,
            'events_per_source': _EVENTS_PER_SOURCE,
        },
    )


@staff_member_required
def submission_form_view(request, pk=None):
    submission = get_object_or_404(PassportSubmission, pk=pk) if pk else None
    read_only = False

    if submission is None:
        if not request.user.has_perm('passports.add_passportsubmission'):
            raise PermissionDenied
    else:
        if not is_bearer_verified(request, submission.bearer_id):
            raise PermissionDenied
        # A locked submission (see access.is_submission_editable) isn't a
        # reason to block a Logger outright — they still legitimately need
        # to look up what was already entered (e.g. finding it again via
        # search) — so this falls back to view-only access instead of a
        # flat 403. Site Admins/superusers hit is_submission_editable's own
        # exemption and never see this branch as read-only.
        read_only = not is_submission_editable(request.user, submission)
        required_perm = 'passports.view_passportsubmission' if read_only else 'passports.change_passportsubmission'
        if not request.user.has_perm(required_perm):
            raise PermissionDenied

    bearer_form = BearerForm(instance=submission.bearer if submission else None)
    if read_only:
        for field in bearer_form.fields.values():
            field.disabled = True
    checked_ids = (
        set(submission.venues_stamped.values_list('pk', flat=True)) if submission else set()
    )
    return render(
        request,
        'passports/submission_form.html',
        {
            'bearer_form': bearer_form,
            'submission': submission,
            'venues': Venue.objects.filter(is_active=True),
            'checked_ids': checked_ids,
            'today': timezone.localdate().isoformat(),
            'read_only': read_only,
        },
    )


@staff_member_required
def bearer_save_view(request):
    bearer_id = request.POST.get('bearer_id') or None

    if bearer_id is None:
        denied = _require_perm(request, 'passports.add_bearer', 'You do not have permission to add bearers.')
        if denied:
            return denied
        instance = None
    else:
        denied = _require_perm(
            request, 'passports.change_bearer', 'You do not have permission to change bearers.'
        )
        if denied:
            return denied
        if not is_bearer_verified(request, bearer_id):
            return _permission_denied_json('Search for this bearer by phone first.')
        instance = get_object_or_404(Bearer, pk=bearer_id)
        if not is_bearer_editable(request.user, instance):
            return _permission_denied_json(
                "This bearer's submission has already been saved and exited, and can no longer be edited."
            )

    form = BearerForm(request.POST, instance=instance)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
    bearer = form.save()
    mark_bearer_verified(request, bearer.pk)
    return JsonResponse(
        {
            'ok': True,
            'bearer': {
                'id': bearer.pk,
                'name': bearer.name,
                'email': bearer.email,
                'phone': bearer.phone,
                'mailing_address': bearer.mailing_address,
            },
        }
    )


@staff_member_required
def submission_save_view(request):
    bearer_id = request.POST.get('bearer_id')
    if not bearer_id:
        return JsonResponse(
            {'ok': False, 'errors': {'bearer_id': ['Save the bearer first.']}}, status=400
        )
    if not is_bearer_verified(request, bearer_id):
        return _permission_denied_json('Search for this bearer by phone first.')
    bearer = get_object_or_404(Bearer, pk=bearer_id)

    submission_id = request.POST.get('submission_id') or None
    existing_submission = None
    if submission_id:
        denied = _require_perm(
            request, 'passports.change_passportsubmission', 'You do not have permission to change submissions.'
        )
        if denied:
            return denied
        existing_submission = get_object_or_404(PassportSubmission, pk=submission_id)
        if not is_bearer_verified(request, existing_submission.bearer_id):
            return _permission_denied_json('Search for this bearer by phone first.')
        # A submission's bearer is immutable once created (same rule the raw
        # admin enforces via readonly_fields — see admin.py) — reassigning
        # would let a verified-but-unrelated bearer's stamps/tickets be
        # overwritten onto someone else's record.
        if int(bearer_id) != existing_submission.bearer_id:
            return _permission_denied_json("A submission's bearer cannot be changed.")
        if not is_submission_editable(request.user, existing_submission):
            return _permission_denied_json(
                'This submission has already been saved and exited, and can no longer be edited.'
            )
    else:
        denied = _require_perm(
            request, 'passports.add_passportsubmission', 'You do not have permission to add submissions.'
        )
        if denied:
            return denied

    venues = Venue.objects.filter(pk__in=request.POST.getlist('venues_stamped'), is_active=True)
    date_received = parse_date(request.POST.get('date_received', '')) or timezone.localdate()
    notes = request.POST.get('notes', '')

    matched_existing = False

    try:
        if submission_id:
            submission = existing_submission
            with transaction.atomic():
                submission.date_received = date_received
                submission.notes = notes
                submission.save()
                submission.venues_stamped.set(venues)
        else:
            season = Season.objects.current()
            if season is None:
                return JsonResponse(
                    {'ok': False, 'errors': {'season': ['No season exists yet — ask an admin to create one.']}},
                    status=400,
                )
            # One submission per bearer per season (enforced by a DB constraint
            # too): a bearer's passport accumulates stamps through the season,
            # so a second "new" save for them updates their existing record
            # rather than creating a duplicate.
            existing = PassportSubmission.objects.filter(bearer=bearer, season=season).first()
            if existing:
                if not is_submission_editable(request.user, existing):
                    return _permission_denied_json(
                        'This bearer already has a submission this season, and it has already been '
                        'saved and exited — it can no longer be edited.'
                    )
                matched_existing = True
                with transaction.atomic():
                    existing.date_received = date_received
                    existing.notes = notes
                    existing.save()
                    existing.venues_stamped.set(venues)
                submission = existing
            else:
                with transaction.atomic():
                    season = Season.objects.select_for_update().get(pk=season.pk)
                    next_number = (
                        PassportSubmission.objects.filter(season=season)
                        .aggregate(Max('intake_number'))['intake_number__max']
                        or 0
                    ) + 1
                    submission = PassportSubmission.objects.create(
                        season=season,
                        bearer=bearer,
                        intake_number=next_number,
                        date_received=date_received,
                        notes=notes,
                        status=PassportSubmission.Status.ENTERED,
                        entered_by=request.user,
                    )
                    submission.venues_stamped.set(venues)
    except IntegrityError:
        return JsonResponse(
            {'ok': False, 'errors': {'bearer_id': ['This bearer already has a different submission this season.']}},
            status=400,
        )

    # Save & Exit closes this submission out for good — see
    # access.is_submission_editable/is_bearer_editable, which a Logger
    # (but not a Site Admin/superuser) is held to from now on. The
    # confirmation email (§5.3) fires exactly once, at this same moment,
    # for the same reason: re-exiting an already-locked submission is
    # blocked above, so this branch only ever runs the first time. A failed
    # send is recorded, not raised — staff retry it from the admin later.
    just_locked = request.POST.get('exit') == 'true' and submission.locked_at is None
    if just_locked:
        submission.locked_at = timezone.now()
        submission.save(update_fields=['locked_at'])

    # Every locked submission gets its raffle ticket numbers, email or not
    # — the draw works only from issued numbers. Also tops up after a Site
    # Admin's later correction adds stamps (never removes any; see
    # RaffleTicketManager.ensure_for_submission).
    if submission.locked_at is not None:
        RaffleTicket.objects.ensure_for_submission(submission)

    if just_locked and submission.bearer.email:
        send_and_record_confirmation(submission)

    # Anything in Notes is an anomaly someone should follow up — tell staff
    # once, when the Logger finishes (not on every intermediate save).
    if just_locked and submission.notes.strip():
        send_notes_alert(submission)

    return JsonResponse(
        {
            'ok': True,
            'submission_id': submission.pk,
            'intake_number': submission.intake_number,
            'season': str(submission.season),
            'stamp_count': submission.stamp_count,
            'raffle_tickets': submission.raffle_tickets,
            'matched_existing': matched_existing,
        }
    )


@staff_member_required
def bearer_search_view(request):
    """Phone is the access-control key for a bearer's details (per the
    charity's ask): searching by phone reveals full details, searching by
    name only confirms a match exists and prompts for the phone number.
    Superusers bypass this and get full details either way (§5.2)."""
    denied = _require_perm(request, 'passports.view_bearer', 'You do not have permission to view bearers.')
    if denied:
        return denied

    q = request.GET.get('q', '').strip()
    results = []
    if q:
        season = Season.objects.current()
        normalized_phone = normalize_uk_phone(q)

        if normalized_phone:
            bearers = Bearer.objects.filter(phone=normalized_phone)
        elif request.user.is_superuser:
            bearers = Bearer.objects.filter(name__icontains=q)[:10]
        else:
            bearers = None

        if bearers is not None:
            bearers = list(bearers)
            existing_by_bearer_id = (
                {
                    s.bearer_id: s
                    for s in PassportSubmission.objects.filter(
                        bearer__in=bearers, season=season
                    )
                }
                if season and bearers
                else {}
            )
            for b in bearers:
                mark_bearer_verified(request, b.pk)
                existing = existing_by_bearer_id.get(b.pk)
                results.append(
                    {
                        'id': b.pk,
                        'name': b.name,
                        'email': b.email,
                        'phone': b.phone,
                        'mailing_address': b.mailing_address,
                        'submission_id': existing.pk if existing else None,
                        'needs_phone': False,
                    }
                )
        else:
            for b in Bearer.objects.filter(name__icontains=q)[:10]:
                results.append({'name': b.name, 'needs_phone': True})

    return JsonResponse({'results': results})


@staff_member_required
def email_campaign_list_view(request):
    if not _is_site_admin(request.user):
        raise PermissionDenied

    campaigns = EmailCampaign.objects.select_related('created_by')
    return render(request, 'passports/email_list.html', {'campaigns': campaigns})


@staff_member_required
def email_campaign_form_view(request, pk=None):
    if not _is_site_admin(request.user):
        raise PermissionDenied

    campaign = get_object_or_404(EmailCampaign, pk=pk) if pk else None
    if campaign and campaign.status != EmailCampaign.Status.DRAFT:
        # A sent (or sending) campaign is a locked record, same spirit as
        # RaffleExport/RaffleWinner — editing content someone already
        # received, after the fact, isn't something the UI should allow.
        raise PermissionDenied

    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        body_html = request.POST.get('body_html', '')
        purpose = request.POST.get('purpose', '')

        errors = {}
        if not subject:
            errors['subject'] = ['Subject is required.']
        if purpose not in EmailCampaign.Purpose.values:
            errors['purpose'] = ['Choose a purpose.']

        if errors:
            return JsonResponse({'ok': False, 'errors': errors}, status=400)

        if campaign is None:
            campaign = EmailCampaign.objects.create(
                subject=subject, body_html=body_html, purpose=purpose, created_by=request.user
            )
        else:
            campaign.subject = subject
            campaign.body_html = body_html
            campaign.purpose = purpose
            campaign.save(update_fields=['subject', 'body_html', 'purpose', 'updated_at'])

        return JsonResponse({'ok': True, 'campaign_id': campaign.pk})

    return render(
        request,
        'passports/email_form.html',
        {
            'campaign': campaign,
            'purposes': EmailCampaign.Purpose.choices,
        },
    )


@staff_member_required
def email_campaign_recipient_count_view(request):
    """Backs the compose page's live "N recipients" readout as the admin
    changes purpose — same qualifying_bearers() the actual send snapshots
    from, so the number shown is never out of step with reality."""
    if not _is_site_admin(request.user):
        raise PermissionDenied

    purpose = request.GET.get('purpose', '')
    if purpose not in EmailCampaign.Purpose.values:
        return JsonResponse({'count': 0})
    return JsonResponse({'count': qualifying_bearers(purpose).count()})


@staff_member_required
@xframe_options_sameorigin
def email_campaign_preview_view(request, pk):
    if not _is_site_admin(request.user):
        raise PermissionDenied

    campaign = get_object_or_404(EmailCampaign, pk=pk)
    return render(
        request,
        'passports/email_frame.html',
        # No specific bearer to build a real unsubscribe link for here —
        # everything else in the frame (branding, body) matches the real
        # send exactly; only this one link is a placeholder.
        {'body_html': campaign.body_html, 'unsubscribe_url': '#'},
    )


@staff_member_required
@require_POST
def email_campaign_send_view(request, pk):
    if not _is_site_admin(request.user):
        raise PermissionDenied

    campaign = get_object_or_404(EmailCampaign, pk=pk)
    if campaign.status == EmailCampaign.Status.DRAFT:
        snapshot_recipients(campaign)
        campaign.status = EmailCampaign.Status.SENDING
        campaign.save(update_fields=['status'])

    if campaign.pk not in _SENDING_CAMPAIGN_IDS:
        _SENDING_CAMPAIGN_IDS.add(campaign.pk)

        def _run():
            try:
                send_campaign(campaign.pk)
            finally:
                _SENDING_CAMPAIGN_IDS.discard(campaign.pk)

        threading.Thread(target=_run, daemon=True).start()

    return redirect('email_campaign_status', pk=campaign.pk)


@staff_member_required
def email_campaign_status_view(request, pk):
    if not _is_site_admin(request.user):
        raise PermissionDenied

    campaign = get_object_or_404(EmailCampaign, pk=pk)
    return render(request, 'passports/email_status.html', {'campaign': campaign})


@staff_member_required
def email_campaign_status_json_view(request, pk):
    if not _is_site_admin(request.user):
        raise PermissionDenied

    campaign = get_object_or_404(EmailCampaign, pk=pk)
    return JsonResponse(
        {
            'status': campaign.status,
            'recipient_count': campaign.recipient_count,
            'sent_count': campaign.sent_count,
            'failed_count': campaign.failed_count,
            'pending_count': campaign.recipients.filter(
                status=EmailCampaignRecipient.Status.PENDING
            ).count(),
        }
    )


def email_unsubscribe_view(request, token, purpose):
    """No-login, unauthenticated — reached from a link in the email
    itself, not the admin app. Scoped to declining only (§5.6's full
    opt-in consent-request flow is separate, not-yet-built work)."""
    if purpose not in EmailCampaign.Purpose.values:
        raise Http404

    bearer = get_object_or_404(Bearer, consent_token=token)
    field = 'next_season_consent_status' if purpose == EmailCampaign.Purpose.NEXT_SEASON else 'marketing_consent_status'
    responded_field = f'{field.removesuffix("_status")}_responded_at'

    setattr(bearer, field, ConsentStatus.DECLINED)
    setattr(bearer, responded_field, timezone.now())
    bearer.save(update_fields=[field, responded_field])

    purpose_label = dict(EmailCampaign.Purpose.choices)[purpose]
    return render(request, 'passports/unsubscribe_confirm.html', {'purpose_label': purpose_label})
