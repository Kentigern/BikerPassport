"""The only page in the app anyone can use without logging in: a text-only
message to the organisers. Kept apart from views.py (where every view
requires staff login) so what's reachable anonymously is obvious.

Off unless settings.PUBLIC_MESSAGES_ENABLED. Abuse controls, all cheap and
invisible to a genuine sender:
- honeypot field (PublicMessageForm.website) — bots fill it, people can't see it
- a signed timestamp in the form — a submit within MIN_FILL_SECONDS of the
  page loading is a bot, one older than MAX_FORM_AGE is stale
- rate limits held only in the cache (no IP address is ever stored in the
  database): RATE_LIMIT per sender per RATE_WINDOW, plus GLOBAL_RATE_LIMIT
  across everyone — the per-sender key relies on proxy headers a
  determined sender can vary, so the global cap is the hard ceiling on
  how much mail this page can ever generate
- plain text only: the message is stored and emailed as text, and Django's
  template escaping means nothing in it can render as HTML
Bot rejections look like success to the bot (no signal to adapt to).
"""

import hashlib

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .emailing import send_staff_alert
from .forms import PublicMessageForm

MIN_FILL_SECONDS = 3
MAX_FORM_AGE = 60 * 60 * 24
RATE_LIMIT = 5
GLOBAL_RATE_LIMIT = 30
RATE_WINDOW = 60 * 60
_SIGNER_SALT = 'passports.public_message'


def _sender_key(request):
    # REMOTE_ADDR is the real client on Krystal (Apache) but Railway's proxy
    # on Railway, where the client is the last X-Forwarded-For hop (the one
    # the proxy itself appended). Combining both works on either host.
    # Only ever used, hashed, as a cache key.
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[-1].strip()
    raw = f"{request.META.get('REMOTE_ADDR', '')}|{forwarded}"
    return 'public-message:' + hashlib.sha256(raw.encode()).hexdigest()


def _over_limit(key, limit):
    count = cache.get(key, 0)
    if count >= limit:
        return True
    cache.set(key, count + 1, RATE_WINDOW)
    return False


def _rate_limited(request):
    return _over_limit('public-message:all', GLOBAL_RATE_LIMIT) or _over_limit(_sender_key(request), RATE_LIMIT)


def _looks_like_bot(request, form):
    if form.cleaned_data.get('website'):
        return True
    try:
        issued = signing.TimestampSigner(salt=_SIGNER_SALT).unsign(request.POST.get('started', ''), max_age=MAX_FORM_AGE)
    except signing.BadSignature:
        return True
    return timezone.now().timestamp() - float(issued) < MIN_FILL_SECONDS


def public_message_view(request):
    if not settings.PUBLIC_MESSAGES_ENABLED:
        raise Http404

    if request.GET.get('sent'):
        return render(request, 'passports/public_message.html', {'sent': True})

    error = ''
    if request.method == 'POST':
        form = PublicMessageForm(request.POST)
        if form.is_valid():
            if _looks_like_bot(request, form):
                return redirect(f"{reverse('public_message')}?sent=1")
            if _rate_limited(request):
                error = "Sorry, we can't accept more messages right now — please try again in an hour."
            else:
                message = form.save()
                admin_path = reverse('admin:passports_publicmessage_change', args=[message.pk])
                message.alert_sent = send_staff_alert(
                    settings.PUBLIC_MESSAGE_ALERT_EMAILS,
                    subject=f'Website message from {message.name or "an anonymous visitor"}',
                    heading='New message from the passport website',
                    message_label='Message',
                    message=message.message,
                    details=[
                        ('From', message.name or '(not given)'),
                        ('Reply to', message.reply_to or '(not given)'),
                        ('Received', timezone.localtime(message.created_at).strftime('%d %b %Y %H:%M')),
                    ],
                    link_url=f'{settings.PUBLIC_BASE_URL}{admin_path}',
                    link_text='Open this message in the admin',
                )
                message.save(update_fields=['alert_sent'])
                return redirect(f"{reverse('public_message')}?sent=1")
    else:
        form = PublicMessageForm()

    started = signing.TimestampSigner(salt=_SIGNER_SALT).sign(str(timezone.now().timestamp()))
    return render(request, 'passports/public_message.html', {'form': form, 'started': started, 'error': error})
