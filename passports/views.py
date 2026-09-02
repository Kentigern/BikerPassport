import csv
import random

from django.contrib.admin.models import LogEntry
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .access import is_bearer_verified, is_site_admin, mark_bearer_verified
from .forms import BearerForm
from .models import Bearer, PassportSubmission, RaffleExport, Season, Venue
from .phone import normalize_uk_phone


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

    context.update(
        {
            'total_logged': submissions.count(),
            'logged_today': submissions.filter(date_received=timezone.localdate()).count(),
            'top_venues': top_venues,
            'top_loggers': top_loggers,
            'top_bearers': top_bearers,
        }
    )
    return render(request, 'passports/dashboard.html', context)


@staff_member_required
@require_POST
def raffle_export_view(request):
    """CSV raffle draw list — one row per *ticket*, not per bearer (a
    bearer with 3 tickets gets 3 rows), shuffled, numbered. Mirrors the
    legacy MARK_Entries.py tool's output shape, adapted to our actual
    Bearer fields (a single mailing_address, not separate address lines).

    Real prizes are on the line, so this is POST-only (a plain GET link
    would let anyone re-roll the shuffle just by refreshing/re-clicking)
    and every export is logged to RaffleExport — an immutable record of
    who generated it, when, and how many tickets it contained."""
    if not _is_site_admin(request.user):
        raise PermissionDenied

    season = Season.objects.current()
    filename = f"raffle_entries_{season or 'no_season'}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Entry ID', 'Name', 'Email', 'Phone', 'Mailing Address'])

    if season is not None:
        submissions = (
            PassportSubmission.objects.filter(season=season)
            .select_related('bearer')
            .annotate(stamp_total=Count('venues_stamped'))
        )
        entries = []
        for submission in submissions:
            tickets = min(submission.stamp_total // 10, PassportSubmission.MAX_RAFFLE_TICKETS)
            entries.extend([submission.bearer] * tickets)
        random.shuffle(entries)
        for entry_id, bearer in enumerate(entries, start=1):
            writer.writerow([entry_id, bearer.name, bearer.email, bearer.phone, bearer.mailing_address])

        RaffleExport.objects.create(
            season=season, generated_by=request.user, entry_count=len(entries)
        )

    return response


HISTORY_LABELS = {'+': 'Created', '~': 'Updated', '-': 'Deleted'}

# Order controls the "All" dropdown's display order in the template too.
EVENT_TYPES = {
    'bearer': 'Bearer',
    'submission': 'Submission',
    'admin': 'User/Site Admin',
    'raffle': 'Raffle export',
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

    if submission is None:
        if not request.user.has_perm('passports.add_passportsubmission'):
            raise PermissionDenied
    else:
        if not request.user.has_perm('passports.change_passportsubmission'):
            raise PermissionDenied
        if not is_bearer_verified(request, submission.bearer_id):
            raise PermissionDenied

    bearer_form = BearerForm(instance=submission.bearer if submission else None)
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
