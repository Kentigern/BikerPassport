from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .access import is_bearer_verified, mark_bearer_verified
from .forms import BearerForm
from .models import Bearer, PassportSubmission, Season, Venue
from .phone import normalize_uk_phone


def _permission_denied_json(message):
    return JsonResponse({'ok': False, 'errors': {'permission': [message]}}, status=403)


@staff_member_required
def landing_view(request):
    return render(request, 'passports/landing.html')


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
