import csv
import random

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .access import is_bearer_verified, mark_bearer_verified
from .forms import BearerForm
from .models import Bearer, PassportSubmission, RaffleExport, Season, Venue
from .phone import normalize_uk_phone


def _permission_denied_json(message):
    return JsonResponse({'ok': False, 'errors': {'permission': [message]}}, status=403)


@staff_member_required
def landing_view(request):
    return render(request, 'passports/landing.html')


def _ranked(queryset, count_attr):
    """Attach each item's share of the list's own max as `pct`, so the
    template can size a CSS bar without doing division itself."""
    items = list(queryset)
    max_count = getattr(items[0], count_attr) if items else 0
    return [
        {'obj': item, 'count': getattr(item, count_attr), 'pct': round(getattr(item, count_attr) / max_count * 100)}
        for item in items
    ]


def _is_site_admin(user):
    return user.is_superuser or user.groups.filter(name='Site Admin').exists()


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


@staff_member_required
def raffle_audit_log_view(request):
    if not _is_site_admin(request.user):
        raise PermissionDenied

    q = request.GET.get('q', '').strip()
    entries = RaffleExport.objects.select_related('season', 'generated_by').order_by('-generated_at')
    if q:
        entries = entries.filter(
            Q(generated_by__username__icontains=q) | Q(season__name__icontains=q)
        )

    return render(request, 'passports/raffle_audit_log.html', {'entries': entries, 'q': q})


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
        if not request.user.has_perm('passports.add_bearer'):
            return _permission_denied_json('You do not have permission to add bearers.')
        instance = None
    else:
        if not request.user.has_perm('passports.change_bearer'):
            return _permission_denied_json('You do not have permission to change bearers.')
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
    if submission_id:
        if not request.user.has_perm('passports.change_passportsubmission'):
            return _permission_denied_json('You do not have permission to change submissions.')
    else:
        if not request.user.has_perm('passports.add_passportsubmission'):
            return _permission_denied_json('You do not have permission to add submissions.')

    venues = Venue.objects.filter(pk__in=request.POST.getlist('venues_stamped'), is_active=True)
    date_received = parse_date(request.POST.get('date_received', '')) or timezone.localdate()
    notes = request.POST.get('notes', '')

    matched_existing = False

    try:
        if submission_id:
            submission = get_object_or_404(PassportSubmission, pk=submission_id)
            submission.bearer = bearer
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
    if not request.user.has_perm('passports.view_bearer'):
        return _permission_denied_json('You do not have permission to view bearers.')

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
            for b in bearers:
                mark_bearer_verified(request, b.pk)
                existing = (
                    PassportSubmission.objects.filter(bearer=b, season=season).first()
                    if season
                    else None
                )
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
