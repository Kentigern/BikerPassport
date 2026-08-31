from django import forms

from .models import Bearer, PassportSubmission, Venue


class BearerForm(forms.ModelForm):
    class Meta:
        model = Bearer
        fields = ['name', 'email', 'mailing_address', 'phone']
        widgets = {
            'mailing_address': forms.Textarea(attrs={'rows': 3}),
        }


class PassportSubmissionForm(forms.ModelForm):
    venues_stamped = forms.ModelMultipleChoiceField(
        queryset=Venue.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = PassportSubmission
        fields = ['season', 'intake_number', 'date_received', 'venues_stamped', 'notes']
        widgets = {
            'date_received': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
