from django import forms

from .models import Bearer, PublicMessage
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


class PublicMessageForm(forms.ModelForm):
    """The public /message/ form. `website` is a honeypot: hidden from
    people by CSS, but naive bots fill every field — anything in it means
    the submission is silently dropped (see public_views)."""

    website = forms.CharField(required=False)

    class Meta:
        model = PublicMessage
        fields = ['name', 'reply_to', 'message']
        labels = {
            'name': 'Your name (optional)',
            'reply_to': 'Email or phone, if you would like a reply (optional)',
            'message': 'Your message',
        }
        widgets = {
            'message': forms.Textarea(attrs={'rows': 6, 'maxlength': 2000}),
        }

    def clean_name(self):
        # Goes into the alert email's subject line — no line breaks there.
        return ' '.join(self.cleaned_data['name'].split())

    def clean_reply_to(self):
        return ' '.join(self.cleaned_data['reply_to'].split())

    def clean_message(self):
        message = self.cleaned_data['message'].strip()
        if len(message) < 2:
            raise forms.ValidationError('Please enter a message.')
        return message
