from django import forms

from .models import Bearer


class BearerForm(forms.ModelForm):
    class Meta:
        model = Bearer
        fields = ['name', 'email', 'mailing_address', 'phone']
        widgets = {
            'mailing_address': forms.Textarea(attrs={'rows': 3}),
        }
