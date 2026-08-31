from django import forms

from .models import Bearer
from .phone import normalize_uk_phone


class BearerForm(forms.ModelForm):
    class Meta:
        model = Bearer
        fields = ['name', 'email', 'mailing_address', 'phone']
        widgets = {
            'mailing_address': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_phone(self):
        normalized = normalize_uk_phone(self.cleaned_data['phone'])
        if not normalized:
            raise forms.ValidationError('Enter a valid UK phone number.')
        return normalized
