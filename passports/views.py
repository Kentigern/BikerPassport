from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import BearerForm, PassportSubmissionForm
from .models import Bearer, PassportSubmission, Season


@staff_member_required
def submission_form_view(request, pk=None):
    submission = get_object_or_404(PassportSubmission, pk=pk) if pk else None

    if request.method == 'POST':
        bearer_id = request.POST.get('bearer_id') or None
        if bearer_id:
            bearer_instance = get_object_or_404(Bearer, pk=bearer_id)
        elif submission:
            bearer_instance = submission.bearer
        else:
            bearer_instance = None

        bearer_form = BearerForm(request.POST, instance=bearer_instance)
        submission_form = PassportSubmissionForm(request.POST, instance=submission)

        if bearer_form.is_valid() and submission_form.is_valid():
            bearer = bearer_form.save()
            new_submission = submission_form.save(commit=False)
            new_submission.bearer = bearer
            if submission is None:
                new_submission.status = PassportSubmission.Status.ENTERED
                new_submission.entered_by = request.user
            new_submission.save()
            submission_form.save_m2m()
            messages.success(
                request,
                f"Saved submission #{new_submission.intake_number} — "
                f"{new_submission.stamp_count} stamps, "
                f"{new_submission.raffle_tickets} raffle tickets.",
            )
            if submission is None:
                return redirect('submission_new')
            return redirect('submission_edit', pk=new_submission.pk)
    else:
        bearer_form = BearerForm(instance=submission.bearer if submission else None)
        initial = {}
        if submission is None:
            current_season = Season.objects.filter(is_current=True).first()
            if current_season:
                initial['season'] = current_season
        submission_form = PassportSubmissionForm(instance=submission, initial=initial)

    return render(
        request,
        'passports/submission_form.html',
        {
            'bearer_form': bearer_form,
            'submission_form': submission_form,
            'submission': submission,
        },
    )


@staff_member_required
def bearer_search_view(request):
    q = request.GET.get('q', '').strip()
    results = []
    if q:
        bearers = Bearer.objects.filter(
            Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q)
        )[:10]
        results = [
            {
                'id': b.pk,
                'name': b.name,
                'email': b.email,
                'phone': b.phone,
                'mailing_address': b.mailing_address,
            }
            for b in bearers
        ]
    return JsonResponse({'results': results})
