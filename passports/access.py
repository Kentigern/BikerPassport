"""Session-scoped record that a login has proven it knows a specific
bearer's phone number (§5.2 access-control note in SPEC.md). Object-level
access to a Bearer — in the admin or via the intake form — requires both
the normal Django permission AND this verification, so knowing/guessing a
bearer's id is never enough on its own.

Superusers bypass this (a deliberate choice, not an oversight): the
phone-gate protects against staff casually browsing bearer PII by role
alone, but a superuser is already the most trusted tier in this app and
the one actually administering it — see SPEC.md §5.2."""


def mark_bearer_verified(request, bearer_id):
    verified = set(request.session.get('verified_bearer_ids', []))
    verified.add(int(bearer_id))
    request.session['verified_bearer_ids'] = list(verified)


def is_bearer_verified(request, bearer_id):
    if request.user.is_superuser:
        return True
    return int(bearer_id) in request.session.get('verified_bearer_ids', [])
