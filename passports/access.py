"""Session-scoped record that a login has proven it knows a specific
bearer's phone number (§5.2 access-control note in SPEC.md). Object-level
access to a Bearer — in the admin or via the intake form — requires both
the normal Django permission AND this verification, so knowing/guessing a
bearer's id is never enough on its own.

Superusers bypass this (a deliberate choice, not an oversight): the
phone-gate protects against staff casually browsing bearer PII by role
alone, but a superuser is already the most trusted tier in this app and
the one actually administering it — see SPEC.md §5.2."""

from django.contrib.auth.models import Permission
from django.db.models import Q


def mark_bearer_verified(request, bearer_id):
    verified = set(request.session.get('verified_bearer_ids', []))
    verified.add(int(bearer_id))
    request.session['verified_bearer_ids'] = list(verified)


def is_bearer_verified(request, bearer_id):
    if request.user.is_superuser:
        return True
    # bearer_id can come straight from a POST body (bearer_save_view,
    # submission_save_view) — a malformed value is simply unverified, not a
    # server error.
    try:
        bearer_id = int(bearer_id)
    except (TypeError, ValueError):
        return False
    return bearer_id in request.session.get('verified_bearer_ids', [])


def is_site_admin(user):
    """The single source of truth for "site admin" access (dashboard, audit
    log, raffle export, and the raw admin index for non-superusers) — a real
    Django permission (passports.is_site_admin, granted to the Site Admin
    group by default) instead of a group-name string, so renaming or
    reorganizing that group can't silently break authorization in three
    unrelated places (config/urls.py, passports/admin.py, passports/views.py)
    that each used to check it independently.

    Deliberately bypasses user.has_perm()'s built-in "active superusers have
    every permission" shortcut and checks the grant itself instead — some
    callers (root_redirect) need to tell a plain superuser apart from one
    who's also (explicitly) a site admin; callers that want superusers
    folded in too check `user.is_superuser` themselves alongside this."""
    if not user.is_authenticated:
        return False
    return Permission.objects.filter(
        content_type__app_label='passports', codename='is_site_admin'
    ).filter(Q(user=user) | Q(group__user=user)).exists()
