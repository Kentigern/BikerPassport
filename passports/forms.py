import re

from django import forms
from django.core.validators import MinValueValidator

from .models import Bearer, ConsentStatus, PublicMessage, Venue
from .phone import normalize_uk_phone


CONSENT_CHOICES = [
    (ConsentStatus.PENDING, 'Not set'),
    (ConsentStatus.GRANTED, 'Yes'),
    (ConsentStatus.DECLINED, 'No'),
]


class BearerForm(forms.ModelForm):
    """The intake form's bearer section. The two consent questions are asked
    by the volunteer; left out of a POST, they keep their current value."""

    class Meta:
        model = Bearer
        fields = ['name', 'email', 'mailing_address', 'phone', *Bearer.CONSENT_FIELDS]
        labels = {
            'retention_consent_status': 'May Make Your Mark keep their contact details after this season?',
            'marketing_consent_status': 'May Make Your Mark use their contact details for marketing (events, merchandise)?',
        }
        widgets = {
            'mailing_address': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in Bearer.CONSENT_FIELDS:
            field = self.fields[name]
            field.choices = CONSENT_CHOICES
            field.widget = forms.RadioSelect(choices=CONSENT_CHOICES)
            field.required = False
            field.help_text = ''

    def _clean_consent(self, name):
        return self.cleaned_data[name] or getattr(self.instance, name)

    def clean_retention_consent_status(self):
        return self._clean_consent('retention_consent_status')

    def clean_marketing_consent_status(self):
        return self._clean_consent('marketing_consent_status')

    def save(self, commit=True):
        # Route the consent answers through set_consent so the answer date is stamped.
        bearer = super().save(commit=False)
        for name in Bearer.CONSENT_FIELDS:
            setattr(bearer, name, self.initial.get(name, ConsentStatus.PENDING))
            bearer.set_consent(name, self.cleaned_data[name])
        if commit:
            bearer.save()
        return bearer

    def clean_phone(self):
        normalized = normalize_uk_phone(self.cleaned_data['phone'])
        if not normalized:
            raise forms.ValidationError('Enter a valid UK phone number.')
        return normalized


# Letters (any language), digits, spaces/line breaks and everyday
# punctuation — nothing else (no <>{}[]\|`~^=*$, emoji or symbols).
PLAIN_TEXT = re.compile(r"[\w\s.,'‘’\"“”\-–—()/&!?:;#@+%]*")
PLAIN_TEXT_ERROR = 'Please use only letters, numbers and ordinary punctuation.'


def _plain_text(value, *, single_line):
    if not PLAIN_TEXT.fullmatch(value):
        raise forms.ValidationError(PLAIN_TEXT_ERROR)
    # Single-line values go into the alert email's subject and table — no
    # line breaks there.
    return ' '.join(value.split()) if single_line else value.strip()


class PublicMessageForm(forms.ModelForm):
    """The public /message/ form: an ambassador's venue report. `website`
    is a honeypot: hidden from people by CSS, but naive bots fill every
    field — anything in it means the submission is silently dropped (see
    public_views). The report date is set on save, never taken from the
    form."""

    website = forms.CharField(required=False)

    class Meta:
        model = PublicMessage
        fields = [
            'name', 'ambassador_number', 'venue_name', 'venue_number',
            'unused_passports', 'passports_collected', 'stamp', 'second_stamp', 'inkpad', 'folder', 'unused_stationery',
            'message', 'reply_to',
        ]
        labels = {
            'name': 'Ambassador name',
            'ambassador_number': 'Ambassador number',
            'venue_name': 'Venue name',
            'venue_number': 'Venue number',
            'unused_passports': 'Unused passports',
            'second_stamp': '2nd stamp',
            'passports_collected': 'Number collected',
            'unused_stationery': 'Unused stationery',
            'message': 'Notes',
            'reply_to': 'Email or phone, if you would like a reply (optional)',
        }
        widgets = {
            'ambassador_number': forms.TextInput(attrs={'inputmode': 'numeric'}),
            'venue_number': forms.TextInput(attrs={'inputmode': 'numeric'}),
            'passports_collected': forms.TextInput(attrs={'inputmode': 'numeric'}),
            'message': forms.Textarea(attrs={'rows': 8, 'maxlength': 2000}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Optional on the model (older general messages lack them), required here.
        for name in ('name', 'ambassador_number', 'venue_name', 'venue_number'):
            self.fields[name].required = True
            self.fields[name].error_messages['required'] = f'Please enter the {self.fields[name].label.lower()}.'
        for name in ('ambassador_number', 'venue_number'):
            self.fields[name].validators.append(MinValueValidator(1))
        self.fields['ambassador_number'].error_messages['invalid'] = 'Please enter the number in digits only.'
        self.fields['venue_number'].error_messages['invalid'] = 'Please enter the venue number in digits only.'
        self.fields['passports_collected'].error_messages['invalid'] = 'Please enter a number in digits only.'

    def clean_name(self):
        return _plain_text(self.cleaned_data['name'], single_line=True)

    def clean_venue_name(self):
        return _plain_text(self.cleaned_data['venue_name'], single_line=True)

    def clean_reply_to(self):
        return _plain_text(self.cleaned_data['reply_to'], single_line=True)

    def clean_message(self):
        return _plain_text(self.cleaned_data['message'], single_line=False)

    def clean_venue_number(self):
        number = self.cleaned_data['venue_number']
        if not Venue.objects.filter(number=number).exists():
            raise forms.ValidationError(f"There's no venue number {number} — please check the number on the venue's pack.")
        return number

    def clean(self):
        cleaned = super().clean()
        collected = cleaned.get('passports_collected')
        if collected is not None:
            # A count without the tick still clearly means passports came back.
            cleaned['unused_passports'] = True
        elif cleaned.get('unused_passports') and 'passports_collected' not in self.errors:
            self.add_error('passports_collected', 'Please enter how many unused passports you collected.')
        return cleaned
